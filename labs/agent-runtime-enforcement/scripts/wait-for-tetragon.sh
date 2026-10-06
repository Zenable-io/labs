#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc. `docker compose up --wait` returns when the container is up, which for
# Tetragon is before its BPF programs are loaded and its gRPC server answers.
# Poll the server through the same CLI the lab uses until it does.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${HERE}" || exit 1

for _ in $(seq 1 60); do
  if docker compose exec -T tetragon tetra status >/dev/null 2>&1; then
    echo "tetragon is answering"
    exit 0
  fi
  sleep 2
done
echo "tetragon never answered on its gRPC port; check: docker compose logs tetragon" >&2
exit 1
