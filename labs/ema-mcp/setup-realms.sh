#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc.
#
# Two-realm EMA topology in one Keycloak:
#
#   realm "enterprise"  = the CUSTOMER's IdP.       Issues ID-JAG. Owns admin policy.
#   realm "vendor"      = the MCP VENDOR's Resource AS. Consumes ID-JAG -> access token.
#
# The two realms are separate trust domains: "vendor" trusts "enterprise" only via an
# explicitly configured jwt-authorization-grant IdP pinned to its issuer + JWKS.
set -euo pipefail

KC="${KC:-docker exec -i kc-idjag /opt/keycloak/bin/kcadm.sh}"
SERVER="${SERVER:-http://localhost:8480}"
ENT="${ENT:-enterprise}"
VEN="${VEN:-vendor}"

# Identifier of the vendor's Resource Authorization Server. Goes in the ID-JAG `aud`.
AS_ID="${AS_ID:-http://localhost:8480/realms/vendor}"
# Canonical resource identifier of the MCP server itself. Goes in the access token `aud`.
MCP_ID="${MCP_ID:-http://localhost:9100/mcp}"

CLIENT_ID="mcp-client"          # the MCP client (e.g. Claude Code), registered by the enterprise admin
CLIENT_SECRET="mcp-client-secret"
# Per EMA, leg 2 is authenticated by the MCP CLIENT at the vendor's AS -- not by the AS
# itself. So the vendor realm carries a client with the same identity, and the ID-JAG's
# `client_id` claim names it. Keycloak enforces that those two match.
AS_CLIENT="mcp-client"
AS_SECRET="mcp-client-vendor-secret"

kc() { $KC "$@"; }

echo "== admin login =="
kc config credentials --server "$SERVER" --realm master --user admin --password admin

############################################################
# REALM 1: enterprise IdP  (the ID-JAG issuer)
############################################################
echo "== realm: $ENT (enterprise IdP) =="
kc delete "realms/$ENT" 2>/dev/null || true
kc create realms -s realm="$ENT" -s enabled=true

for u in alice bob; do
  kc create users -r "$ENT" -s username=$u -s enabled=true \
    -s email=$u@acme.example -s firstName=${u^} -s lastName=Acme
  kc set-password -r "$ENT" --username $u --new-password $u
done

# Stub client representing the EXTERNAL vendor AS. Its identifier attribute is what the
# `audience` parameter on leg 1 resolves against, and becomes the ID-JAG `aud`.
echo "== $ENT: stub for the external vendor AS =="
kc create clients -r "$ENT" \
  -s clientId=vendor-as-stub -s enabled=true -s publicClient=false \
  -s secret=unused-stub-secret \
  -s "attributes.\"idjag.resource.authorization.server.identifier\"=$AS_ID"

# The MCP client. The two idjag.* attributes ARE the admin policy:
#   idjag.clientid.at.<stub>       -> which client_id the vendor will see (authorizes the pair)
#   idjag.permitted.scopes.at.<stub> -> the scope ceiling the admin allows
echo "== $ENT: MCP client + admin policy attributes =="
kc create clients -r "$ENT" \
  -s clientId=$CLIENT_ID -s enabled=true -s publicClient=false \
  -s directAccessGrantsEnabled=true -s standardFlowEnabled=true \
  -s secret="$CLIENT_SECRET" \
  -s 'attributes."standard.token.exchange.enabled"=true' \
  -s "attributes.\"idjag.clientid.at.vendor-as-stub\"=$AS_CLIENT" \
  -s 'attributes."idjag.permitted.scopes.at.vendor-as-stub"=findings.read findings.write'

############################################################
# REALM 2: vendor Resource AS  (the ID-JAG consumer)
############################################################
echo "== realm: $VEN (vendor Resource AS) =="
kc delete "realms/$VEN" 2>/dev/null || true
kc create realms -s realm="$VEN" -s enabled=true

ENT_ISSUER="$SERVER/realms/$ENT"
ENT_JWKS="$ENT_ISSUER/protocol/openid-connect/certs"

# THE TRUST BOUNDARY: vendor trusts the enterprise issuer, and only via this pinned JWKS.
echo "== $VEN: trust the enterprise issuer (jwt-authorization-grant IdP) =="
kc create identity-provider/instances -r "$VEN" \
  -s alias=acme-idp -s providerId=jwt-authorization-grant -s enabled=true \
  -s "config.issuer=$ENT_ISSUER" \
  -s 'config.useJwksUrl=true' \
  -s "config.jwksUrl=$ENT_JWKS" \
  -s 'config.jwtAuthorizationGrantEnabled=true' \
  -s 'config.jwtAuthorizationGrantAssertionSignatureAlg=RS256' \
  -s 'config.jwtAuthorizationGrantAllowedClockSkew=30' \
  -s 'config.jwtAuthorizationGrantMaxAllowedAssertionExpiration=3600'

