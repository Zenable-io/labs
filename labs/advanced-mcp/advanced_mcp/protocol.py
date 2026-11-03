# Copyright (c) 2026 Zenable, Inc.
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import parse_qs, urlencode

import httpx2
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import RemoteAuthProvider, require_scopes, restrict_tag
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import AuthMiddleware
from joserfc import jwk, jwt
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
)
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
)
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from advanced_mcp.cache import (
    ALICE,
    PROD,
    READ,
    AuthorizationContext,
    DeploymentStatus,
    Identity,
    ResultCache,
)

ALL_SCOPES = frozenset({READ, PROD})
PROTOCOL = "2026-07-28"
Mode = Literal["bridge", "component", "middleware", "transport"]


class Event(BaseModel):
    event: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class Grant(BaseModel):
    scopes: list[str]
    client: str
    resource: str


class PendingCode(Grant):
    redirect: str
    challenge: str
    expires_at: float


class DeploymentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment: Literal["staging", "production"]
    release: str = Field(min_length=1, max_length=64)
    operation_key: str | None = Field(default=None, min_length=1, max_length=128)


class CompletedOperation(BaseModel):
    fingerprint: str
    message: str


class MemoryStorage(BaseModel):
    tokens: OAuthToken | None = None
    client_info: OAuthClientInformationFull

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


class LabState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    base_url: str
    issuer: str
    callback_url: str
    client: str = Field(default_factory=lambda: secrets.token_hex(12))
    key: jwk.RSAKey = Field(
        default_factory=lambda: jwk.RSAKey.generate_key(2048), exclude=True
    )
    policy: Literal["grant", "downscope", "deny"] = "grant"
    events: list[Event] = Field(default_factory=list)
    codes: dict[str, PendingCode] = Field(default_factory=dict, exclude=True)
    refreshes: dict[str, Grant] = Field(default_factory=dict, exclude=True)
    executions: list[str] = Field(default_factory=list)
    callback: AuthorizationCodeResult | None = Field(default=None, exclude=True)
    storage: MemoryStorage | None = Field(default=None, exclude=True)
    result_cache: ResultCache = Field(default_factory=ResultCache)
    releases: dict[str, str] = Field(
        default_factory=lambda: {"blue": "v1", "red": "v9"}
    )
    backend_reads: int = 0
    completed: dict[tuple[str, str, str], CompletedOperation] = Field(
        default_factory=dict
    )
    operation_lock: asyncio.Lock = Field(default_factory=asyncio.Lock, exclude=True)

    @property
    def resource(self) -> str:
        return f"{self.base_url}/mcp"

    @property
    def metadata_url(self) -> str:
        return f"{self.base_url}/.well-known/oauth-protected-resource/mcp"

    def record(self, event: str, **details: JsonValue) -> None:
        self.events.append(Event(event=event, details=details))

    def mint(
        self,
        scopes: list[str],
        *,
        identity: Identity = ALICE,
        audience: str | None = None,
        expires_in: int = 300,
    ) -> str:
        issued = int(time.time())
        return jwt.encode(
            {"alg": "RS256"},
            {
                "iss": self.issuer,
                "sub": identity.subject,
                "tenant": identity.tenant,
                "aud": audience or self.resource,
                "iat": issued,
                "exp": issued + expires_in,
                "scope": " ".join(sorted(scopes)),
                "client_id": self.client,
                "jti": secrets.token_hex(16),
            },
            self.key,
        )

    def issue(self, grant: Grant) -> JSONResponse:
        refresh = secrets.token_urlsafe(32)
        self.refreshes[refresh] = grant
        return JSONResponse(
            {
                "access_token": self.mint(grant.scopes),
                "token_type": "Bearer",
                "expires_in": 300,
                "scope": " ".join(sorted(grant.scopes)),
                "refresh_token": refresh,
            },
            headers={"Cache-Control": "no-store"},
        )


def challenge_for(state: LabState, scopes: list[str]) -> str:
    return (
        f'Bearer error="insufficient_scope", scope="{" ".join(sorted(scopes))}", '
        f'resource_metadata="{state.metadata_url}"'
    )


