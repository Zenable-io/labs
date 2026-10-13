#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc. Six ways to be refused. Each isolates ONE rule, so a rejection can only be
# explained by the rule under test.
#
# Run with both agents up:  ./scripts/negative-tests.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORECAST="http://localhost:9001/"
# A2A 1.0 JSON-RPC method names are the PascalCase RPC names. The 0.x
# `message/send` form is gone unless the server opts into compat, and it is
# still what most tutorials on the internet show.
RPC='{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"role":"ROLE_USER","parts":[{"text":"forecast for Lisbon"}],"messageId":"m1"}}}'

call() {
  local label="$1" token="${2:-}"
  # Without A2A-Version the handler assumes 0.3 and refuses the request.
  # The SDK client sets this for you; curl does not.
  local args=(-s -o /tmp/neg-body.json -w '%{http_code}' -X POST "${FORECAST}"
    -H 'content-type: application/json' -H 'A2A-Version: 1.0' -d "${RPC}")
  [[ -n "${token}" ]] && args+=(-H "authorization: Bearer ${token}")
  local code
  code=$(curl "${args[@]}")
  printf '%-34s HTTP %s  %s\n' "${label}" "${code}" "$(head -c 120 /tmp/neg-body.json)"
}

echo "=== 1. No token at all ==="
call "no credentials" ""

echo
echo "=== 2. Wrong audience (token minted for Agent B) ==="
call "aud=agent-b-planner" "$("${HERE}/scripts/get-token.sh" workshop-cli workshop-cli-secret)"

echo
echo "=== 3. Right audience, wrong scope ==="
call "scope=forecast:write" "$("${HERE}/scripts/get-token.sh" agent-c-stranger agent-c-secret)"

echo
echo "=== 4. Expired token ==="
EXPIRING="$("${HERE}/scripts/get-token.sh" agent-d-expiring agent-d-secret)"
echo "    (token lifespan is 1s; sleeping 3s to let it die)"
sleep 3
call "expired" "${EXPIRING}"

echo
echo "=== 5. Valid token from a different trust domain ==="
call "iss=rogue-realm" "$(ISSUER=http://localhost:8080/realms/rogue-realm \
  "${HERE}/scripts/get-token.sh" impostor impostor-secret)"

echo
echo "=== 6. Garbage that is not a JWT ==="
call "not-a-jwt" "obviously-not-a-token"

echo
echo "=== Control: the request that SHOULD work ==="
call "aud+scope correct" "$("${HERE}/scripts/get-token.sh" agent-b-planner agent-b-secret)"
