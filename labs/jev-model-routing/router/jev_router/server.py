"""Copyright (c) 2026 Zenable, Inc. The ExtProc server agentgateway calls before it selects a model.

One bidirectional gRPC stream per request. agentgateway sends request headers,
then the buffered request body; the router answers each with a
`ProcessingResponse`. The body answer carries the rewritten `model`, and because
`llm.policies.extProc` runs before model selection, the router's answer is what
the model router then reads.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import grpc

from jev_router.cache import Decision, RoutingCache
from jev_router.catalog import policy_fingerprint
from jev_router.config import RouterSettings
from jev_router.decide import FALLBACK_MODEL, JevUnavailable, build_client
from jev_router.features import extract
from jev_router.proto import ext_proc_pb2 as pb
from jev_router.proto import ext_proc_pb2_grpc as pb_grpc
from jev_router.proto import shared_envoy_pb2 as envoy_pb

LOG = logging.getLogger("jev_router.server")

_CONTINUE = pb.ProcessingResponse(
    request_headers=pb.HeadersResponse(response=pb.CommonResponse())
)
_CONTINUE_BODY = pb.ProcessingResponse(
    request_body=pb.BodyResponse(response=pb.CommonResponse())
)
_OVERWRITE = envoy_pb.HeaderValueOption.OVERWRITE_IF_EXISTS_OR_ADD


class RouterServicer(pb_grpc.ExternalProcessorServicer):
    def __init__(
        self, settings: RouterSettings, jev: object, cache: RoutingCache | None
    ) -> None:
        self._settings = settings
        self._jev = jev
        self._cache = cache
        self.decisions: list[Decision] = []

    async def Process(  # noqa: N802 - the gRPC method name is fixed by the proto
        self,
        request_iterator: AsyncIterator[pb.ProcessingRequest],
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[pb.ProcessingResponse]:
        buffered = bytearray()
        async for message in request_iterator:
            kind = message.WhichOneof("request")
            if kind == "request_headers":
                yield _CONTINUE
            elif kind == "request_body":
                buffered.extend(message.request_body.body)
                if not message.request_body.end_of_stream:
                    # bufferedPartial and fullDuplexStreamed can deliver a body in
                    # pieces; hold until the last one before parsing JSON.
                    continue
                yield await self._route(bytes(buffered))
                buffered.clear()
            elif kind == "request_trailers":
                yield pb.ProcessingResponse(request_trailers=pb.TrailersResponse())
            elif kind == "response_headers":
                yield pb.ProcessingResponse(
                    response_headers=pb.HeadersResponse(response=pb.CommonResponse())
                )
            elif kind == "response_body":
                yield pb.ProcessingResponse(
                    response_body=pb.BodyResponse(response=pb.CommonResponse())
                )
            elif kind == "response_trailers":
                yield pb.ProcessingResponse(response_trailers=pb.TrailersResponse())

    async def _route(self, raw: bytes) -> pb.ProcessingResponse:
        try:
            body = json.loads(raw)
        except ValueError:
            return _CONTINUE_BODY
        if (
            not isinstance(body, dict)
            or body.get("model") != self._settings.routed_model
        ):
            # Not a routed request. This is also what keeps the router's own Jev
            # traffic from recursing when it is proxied back through the gateway.
            return _CONTINUE_BODY

        features = extract(body)
        if features is None:
            decision = Decision(
                model=FALLBACK_MODEL,
                confidence=0.0,
                source="fallback",
                reason="no user message",
            )
        else:
            try:
                if self._cache is None:
                    # Both levels off means no cache at all, so no single-flight
                    # either: identical concurrent misses each pay their own call.
                    decision = await self._jev.decide(features)
                else:
                    decision = await self._cache.resolve(
                        exact_key=features.exact_key,
                        bucket_key=features.bucket_key,
                        compute=lambda: self._jev.decide(features),
                    )
            except (JevUnavailable, asyncio.TimeoutError) as error:
                decision = Decision(
                    model=FALLBACK_MODEL,
                    confidence=0.0,
                    source="fallback",
                    reason=str(error)[:200],
                )

        body["model"] = decision.model
        replaced = json.dumps(body, separators=(",", ":")).encode()
        self._record(decision)

        return pb.ProcessingResponse(
            request_body=pb.BodyResponse(
                response=pb.CommonResponse(
                    status=pb.CommonResponse.CONTINUE_AND_REPLACE,
                    body_mutation=pb.BodyMutation(body=replaced),
                    header_mutation=pb.HeaderMutation(
                        set_headers=[
                            envoy_pb.HeaderValueOption(
                                header=envoy_pb.HeaderValue(
                                    key=self._settings.decision_header,
                                    raw_value=f"{decision.model};{decision.source};{decision.confidence:.3f}".encode(),
                                ),
                                append_action=_OVERWRITE,
                            ),
                            # The body changed length, so the client's
                            # content-length no longer describes it. The default
                            # append action would add a second value rather than
                            # replace the first.
                            envoy_pb.HeaderValueOption(
                                header=envoy_pb.HeaderValue(
                                    key="content-length",
                                    raw_value=str(len(replaced)).encode(),
                                ),
                                append_action=_OVERWRITE,
                            ),
                        ]
                    ),
                )
            )
        )

    def _record(self, decision: Decision) -> None:
        self.decisions.append(decision)
        LOG.info(
            "route -> %-11s src=%-8s conf=%.2f %s",
            decision.model,
            decision.source,
            decision.confidence,
            decision.probabilities or "",
        )


async def serve(settings: RouterSettings) -> None:
    jev = build_client(settings)
    cache = (
        RoutingCache(
            fingerprint=policy_fingerprint(settings.jev_model),
            ttl_seconds=settings.cache_ttl_seconds,
            max_entries=settings.cache_max_entries,
            bucket_enabled=settings.cache_bucket_enabled,
        )
        if settings.cache_exact_enabled or settings.cache_bucket_enabled
        else None
    )
    servicer = RouterServicer(settings, jev, cache)
    server = grpc.aio.server()
    pb_grpc.add_ExternalProcessorServicer_to_server(servicer, server)
    server.add_insecure_port(settings.listen)
    await server.start()
    await jev.warm()
    LOG.info(
        "ext_proc listening on %s | jev=%s | deadline=%.1fs | cache exact=%s bucket=%s ttl=%.0fs | policy=%s",
        settings.listen,
        settings.jev_model,
        settings.jev_deadline_seconds,
        settings.cache_exact_enabled,
        settings.cache_bucket_enabled,
        settings.cache_ttl_seconds,
        policy_fingerprint(settings.jev_model),
    )
    try:
        await server.wait_for_termination()
    finally:
        await jev.aclose()