class ScopeChallengeMiddleware:
    """HTTP preflight because FastMCP tool middleware emits JSON-RPC errors."""

    def __init__(self, app: ASGIApp, state: LabState, verifier: JWTVerifier) -> None:
        self.app = app
        self.state = state
        self.verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] != "/mcp"
        ):
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                await Response(status_code=413)(scope, receive, send)
                return
        try:
            message = json.loads(body)
            params = message.get("params", {})
            arguments = (
                DeploymentArgs.model_validate(params.get("arguments"))
                if (
                    message.get("method") == "tools/call"
                    and params.get("name") == "deploy"
                )
                else None
            )
            required = (
                ([PROD] if arguments.environment == "production" else [READ])
                if arguments
                else (
                    [READ]
                    if message.get("method") == "resources/read"
                    or params.get("name") == "inspect_deployments"
                    else []
                )
            )
        except (ValueError, AttributeError, ValidationError):
            arguments = None
            required = []
        if required:
            authorization = request.headers.get("authorization", "")
            token = (
                await self.verifier.verify_token(authorization[7:])
                if authorization.startswith("Bearer ")
                else None
            )
            if token and not set(required) <= set(token.scopes):
                self.state.record(
                    "preflight_denied",
                    requested=arguments.model_dump() if arguments else {},
                    required_scopes=required,
                    executions_before=len(self.state.executions),
                )
                await JSONResponse(
                    {"error": "insufficient_scope"},
                    status_code=403,
                    headers={"WWW-Authenticate": challenge_for(self.state, required)},
                )(scope, receive, send)
                return
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class WireTrace:
    def __init__(self, app: ASGIApp, state: LabState) -> None:
        self.app = app
        self.state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        body = bytearray()

        async def traced_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                body.extend(message.get("body", b""))
            return message

        async def traced_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = dict(message.get("headers", []))
                self.state.record(
                    "http",
                    method=scope["method"],
                    path=scope["path"],
                    protocol=headers.get(b"mcp-protocol-version", b"").decode(),
                    rpc=headers.get(b"mcp-method", b"").decode(),
                    tool=headers.get(b"mcp-name", b"").decode(),
                    status=message["status"],
                    body_sha256=hashlib.sha256(body).hexdigest() if body else "",
                    challenge=response_headers.get(b"www-authenticate", b"").decode(),
                )
            await send(message)

        await self.app(scope, traced_receive, traced_send)


def authorization_app(state: LabState) -> Starlette:
    async def metadata(request: Request) -> Response:
        return JSONResponse(
            {
                "issuer": state.issuer,
                "authorization_endpoint": f"{state.issuer}authorize",
                "token_endpoint": f"{state.issuer}token",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": sorted(ALL_SCOPES),
                "authorization_response_iss_parameter_supported": True,
            }
        )

    async def authorize(request: Request) -> Response:
        query = request.query_params
        requested = set(query.get("scope", "").split())
        if (
            query.get("client_id") != state.client
            or query.get("redirect_uri") != state.callback_url
            or query.get("resource") != state.resource
            or query.get("response_type") != "code"
            or query.get("code_challenge_method") != "S256"
            or not query.get("code_challenge")
            or not query.get("state")
            or not requested
            or not requested <= ALL_SCOPES
        ):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        state.record(
            "authorization_request",
            scopes=sorted(requested),
            resource=query["resource"],
            pkce="S256",
        )
        if state.policy == "deny" and PROD in requested:
            state.record("consent_denied", scopes=sorted(requested))
            return RedirectResponse(
                state.callback_url
                + "?"
                + urlencode(
                    {
                        "error": "access_denied",
                        "state": query["state"],
                        "iss": state.issuer,
                    }
                ),
                status_code=302,
            )
        granted = requested & {READ} if state.policy == "downscope" else requested
        code = secrets.token_urlsafe(32)
        state.codes[hashlib.sha256(code.encode()).hexdigest()] = PendingCode(
            scopes=sorted(granted),
            client=state.client,
            resource=state.resource,
            redirect=state.callback_url,
            challenge=query["code_challenge"],
            expires_at=time.time() + 60,
        )
        state.record("authorization_granted", scopes=sorted(granted))
        return RedirectResponse(
            state.callback_url
            + "?"
            + urlencode(
                {
                    "code": code,
                    "state": query["state"],
                    "iss": state.issuer,
                }
            ),
            status_code=302,
        )

    async def token(request: Request) -> Response:
        body = parse_qs((await request.body()).decode())
        values = {key: value[0] for key, value in body.items() if len(value) == 1}
        if (
            values.get("client_id") != state.client
            or values.get("resource") != state.resource
        ):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if values.get("grant_type") == "authorization_code":
            code_hash = hashlib.sha256(values.get("code", "").encode()).hexdigest()
            pending = state.codes.pop(code_hash, None)
            verifier = values.get("code_verifier", "")
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            if (
                not pending
                or pending.expires_at < time.time()
                or pending.redirect != values.get("redirect_uri")
                or not 43 <= len(verifier) <= 128
                or not secrets.compare_digest(pending.challenge, challenge)
            ):
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            state.record(
                "token_exchange",
                grant_type="authorization_code",
                resource=values["resource"],
                scopes=pending.scopes,
                pkce_verified=True,
            )
            return state.issue(
                Grant(
                    scopes=pending.scopes, client=state.client, resource=state.resource
                )
            )
        if values.get("grant_type") == "refresh_token":
            previous = state.refreshes.get(values.get("refresh_token", ""))
            if not previous:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            requested = set(values.get("scope", " ".join(previous.scopes)).split())
            if not requested <= set(previous.scopes):
                state.record(
                    "refresh_rejected",
                    requested_scopes=sorted(requested),
                    original_scopes=previous.scopes,
                )
                return JSONResponse({"error": "invalid_scope"}, status_code=400)
            del state.refreshes[values["refresh_token"]]
            state.record(
                "token_exchange",
                grant_type="refresh_token",
                resource=values["resource"],
                scopes=sorted(requested),
            )
            return state.issue(
                Grant(
                    scopes=sorted(requested),
                    client=state.client,
                    resource=state.resource,
                )
            )
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    return Starlette(
        routes=[
            Route("/.well-known/oauth-authorization-server", metadata),
            Route("/authorize", authorize),
            Route("/token", token, methods=["POST"]),
        ]
    )


