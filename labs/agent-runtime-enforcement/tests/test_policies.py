# Copyright (c) 2026 Zenable, Inc.
from pathlib import Path

import pytest
import yaml

RIG = Path(__file__).resolve().parents[1]

TEMPLATES = sorted((RIG / "policies").glob("*.yaml.tmpl"))


def rendered(template: Path, goose_bin: str = "/home/learner/.local/bin/goose") -> dict:
    return yaml.safe_load(template.read_text().replace("${GOOSE_BIN}", goose_bin))


@pytest.mark.unit
def test_every_policy_is_scoped_to_the_agent_tree():
    for template in TEMPLATES:
        policy = rendered(template)
        for probe in policy["spec"]["kprobes"]:
            for selector in probe["selectors"]:
                binaries = selector["matchBinaries"][0]
                assert binaries["followChildren"] is True, (
                    f"{template.name}: {probe['call']} would match every process"
                )
                assert binaries["values"] == ["/home/learner/.local/bin/goose"]


@pytest.mark.unit
def test_enforce_is_observe_plus_actions_only():
    observe = rendered(RIG / "policies" / "10-observe.yaml.tmpl")
    enforce = rendered(RIG / "policies" / "20-enforce.yaml.tmpl")
    assert [p["call"] for p in observe["spec"]["kprobes"]] == [
        p["call"] for p in enforce["spec"]["kprobes"]
    ]
    for probe in enforce["spec"]["kprobes"]:
        for selector in probe["selectors"]:
            assert selector["matchActions"] == [{"action": "Sigkill"}]
    for probe in observe["spec"]["kprobes"]:
        for selector in probe["selectors"]:
            assert "matchActions" not in selector


@pytest.mark.unit
def test_enforce_keeps_loopback_open_for_the_model():
    enforce = rendered(RIG / "policies" / "20-enforce.yaml.tmpl")
    connect = next(p for p in enforce["spec"]["kprobes"] if p["call"] == "tcp_connect")
    addr = next(
        a for a in connect["selectors"][0]["matchArgs"] if a["operator"] == "NotDAddr"
    )
    assert "127.0.0.0/8" in addr["values"]
    assert "::1/128" in addr["values"]
