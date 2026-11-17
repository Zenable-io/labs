#!/usr/bin/env bash
# Copyright (c) 2026 Zenable, Inc.
# The newest trace the agent started: one line per hop in time order (which
# service did what, and how it answered), and under each hop the AAuth claims
# that hop put on its span, so the tokens are read here as well as in Jaeger.
# Every party exports its spans in its own batch; give the slowest a moment.
set -euo pipefail
sleep 3
until curl -s "http://127.0.0.1:16686/api/traces?service=agent&limit=1" | jq -e '.data | length > 0' >/dev/null; do sleep 1; done
curl -s "http://127.0.0.1:16686/api/traces?service=agent&limit=50" | jq -r '
  def tag($k): [.tags[] | select(.key == $k) | .value][0];
  .data | max_by(.spans | map(.startTime) | min) as $t
  | $t.spans
  | map(select(.operationName | test("http (send|receive)$") | not))
  | sort_by(.startTime)[]
  | ($t.processes[.processID].serviceName) as $svc
  | (tag("http.response.status_code") // tag("http.status_code") // tag("http.status") // "" | tostring) as $status
  | (($svc + " " * 14)[:14] + (.operationName + " " * 40)[:40] + $status),
    (.tags[] | select(.key | test("^(aauth\\.|x-aauth-)")) | "                \(.key) = \(.value)")'
