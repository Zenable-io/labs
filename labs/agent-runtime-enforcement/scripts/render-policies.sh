#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc. Render policies/*.yaml.tmpl into policies/rendered/ with this machine's
# goose path filled in. Tetragon matches binaries by absolute path, and goose
# installs under whoever's home ran the installer.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GOOSE_BIN="${GOOSE_BIN:-$(command -v goose || true)}"
if [[ -z "${GOOSE_BIN}" ]]; then
  echo "goose is not on PATH; install it or set GOOSE_BIN" >&2
  exit 1
fi
# Resolve the symlink the installer may have left, so the policy names the
# file the kernel actually execs.
if [[ -e "${GOOSE_BIN}" ]]; then
  GOOSE_BIN="$(readlink -f "${GOOSE_BIN}")"
fi
export GOOSE_BIN

mkdir -p "${HERE}/policies/rendered"
for tmpl in "${HERE}"/policies/*.yaml.tmpl; do
  out="${HERE}/policies/rendered/$(basename "${tmpl%.tmpl}")"
  envsubst "\${GOOSE_BIN}" < "${tmpl}" > "${out}"
  echo "rendered ${out##*/} for ${GOOSE_BIN}"
done