def callback_app(state: LabState) -> Starlette:
    async def callback(request: Request) -> Response:
        if request.query_params.get("error"):
            state.record("callback_error", error=request.query_params["error"])
            return JSONResponse(
                {"error": request.query_params["error"]}, status_code=400
            )
        try:
            state.callback = AuthorizationCodeResult.model_validate(
                dict(request.query_params)
            )
        except ValidationError:
            return JSONResponse({"error": "invalid_callback"}, status_code=400)
        state.record("callback_received", issuer=state.callback.iss)
        return Response("Test callback received")

    return Starlette(routes=[Route("/callback", callback)])


def caller_context() -> AuthorizationContext:
    token = get_access_token()
    if token is None or not token.subject:
        raise PermissionError("Authenticated identity required")
    return AuthorizationContext(
        tenant=token.claims["tenant"],
        subject=token.subject,
        scopes=frozenset(token.scopes),
    )


def mcp_app(
    state: LabState, mode: Mode, cache_scope: Literal["private", "public"]
) -> ASGIApp:
    verifier = JWTVerifier(
        public_key=state.key.as_pem(private=False).decode(),
        algorithm="RS256",
        issuer=state.issuer,
        audience=state.resource,
        required_scopes=[READ, PROD] if mode == "transport" else [],
    )
    auth = RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[AnyHttpUrl(state.issuer)],
        base_url=state.base_url,
        scopes_supported=[READ],
        challenge_scopes=None if mode == "transport" else [READ],
    )
    middleware = (
        [AuthMiddleware(auth=restrict_tag("production", scopes=[PROD]))]
        if mode == "middleware"
        else []
    )
    mcp = FastMCP(
        "Advanced MCP",
        auth=auth,
        middleware=middleware,
        cache_ttl=30,
        cache_scope=cache_scope,
    )

    def read_status() -> DeploymentStatus:
        caller = caller_context()

        def load() -> DeploymentStatus:
            state.backend_reads += 1
            return DeploymentStatus(
                tenant=caller.tenant,
                subject=caller.subject,
                release=state.releases.get(caller.tenant, "v0"),
            )

        return state.result_cache.read(caller, time.monotonic(), load)

    @mcp.tool(auth=require_scopes(READ))
    def inspect_deployments() -> DeploymentStatus:
        return read_status()

    @mcp.resource("deployment://status")
    def deployment_status() -> str:
        return read_status().model_dump_json()

    @mcp.tool(auth=require_scopes(PROD))
    def production_audit() -> str:
        return f"Production audit: {caller_context().tenant}"

    @mcp.tool(
        auth=require_scopes(PROD) if mode == "component" else None, tags={"production"}
    )
    async def deploy(
        environment: Literal["staging", "production"],
        release: str,
        operation_key: str | None = None,
    ) -> str:
        arguments = DeploymentArgs(
            environment=environment, release=release, operation_key=operation_key
        )
        caller = caller_context()
        caller.require(PROD if arguments.environment == "production" else READ)
        key = (caller.tenant, caller.subject, operation_key or "")
        fingerprint = hashlib.sha256(
            arguments.model_dump_json(exclude={"operation_key"}).encode()
        ).hexdigest()
        async with state.operation_lock:
            if operation_key and (previous := state.completed.get(key)):
                if previous.fingerprint != fingerprint:
                    raise ValueError(
                        "Operation key already used for different arguments"
                    )
                state.record("idempotent_replay", operation_key=operation_key)
                return previous.message
            state.executions.append(f"{arguments.environment}:{arguments.release}")
            state.releases[caller.tenant] = arguments.release
            state.result_cache.invalidate(caller.tenant)
            state.record(
                "tool_executed",
                arguments=arguments.model_dump(),
                execution_count=len(state.executions),
            )
            result = f"Deployed {arguments.release} to {arguments.environment}"
            if operation_key:
                state.completed[key] = CompletedOperation(
                    fingerprint=fingerprint, message=result
                )
            return result

    asgi_middleware = (
        [Middleware(ScopeChallengeMiddleware, state=state, verifier=verifier)]
        if mode == "bridge"
        else []
    )
    app = mcp.http_app(
        path="/mcp", json_response=True, stateless_http=True, middleware=asgi_middleware
    )
    return WireTrace(app, state)


