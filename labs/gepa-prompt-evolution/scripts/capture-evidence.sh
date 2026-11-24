#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc. Reruns every step of the lab with a key and writes the raw output to evidence/.
# Everything quoted in the published lab comes from these files. Run `record`
# first so the replay steps have fixtures; every other step here is live, so
# this costs model calls.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Default is the public layout, where evidence/ sits inside the lab directory.
# In the authoring repo it is a sibling of rig/, so the updater passes
# EVIDENCE_DIR=../evidence.
mkdir -p "${EVIDENCE_DIR:-${HERE}/evidence}"
EV="$(cd "${EVIDENCE_DIR:-${HERE}/evidence}" && pwd)"
cd "${HERE}" || exit 1
rm -rf runs

run() {
  local name="$1"
  shift
  echo "==> ${name}"
  uv run --locked python -m gepalab "$@" > "${EV}/${name}.txt" 2>&1
}

run 01-baseline baseline --misses 2
run 02-select select --seed 0
run 03-feedback feedback
run 04-reflection evolve --fixtures --refinements 1 --out runs/reflection
run 05-merge merge
run 06-live evolve --refinements 3 --out runs/live
run 07-replay evolve --fixtures --refinements 3 --out runs/replay
run 08-show show runs/reflection/run.json --lineage
cp runs/live/optimizer.log "${EV}/09-live-optimizer.log"

echo
echo "Evidence written to ${EV}:"
ls -1 "${EV}"
