#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc. Fetch a client_credentials access token for one agent. Prints the raw JWT.
#
#   ./scripts/get-token.sh agent-b-planner agent-b-secret
set -euo pipefail

CLIENT_ID="${1:?usage: get-token.sh <client-id> <client-secret> [scope]}"
CLIENT_SECRET="${2:?usage: get-token.sh <client-id> <client-secret> [scope]}"
ISSUER="${ISSUER:-http://localhost:8080/realms/a2a-workshop}"

args=(-d grant_type=client_credentials -d "client_id=${CLIENT_ID}" -d "client_secret=${CLIENT_SECRET}")
[[ $# -ge 3 ]] && args+=(-d "scope=$3")

curl -sf -X POST "${ISSUER}/protocol/openid-connect/token" "${args[@]}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
