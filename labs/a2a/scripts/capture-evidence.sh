#!/usr/bin/env bash
# Reruns every step of the lab and writes the raw output to evidence/.
# Everything quoted in the published lab comes from these files.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Default is the public layout, where evidence/ sits inside the lab directory.
# In the authoring repo it is a sibling of rig/, so the updater passes
# EVIDENCE_DIR=../evidence.
mkdir -p "${EVIDENCE_DIR:-${HERE}/evidence}"
EV="$(cd "${EVIDENCE_DIR:-${HERE}/evidence}" && pwd)"
cd "${HERE}/agents" || exit 1

echo "==> versions"
{
  echo "captured: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  uv run python -c "import importlib.metadata as m; print('a2a-sdk', m.version('a2a-sdk'))"
  uv run python -c "from a2a.utils.constants import PROTOCOL_VERSION_CURRENT as v, AGENT_CARD_WELL_KNOWN_PATH as p; print('protocol', v); print('card path', p)"
  docker inspect --format '{{index .Config.Image}}' a2a-keycloak
  uv run python --version
} > "${EV}/versions.txt" 2>&1

echo "==> agent cards"
curl -s http://localhost:9001/.well-known/agent-card.json | python3 -m json.tool > "${EV}/card-forecast-signed.json"
curl -s http://localhost:9002/.well-known/agent-card.json | python3 -m json.tool > "${EV}/card-planner.json"
curl -s http://localhost:9009/.well-known/agent-card.json | python3 -m json.tool > "${EV}/card-rogue.json"

echo "==> keycloak discovery + jwks"
curl -s http://localhost:8080/realms/a2a-workshop/.well-known/openid-configuration \
  | python3 -m json.tool > "${EV}/keycloak-discovery.json"
curl -s http://localhost:8080/realms/a2a-workshop/protocol/openid-connect/certs \
  | python3 -m json.tool > "${EV}/keycloak-jwks.json"

echo "==> decoded tokens for every client"
{
  for pair in agent-a-forecast:agent-a-secret agent-b-planner:agent-b-secret \
              workshop-cli:workshop-cli-secret agent-c-stranger:agent-c-secret; do
    id="${pair%%:*}"; secret="${pair##*:}"
    echo "--- ${id}"
    "${HERE}/scripts/get-token.sh" "${id}" "${secret}" \
      | "${HERE}/scripts/decode-jwt.py" \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); p=d["payload"]; print(json.dumps({k:p.get(k) for k in ("iss","aud","azp","scope","typ","exp")}, indent=2))'
  done
} > "${EV}/tokens-decoded.txt" 2>&1

echo "==> end to end, both directions"
TOKEN="$("${HERE}/scripts/get-token.sh" workshop-cli workshop-cli-secret)"
: > /tmp/forecast.log
{
  echo "--- CLI -> Planner -> Forecast (clear weather)"
  uv run python -c "
import asyncio
from a2a_client_util import send_text
print(asyncio.run(send_text('http://localhost:9002','plan a day in Lisbon',token='${TOKEN}')))
" 2>&1
  echo
  echo "--- CLI -> Planner -> Forecast -> (severe) Forecast calls back into Planner"
  uv run python -c "
import asyncio
from a2a_client_util import send_text
print(asyncio.run(send_text('http://localhost:9002','plan a day in Reykjavik',token='${TOKEN}')))
" 2>&1
  sleep 3
  echo
  echo "--- forecast agent log showing the reverse call"
  cat /tmp/forecast.log
} > "${EV}/end-to-end.txt" 2>&1

echo "==> extended agent card"
# Agent A's audience, so it must be the planner's token, not the CLI's.
TOKEN_FOR_A="$("${HERE}/scripts/get-token.sh" agent-b-planner agent-b-secret)"
uv run python -c "
import asyncio, httpx
from a2a.client import create_client, AuthInterceptor, ClientConfig
from a2a.types import GetExtendedAgentCardRequest
from a2a_client_util import StaticTokenCredentials

async def main():
    async with httpx.AsyncClient(timeout=30) as http:
        client = await create_client(
            'http://localhost:9001',
            client_config=ClientConfig(httpx_client=http, streaming=False),
            interceptors=[AuthInterceptor(StaticTokenCredentials('${TOKEN_FOR_A}'))],
        )
        card = await client.get_extended_agent_card(GetExtendedAgentCardRequest())
        print('skills on the EXTENDED card:', [s.id for s in card.skills])

asyncio.run(main())
" > "${EV}/extended-card.txt" 2>&1
python3 -c "
import json
public = json.load(open('${EV}/card-forecast-signed.json'))
print('skills on the PUBLIC card:', [s['id'] for s in public['skills']])
" >> "${EV}/extended-card.txt" 2>&1

echo "==> negative tests"
"${HERE}/scripts/negative-tests.sh" > "${EV}/negative-tests.txt" 2>&1

echo "==> rogue card: attack, then defense"
TOKEN_B="$("${HERE}/scripts/get-token.sh" agent-b-planner agent-b-secret)"
: > /tmp/rogue.log
{
  echo "### ATTACK: client does not verify the card signature"
  uv run python -c "
import asyncio
from a2a_client_util import send_text
print('client saw:', asyncio.run(send_text('http://localhost:9009','forecast for Lisbon',token='${TOKEN_B}')))
" 2>&1 | grep -v '^\[client\]'
  echo "--- what the rogue captured:"
  cat /tmp/rogue.log
  echo
  echo "### DEFENSE: same call, signature verification on"
  : > /tmp/rogue.log
  uv run python -c "
import asyncio
from a2a_client_util import send_text
try:
    print('client saw:', asyncio.run(send_text('http://localhost:9009','forecast for Lisbon',token='${TOKEN_B}',verify_signature=True)))
except Exception as e:
    print(f'client refused: {type(e).__name__}: {e}')
" 2>/dev/null
  echo "--- bytes the rogue captured this time: $(wc -c < /tmp/rogue.log | tr -d ' ')"
  echo
  echo "### CONTROL: verifying client against the real, signed agent"
  uv run python -c "
import asyncio
from a2a_client_util import send_text
print('client saw:', asyncio.run(send_text('http://localhost:9001','forecast for Lisbon',token='${TOKEN_B}',verify_signature=True)))
" 2>/dev/null | grep -v '^\[client\]'
} > "${EV}/rogue-card.txt" 2>&1

echo
echo "Evidence written to ${EV}:"
ls -1 "${EV}"
