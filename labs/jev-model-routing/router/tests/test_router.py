# Copyright (c) 2026 Zenable, Inc.

"""Unit tests for the parts of the router that do not need Jev."""

import asyncio
import json
from pathlib import Path

import pytest
from jev_router import align, catalog, house
from jev_router.cache import Decision, RoutingCache
from jev_router.catalog import MODEL_NAMES, build_questions, policy_fingerprint
from jev_router.config import RouterSettings
from jev_router.decide import FixtureClient, JevClient, JevUnavailable, build_client
from jev_router.features import build_state, extract


def body(text: str, **extra: object) -> dict:
    return {"model": "auto", "messages": [{"role": "user", "content": text}], **extra}


def test_criteria_keys_are_the_model_names() -> None:
    criteria = build_questions()["route"]["criteria"]
    assert set(criteria) == set(MODEL_NAMES)


def test_fingerprint_changes_when_a_criterion_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = policy_fingerprint("jev-latest")
    widened = catalog.CandidateModel(name="qwen-small", criterion="anything at all")
    monkeypatch.setattr(catalog, "CATALOG", (widened, catalog.CATALOG[1]))
    assert policy_fingerprint("jev-latest") != before


def test_fingerprint_changes_with_the_jev_model() -> None:
    assert policy_fingerprint("jev-latest") != policy_fingerprint("jev-1.13.0")


def test_exact_key_ignores_digits_and_hex_blobs() -> None:
    a = extract(body("Retry ticket 1183 with request id deadbeefcafe1234"))
    b = extract(body("Retry ticket 1184 with request id 0123456789abcdef"))
    assert a.exact_key == b.exact_key


def test_exact_key_covers_everything_that_reaches_the_state() -> None:
    plain = extract(body("Rename cfg to config"))
    with_tools = extract(
        body(
            "Rename cfg to config",
            tools=[{"type": "function", "function": {"name": "read_file"}}],
        )
    )
    assert plain.exact_key != with_tools.exact_key


def test_no_user_message_is_not_routable() -> None:
    assert (
        extract(
            {"model": "auto", "messages": [{"role": "system", "content": "be nice"}]}
        )
        is None
    )
    assert extract({"model": "auto"}) is None


def test_multimodal_content_keeps_only_the_text_parts() -> None:
    features = extract(
        {
            "model": "auto",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Explain this screenshot"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64,AAAA"},
                        },
                    ],
                }
            ],
        }
    )
    assert features.newest_message == "Explain this screenshot"


def test_state_is_trimmed_from_the_middle() -> None:
    features = extract(body("x" * 20_000))
    state = build_state(features, 600)
    message = state["request"]["newest_message"]
    assert len(message) <= 610
    assert "\n...\n" in message


def test_prior_turns_counts_only_what_precedes_the_newest_user_message() -> None:
    features = extract(
        {
            "model": "auto",
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "answer"},
                {"role": "user", "content": "second"},
            ],
        }
    )
    assert features.prior_turns == 2
    assert features.newest_message == "second"


def test_cache_serves_then_expires() -> None:
    async def run() -> None:
        cache = RoutingCache(fingerprint="fp", ttl_seconds=0.05)
        calls = 0

        async def compute() -> Decision:
            nonlocal calls
            calls += 1
            return Decision(model="qwen-small", confidence=1.0)

        first = await cache.resolve(exact_key="e", bucket_key="b", compute=compute)
        second = await cache.resolve(exact_key="e", bucket_key="b", compute=compute)
        assert (first.source, second.source) == ("jev", "exact")
        assert calls == 1
        await asyncio.sleep(0.08)
        third = await cache.resolve(exact_key="e", bucket_key="b", compute=compute)
        assert third.source == "jev"
        assert calls == 2

    asyncio.run(run())


def test_identical_concurrent_misses_make_one_call() -> None:
    async def run() -> None:
        cache = RoutingCache(fingerprint="fp")
        calls = 0

        async def compute() -> Decision:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return Decision(model="qwen-large", confidence=1.0)

        results = await asyncio.gather(
            *(
                cache.resolve(exact_key="e", bucket_key="b", compute=compute)
                for _ in range(20)
            )
        )
        assert calls == 1
        assert {r.model for r in results} == {"qwen-large"}
        assert sum(1 for r in results if r.source == "coalesced") == 19

    asyncio.run(run())


def test_a_failed_miss_wakes_the_waiters_with_the_same_error() -> None:
    async def run() -> None:
        cache = RoutingCache(fingerprint="fp")

        async def compute() -> Decision:
            await asyncio.sleep(0.02)
            raise RuntimeError("jev is down")

        results = await asyncio.gather(
            *(
                cache.resolve(exact_key="e", bucket_key="b", compute=compute)
                for _ in range(5)
            ),
            return_exceptions=True,
        )
        assert all(isinstance(r, RuntimeError) for r in results)

    asyncio.run(run())


