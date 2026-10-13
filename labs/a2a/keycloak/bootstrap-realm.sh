#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc. Build the a2a-workshop realm with kcadm.sh.
#
# Deliberately a script rather than a realm-export JSON: every object that
# matters (client scope, audience mapper, client, grant) is one readable line
# here, where a 600-line export would hide all of it.
#
# Idempotent -- rerunning it is a no-op.
set -euo pipefail

kc() { docker exec a2a-keycloak /opt/keycloak/bin/kcadm.sh "$@"; }
REALM=a2a-workshop
quiet() { "$@" >/dev/null 2>&1 || true; }

kc config credentials --server http://localhost:8080 \
  --realm master --user admin --password admin >/dev/null
echo "==> authenticated"

quiet kc create realms -s realm="${REALM}" -s enabled=true
quiet kc create realms -s realm=rogue-realm -s enabled=true
echo "==> realms: ${REALM}, rogue-realm (a second trust domain)"

scope_id() {
  kc get client-scopes -r "${REALM}" --fields id,name | tr -d ' \n' \
    | grep -o "{\"id\":\"[^\"]*\",\"name\":\"$1\"}" | sed 's/.*"id":"\([^"]*\)".*/\1/'
}
client_id() {
  kc get clients -r "${2:-$REALM}" -q clientId="$1" --fields id \
    | sed -n 's/.*"id" *: *"\([^"]*\)".*/\1/p' | head -1
}

# The scope name is what the card advertises AND what the server enforces, so
# the two cannot drift. The audience mapper is load-bearing: without it every
# token's audience is "account" and any agent accepts any other agent's token.
for entry in "forecast:read=agent-a-forecast" \
             "trip:plan=agent-b-planner" \
             "forecast:write=agent-a-forecast"; do
  scope="${entry%%=*}"; audience="${entry##*=}"
  quiet kc create client-scopes -r "${REALM}" -s name="${scope}" \
    -s protocol=openid-connect -s 'attributes."include.in.token.scope"=true'
  quiet kc create "client-scopes/$(scope_id "${scope}")/protocol-mappers/models" \
    -r "${REALM}" -s name="${scope}-aud" -s protocol=openid-connect \
    -s protocolMapper=oidc-audience-mapper \
    -s "config.\"included.client.audience\"=${audience}" \
    -s 'config."access.token.claim"=true'
  echo "==> scope ${scope} -> audience ${audience}"
done

# A confidential client with a service account IS an agent's workload
# identity: no human, no browser, client_credentials only.
for entry in "agent-a-forecast=agent-a-secret" \
             "agent-b-planner=agent-b-secret" \
             "workshop-cli=workshop-cli-secret" \
             "agent-c-stranger=agent-c-secret" \
             "agent-d-expiring=agent-d-secret"; do
  client="${entry%%=*}"; secret="${entry##*=}"
  quiet kc create clients -r "${REALM}" -s clientId="${client}" -s secret="${secret}" \
    -s enabled=true -s publicClient=false -s serviceAccountsEnabled=true \
    -s standardFlowEnabled=false -s directAccessGrantsEnabled=false
  echo "==> client ${client}"
done
quiet kc create clients -r rogue-realm -s clientId=impostor -s secret=impostor-secret \
  -s enabled=true -s publicClient=false -s serviceAccountsEnabled=true \
  -s standardFlowEnabled=false
echo "==> client impostor (in rogue-realm)"

# Each agent gets the scope for the agent it CALLS, never the scope it
# enforces -- an agent holding its own scope could mint tokens for itself.
# agent-c (right audience, wrong permission) and agent-d (1-second tokens)
# each isolate one failure so a rejection has exactly one explanation.
for entry in "agent-b-planner=forecast:read" \
             "agent-a-forecast=trip:plan" \
             "workshop-cli=trip:plan" \
             "agent-c-stranger=forecast:write" \
             "agent-d-expiring=forecast:read"; do
  client="${entry%%=*}"; scope="${entry##*=}"
  quiet kc update "clients/$(client_id "${client}")/default-client-scopes/$(scope_id "${scope}")" \
    -r "${REALM}"
  echo "==> ${client} may request ${scope}"
done

kc update "clients/$(client_id agent-d-expiring)" -r "${REALM}" \
  -s 'attributes."access.token.lifespan"=1' >/dev/null
echo "==> agent-d-expiring tokens now live 1 second"

echo
echo "Realm ready.  issuer: http://localhost:8080/realms/${REALM}"
