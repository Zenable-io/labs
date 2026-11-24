#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc. `docker compose up --wait` returns when the container is up, which for
# Tetragon is before its gRPC server answers and before the startup policy has
# finished loading. Adding or deleting a policy while one is still loading can
# take Tetragon down, so wait for the observe policy to report enabled.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${HERE}" || exit 1

for _ in $(seq 1 60); do
  state="$(docker compose exec -T tetragon tetra tracingpolicy list 2>/dev/null \
    | awk '$2 == "agent-observe" { print $3 }')"
  if [[ "${state}" == "enabled" ]]; then
    echo "tetragon is answering, agent-observe enabled"
    exit 0
  fi
  sleep 2
done
echo "agent-observe never reached enabled; check: docker compose logs tetragon" >&2
exit 1
