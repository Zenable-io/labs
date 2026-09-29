#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc. Reruns the policy-facing steps on the sandbox with the compose stack up and
# nono installed, and writes the raw output to evidence/.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${HERE}" || exit 1
EV="${EVIDENCE_DIR:-${HERE}/evidence}"
mkdir -p "${EV}" || exit 1
EV="$(cd "${EV}" && pwd)" || exit 1

echo "==> versions and kernel features"
{
  echo "captured: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  uname -r
  cat /sys/kernel/security/lsm
  docker compose exec -T tetragon tetra version
  docker compose exec -T collector /otelcol-contrib --version
  nono --version
  goose --version
  uv run python -c "import importlib.metadata as m; print('nono-py', m.version('nono-py'))"
} > "${EV}/versions.txt" 2>&1

echo "==> policies as loaded"
docker compose exec -T tetragon tetra tracingpolicy list > "${EV}/tracingpolicy-list.txt" 2>&1

echo "==> nono dry run and why"
{
  nono run --dry-run -v --allow-cwd --open-port 11434 -- ./run-agent.sh
  echo "--- why: decoy path under the agent profile"
  nono why --profile agent --path "${HERE}/decoys/.aws/credentials" --op read
  echo "--- why: example.com under the agent profile"
  nono why --profile agent --host example.com --port 443
} > "${EV}/nono-policy.txt" 2>&1

echo "==> nono-py negative tests"
{
  echo "--- cat decoys/.aws/credentials"
  uv run python nono_agent.py -- cat decoys/.aws/credentials
  echo "exit=$?"
  echo "--- curl example.com"
  uv run python nono_agent.py -- curl -sS --max-time 5 https://example.com/
  echo "exit=$?"
} > "${EV}/nono-negative-tests.txt" 2>&1
