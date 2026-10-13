"""Copyright (c) 2026 Zenable, Inc. Forty log lines from one fictional cluster, and the request id in each.

Five services, five logging libraries, nobody agreeing on a field name. Six of
the lines carry no request id at all, and a pattern that invents one for those
is worse than a pattern that misses one, so they are labelled with the empty
string and scored like every other line.

The split is fixed rather than shuffled at import. GEPA selects candidates on
the validation set, so a split that moves between runs makes two runs of the
same command incomparable, which is the one thing a lab measurement cannot
afford.
"""

from pydantic import BaseModel, ConfigDict


class LogLine(BaseModel):
    """One line, and the request id a human reads out of it."""

    model_config = ConfigDict(frozen=True, strict=True)

    line: str
    request_id: str
    """The empty string when the line carries no request id."""


LINES: tuple[LogLine, ...] = (
    # --- structured key=value, the shape most patterns are written against ---
    LogLine(
        line="2026-03-04T10:15:22Z INFO  req_id=8f21ac status=200 path=/v1/users",
        request_id="8f21ac",
    ),
    LogLine(
        line="2026-03-04T10:15:29Z INFO  req_id=8f21b7 status=204 path=/v1/session",
        request_id="8f21b7",
    ),
    LogLine(
        line="2026-03-04T10:16:02Z ERROR req_id=8f21c4 status=500 path=/v1/invoices",
        request_id="8f21c4",
    ),
    LogLine(
        line="2026-03-04T10:16:41Z INFO  status=200 req_id=8f21d0 path=/v1/users/9",
        request_id="8f21d0",
    ),
    # --- the same idea, spelled four other ways ---
    LogLine(
        line="[2026-03-04 10:15:23] WARN  (req 8f21ad) upstream took 4.2s",
        request_id="8f21ad",
    ),
    LogLine(
        line="[2026-03-04 10:17:05] INFO  (req 8f21e2) cache warm, 118 keys",
        request_id="8f21e2",
    ),
    LogLine(
        line="trace=3b1d02 span=9c02 request-id: 8f21b0 svc=billing",
        request_id="8f21b0",
    ),
    LogLine(
        line="trace=3b1d55 span=9c19 request-id: 8f21f6 svc=search",
        request_id="8f21f6",
    ),
    LogLine(
        line='{"ts":"2026-03-04T10:15:24Z","level":"error","request_id":"8f21ae","msg":"upstream reset"}',
        request_id="8f21ae",
    ),
    LogLine(
        line='{"ts":"2026-03-04T10:18:11Z","level":"info","request_id":"8f2201","msg":"lease renewed"}',
        request_id="8f2201",
    ),
    LogLine(
        line='{"level":"warn","msg":"retry 2 of 3","requestId":"8f220c","attempt":2}',
        request_id="8f220c",
    ),
    LogLine(
        line='{"level":"info","msg":"batch flushed","requestId":"8f2217","rows":512}',
        request_id="8f2217",
    ),
    # --- an access log, where the id is the last thing on a long line ---
    LogLine(
        line='10.0.0.4 - - [04/Mar/2026:10:15:25 +0000] "GET /health HTTP/1.1" 200 12 "-" "kube-probe/1.29" rid=8f21af',
        request_id="8f21af",
    ),
    LogLine(
        line='10.0.0.9 - - [04/Mar/2026:10:19:48 +0000] "POST /v1/invoices HTTP/1.1" 201 884 "-" "curl/8.6.0" rid=8f2223',
        request_id="8f2223",
    ),
    LogLine(
        line='10.0.1.7 - - [04/Mar/2026:10:20:15 +0000] "GET /v1/users?page=2 HTTP/1.1" 200 4120 "-" "Go-http-client/2.0" rid=8f222e',
        request_id="8f222e",
    ),
    # --- ids that are not six hex characters ---
    LogLine(
        line="2026-03-04T10:21:00Z INFO  req_id=r-0091 status=200 path=/v1/exports",
        request_id="r-0091",
    ),
    LogLine(
        line="2026-03-04T10:21:44Z INFO  req_id=r-0104 status=200 path=/v1/exports/3",
        request_id="r-0104",
    ),
    LogLine(
        line='{"level":"info","request_id":"7c1e5a90-4d2b-4f61-9a77-2f0c1d3e8b44","msg":"job accepted"}',
        request_id="7c1e5a90-4d2b-4f61-9a77-2f0c1d3e8b44",
    ),
    LogLine(
        line='{"level":"info","request_id":"1b9f0c72-88ad-4e15-bc30-5a6e2d47f019","msg":"job finished"}',
        request_id="1b9f0c72-88ad-4e15-bc30-5a6e2d47f019",
    ),
    LogLine(
        line="2026-03-04T10:23:12Z DEBUG request-id: RQ-2026-03-04-0817 worker=4",
        request_id="RQ-2026-03-04-0817",
    ),
    # --- a neighbouring field that looks exactly like the answer ---
    LogLine(
        line="2026-03-04T10:24:01Z INFO  session_id=8f2240 req_id=8f2241 path=/v1/login",
        request_id="8f2241",
    ),
    LogLine(
        line="2026-03-04T10:24:33Z INFO  parent_id=8f2249 req_id=8f224a depth=2",
        request_id="8f224a",
    ),
    LogLine(
        line='{"trace_id":"8f2252","request_id":"8f2253","level":"info","msg":"span closed"}',
        request_id="8f2253",
    ),
    LogLine(
        line="trace=8f225b request-id: 8f225c svc=notifications attempt=1",
        request_id="8f225c",
    ),
    LogLine(
        line="2026-03-04T10:26:18Z INFO  correlation_id=8f2264 req_id=8f2265 hop=2",
        request_id="8f2265",
    ),
    # --- the id carries a prefix the label keeps ---
    LogLine(
        line="2026-03-04T10:27:02Z INFO  req_id=req_8f2270 status=200 path=/v1/ping",
        request_id="req_8f2270",
    ),
    LogLine(
        line='{"level":"info","request_id":"req_8f227b","msg":"queued"}',
        request_id="req_8f227b",
    ),
    # --- quoting and spacing a pattern has to survive ---
    LogLine(
        line="2026-03-04T10:28:40Z INFO  req_id='8f2286' status=200 path=/v1/keys",
        request_id="8f2286",
    ),
    LogLine(
        line='2026-03-04T10:29:14Z INFO  req_id = "8f2291" status=200 path=/v1/keys/7',
        request_id="8f2291",
    ),
    LogLine(
        line="2026-03-04T10:30:05Z INFO  req_id=8f229c, status=200, path=/v1/tokens",
        request_id="8f229c",
    ),
    LogLine(
        line='level=info msg="request complete" req_id=8f22a7 duration_ms=41',
        request_id="8f22a7",
    ),
    LogLine(
        line='level=error msg="upstream 503" req_id=8f22b2 duration_ms=9004',
        request_id="8f22b2",
    ),
    LogLine(
        line="2026-03-04T10:32:19Z INFO  [8f22bd] GET /v1/users 200 18ms",
        request_id="8f22bd",
    ),
    LogLine(
        line="2026-03-04T10:33:47Z WARN  [8f22c8] POST /v1/invoices 429 3ms",
        request_id="8f22c8",
    ),
    # --- no request id at all: a pattern that invents one here is wrong ---
    LogLine(
        line="2026-03-04T10:15:20Z INFO  starting billing worker, pool=8",
        request_id="",
    ),
    LogLine(
        line="2026-03-04T10:34:02Z INFO  config reloaded from /etc/svc/config.yaml",
        request_id="",
    ),
    LogLine(
        line='{"level":"info","msg":"listening","addr":"0.0.0.0:8080","pid":41}',
        request_id="",
    ),
    LogLine(
        line="[2026-03-04 10:35:11] ERROR postgres connection lost, retrying in 2s",
        request_id="",
    ),
    LogLine(
        line="trace=8f22d3 span=9c44 svc=search cache=miss rows=0",
        request_id="",
    ),
    LogLine(
        line='10.0.0.2 - - [04/Mar/2026:10:36:00 +0000] "GET /metrics HTTP/1.1" 200 9931 "-" "Prometheus/2.53"',
        request_id="",
    ),
)

# Spread by hand across the shapes above rather than sliced off the end. The
# lines are grouped by format here for a reader, so a contiguous slice would
# hand the held-out set every line carrying no request id, and "match nothing"
# would score full marks on it.
#
# Validation carries twelve rather than eight. GEPA keeps a candidate by how it
# scores here, and on eight lines one line is 12.5 points, which is enough noise
# for the search to keep a candidate that is only lucky.
_VALIDATION_INDEXES = frozenset({1, 2, 5, 9, 12, 13, 16, 19, 21, 25, 30, 35})
_HELD_OUT_INDEXES = frozenset({3, 7, 11, 14, 18, 22, 28, 37})

VALIDATION: tuple[LogLine, ...] = tuple(
    line for index, line in enumerate(LINES) if index in _VALIDATION_INDEXES
)
HELD_OUT: tuple[LogLine, ...] = tuple(
    line for index, line in enumerate(LINES) if index in _HELD_OUT_INDEXES
)
TRAIN: tuple[LogLine, ...] = tuple(
    line
    for index, line in enumerate(LINES)
    if index not in _VALIDATION_INDEXES and index not in _HELD_OUT_INDEXES
)
