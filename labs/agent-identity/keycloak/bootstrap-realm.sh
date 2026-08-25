#!/usr/bin/env bash
# Build the agent-identity realm with kcadm.sh.
#
# Deliberately a script rather than a realm-export JSON: every object that
# matters (client scope, audience mapper, client, DPoP binding) is one
# readable line here, where a 600-line export would hide all of it.
#
# Idempotent -- rerunning it is a no-op.
set -euo pipefail

kc() { docker exec agent-identity-keycloak /opt/keycloak/bin/kcadm.sh "$@"; }
REALM=agent-identity
quiet() { "$@" >/dev/null 2>&1 || true; }

kc config credentials --server http://localhost:8080 \
  --realm master --user admin --password admin >/dev/null
echo "==> authenticated"

quiet kc create realms -s realm="${REALM}" -s enabled=true
echo "==> realm: ${REALM}"

client_id() {
  kc get clients -r "${REALM}" -q clientId="$1" --fields id \
    | sed -n 's/.*"id" *: *"\([^"]*\)".*/\1/p' | head -1
}
scope_id() {
  kc get client-scopes -r "${REALM}" --fields id,name | tr -d ' \n' \
    | grep -o "{\"id\":\"[^\"]*\",\"name\":\"$1\"}" | sed 's/.*"id":"\([^"]*\)".*/\1/'
}

# The audience mapper is load-bearing. Without it every token's audience is
# "account", and a resource server that checks `aud` correctly would reject
# the token it was just handed -- or, worse, one that doesn't check would
# accept a token minted for some other service in the same realm.
quiet kc create client-scopes -r "${REALM}" -s name="invoice:read" \
  -s protocol=openid-connect -s 'attributes."include.in.token.scope"=true'
SCOPE=$(scope_id "invoice:read")
quiet kc create "client-scopes/${SCOPE}/protocol-mappers/models" -r "${REALM}" \
  -s name=aud-ledger-api -s protocol=openid-connect \
  -s protocolMapper=oidc-audience-mapper \
  -s 'config."included.client.audience"=ledger-api' \
  -s 'config."access.token.claim"=true'
echo "==> scope: invoice:read (audience ledger-api)"

# Two clients, identical except for one attribute. `agent-bound` gets
# DPoP-bound tokens; `agent-bearer` is the control group, and every negative
# test in this lab is really a question about the difference between them.
for pair in "agent-bound:true" "agent-bearer:false"; do
  name="${pair%%:*}"; bound="${pair##*:}"
  quiet kc create clients -r "${REALM}" \
    -s clientId="${name}" -s enabled=true \
    -s protocol=openid-connect -s publicClient=false \
    -s standardFlowEnabled=false -s serviceAccountsEnabled=true \
    -s secret="${name}-secret" \
    -s "attributes.\"dpop.bound.access.tokens\"=${bound}"
  CID=$(client_id "${name}")
  # Re-assert the attribute and the secret on rerun: `create` is a no-op once
  # the client exists, so a changed value would otherwise never land.
  kc update "clients/${CID}" -r "${REALM}" \
    -s "attributes.\"dpop.bound.access.tokens\"=${bound}" \
    -s secret="${name}-secret" >/dev/null
  quiet kc update "clients/${CID}/optional-client-scopes/${SCOPE}" -r "${REALM}"
  echo "==> client: ${name} (dpop.bound.access.tokens=${bound})"
done

# The resource server itself. It never requests a token -- it exists so that
# `ledger-api` is a real client id the audience mapper can name.
quiet kc create clients -r "${REALM}" -s clientId=ledger-api -s enabled=true \
  -s protocol=openid-connect -s publicClient=false \
  -s standardFlowEnabled=false -s serviceAccountsEnabled=false
echo "==> client: ledger-api (audience only, never requests a token)"

echo
echo "Realm ready: http://localhost:8080/realms/${REALM}/.well-known/openid-configuration"
