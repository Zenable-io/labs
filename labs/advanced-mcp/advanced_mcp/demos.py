# Copyright (c) 2026 Zenable, Inc.
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx2
from mcp import Client as SDKClient
from mcp.client import CacheConfig, InMemoryResponseCacheStore
from mcp.client.streamable_http import streamable_http_client
from mcp_types import ReadResourceResult
from pydantic import BaseModel, Field

from advanced_mcp.cache import (
    ALICE,
    BOB,
    PROD,
    READ,
    AuthorizationContext,
    DeploymentStatus,
    Identity,
    ManualClock,
)
from advanced_mcp.protocol import (
    ALL_SCOPES,
    PROTOCOL,
    LabState,
    oauth_client,
    raw_call,
    running_lab,
)


class DemoResult(BaseModel):
    title: str
    rows: list[tuple[str, str]] = Field(default_factory=list)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def wire_reads(state: LabState) -> int:
    return sum(
        event.event == "http" and event.details.get("rpc") == "resources/read"
        for event in state.events
    )


def status_from(result: ReadResourceResult) -> DeploymentStatus:
    return DeploymentStatus.model_validate_json(result.contents[0].text)


@asynccontextmanager
async def cached_client(
    state: LabState,
    identity: Identity,
    config: CacheConfig,
    scopes: list[str] | None = None,
) -> AsyncIterator[SDKClient]:
    token = state.mint([READ] if scopes is None else scopes, identity=identity)
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"}, trust_env=False
    ) as http:
        transport = streamable_http_client(state.resource, http_client=http)
        async with SDKClient(transport, cache=config) as client:
            yield client


async def step_up() -> DemoResult:
    async with running_lab() as state:
        async with oauth_client(state) as client:
            check(
                client.protocol_version == PROTOCOL, "Unexpected MCP protocol version"
            )
            await client.call_tool("inspect_deployments")
            initial = state.storage.tokens.scope
            await client.call_tool(
                "deploy", {"environment": "staging", "release": "v2"}
            )
            await client.call_tool(
                "deploy",
                {
                    "environment": "production",
                    "release": "v2",
                    "operation_key": "release-v2",
                },
            )
            await client.call_tool("inspect_deployments")
            upgraded = state.storage.tokens.scope
        denied = next(
            event.details
            for event in state.events
            if event.event == "http" and event.details["status"] == 403
        )
        replayed = [
            event
            for event in state.events
            if event.event == "http"
            and event.details["status"] == 200
            and event.details["body_sha256"] == denied["body_sha256"]
        ]
        effects = state.executions.count("production:v2")
        check(
            effects == 1 and len(replayed) == 1, "Production retry executed incorrectly"
        )
        check(set(upgraded.split()) == ALL_SCOPES, "Scope upgrade dropped a permission")
        return DemoResult(
            title="Step-up authorization",
            rows=[
                ("protocol", PROTOCOL),
                ("initial grant", initial),
                ("staging", "200"),
                ("production challenge", f"403 insufficient_scope {PROD}"),
                ("new grant", upgraded),
                ("retry body", "identical"),
                ("production effects", str(effects)),
                ("read after upgrade", "200"),
            ],
        )


async def auth_errors() -> DemoResult:
    rows: list[tuple[str, str]] = []
    for mode in ("component", "middleware", "transport", "bridge"):
        async with running_lab(mode) as state:
            response = await raw_call(state, state.mint([READ]))
            check(not state.executions, "Denied request performed a deployment")
            if response.status_code == 200:
                message = response.json()["result"]["content"][0]["text"]
            else:
                message = response.json()["error"]
            rows.append((mode, f"{response.status_code} {message}"))
    return DemoResult(title="FastMCP 4.0.11 authorization responses", rows=rows)


async def cache_ttl() -> DemoResult:
    async with running_lab() as state:
        clock = ManualClock()
        config = CacheConfig(target_id=state.resource, clock=lambda: clock.now)
        rows: list[tuple[str, str]] = []
        async with cached_client(state, ALICE, config) as client:
            first = await client.read_resource("deployment://status")
            rows.append(
                ("wire hints", f"ttlMs={first.ttl_ms} cacheScope={first.cache_scope}")
            )
            rows.append(("t=0  use", f"wire reads={wire_reads(state)}"))
            clock.now = 1
            await client.read_resource("deployment://status")
            rows.append(("t=1  use", f"wire reads={wire_reads(state)}"))
            clock.now = 31
            await client.read_resource("deployment://status")
            rows.append(("t=31 use", f"wire reads={wire_reads(state)}"))
            await client.read_resource("deployment://status", cache_mode="refresh")
            rows.append(("refresh", f"wire reads={wire_reads(state)}"))
            await client.read_resource("deployment://status", cache_mode="bypass")
            rows.append(("bypass", f"wire reads={wire_reads(state)}"))
            await client.read_resource("deployment://status")
            rows.append(("use after bypass", f"wire reads={wire_reads(state)}"))
        check(wire_reads(state) == 4, "Cache TTL or cache_mode changed")
        return DemoResult(title="Client cache TTL", rows=rows)


