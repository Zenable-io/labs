#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc. Reruns the lab's kernel-facing steps on the sandbox and writes the raw output
# to evidence/. Everything quoted in the published lab comes from these files
# or from the e2e transcript refresh.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${HERE}" || exit 1
EV="${EVIDENCE_DIR:-${HERE}/evidence}"
mkdir -p "${EV}" || exit 1
EV="$(cd "${EV}" && pwd)" || exit 1

echo "==> versions"
{
  echo "captured: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  uname -r
  strace --version | head -1
  docker --version
  goose --version
  uv run python --version
} > "${EV}/versions.txt" 2>&1

echo "==> the filter, disassembled"
uv run python seccomp_sandbox.py --deny connect --show > "${EV}/filter-connect.txt" 2>&1

echo "==> denied connect, denied openat"
{
  echo "--- --deny connect --action errno"
  uv run python seccomp_sandbox.py --deny connect -- curl -sS --max-time 5 https://example.com/
  echo "exit=$?"
  echo "--- --deny openat --action kill"
  uv run python seccomp_sandbox.py --deny openat --action kill -- cat decoys/.aws/credentials
  echo "exit=$?"
} > "${EV}/negative-tests.txt" 2>&1

echo "==> syscall summary of one agent run"
strace -f -c -o "${EV}/agent-strace.txt" ./run-agent.sh > /dev/null 2>&1
uv run python profile_from_strace.py "${EV}/agent-strace.txt" > "${EV}/agent-seccomp.json" 2> "${EV}/agent-seccomp.count.txt"
