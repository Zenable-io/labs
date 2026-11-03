# Copyright (c) 2026 Zenable, Inc.
import pytest
from advanced_mcp.cache import (
    ALICE,
    BOB,
    PROD,
    READ,
    AuthorizationContext,
    DeploymentStatus,
    ResultCache,
)


def context(
    tenant: str = "blue",
    subject: str = "alice",
    scopes: frozenset[str] = frozenset({READ}),
) -> AuthorizationContext:
    return AuthorizationContext(tenant=tenant, subject=subject, scopes=scopes)


@pytest.mark.unit
def test_partitions_separate_tenants_users_and_scope_grants() -> None:
    variants = [
        context(),
        context(tenant="red"),
        context(subject="bob"),
        context(scopes=frozenset({READ, PROD})),
    ]
    assert len({caller.partition() for caller in variants}) == len(variants)
    assert (
        context(scopes=frozenset({READ, PROD})).partition()
        == context(scopes=frozenset({PROD, READ})).partition()
    )


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["broken", "fixed"])
def test_cache_authorizes_before_using_a_fresh_entry(mode: str) -> None:
    cache = ResultCache(mode=mode)
    cache.read(
        context(),
        0,
        lambda: DeploymentStatus(tenant="blue", subject="alice", release="v1"),
    )
    with pytest.raises(PermissionError, match=READ):
        cache.read(
            context(scopes=frozenset()),
            1,
            lambda: pytest.fail("Unauthorized loader ran"),
        )
    assert cache.hits == 0


@pytest.mark.unit
def test_fixed_cache_expires_and_copies_results() -> None:
    cache = ResultCache(mode="fixed")
    value = cache.read(
        context(),
        0,
        lambda: DeploymentStatus(tenant="blue", subject="alice", release="v1"),
    )
    value.release = "mutated"
    assert (
        cache.read(context(), 1, lambda: pytest.fail("Fresh cache missed")).release
        == "v1"
    )
    assert (
        cache.read(
            context(),
            30,
            lambda: DeploymentStatus(tenant="blue", subject="alice", release="v2"),
        ).release
        == "v2"
    )
    cache.invalidate("blue")
    assert (
        cache.read(
            context(),
            31,
            lambda: DeploymentStatus(tenant="blue", subject="alice", release="v3"),
        ).release
        == "v3"
    )


@pytest.mark.unit
def test_invalidation_retains_other_tenants_entries() -> None:
    cache = ResultCache(mode="fixed")
    for identity in (ALICE, BOB):
        cache.read(
            context(identity.tenant, identity.subject),
            0,
            lambda: DeploymentStatus(**identity.model_dump(), release="v1"),
        )
    cache.invalidate("blue")
    assert (
        cache.read(
            context("red", "bob"),
            1,
            lambda: pytest.fail("Other tenant cache was discarded"),
        ).tenant
        == "red"
    )


@pytest.mark.unit
@pytest.mark.parametrize("mode,expected_tenant", [("broken", "blue"), ("fixed", "red")])
def test_server_cache_demo_exposes_only_the_intended_bad_key(
    mode: str, expected_tenant: str
) -> None:
    cache = ResultCache(mode=mode)
    for identity in (ALICE, BOB):
        caller = context(identity.tenant, identity.subject)
        value = cache.read(
            caller, 0, lambda: DeploymentStatus(**identity.model_dump(), release="v1")
        )
    assert value.tenant == expected_tenant
