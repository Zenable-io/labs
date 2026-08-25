#!/usr/bin/env bash
# Regenerate everything in evidence/ from the running rig.
#
# The lab quotes these files verbatim. Regenerating them is how we find out
# that a Keycloak upgrade changed a claim name before a reader does.
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p evidence

echo "==> versions"
{
  docker compose exec -T keycloak /opt/keycloak/bin/kc.sh --version 2>/dev/null | head -1
  echo "docker: $(docker version --format '{{.Server.Version}}')"
  (cd agent && uv run python -c "
import importlib.metadata as m
for pkg in ('pyjwt', 'sd-jwt', 'jwcrypto', 'cryptography', 'httpx'):
    print(f'{pkg}: {m.version(pkg)}')
import sys; print(f'python: {sys.version.split()[0]}')")
} > evidence/versions.txt

echo "==> discovery + jwks"
curl -fsS http://localhost:8080/realms/agent-identity/.well-known/openid-configuration \
  | python3 -m json.tool > evidence/discovery.json
curl -fsS http://localhost:8080/realms/agent-identity/protocol/openid-connect/certs \
  | python3 -m json.tool > evidence/jwks.json

echo "==> tokens (bound vs bearer)"
(cd agent && uv run python dump_tokens.py) > evidence/tokens-decoded.txt

echo "==> credential (issued, presented, verified)"
(cd agent && uv run python dump_credential.py) > evidence/sdjwt-walkthrough.txt

echo "==> negative tests"
(cd agent && uv run python negative_tests.py) > evidence/negative-tests.txt

echo
echo "evidence/ regenerated:"
ls -la evidence/
