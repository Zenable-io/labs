<!-- Generated from src/lib/labs/content/labs/agent-identity-dpop-sdjwt.mdx in Zenable-io/next-gen-governance
     by services/ui_frontend/scripts/export-lab-readme.js. Do not edit by hand. -->

# Agent Identity: DPoP Token Binding and SD-JWT Selective Disclosure

Bind an agent's access tokens to a key it holds (DPoP, RFC 9449) and give it a credential that reveals only what each verifier needs (SD-JWT, RFC 9901). Steal the tokens yourself and watch both hold.

**[▶ Take this lab on the Zenable Learning Hub](https://www.zenable.app/learn?lab=agent-identity-dpop-sdjwt&utm_source=github&utm_medium=labs_repo&utm_campaign=agent-identity-dpop-sdjwt_readme)** — fully hosted sandbox environment, progress tracking, and a full-featured lab workspace.

**Duration** 75 minutes · **Difficulty** Advanced

**Topics** `Agent Identity` · `DPoP` · `SD-JWT` · `Identity` · `OAuth2` · `OIDC` · `Keycloak` · `JWT` · `Least Privilege` · `Open Source` · `Python`

**Prerequisites**

- Docker and Docker Compose
- Python 3.11+, and enough OAuth to know what an access token is
- The A2A or MCP Authorization lab, or equivalent hard-won experience

---

_This README is only the hands-on lab. The concept walk-through (What we're building · Terminology · Why a stolen token still works · Conclusion) lives on the [Learning Hub](https://www.zenable.app/learn?lab=agent-identity-dpop-sdjwt&utm_source=github&utm_medium=labs_repo&utm_campaign=agent-identity-dpop-sdjwt_readme)._

## Getting started

_~6 min · Hands-on_

Clone the lab rig and bring up Keycloak. The `--wait` flag blocks until its healthcheck passes, so the next command can't race a server that's still opening its ports:

```bash
git clone https://github.com/Zenable-io/labs.git ~/zenable-labs 2>/dev/null \
  || git -C ~/zenable-labs pull --ff-only
cd ~/zenable-labs/labs/agent-identity
docker compose up -d --wait
```

```console
 Network agent-identity_default  Creating
 Network agent-identity_default  Created
 Container agent-identity-keycloak  Creating
 Container agent-identity-keycloak  Created
 Container agent-identity-keycloak  Starting
 Container agent-identity-keycloak  Started
 Container agent-identity-keycloak  Waiting
 Container agent-identity-keycloak  Healthy
```

> [!WARNING]
> `start-dev` gives you in-memory storage, HTTP only, no TLS, and the hostname checks disabled. Exactly right for a workshop, catastrophic anywhere else. Nothing you configure in this lab is a production Keycloak configuration.

DPoP is a **preview** feature in Keycloak, so the compose file names it explicitly:

```yaml
command: ["start-dev", "--http-port=8080", "--features=dpop"]
```

Now build the realm and install the agent's dependencies:

```bash
./keycloak/bootstrap-realm.sh
```

```console
Logging into http://localhost:8080 as user admin of realm master
==> authenticated
==> realm: agent-identity
==> scope: invoice:read (audience ledger-api)
==> client: agent-bound (dpop.bound.access.tokens=true)
==> client: agent-bearer (dpop.bound.access.tokens=false)
==> client: ledger-api (audience only, never requests a token)
```

```bash
cd agent && uv sync
```

```console
Using CPython 3.13.12
Creating virtual environment at: .venv
Resolved 19 packages in 12ms
Installed 17 packages in 12ms
 + cryptography==50.0.0
 + httpx==0.28.1
 + jwcrypto==1.5.8
 + pyjwt==2.13.0
...
 + sd-jwt==0.10.4
 + starlette==1.6.0
 + uvicorn==0.52.4
```

The realm is up and the agent is ready. Success!

Question: what happens if you forget `--features=dpop`? Make a prediction before opening the answer.

<details>
<summary>Answer</summary>

The client attribute you're about to set is accepted without complaint and silently does nothing. Every token comes back unbound, and every negative test in this lab passes for the wrong reason. This is the single most likely way to waste an hour here.

You can confirm the running server actually advertises DPoP by asking its discovery document:

```bash
curl -s http://localhost:8080/realms/agent-identity/.well-known/openid-configuration \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['dpop_signing_alg_values_supported'])"
```

```console
['PS384', 'RS384', 'EdDSA', 'ES384', 'ES256', 'RS256', 'ES512', 'PS256', 'PS512', 'RS512']
```

If that key is missing, the feature flag never took, and you should stop and fix it before going further.

</details>

## A token that knows whose it is

_~12 min · Hands-on_

`bootstrap-realm.sh` created two clients, `agent-bound` and `agent-bearer`. They're identical except for one line:

```bash
-s "attributes.\"dpop.bound.access.tokens\"=${bound}"
```

That's the whole configuration. Ask each client for a token and decode both side by side:

```bash
uv run python dump_tokens.py
```

```console
Agent's DPoP public key thumbprint (RFC 7638): J4ksYlMkQF8i7fAQ4x176UwCbSuK6FJcF6coZJyvTPs

--- agent-bound ---
token_type: DPoP
expires_in: 300
iss: "http://localhost:8080/realms/agent-identity"
aud: ["ledger-api", "account"]
azp: "agent-bound"
scope: "email profile invoice:read"
cnf: {"jkt": "J4ksYlMkQF8i7fAQ4x176UwCbSuK6FJcF6coZJyvTPs", "kc-jkt-type": "DPoP"}

--- agent-bearer ---
token_type: Bearer
expires_in: 300
iss: "http://localhost:8080/realms/agent-identity"
aud: ["ledger-api", "account"]
azp: "agent-bearer"
scope: "email profile invoice:read"
cnf: null
```

Your thumbprint will differ (the key is generated fresh each run), and that's fine. Read the two highlighted lines.

`token_type` is `DPoP`, not `Bearer`: RFC 9449 §7.1 defines a separate `Authorization: DPoP` scheme, and a bound token sent under `Bearer` must be rejected.

And `cnf.jkt` on the bound token is the SHA-256 thumbprint of the agent's public key. Our script computed that thumbprint independently from our own key and printed it on the first line. They match. The authorisation server stamped *which key this token belongs to* into the token itself. Success!

Question: that `cnf.jkt` appeared in the token. Did the resource server put it there, or something earlier?

<details>
<summary>Answer</summary>

The **token endpoint** did, at issuance time. The client sent a DPoP proof when it requested the token, the authorisation server read the proof's public key, and stamped its thumbprint into `cnf.jkt`.

Binding is an issuance-time decision. Nothing a resource server does later can bind a token that was issued unbound, which is why the "downgrade" attack later matters.

</details>

That thumbprint is fussy on purpose. Open `agent/dpop.py` and look at `jkt()`:

```python
canonical = json.dumps(
    {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"], "y": jwk["y"]},
    separators=(",", ":"),
    sort_keys=True,
)
return b64u(hashlib.sha256(canonical.encode()).digest())
```

Lexical member order, no whitespace, and **only the required members for the key type**. Add `alg` or `use` (both perfectly legal JWK members) and the thumbprint changes, so the same key stops matching its own `cnf.jkt`.

This is the most common DPoP integration bug, and it presents as "our tokens randomly stop working", which sends people looking at clocks and caches for a day.

Finally, the proof itself. A DPoP proof is a small JWT the agent signs per request:

```python
claims = {
    "jti": jti or str(uuid.uuid4()),
    "htm": htm,
    "htu": htu.split("?")[0].split("#")[0],
    "iat": iat if iat is not None else int(time.time()),
}
if access_token is not None:
    claims["ath"] = access_token_hash(access_token)
```

Four claims (RFC 9449 §4.2), and each closes a specific attack we're about to demonstrate: `htm`/`htu` pin the method and URL, `iat` bounds how long a captured proof stays interesting, `jti` turns "bounded" into "once", and `ath` binds the proof to this exact token. Note `htu` drops query and fragment; including them is another silent-mismatch bug.

Now start the resource server. It serves two endpoints that differ only in rigour: `/invoices` validates signature, issuer, audience, expiry, and scope and stops there (what most services do today), while `/invoices/strict` additionally demands the `DPoP` scheme, a `cnf.jkt`, and a proof that survives every check in RFC 9449 §4.3:

```bash
uv run python ledger_api.py
```

It logs at warning level, so a healthy start is silent. Leave it running in this terminal and open a second one for the attacks; everything below runs from the same `agent` directory. Having both endpoints is the point: nearly every result below is only interesting as a *difference* between the two.

## Steal the token

_~15 min · Hands-on_

Time to be the attacker. `negative_tests.py` runs twenty-two cases against the running ledger. `HELD` means the defence worked; `ATTACKS` means the attacker won. The `ATTACKS` lines aren't bugs, they're the control group:

```bash
uv run python negative_tests.py
```

```console
DPoP -- attacker has exfiltrated the access token
  [   HELD] legitimate agent with its key
            HTTP 200 {"paid":true,"by":"agent-bound","endpoint":"strict"}

  -- the same stolen token, against each endpoint --
  [ATTACKS] stolen BEARER token replayed (lax endpoint)
            HTTP 200 {"paid":true,"by":"agent-bearer","endpoint":"lax"}  <- the attacker is paid. This is what a bearer token is.
  [   HELD] stolen bound token, no proof, Bearer scheme
            HTTP 401 Authorization scheme is 'Bearer', expected 'DPoP'
  [   HELD] stolen bound token, DPoP scheme, no proof
            HTTP 401 bound token presented with no DPoP proof
  [   HELD] stolen token + attacker's own proof key
            HTTP 401 DPoP proof rejected: proof key thumbprint does not match token cnf.jkt
  [   HELD] captured token + proof, replayed verbatim
            first 200, replay HTTP 401 DPoP proof rejected: replayed jti e251156a-2beb-40bc-bcc7-08d640bdcb4a
  [   HELD] proof minted for a different URL (htu)
            HTTP 401 DPoP proof rejected: htu 'http://localhost:8081/invoices' != 'http://localhost:8081/invoices/strict'
  [   HELD] proof minted for a different method (htm)
            HTTP 401 DPoP proof rejected: htm 'GET' != 'POST'
  [   HELD] proof harvested an hour ago (iat window)
            HTTP 401 DPoP proof rejected: iat is 3600s away from now
  [   HELD] right key, proof minted over a different token (ath)
            HTTP 401 DPoP proof rejected: ath does not match the presented access token
  [   HELD] proof signed with symmetric HS256 (alg confusion)
            HTTP 401 DPoP proof rejected: alg 'HS256' is not in the allowlist ['ES256']
  [   HELD] proof signed with symmetric HS384 (alg confusion)
            HTTP 401 DPoP proof rejected: alg 'HS384' is not in the allowlist ['ES256']
  [   HELD] proof signed with symmetric HS512 (alg confusion)
            HTTP 401 DPoP proof rejected: alg 'HS512' is not in the allowlist ['ES256']
  [   HELD] unbound token on the strict endpoint (downgrade)
            HTTP 401 token has no cnf.jkt -- it is not sender-constrained

  -- and the honest comparison --
  [ATTACKS] bound token, no proof, against the LAX endpoint
            HTTP 200 {"paid":true,"by":"agent-bound","endpoint":"lax"}  <- binding does nothing if the RS never checks it
```

Read the first `ATTACKS` line and the last one together. The first is today: an attacker who reads one log line is paid.

The last is the trap everyone walks into. That's a **bound** token, with a `cnf.jkt`, presented with no proof at all, and it works, because the lax endpoint never looked. Turning on DPoP at the authorisation server changes nothing by itself. If you take one operational lesson from this lab, take this one: rollout is the resource server, not the IdP.

Now the case that carries the whole argument: `stolen token + attacker's own proof key`. This is the Storm-0558-shaped attacker reproduced. They have the complete token. They have working DPoP code. They mint a perfectly valid proof over the right URL, right method, a fresh `iat`, a unique `jti`, the correct `ath`. Every check passes except one:

```console
proof key thumbprint does not match token cnf.jkt
```

They don't have the key. That's why the key-storage question from earlier isn't a footnote.

Look at the three `alg confusion` cases. They all fail the same way, and there's a story there.

Question: an earlier version of this lab used a **denylist** that rejected `none` and `HS256` and accepted anything else. Every test passed. Why did `HS384` walk straight through it?

<details>
<summary>Answer</summary>

Because nobody thought to block it. A denylist only rejects the algorithms you anticipated. An attacker sends `HS384`, signs the proof with a secret they chose, and the verifier happily checks that signature against data the attacker also controls. The public key in the header stops being a claim of possession and becomes decoration.

The fix is one line, and it's the rule for every JWT verifier you'll ever write:

```python
PROOF_ALGS = frozenset({"ES256"})
if alg not in PROOF_ALGS:
    raise ProofRejected(...)
```

An allowlist fails closed on the algorithm nobody anticipated; a denylist fails open on it. The same set also feeds `jwt.decode(..., algorithms=sorted(PROOF_ALGS))`, so the check and the decode can't drift into disagreeing about what's acceptable.

</details>

Two more cases are subtler than they look. **Replay** dies on `jti`: the attacker captured a complete request (token and proof together, what a compromised proxy gives you), the first use works, and the replay is refused. But read the admission in `agent/dpop.py`:

```python
class ReplayCache:
    """In-memory and per-process, which is wrong the moment a resource server
    runs more than one replica: an attacker replays against a different replica
    and the cache never sees the collision."""
```

Your production replay cache is a shared store with a TTL matching the proof window. A per-process dict passes this test and fails in your cluster, quietly.

And **`ath`** needs the right key and the wrong token to prove anything at all: an attacker with a *different* key trips the thumbprint check first, so the `ath` rule would never be reached. In layered checks, a test can pass because of a check other than the one it claims to exercise, so order your assertions to keep each one reachable.

The best fifteen minutes in this lab: comment out one check in `verify_proof()` at a time, rerun, and watch exactly one case flip to `BROKEN`. Then try to find a check whose removal breaks nothing, and decide whether you've found redundancy or a test gap. Success once every case behaves as documented.

## A credential that says less

_~13 min · Hands-on_

Different question now. The ledger knows the agent may pay invoices. It doesn't know what the agent *is*: who operates it, what model it runs, who to call at 3am when it starts paying the wrong invoices.

The reflex is to stuff those claims into the access token. Resist it. The access token goes to every resource server the agent talks to, so every one of them learns the cost centre and the owner's employee id. It also lives five minutes, so provenance that's stable for months gets re-minted constantly.

SD-JWT gives us one credential, signed once, presented differently to each verifier:

```bash
uv run python dump_credential.py
```

```console
What the issuer signed:
  iss                  always disclosed
  sub                  always disclosed
  cnf                  always disclosed
  operator             selectively disclosable
  operator_contact     selectively disclosable
  model                selectively disclosable
  deployment_env       selectively disclosable
  cost_center          selectively disclosable
  owner_employee_id    selectively disclosable
  capabilities         selectively disclosable

Issued: 7 disclosable claims, plus decoy digests to blur that count

--- presented to the ledger, which only needs to know who runs this agent ---
verifier sees:  ['capabilities', 'cnf', 'iss', 'operator', 'sub']
verifier cannot open: 10 digests

--- presented to the incident responder, who needs to reach a human ---
verifier sees:  ['cnf', 'deployment_env', 'iss', 'operator', 'operator_contact', 'sub']
verifier cannot open: 9 digests
```

One credential, two presentations. Neither verifier can open what it wasn't given, and both can verify the issuer's signature over what they *were* given. Success!

Notice `iss`, `sub`, and `cnf` are always disclosed. That's a design decision, not an oversight: a verifier that can't see who issued a credential has no trust anchor to check it against, and one that can't see `cnf` can't verify key binding. Hiding those makes the credential unverifiable, not private.

Now look at the digest counts: 10 and 9 unopenable digests for a credential with 7 disclosable claims. The arithmetic doesn't work, and that's the feature.

Selective disclosure hides claim *content*, but the digest array is right there in the payload, and its length would otherwise leak how many claims exist. **Decoy digests** (RFC 9901 §4.2.5) are random hashes that correspond to no claim, added so the array length stops meaning anything. They're regenerated each run, which is why you'll see the count wobble between commands.

The presentation ends with a Key Binding JWT (RFC 9901 §4.3), the holder's signature over *this* verifier's audience and nonce. The second half of `negative_tests.py` attacks exactly that; this is the same run you did earlier, scrolled down:

```console
SD-JWT -- what a verifier learns, and what it can replay
  [   HELD] verifier sees only the disclosed claims
            disclosed ['capabilities', 'cnf', 'iss', 'operator', 'sub']; withheld ['cost_center', 'deployment_env', 'model', 'operator_contact', 'owner_employee_id']
  [   HELD] count of withheld claims is blurred by decoys
            8 unopenable digests hide 5 real claims
  [   HELD] verifier replays the presentation elsewhere (aud)
            rejected: Invalid audience in KB-JWT
  [   HELD] presentation replayed in a later session (nonce)
            rejected: Invalid nonce in KB-JWT
  [   HELD] holder edits a disclosed value (digest)
            rejected: Invalid digest in KB-JWT
  [   HELD] holder invents a claim the issuer never signed
            rejected: Invalid digest in KB-JWT
  [   HELD] key-binding JWT stripped
            rejected: Invalid JWS Object [Invalid format]
```

Question: the "replays the presentation elsewhere" attacker is a **legitimate** verifier. You handed it a valid, correctly signed presentation in the normal course of business. Why can't it turn around and present that to a second verifier?

<details>
<summary>Answer</summary>

The KB-JWT is signed over the first verifier's audience and nonce, so the second verifier rejects it with `Invalid audience in KB-JWT`. Strip the KB-JWT entirely and you'd have a bearer credential with fewer claims in it, replayable by anyone who receives it.

Without key binding, every verifier you present to becomes able to impersonate you to every other verifier, forever. That's the case worth sitting with.

</details>

The last two `HELD` cases are the naive-verifier attack from RFC 9901 §9: the holder edits a disclosed value, then invents a claim outright. A verifier that reads disclosed values without recomputing their digests would accept both.

The RFC calls this out because reading the value is the obvious thing to do and checking the hash is the extra step people skip.

Judge SD-JWT on its honest tradeoffs, since there's no named breach to cite.

In its favour: each verifier's compromise exposes only what that verifier was given, claims stay individually verifiable (the ledger can prove the operator name came from your issuer), and the credential outlives any single token.

Against: you now run an issuer with a signing key and an availability requirement, revocation is genuinely unsettled, and the privacy win is partial. Unless the credential is re-issued, the same digests appear in every presentation, so colluding verifiers can correlate you without opening a thing.

That last point is worth saying out loud. "Selective disclosure" sounds like it solves linkability, and it doesn't; that needs batch issuance or more maths.

## Cleanup

_~5 min · Hands-on_

Stop the ledger with Ctrl-C in its terminal, then tear down Keycloak and its volumes:

```bash
docker compose down -v
```

```console
 Container agent-identity-keycloak  Stopping
 Container agent-identity-keycloak  Stopped
 Container agent-identity-keycloak  Removing
 Container agent-identity-keycloak  Removed
 Network agent-identity_default  Removing
 Network agent-identity_default  Removed
```

If you want the rig gone too, `rm -rf ~/zenable-labs` finishes the job. Thanks for building with us!

---

_Written for the [Zenable Learning Hub](https://www.zenable.app/learn?lab=agent-identity-dpop-sdjwt&utm_source=github&utm_medium=labs_repo&utm_campaign=agent-identity-dpop-sdjwt_readme); published here because the rig lives here. [Browse every lab](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=agent-identity-dpop-sdjwt_readme), or open an issue on this repo if something is broken._
