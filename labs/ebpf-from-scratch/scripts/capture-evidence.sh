#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc. Reruns the lab's kernel-facing steps on the sandbox (needs sudo for the BPF
# loads) and writes the raw output to evidence/.
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
  ls -la /sys/kernel/btf/vmlinux
  clang --version | head -1
  bpftool version | head -1
  bpftrace --version
  uv run python --version
} > "${EV}/versions.txt" 2>&1

echo "==> build"
make clean > /dev/null 2>&1
make > "${EV}/make.txt" 2>&1
llvm-objdump -h bpf/agentwatch.bpf.o > "${EV}/objdump-agentwatch.txt" 2>&1

echo "==> kill is a race, deny is not"
{
  echo "--- --kill: strace shows the open returned before the signal"
  sudo uv run python agentwatch.py --kill -- strace -e trace=openat,read -o /tmp/agentwatch-strace.out cat decoys/.aws/credentials
  echo "exit=$?"
  tail -4 /tmp/agentwatch-strace.out
  echo "--- --deny: the open fails"
  sudo uv run python agentwatch.py --deny -- cat decoys/.aws/credentials
  echo "exit=$?"
} > "${EV}/kill-vs-deny.txt" 2>&1
