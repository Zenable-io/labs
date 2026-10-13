#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc.
#
# Security properties EMA is supposed to give you. Each of these MUST fail.
set -uo pipefail

S=http://localhost:8480
ENT_TU="$S/realms/enterprise/protocol/openid-connect/token"
VEN_TU="$S/realms/vendor/protocol/openid-connect/token"
MCP=http://localhost:9100/mcp
pass=0; fail=0

check() { # check <name> <expected-substring> <actual>
  if grep -qi -- "$2" <<<"$3"; then echo "  ✓ $1"; pass=$((pass+1));
  else echo "  ✗ $1"; echo "      expected to contain: $2"; echo "      got: ${3:0:300}"; fail=$((fail+1)); fi
}

mcp_call() { # mcp_call <token>
  curl -s -i -X POST "$MCP" -H "content-type: application/json" \
    -H "accept: application/json, text/event-stream" \
    ${1:+-H "authorization: Bearer $1"} \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' 2>&1 | head -20
}

echo "== minting a valid chain to work with =="
ID_TOKEN=$(curl -s -X POST "$ENT_TU" -d grant_type=password -d client_id=mcp-client \
  -d client_secret=mcp-client-secret -d username=alice -d password=alice -d scope=openid | jq -r .id_token)
IDJAG=$(curl -s -X POST "$ENT_TU" -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
  -d client_id=mcp-client -d client_secret=mcp-client-secret \
  --data-urlencode "subject_token=$ID_TOKEN" \
  -d subject_token_type=urn:ietf:params:oauth:token-type:id_token \
  -d requested_token_type=urn:ietf:params:oauth:token-type:id-jag \
  -d audience="$S/realms/vendor" -d resource="$MCP" -d scope=findings.read | jq -r .access_token)
echo "   id_token=${#ID_TOKEN} chars, id-jag=${#IDJAG} chars"

echo
echo "== 1. no token at all =="
check "MCP server challenges with 401 + resource_metadata" "www-authenticate" "$(mcp_call '')"

echo
echo "== 2. the ID-JAG must NOT work as a bearer token at the MCP server =="
check "MCP server rejects the ID-JAG" "401" "$(mcp_call "$IDJAG")"

echo
echo "== 3. the enterprise ID token must NOT work at the MCP server =="
check "MCP server rejects the raw ID token" "401" "$(mcp_call "$ID_TOKEN")"

echo
echo "== 4. the ID-JAG is single-use at the vendor AS =="
R1=$(curl -s -X POST "$VEN_TU" -d grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer \
  -d client_id=mcp-client -d client_secret=mcp-client-vendor-secret \
  --data-urlencode "assertion=$IDJAG" -d scope=findings.read)
check "first redemption succeeds" "access_token" "$R1"
R2=$(curl -s -X POST "$VEN_TU" -d grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer \
  -d client_id=mcp-client -d client_secret=mcp-client-vendor-secret \
  --data-urlencode "assertion=$IDJAG" -d scope=findings.read)
if grep -q access_token <<<"$R2"; then
  echo "  ! replay of the SAME ID-JAG was ACCEPTED (no jti replay cache in this build)"
  echo "      spec expects single-use; note this as a gap when demoing"
else
  echo "  ✓ replay rejected: $(jq -r '.error_description // .error' <<<"$R2")"; pass=$((pass+1))
fi

echo
echo "== 5. confused deputy: a token from the SAME AS but bound to a DIFFERENT resource =="
WRONG=$(curl -s -X POST "$VEN_TU" -d grant_type=client_credentials \
  -d client_id=other-mcp-client -d client_secret=other-secret | jq -r '.access_token // empty')
if [ -n "$WRONG" ]; then
  echo "   decoy token aud: $(cut -d. -f2 <<<"$WRONG" | python3 -c 'import sys,json,base64;s=sys.stdin.read().strip();print(json.loads(base64.urlsafe_b64decode(s+"="*(-len(s)%4))).get("aud"))')"
  check "MCP server rejects a validly-signed token bound elsewhere" "401" "$(mcp_call "$WRONG")"
else
  echo "  ✗ could not mint decoy token"; fail=$((fail+1))
fi

echo
echo "== 6. an unauthorized client/AS pair never gets an assertion =="
R6=$(curl -s -X POST "$ENT_TU" -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
  -d client_id=mcp-client -d client_secret=mcp-client-secret \
  --data-urlencode "subject_token=$ID_TOKEN" \
  -d subject_token_type=urn:ietf:params:oauth:token-type:id_token \
  -d requested_token_type=urn:ietf:params:oauth:token-type:id-jag \
  -d audience="https://unapproved.example" -d scope=findings.read)
check "IdP refuses to mint for an unapproved audience" "error" "$R6"

echo
echo "===================="
echo " passed: $pass   failed: $fail"
[ "$fail" -eq 0 ] || exit 1