async def _serve_trickle(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """A Jev that answers within every read timeout and never finishes."""
    await reader.readuntil(b"\r\n\r\n")
    writer.write(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
    )
    try:
        while True:
            writer.write(b"1\r\n \r\n")
            await writer.drain()
            await asyncio.sleep(0.05)
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


def test_the_deadline_is_the_whole_call_not_each_chunk() -> None:
    async def run() -> None:
        server = await asyncio.start_server(_serve_trickle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        settings = RouterSettings(
            jev_api_key="unused",
            jev_base_url=f"http://127.0.0.1:{port}",
            jev_deadline_seconds=0.3,
        )
        client = JevClient(settings)
        try:
            started = asyncio.get_running_loop().time()
            with pytest.raises(JevUnavailable, match="TimeoutError"):
                await client.decide(extract(body("Rename cfg to config")))
            assert asyncio.get_running_loop().time() - started < 1.0
        finally:
            await client.aclose()
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_bucket_level_can_be_switched_off() -> None:
    async def run() -> None:
        cache = RoutingCache(fingerprint="fp", bucket_enabled=False)
        calls = 0

        async def compute() -> Decision:
            nonlocal calls
            calls += 1
            return Decision(model="qwen-small", confidence=1.0)

        await cache.resolve(exact_key="e1", bucket_key="same", compute=compute)
        await cache.resolve(exact_key="e2", bucket_key="same", compute=compute)
        assert calls == 2

    asyncio.run(run())


def test_entries_do_not_survive_a_policy_change() -> None:
    async def run() -> None:
        async def compute() -> Decision:
            return Decision(model="qwen-small", confidence=1.0)

        old = RoutingCache(fingerprint="fp-old")
        await old.resolve(exact_key="e", bucket_key="b", compute=compute)
        assert old.peek("e", "b") is not None
        new = RoutingCache(fingerprint="fp-new")
        assert new.peek("e", "b") is None

    asyncio.run(run())


def test_policy_file_is_what_the_router_asks() -> None:
    policy = catalog.load_policy()
    criteria = build_questions()["route"]["criteria"]
    assert {model.name: model.criterion for model in policy.models} == criteria
    assert build_questions()["route"]["instructions"]["question"] == policy.question


def test_an_empty_focus_is_left_out_rather_than_sent_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(catalog, "QUESTION_FOCUS", "")
    assert "focus" not in build_questions()["route"]["instructions"]


def test_grade_scores_the_house_corpus_against_the_larger_model() -> None:
    every_large = {
        "policy": "test",
        "answers": {
            message: {"model": catalog.CATALOG[-1].name, "confidence": 1.0}
            for message in house.HOUSE_MESSAGES
        },
    }
    result = align.grade(every_large, "house")
    assert result.graded == len(house.HOUSE_MESSAGES)
    assert result.agreed == result.graded
    assert not result.disagreements


def test_grade_names_the_family_behind_a_disagreement() -> None:
    message = house.HOUSE_MESSAGES[0]
    oracle = {
        "policy": "test",
        "answers": {message: {"model": catalog.CATALOG[0].name, "confidence": 0.9}},
    }
    result = align.grade(oracle, "house")
    assert result.graded == 1
    assert result.accuracy == 0.0
    assert result.disagreements[0].family == house.HOUSE_FAMILY_OF[message].name


def test_adopting_a_run_keeps_the_catalogue_order() -> None:
    criteria = {model.name: f"{model.name} criterion" for model in catalog.CATALOG}
    policy = align.policy_from_spec("instructions from the run", criteria)
    assert [model.name for model in policy.models] == [
        model.name for model in catalog.CATALOG
    ]
    assert policy.focus == ""


def test_a_run_naming_a_model_the_gateway_does_not_have_is_refused() -> None:
    with pytest.raises(SystemExit):
        align.policy_from_spec("instructions", {"gpt-9": "anything"})


def test_an_unresolved_proposal_is_refused() -> None:
    with pytest.raises(SystemExit):
        align.spec_from_state(
            {
                "current_candidate": {"instructions": "a", "criteria": {}},
                "pending_candidate": {"instructions": "b", "criteria": {}},
            }
        )


def test_the_shipped_policy_is_the_one_the_recordings_answer() -> None:
    # Every recorded decision and both oracle fixtures are filed under this
    # fingerprint, so a policy edit that forgets to re-record them shows up
    # here rather than as a rig that silently replays nothing.
    fingerprint = policy_fingerprint("jev-latest")
    assert fingerprint == "6ecdbc563f806f13"
    for name in ("oracle.json", "house-oracle.json", "mixed-oracle.json"):
        recorded = json.loads(
            (catalog.POLICY_FILE.parent / "fixtures" / name).read_text()
        )
        assert recorded["policy"] == fingerprint, name
    decisions = json.loads(
        (catalog.POLICY_FILE.parent / "fixtures" / "decisions.json").read_text()
    )
    assert any(item["fingerprint"] == fingerprint for item in decisions)


def test_the_mixed_pool_carries_both_sides_of_the_boundary() -> None:
    messages, labels = align._corpus_labels("mixed")
    models = {labels[message][1] for message in messages}
    assert models == set(catalog.MODEL_NAMES), (
        "a pool with one answer teaches that answer"
    )
    money = [m for m in messages if m in house.HOUSE_FAMILY_OF]
    ordinary = [m for m in messages if m not in house.HOUSE_FAMILY_OF]
    assert len(money) == len(house.HOUSE_MESSAGES)
    assert len(ordinary) == align.MIXED_ORDINARY
    # Every money request goes large however it reads; the ordinary ones split.
    assert {labels[m][1] for m in money} == {catalog.CATALOG[-1].name}
    assert {labels[m][1] for m in ordinary} == set(catalog.MODEL_NAMES)


def test_the_mixed_pool_is_the_same_two_exports_running() -> None:
    first, _ = align._corpus_labels("mixed")
    second, _ = align._corpus_labels("mixed")
    assert first == second


def test_the_aligned_pair_is_filed_under_its_own_policy() -> None:
    # The lab adopts `policy-aligned.json` and then grades
    # `mixed-oracle-aligned.json` against it, so the two have to describe the
    # same question. They are deliberately NOT the shipped fingerprint: adopting
    # them is what moves it.
    fixtures = catalog.POLICY_FILE.parent / "fixtures"
    aligned = catalog.RoutingPolicy.model_validate_json(
        (fixtures / "policy-aligned.json").read_text()
    )
    recorded = json.loads((fixtures / "mixed-oracle-aligned.json").read_text())
    assert recorded["policy"] == align._fingerprint_of(aligned, "jev-latest")
    assert recorded["policy"] != policy_fingerprint("jev-latest")
    assert len(recorded["answers"]) == len(align._corpus_labels("mixed")[0])


@pytest.mark.unit
@pytest.mark.parametrize(
    ("jev_base_url", "typesafe_base_url", "expected"),
    [
        ("", "", "https://api.typesafe.ai"),
        ("", "https://openrouter.ai/api", "https://openrouter.ai/api"),
        (
            "http://host.docker.internal:9099",
            "https://openrouter.ai/api",
            "http://host.docker.internal:9099",
        ),
    ],
)
def test_the_stand_in_knob_beats_the_host_the_key_is_good_for(
    monkeypatch: pytest.MonkeyPatch,
    jev_base_url: str,
    typesafe_base_url: str,
    expected: str,
) -> None:
    # Compose passes an unset shell variable through as an empty string.
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "a-key")
    monkeypatch.setenv("JEV_BASE_URL", jev_base_url)
    monkeypatch.setenv("TYPESAFE_BASE_URL", typesafe_base_url)
    assert RouterSettings.from_env().jev_base_url == expected


@pytest.mark.unit
@pytest.mark.parametrize("key", ["", "a-key"])
def test_failure_exercises_override_replay_and_cleanup_restores_it(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
) -> None:
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", key)
    monkeypatch.setenv("JEV_FIXTURES", "1")
    monkeypatch.delenv("JEV_BASE_URL", raising=False)
    assert isinstance(build_client(RouterSettings.from_env()), FixtureClient)

    monkeypatch.setenv("JEV_BASE_URL", "http://host.docker.internal:9099")
    client = build_client(RouterSettings.from_env())
    assert isinstance(client, JevClient)
    try:
        assert str(client._client.base_url) == "http://host.docker.internal:9099"
        assert client._client.headers.get("Authorization") == (
            f"Bearer {key}" if key else None
        )
    finally:
        asyncio.run(client.aclose())

    monkeypatch.delenv("JEV_BASE_URL")
    assert isinstance(build_client(RouterSettings.from_env()), FixtureClient)


@pytest.mark.unit
def test_a_stand_in_url_alone_does_not_enable_keyless_provider_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    monkeypatch.setenv("JEV_FIXTURES", "0")
    monkeypatch.setenv("JEV_BASE_URL", "http://host.docker.internal:9099")
    with pytest.raises(SystemExit, match="TYPESAFE_API_KEY is not set"):
        RouterSettings.from_env()


@pytest.mark.unit
def test_the_seed_names_the_sandbox_model_when_the_key_is_openrouters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "a-key")
    monkeypatch.setenv("ZENABLE_SANDBOX_MODEL", "anthropic/claude-haiku-4.5")
    assert align._sandbox_reflection_model() == "openrouter/anthropic/claude-haiku-4.5"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert align._sandbox_reflection_model() is None


@pytest.mark.unit
def test_the_seed_asks_jeva_for_the_routers_jev_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    GIVEN no --jev-model on the seed command
    WHEN the seed writes the jeva command
    THEN it names the model the router asks, not jeva's pinned release
    """
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = tmp_path / "jeva-run.sh"

    assert align.main(["seed", "--data", "pool.csv", "--out", str(out)]) == 0

    script = out.read_text()
    assert "--jev-model 'jev-latest'" in script
    assert script.index("--jev-model") < script.index("--batch-size")
