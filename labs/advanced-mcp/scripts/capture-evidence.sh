#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc.
set -euo pipefail

rig_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
capture_dir="${EVIDENCE_DIR:-${rig_dir}/evidence}"
mkdir -p "${capture_dir}"
capture_dir="$(cd -- "${capture_dir}" && pwd)"
cd "${rig_dir}"

for demo in step-up auth-errors cache-ttl cache-client cache-public cache-server cache-auth retry; do
  uv run --locked python -m advanced_mcp "${demo}" > "${capture_dir}/${demo}.txt"
done