echo "== $VEN: leg-2 consumer client =="
kc create clients -r "$VEN" \
  -s clientId=$AS_CLIENT -s enabled=true -s publicClient=false \
  -s secret="$AS_SECRET"
RID=$(kc get clients -r "$VEN" -q clientId=$AS_CLIENT --fields id --format csv --noquotes)

kc update "clients/$RID" -r "$VEN" -f - <<JSON
{
  "attributes": {
    "oauth2.jwt.authorization.grant.enabled": "true",
    "oauth2.jwt.authorization.grant.idp": "acme-idp",
    "oauth2.jwt.authorization.grant.audience": "[{\"key\":\"acme-idp\",\"value\":\"$AS_ID\"}]"
  }
}
JSON

# Scopes the vendor recognises. Leg 2 mints a real access token, so these must be
# registered client scopes here (leg 1 only filters against the attribute allow-list).
echo "== $VEN: client scopes =="
for s in findings.read findings.write; do
  kc create client-scopes -r "$VEN" -s name="$s" -s protocol=openid-connect \
    -s 'attributes."include.in.token.scope"=true' \
    -s 'attributes."display.on.consent.screen"=false' 2>/dev/null || true
  SID=$(kc get client-scopes -r "$VEN" --fields id,name --format csv --noquotes | awk -F, -v n="$s" '$2==n{print $1}')
  kc update "clients/$RID/optional-client-scopes/$SID" -r "$VEN"
done

# EMA requires the access token be audience-restricted to the MCP server. Keycloak defaults
# to aud=account, so add an explicit audience mapper for the MCP server's resource id.
echo "== $VEN: audience mapper -> $MCP_ID =="
kc create "clients/$RID/protocol-mappers/models" -r "$VEN" -f - <<JSON
{
  "name": "mcp-audience",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-audience-mapper",
  "config": {
    "included.custom.audience": "$MCP_ID",
    "access.token.claim": "true",
    "id.token.claim": "false"
  }
}
JSON

# A second, unrelated resource on the SAME vendor AS. Used to prove the MCP server rejects
# a token that is validly signed by its own AS but audience-bound elsewhere (confused deputy).
echo "== $VEN: decoy client bound to a different resource =="
kc create clients -r "$VEN" \
  -s clientId=other-mcp-client -s enabled=true -s publicClient=false \
  -s secret=other-secret -s serviceAccountsEnabled=true
OID=$(kc get clients -r "$VEN" -q clientId=other-mcp-client --fields id --format csv --noquotes)
kc create "clients/$OID/protocol-mappers/models" -r "$VEN" -f - <<JSON
{
  "name": "other-audience",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-audience-mapper",
  "config": {
    "included.custom.audience": "http://localhost:9999/other-mcp",
    "access.token.claim": "true",
    "id.token.claim": "false"
  }
}
JSON

# Federated link: the ID-JAG `sub` is the ENTERPRISE realm's user id, so the vendor realm
# needs a local user carrying that id as its federated identity for the broker to resolve.
# (This pre-provisioning requirement is the real-world scaling gap in Keycloak-as-Resource-AS.)
echo "== $VEN: pre-provision + federate users =="
for u in alice bob; do
  EID=$(kc get users -r "$ENT" -q username=$u --fields id --format csv --noquotes)
  kc create users -r "$VEN" -s username=$u -s enabled=true -s email=$u@acme.example
  VID=$(kc get users -r "$VEN" -q username=$u --fields id --format csv --noquotes)
  kc create "users/$VID/federated-identity/acme-idp" -r "$VEN" \
    -s identityProvider=acme-idp -s userId="$EID" -s userName=$u
  echo "   $u: enterprise=$EID -> vendor=$VID"
done

cat <<EOF

================ TOPOLOGY READY ================
 enterprise IdP : $ENT_ISSUER
   users        : alice/alice, bob/bob
   mcp client   : $CLIENT_ID / $CLIENT_SECRET
   policy       : $CLIENT_ID -> vendor-as-stub, scopes [findings.read findings.write]
 vendor AS      : $SERVER/realms/$VEN
   as client    : $AS_CLIENT / $AS_SECRET
   trusts       : $ENT_ISSUER (JWKS pinned)
   token aud    : $MCP_ID
================================================
EOF
