#!/usr/bin/env bash
# Regenerate everything in evidence/ from the running rig.
#
# The lab quotes these files verbatim. Regenerating them is how we find out
# that a Keycloak upgrade changed a claim name before a reader does.
set -euo pipefail

cd "$(dirname "$0")/.."
# Default is the public layout, where evidence/ sits inside the lab directory.
# In the authoring repo it is a sibling of rig/, so the updater passes
# EVIDENCE_DIR=../evidence.
mkdir -p "${EVIDENCE_DIR:-evidence}"
EV="$(cd "${EVIDENCE_DIR:-evidence}" && pwd)"

echo "==> versions"
{
  docker compose exec -T keycloak /opt/keycloak/bin/kc.sh --version 2>/dev/null | head -1
  echo "docker: $(docker version --format '{{.Server.Version}}')"
  (cd agent && uv run python -c "
import importlib.metadata as m
for pkg in ('pyjwt', 'sd-jwt', 'jwcrypto', 'cryptography', 'httpx'):
    print(f'{pkg}: {m.version(pkg)}')
import sys; print(f'python: {sys.version.split()[0]}')")
} > "$EV"/versions.txt

echo "==> discovery + jwks"
curl -fsS http://localhost:8080/realms/agent-identity/.well-known/openid-configuration \
  | python3 -m json.tool > "$EV"/discovery.json
curl -fsS http://localhost:8080/realms/agent-identity/protocol/openid-connect/certs \
  | python3 -m json.tool > "$EV"/jwks.json

echo "==> tokens (bound vs bearer)"
(cd agent && uv run python dump_tokens.py) > "$EV"/tokens-decoded.txt

echo "==> credential (issued, presented, verified)"
(cd agent && uv run python dump_credential.py) > "$EV"/sdjwt-walkthrough.txt

echo "==> negative tests"
(cd agent && uv run python negative_tests.py) > "$EV"/negative-tests.txt

echo
echo "$EV regenerated:"
ls -la "$EV"
