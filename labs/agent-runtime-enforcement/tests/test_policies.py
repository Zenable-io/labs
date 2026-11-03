# Copyright (c) 2026 Zenable, Inc.
from pathlib import Path

import pytest
import yaml

RIG = Path(__file__).resolve().parents[1]

TEMPLATES = sorted((RIG / "policies").glob("*.yaml.tmpl"))


GOOSE_BIN = "/home/learner/.local/bin/goose"


def rendered(template: Path, goose_bin: str = GOOSE_BIN) -> dict:
    return yaml.safe_load(template.read_text().replace("${GOOSE_BIN}", goose_bin))


def is_goose_own_https(selector: dict) -> bool:
    return any(
        arg["operator"] == "DPort" and arg["values"] == ["443"]
        for arg in selector.get("matchArgs", [])
    )


@pytest.mark.unit
def test_every_policy_is_scoped_to_the_agent_tree():
    for template in TEMPLATES:
        policy = rendered(template)
        for probe in policy["spec"]["kprobes"]:
            for selector in probe["selectors"]:
                binaries = selector["matchBinaries"][0]
                assert binaries["values"] == [GOOSE_BIN], (
                    f"{template.name}: {probe['call']} would match every process"
                )
                if not is_goose_own_https(selector):
                    assert binaries.get("followChildren") is True, (
                        f"{template.name}: {probe['call']} misses goose's children"
                    )


@pytest.mark.unit
def test_enforce_lets_only_goose_itself_reach_443():
    enforce = rendered(RIG / "policies" / "20-enforce.yaml.tmpl")
    connect = next(p for p in enforce["spec"]["kprobes"] if p["call"] == "tcp_connect")
    first = connect["selectors"][0]
    assert is_goose_own_https(first)
    assert "followChildren" not in first["matchBinaries"][0]
    assert "matchActions" not in first
    assert not any(is_goose_own_https(s) for s in connect["selectors"][1:])


@pytest.mark.unit
def test_enforce_is_observe_plus_actions_only():
    observe = rendered(RIG / "policies" / "10-observe.yaml.tmpl")
    enforce = rendered(RIG / "policies" / "20-enforce.yaml.tmpl")
    assert [p["call"] for p in observe["spec"]["kprobes"]] == [
        p["call"] for p in enforce["spec"]["kprobes"]
    ]
    for probe in enforce["spec"]["kprobes"]:
        for selector in probe["selectors"]:
            if not is_goose_own_https(selector):
                assert selector["matchActions"] == [{"action": "Sigkill"}]
    for probe in observe["spec"]["kprobes"]:
        for selector in probe["selectors"]:
            assert "matchActions" not in selector


@pytest.mark.unit
def test_enforce_keeps_loopback_open_for_the_model():
    enforce = rendered(RIG / "policies" / "20-enforce.yaml.tmpl")
    connect = next(p for p in enforce["spec"]["kprobes"] if p["call"] == "tcp_connect")
    addr = next(
        a
        for selector in connect["selectors"]
        for a in selector.get("matchArgs", [])
        if a["operator"] == "NotDAddr"
    )
    assert "127.0.0.0/8" in addr["values"]
    assert "::1/128" in addr["values"]
