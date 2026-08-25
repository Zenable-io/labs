# Agent Identity: DPoP + SD-JWT

The rig behind the "Agent Identity" workshop. Keycloak issues DPoP-bound
access tokens (RFC 9449); a local issuer mints SD-JWT agent credentials
(RFC 9901); a two-endpoint resource server accepts or refuses them.

```bash
docker compose up -d --wait
./keycloak/bootstrap-realm.sh
(cd agent && uv sync)

cd agent
uv run python ledger_api.py &     # resource server on :8081
uv run python negative_tests.py   # 19 attacks; HELD = defence worked
```

## Layout

| Path | What it is |
|---|---|
| `docker-compose.yml` | Keycloak, `--features=dpop`. Without that flag every token comes back unbound and every test passes for the wrong reason. |
| `keycloak/bootstrap-realm.sh` | The realm as readable lines rather than a realm-export JSON. Idempotent. |
| `agent/dpop.py` | Proof minting and verification, longhand. Each check maps to a rule in RFC 9449 §4.3. |
| `agent/ledger_api.py` | Two endpoints: `/invoices` (validates the token and stops, like most services) and `/invoices/strict` (demands binding). The difference between them is the lab. |
| `agent/sdjwt_issue.py` | Issue a credential, present a subset of it. |
| `agent/sdjwt_verify.py` | Verify a presentation; return only disclosed claims. |
| `agent/negative_tests.py` | Every attack, run against the rig. `ATTACKS` marks the control group — cases the attacker is *supposed* to win. |
| `scripts/capture-evidence.sh` | Regenerates `evidence/`, which the lab quotes verbatim. |

## Two things that will cost you an hour

**`--features=dpop`.** DPoP is a Keycloak preview feature. Omit the flag and
`dpop.bound.access.tokens=true` is accepted silently and does nothing.

**JWK thumbprint canonicalization.** RFC 7638 requires lexical member order, no
whitespace, and *only* the required members for the key type. An extra `alg` or
`use` changes the thumbprint, so a key stops matching its own `cnf.jkt` — which
presents as "tokens randomly stop working".

## Not production

`start-dev` means in-memory storage, HTTP, no TLS, hostname checks off. The
replay cache is a per-process dict, which is wrong the moment the resource
server has two replicas. Both are called out in the code where they live.