async def cache_client() -> DemoResult:
    rows: list[tuple[str, str]] = []
    for mode in ("broken", "fixed"):
        async with running_lab() as state:
            store = InMemoryResponseCacheStore()
            for identity in (ALICE, BOB):
                caller = AuthorizationContext(
                    **identity.model_dump(), scopes=frozenset({READ})
                )
                partition = "everyone" if mode == "broken" else caller.partition()
                config = CacheConfig(
                    store=store, partition=partition, target_id=state.resource
                )
                async with cached_client(state, identity, config) as client:
                    value = status_from(
                        await client.read_resource("deployment://status")
                    )
                rows.append(
                    (
                        f"{mode} {identity.subject}",
                        f"tenant={value.tenant} release={value.release}",
                    )
                )
                check(
                    value.tenant == ("blue" if mode == "broken" else identity.tenant),
                    "Unexpected client cache result",
                )
            rows.append((f"{mode} wire reads", str(wire_reads(state))))
    return DemoResult(title="Client cache partitions", rows=rows)


async def cache_public() -> DemoResult:
    rows: list[tuple[str, str]] = []
    for scope in ("public", "private"):
        async with running_lab(cache_scope=scope) as state:
            store = InMemoryResponseCacheStore()
            for identity in (ALICE, BOB):
                caller = AuthorizationContext(
                    **identity.model_dump(), scopes=frozenset({READ})
                )
                config = CacheConfig(
                    store=store,
                    partition=caller.partition(),
                    target_id=state.resource,
                    share_public=True,
                )
                async with cached_client(state, identity, config) as client:
                    value = status_from(
                        await client.read_resource("deployment://status")
                    )
                rows.append((f"{scope} {identity.subject}", f"tenant={value.tenant}"))
                check(
                    value.tenant == ("blue" if scope == "public" else identity.tenant),
                    "Unexpected public cache result",
                )
    return DemoResult(title="Server cacheScope and shared clients", rows=rows)


async def cache_server() -> DemoResult:
    rows: list[tuple[str, str]] = []
    for mode in ("broken", "fixed"):
        async with running_lab(application_cache=mode) as state:
            for identity in (ALICE, BOB):
                async with cached_client(
                    state,
                    identity,
                    CacheConfig(target_id=state.resource, default_ttl_ms=0),
                ) as client:
                    value = status_from(
                        await client.read_resource(
                            "deployment://status", cache_mode="bypass"
                        )
                    )
                rows.append(
                    (
                        f"{mode} {identity.subject}",
                        f"tenant={value.tenant} release={value.release}",
                    )
                )
                check(
                    value.tenant == ("blue" if mode == "broken" else identity.tenant),
                    "Unexpected server cache result",
                )
            rows.append((f"{mode} backend reads", str(state.backend_reads)))
    return DemoResult(title="Server application cache", rows=rows)


async def cache_auth() -> DemoResult:
    async with running_lab() as state:
        async with oauth_client(state, cached=True) as client:
            before = {tool.name for tool in await client.list_tools()}
            await client.call_tool(
                "deploy", {"environment": "production", "release": "v2"}
            )
            stale = {tool.name for tool in await client.list_tools()}
            refreshed = {
                tool.name for tool in await client.list_tools(cache_mode="refresh")
            }
        check(
            "production_audit" not in before
            and "production_audit" not in stale
            and "production_audit" in refreshed,
            "Authorization-sensitive list refresh changed",
        )
        return DemoResult(
            title="Tool list after step-up",
            rows=[
                ("initial list", "production_audit absent"),
                ("scope upgrade", "deploy:read + deploy:prod"),
                ("cached list", "production_audit absent"),
                ("refresh", "production_audit present"),
            ],
        )


async def retry() -> DemoResult:
    async with running_lab() as state:
        async with oauth_client(state) as client:
            request = {"environment": "production", "release": "v2"}
            await client.call_tool("deploy", request)
            await client.call_tool("deploy", request)
            unkeyed = len(state.executions)
            request["operation_key"] = "release-v3"
            request["release"] = "v3"
            await asyncio.gather(
                client.call_tool("deploy", request), client.call_tool("deploy", request)
            )
            keyed = len(state.executions) - unkeyed
            conflicting = await client.call_tool(
                "deploy", {**request, "release": "v4"}, raise_on_error=False
            )
            await client.call_tool(
                "deploy", {**request, "operation_key": "another-release-v3"}
            )
        check(
            unkeyed == 2
            and keyed == 1
            and conflicting.is_error
            and len(state.executions) == 4,
            "Idempotency behavior changed",
        )
        return DemoResult(
            title="Retries and idempotency",
            rows=[
                ("same args, no key", f"effects={unkeyed}"),
                ("same key, concurrent retry", f"effects={keyed}"),
                ("same key, different args", "rejected"),
                ("new key, same args", "new deployment"),
            ],
        )


DEMOS: dict[str, Callable[[], Awaitable[DemoResult]]] = {
    "step-up": step_up,
    "auth-errors": auth_errors,
    "cache-ttl": cache_ttl,
    "cache-client": cache_client,
    "cache-public": cache_public,
    "cache-server": cache_server,
    "cache-auth": cache_auth,
    "retry": retry,
}