def reserve_socket() -> socket.socket:
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.bind(("127.0.0.1", 0))
    connection.listen(128)
    connection.setblocking(False)
    return connection


@asynccontextmanager
async def serve(app: ASGIApp, connection: socket.socket) -> AsyncIterator[None]:
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="critical", access_log=False, lifespan="on")
    )
    running = asyncio.create_task(server.serve(sockets=[connection]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if running.done():
                    await running
                    raise RuntimeError("Test HTTP server exited before startup")
                await asyncio.sleep(0.01)
        yield
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(running, timeout=5)
        finally:
            connection.close()


@asynccontextmanager
async def running_lab(
    mode: Mode = "bridge",
    policy: Literal["grant", "downscope", "deny"] = "grant",
    *,
    cache_scope: Literal["private", "public"] = "private",
    application_cache: Literal["off", "broken", "fixed"] = "off",
) -> AsyncIterator[LabState]:
    mcp_socket, auth_socket, callback_socket = (
        reserve_socket(),
        reserve_socket(),
        reserve_socket(),
    )
    state = LabState(
        base_url=f"http://127.0.0.1:{mcp_socket.getsockname()[1]}",
        issuer=f"http://127.0.0.1:{auth_socket.getsockname()[1]}/",
        callback_url=f"http://127.0.0.1:{callback_socket.getsockname()[1]}/callback",
        policy=policy,
        result_cache=ResultCache(mode=application_cache),
    )
    async with (
        serve(authorization_app(state), auth_socket),
        serve(callback_app(state), callback_socket),
        serve(mcp_app(state, mode, cache_scope), mcp_socket),
    ):
        yield state


def oauth_client(state: LabState, *, cached: bool = False) -> Client:
    metadata = OAuthClientMetadata(
        redirect_uris=[AnyHttpUrl(state.callback_url)],
        client_name="Step-up experiment",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
        scope=READ,
    )
    state.storage = MemoryStorage(
        client_info=OAuthClientInformationFull(
            client_id=state.client,
            issuer=state.issuer,
            **metadata.model_dump(exclude_none=True),
        )
    )

    async def follow_redirect(url: str) -> None:
        state.callback = None
        async with httpx2.AsyncClient(
            follow_redirects=True, trust_env=False
        ) as browser:
            response = await browser.get(url)
            if (
                response.status_code == 400
                and response.json().get("error") == "access_denied"
            ):
                raise PermissionError("Test user declined the scope upgrade")
            response.raise_for_status()

    async def receive_callback() -> AuthorizationCodeResult:
        if state.callback is None:
            raise RuntimeError("Authorization did not reach the test callback")
        return state.callback

    provider = OAuthClientProvider(
        server_url=state.resource,
        client_metadata=metadata,
        storage=state.storage,
        redirect_handler=follow_redirect,
        callback_handler=receive_callback,
    )
    transport = StreamableHttpTransport(state.resource, auth=provider)
    return Client(transport, cache=True if cached else None)


def deployment_request() -> dict[str, JsonValue]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "deploy",
            "arguments": {"environment": "production", "release": "v1"},
            "_meta": {
                CLIENT_INFO_META_KEY: {"name": "wire-test", "version": "1"},
                PROTOCOL_VERSION_META_KEY: PROTOCOL,
                CLIENT_CAPABILITIES_META_KEY: {},
            },
        },
    }


async def raw_call(state: LabState, token: str | None) -> httpx2.Response:
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL,
        "Mcp-Method": "tools/call",
        "Mcp-Name": "deploy",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx2.AsyncClient(trust_env=False) as client:
        return await client.post(
            state.resource, headers=headers, json=deployment_request()
        )
