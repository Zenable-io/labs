#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc. Install one pinned nono release into ~/.local/bin, verified against the
# checksum file the release publishes. The static musl build is chosen on
# purpose: the sandbox userland is glibc 2.28, and musl asks nothing of it.
set -euo pipefail

NONO_VERSION="${NONO_VERSION:-0.77.0}"
ARCH="$(uname -m)"
ASSET="nono-v${NONO_VERSION}-${ARCH}-unknown-linux-musl.tar.gz"
BASE="https://github.com/nolabs-ai/nono/releases/download/v${NONO_VERSION}"
DEST="${HOME}/.local/bin"

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT
cd "${work}"

curl -fsSL -o "${ASSET}" "${BASE}/${ASSET}"
curl -fsSL -o SHA256SUMS.txt "${BASE}/SHA256SUMS.txt"
grep " ${ASSET}\$" SHA256SUMS.txt | sha256sum -c -

mkdir -p "${DEST}"
tar -xzf "${ASSET}"
install -m 0755 "$(find . -type f -name nono | head -1)" "${DEST}/nono"
"${DEST}/nono" --version
