# Copyright (c) 2026 Zenable, Inc.
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

RIG = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_render_script_substitutes_only_the_goose_path(tmp_path: Path) -> None:
    script = tmp_path / "scripts/render-policies.sh"
    script.parent.mkdir()
    shutil.copy2(RIG / "scripts/render-policies.sh", script)
    policies = tmp_path / "policies"
    policies.mkdir()
    for template in (RIG / "policies").glob("*.yaml.tmpl"):
        (policies / template.name).write_text(template.read_text() + "\n# ${HOME}\n")
    env = dict(os.environ, GOOSE_BIN="/opt/goose/goose", HOME=str(tmp_path))

    subprocess.run(["bash", str(script)], check=True, env=env, capture_output=True)

    text = (policies / "rendered/10-observe.yaml").read_text()
    assert "# ${HOME}" in text
    out = yaml.safe_load(text)
    values = out["spec"]["kprobes"][0]["selectors"][0]["matchBinaries"][0]["values"]
    assert values == ["/opt/goose/goose"]
