#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc.
#
# One command: bring up the whole EMA topology from nothing and run the demo.
#   ./run.sh          full demo (happy path + deny paths + security negatives)
#   ./run.sh up       just bring the stack up
#   ./run.sh down     tear everything down
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

IMAGE="${KC_IMAGE:-ceposta/keycloak:id-jag}"
CONTAINER=kc-idjag

down() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  pkill -f "python mcp_server.py" >/dev/null 2>&1 || true
  echo "torn down"
}

up() {
  echo "==> starting Keycloak ($IMAGE)"
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$CONTAINER" -p 8480:8480 \
    -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin \
    "$IMAGE" start-dev --http-port=8480 >/dev/null
  for i in $(seq 1 120); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8480/realms/master 2>/dev/null)" = "200" ] \
      && { echo "    up after ${i}s"; break; }
    sleep 1
  done

  echo "==> configuring realms (enterprise IdP + vendor resource AS)"
  ./setup-realms.sh >/tmp/ema-realms.log 2>&1 || { tail -20 /tmp/ema-realms.log; exit 1; }
  sed -n '/TOPOLOGY READY/,$p' /tmp/ema-realms.log

  echo "==> installing python deps"
  uv sync --quiet

  echo "==> starting MCP server on :9100"
  pkill -f "python mcp_server.py" >/dev/null 2>&1 || true
  (uv run python mcp_server.py >/tmp/ema-mcp.log 2>&1 &)
  for i in $(seq 1 30); do
    curl -sf http://localhost:9100/.well-known/oauth-protected-resource/mcp >/dev/null 2>&1 \
      && { echo "    up after ${i}s"; break; }
    sleep 1
  done
}

case "${1:-demo}" in
  down) down ;;
  up)   up ;;
  demo)
    up
    echo; echo "############################################################"
    echo "# 1/4  HAPPY PATH — alice, findings.read"
    echo "############################################################"
    uv run python ema_client.py --user alice --scope findings.read

    echo; echo "############################################################"
    echo "# 2/4  DENY — scope outside the admin allow-list"
    echo "############################################################"
    uv run python ema_client.py --scope findings.admin || true

    echo; echo "############################################################"
    echo "# 3/4  DENY — an MCP server the admin never approved"
    echo "############################################################"
    uv run python ema_client.py --audience https://unapproved-vendor.example || true

    echo; echo "############################################################"
    echo "# 4/4  SECURITY NEGATIVES"
    echo "############################################################"
    ./negative-tests.sh

    echo; echo "MCP server log: /tmp/ema-mcp.log      teardown: ./run.sh down"
    ;;
  *) echo "usage: $0 [demo|up|down]"; exit 1 ;;
esac
