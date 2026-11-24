# Copyright (c) 2026 Zenable, Inc.
import asyncio

import httpx2
import pytest
from advanced_mcp.cache import ALICE, BOB, PROD, READ
from advanced_mcp.demos import (
    cache_auth,
    cache_client,
    cache_public,
    cache_server,
    cache_ttl,
    cached_client,
    retry,
)
from advanced_mcp.protocol import (
    ALL_SCOPES,
    PROTOCOL,
    deployment_request,
    oauth_client,
    raw_call,
    running_lab,
)
from mcp.client import CacheConfig


@pytest.mark.integration
def test_oauth_step_up_replays_the_same_body_after_granting_both_scopes() -> None:
    async def run() -> None:
        async with running_lab() as state:
            async with oauth_client(state) as client:
                assert client.protocol_version == PROTOCOL
                await client.call_tool("inspect_deployments")
                assert state.storage.tokens.scope == READ
                await client.call_tool(
                    "deploy", {"environment": "production", "release": "v2"}
                )
                assert set(state.storage.tokens.scope.split()) == ALL_SCOPES
                await client.call_tool("inspect_deployments")
            challenged = [
                event.details
                for event in state.events
                if event.event == "http" and event.details["status"] == 403
            ]
            assert len(challenged) == 1
            assert f'scope="{PROD}"' in challenged[0]["challenge"]
            assert READ not in challenged[0]["challenge"]
            replayed = [
                event
                for event in state.events
                if event.event == "http"
                and event.details["status"] == 200
                and event.details["body_sha256"] == challenged[0]["body_sha256"]
            ]
            assert len(replayed) == 1 and state.executions == ["production:v2"]
            assert (
                len(
                    [
                        event
                        for event in state.events
                        if event.event == "token_exchange"
                        and event.details["pkce_verified"]
                    ]
                )
                == 2
            )

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.parametrize("policy", ["deny", "downscope"])
def test_refused_upgrade_never_runs_production_and_does_not_loop(policy: str) -> None:
    async def run() -> None:
        async with running_lab(policy=policy) as state:
            client = oauth_client(state)
            async with client:
                await client.call_tool("inspect_deployments")
            async with httpx2.AsyncClient(
                auth=client.transport.auth, trust_env=False
            ) as requester:
                request = requester.post(
                    state.resource,
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "MCP-Protocol-Version": PROTOCOL,
                        "Mcp-Method": "tools/call",
                        "Mcp-Name": "deploy",
                    },
                    json=deployment_request(),
                )
                if policy == "deny":
                    with pytest.raises(PermissionError, match="declined"):
                        await request
                else:
                    assert (await request).status_code == 403
            assert not state.executions
            assert state.storage.tokens.scope == READ
            assert (
                len(
                    [
                        event
                        for event in state.events
                        if event.event == "authorization_request"
                    ]
                )
                == 2
            )

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.parametrize(
    "mode,status",
    [("component", 200), ("middleware", 200), ("transport", 401), ("bridge", 403)],
)
def test_native_and_http_preflight_denials_are_distinct(mode: str, status: int) -> None:
    async def run() -> None:
        async with running_lab(mode) as state:
            response = await raw_call(state, state.mint([READ]))
            assert response.status_code == status
            assert not state.executions
            if status == 200:
                assert response.json()["result"]["isError"]
                assert "www-authenticate" not in response.headers
            elif status == 403:
                assert (
                    'error="insufficient_scope"' in response.headers["www-authenticate"]
                )
            else:
                assert 'error="invalid_token"' in response.headers["www-authenticate"]

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.parametrize("invalid", ["expired", "wrong-audience", "missing"])
def test_invalid_tokens_cannot_trigger_a_deployment(invalid: str) -> None:
    async def run() -> None:
        async with running_lab() as state:
            token = {
                "expired": state.mint([PROD], expires_in=-60),
                "wrong-audience": state.mint(
                    [PROD], audience=f"{state.base_url}/other"
                ),
                "missing": None,
            }[invalid]
            assert (await raw_call(state, token)).status_code == 401
            assert not state.executions

    asyncio.run(run())


@pytest.mark.integration
def test_protocol_cache_ttl_refresh_and_bypass_have_observable_wire_counts() -> None:
    result = asyncio.run(cache_ttl())
    counts = [value for label, value in result.rows if label != "wire hints"]
    assert counts == [f"wire reads={count}" for count in (1, 1, 2, 3, 4, 4)]
    assert result.rows[0][1] == "ttlMs=30000 cacheScope=private"


@pytest.mark.integration
def test_shared_client_store_leaks_only_when_partitions_are_reused() -> None:
    rows = dict(asyncio.run(cache_client()).rows)
    assert rows["broken bob"] == "tenant=blue release=v1"
    assert rows["fixed bob"] == "tenant=red release=v9"
    assert rows["broken wire reads"] == "1" and rows["fixed wire reads"] == "2"


@pytest.mark.integration
def test_public_hint_can_leak_even_with_distinct_client_partitions() -> None:
    rows = dict(asyncio.run(cache_public()).rows)
    assert rows["public bob"] == "tenant=blue"
    assert rows["private bob"] == "tenant=red"


@pytest.mark.integration
def test_server_application_cache_is_separate_from_client_caching() -> None:
    rows = dict(asyncio.run(cache_server()).rows)
    assert rows["broken bob"] == "tenant=blue release=v1"
    assert rows["fixed bob"] == "tenant=red release=v9"
    assert rows["broken backend reads"] == "1" and rows["fixed backend reads"] == "2"


@pytest.mark.integration
def test_scope_upgrade_requires_refreshing_an_authorization_sensitive_tool_list() -> (
    None
):
    rows = dict(asyncio.run(cache_auth()).rows)
    assert rows["cached list"] == "production_audit absent"
    assert rows["refresh"] == "production_audit present"


@pytest.mark.integration
def test_retries_deduplicate_concurrent_calls_and_reject_key_conflicts() -> None:
    rows = dict(asyncio.run(retry()).rows)
    assert rows["same args, no key"] == "effects=2"
    assert rows["same key, concurrent retry"] == "effects=1"
    assert rows["same key, different args"] == "rejected"
    assert rows["new key, same args"] == "new deployment"


@pytest.mark.integration
def test_idempotency_keys_are_scoped_to_the_authenticated_caller() -> None:
    async def run() -> None:
        async with running_lab() as state:
            for identity in (ALICE, BOB):
                async with cached_client(
                    state,
                    identity,
                    CacheConfig(target_id=state.resource),
                    scopes=[PROD],
                ) as client:
                    result = await client.call_tool(
                        "deploy",
                        {
                            "environment": "production",
                            "release": "v2",
                            "operation_key": "shared-key",
                        },
                    )
                    assert not result.is_error
            assert len(state.executions) == 2

    asyncio.run(run())
