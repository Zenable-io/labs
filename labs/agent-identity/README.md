<!-- Generated from src/lib/labs/content/labs/agent-identity-dpop-sdjwt.mdx in Zenable-io/next-gen-governance
     by services/ui_frontend/scripts/export-lab-readme.js. Do not edit by hand. -->

# Agent Identity: Tokens That Cannot Be Stolen, Claims You Do Not Have to Share

Bind an agent's access tokens to a key it holds (DPoP, RFC 9449) and give it a credential that reveals only what each verifier needs (SD-JWT, RFC 9901). Steal the tokens yourself and watch both hold.

**[▶ Take this lab on the Zenable Learning Hub](https://www.zenable.app/learn?lab=agent-identity-dpop-sdjwt&utm_source=github&utm_medium=labs_repo&utm_campaign=agent-identity-dpop-sdjwt_readme)** — fully hosted sandbox environment, progress tracking, and a full-featured lab workspace.

**Duration** 2 hours · **Difficulty** Advanced

**Topics** `Agent Identity` · `DPoP` · `SD-JWT` · `Identity` · `OAuth2` · `OIDC` · `Keycloak` · `JWT` · `Least Privilege` · `Open Source` · `Python`

**Prerequisites**

- Docker and Docker Compose
- Python 3.11+, and enough OAuth to know what an access token is
- The A2A or MCP Authorization lab, or equivalent scar tissue

---

_This README is only the hands-on lab. The concept walk-through (Why Agent Identity Is Different · Attacks This Would Have Changed) lives on the [Learning Hub](https://www.zenable.app/learn?lab=agent-identity-dpop-sdjwt&utm_source=github&utm_medium=labs_repo&utm_campaign=agent-identity-dpop-sdjwt_readme)._

## Hands-on: A Token That Knows Whose It Is

_~25 min · Hands-on_

### Getting started

```bash
git clone https://github.com/Zenable-io/labs.git ~/zenable-labs 2>/dev/null \
  || git -C ~/zenable-labs pull --ff-only
cd ~/zenable-labs/labs/agent-identity

# --wait blocks until Keycloak's healthcheck passes, so the next command
# cannot race a server that is still opening its ports.
docker compose up -d --wait

./keycloak/bootstrap-realm.sh
(cd agent && uv sync)
```

> [!WARNING]
> `start-dev` gives you in-memory storage, HTTP only, no TLS, and the
> hostname checks disabled. Exactly right for a workshop, catastrophic anywhere
> else. Nothing you configure in this lab is a production Keycloak
> configuration.

DPoP is a **preview** feature in Keycloak, so the compose file names it explicitly:

```yaml
command: ["start-dev", "--http-port=8080", "--features=dpop"]
```

Leave that flag off and the client attribute you are about to read is accepted without complaint and silently does nothing. Every token comes back unbound and every test in this lab passes for the wrong reason. This is the single most likely way to waste an hour here.

### Two clients, one attribute apart

`bootstrap-realm.sh` creates `agent-bound` and `agent-bearer`. They are identical except for one line:

```bash
-s "attributes.\"dpop.bound.access.tokens\"=${bound}"
```

That is the whole configuration. Ask each for a token:

```bash
cd agent && uv run python dump_tokens.py
```

```
Agent's DPoP public key thumbprint (RFC 7638): H0fEUvMuKrtrHewPLh6GSdB-v8pb3KgMMvBQjV5kqTU

--- agent-bound ---
token_type: DPoP
expires_in: 300
aud: ["ledger-api", "account"]
azp: "agent-bound"
scope: "invoice:read profile email"
cnf: {"jkt": "H0fEUvMuKrtrHewPLh6GSdB-v8pb3KgMMvBQjV5kqTU", "kc-jkt-type": "DPoP"}

--- agent-bearer ---
token_type: Bearer
cnf: null
```

Read the two things that changed.

`token_type` is `DPoP`, not `Bearer`. That difference is functional: RFC 9449 §7.1 defines a separate `Authorization: DPoP` scheme, and a bound token sent under `Bearer` must be rejected. The scheme is what stops a proxy or cache that only understands bearer semantics from happily forwarding a token whose rules it doesn't know.

`cnf.jkt` is the SHA-256 thumbprint of the agent's public key (RFC 9449 §6.1, thumbprint computed per RFC 7638). Our script computed that thumbprint independently from our own key and printed it on the first line. They match. The authorization server has stamped *which key this token belongs to* into the token itself.

Note where that happened: at the **token endpoint**. Binding is an issuance-time decision. Nothing a resource server does later can bind a token that was issued unbound, which is why the "downgrade" test later matters.

### The thumbprint is fussy on purpose

Open `agent/dpop.py` and look at `jkt()`:

```python
canonical = json.dumps(
    {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"], "y": jwk["y"]},
    separators=(",", ":"),
    sort_keys=True,
)
return b64u(hashlib.sha256(canonical.encode()).digest())
```

Lexical member order, no whitespace, and **only the required members for the key type**. Add `alg` or `use` (both perfectly legal JWK members) and the thumbprint changes, so the same key stops matching its own `cnf.jkt`. This is the most common DPoP integration bug and it presents as "our tokens randomly stop working", which sends people looking at clocks and caches for a day.

### The proof

A DPoP proof is a small JWT the agent signs per request, carrying its public key in the header:

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

Four required claims (RFC 9449 §4.2), and each one exists to close a specific attack, which is exactly what we are about to demonstrate:

- `htm` / `htu`: method and URL. A proof captured for `POST /invoices` is
useless against `POST /invoices/strict`. Note `htu` drops query and fragment; including them is another silent-mismatch bug.
- `iat`: creation time, checked against a window. Bounds how long a captured
proof stays interesting.
- `jti`: unique id, recorded by the server. Turns "bounded" into "once".
- `ath`: hash of the access token it accompanies (§4.2). Without it a proof is
bound to an endpoint but not to a token, so a captured proof pairs with any other stolen token for the same endpoint.

### The resource server, and its control group

Start it:

```bash
uv run python ledger_api.py
```

`agent/ledger_api.py` serves two endpoints that differ only in rigor. `/invoices` validates signature, issuer, audience, expiry, and scope, and stops there. That is what most services do today, and it's a fair representation of production, not a strawman.

`/invoices/strict` additionally requires the `DPoP` scheme, a `cnf.jkt`, and a proof that survives every check in RFC 9449 §4.3.

Having both is the point. Nearly every result below is only interesting as a *difference* between the two.

---

## Hands-on: Steal the Token

_~20 min · Hands-on_

```bash
uv run python negative_tests.py
```

Twenty-two cases. `HELD` means the defence worked. `ATTACKS` means the attacker won. Those are not bugs, they are the control group.

```
  [   HELD] legitimate agent with its key
            HTTP 200 {"paid":true,"by":"agent-bound","endpoint":"strict"}

  -- the same stolen token, against each endpoint --
  [ATTACKS] stolen BEARER token replayed (lax endpoint)
            HTTP 200  <- the attacker is paid. This is what a bearer token is.
  [   HELD] stolen bound token, no proof, Bearer scheme
            HTTP 401 Authorization scheme is 'Bearer', expected 'DPoP'
  [   HELD] stolen bound token, DPoP scheme, no proof
            HTTP 401 bound token presented with no DPoP proof
  [   HELD] stolen token + attacker's own proof key
            HTTP 401 proof key thumbprint does not match token cnf.jkt
  [   HELD] captured token + proof, replayed verbatim
            first 200, replay HTTP 401 replayed jti f35f9e59-...
  [   HELD] proof minted for a different URL (htu)
            HTTP 401 htu 'http://localhost:8081/invoices' != '.../invoices/strict'
  [   HELD] proof minted for a different method (htm)
            HTTP 401 htm 'GET' != 'POST'
  [   HELD] proof harvested an hour ago (iat window)
            HTTP 401 iat is 3600s away from now
  [   HELD] right key, proof minted over a different token (ath)
            HTTP 401 ath does not match the presented access token
  [   HELD] proof signed with symmetric HS256 (alg confusion)
            HTTP 401 alg 'HS256' is not in the allowlist ['ES256']
  [   HELD] proof signed with symmetric HS384 (alg confusion)
            HTTP 401 alg 'HS384' is not in the allowlist ['ES256']
  [   HELD] proof signed with symmetric HS512 (alg confusion)
            HTTP 401 alg 'HS512' is not in the allowlist ['ES256']
  [   HELD] unbound token on the strict endpoint (downgrade)
            HTTP 401 token has no cnf.jkt -- it is not sender-constrained

  -- and the honest comparison --
  [ATTACKS] bound token, no proof, against the LAX endpoint
            HTTP 200  <- binding does nothing if the RS never checks it
```

### Read the first case and the last case together

The first `ATTACKS` line is today. An attacker who reads one log line is paid.

The last `ATTACKS` line is the trap everyone walks into: that is a **bound** token, with a `cnf.jkt`, presented with no proof at all, and it works, because the endpoint never looked. Turning on DPoP at the authorization server changes nothing by itself. The resource server has to refuse. If you take one operational lesson from this lab, take that one: **rollout is the resource server, not the IdP.**

### The case that carries the argument

`stolen token + attacker's own proof key` is the incident from the previous section, reproduced. The attacker has the complete token. They have working DPoP code. They mint a perfectly valid proof: over the right URL, the right method, a fresh `iat`, a unique `jti`, the correct `ath`. Every check passes except one:

```
proof key thumbprint does not match token cnf.jkt
```

They don't have the key. That is the whole mitigation, and it's why the key storage question from the first section isn't a footnote.

### The three that are one bug in disguise

The `alg confusion` cases all fail with the same message, and the reason they are worth their own heading is what an earlier version of this lab got wrong.

That version checked the algorithm with a **denylist**: reject `none`, reject `HS256`, accept anything else. It passed every test written against it, because the tests only sent `HS256`. An attacker sends `HS384`, which nobody thought to block, signs the proof with a secret they chose, and the verifier happily checks that signature against data the attacker also controls. The key in the header stops being a claim of possession and becomes a decoration.

The fix is one line, and it's the rule for every JWT verifier you will ever write:

```python
PROOF_ALGS = frozenset({"ES256"})
if alg not in PROOF_ALGS:
    raise ProofRejected(...)
```

An allowlist fails closed on the algorithm nobody anticipated; a denylist fails open on it. Note also that the same set feeds `jwt.decode(..., algorithms=sorted(PROOF_ALGS))`: one source, so the check and the decode can't drift into disagreeing about what is acceptable.

### Two cases that are subtler than they look

**Replay.** Watch the ordering: `first 200, replay 401`. The attacker captured a complete, valid request: token and proof together, which is what a compromised proxy or a mirrored TLS session gives you. The first use works because it was the legitimate request. The replay dies on `jti`.

Now read the admission in `agent/dpop.py`:

```python
class ReplayCache:
    """In-memory and per-process, which is wrong the moment a resource server
    runs more than one replica: an attacker replays against a different replica
    and the cache never sees the collision."""
```

Your production replay cache is a shared store with a TTL matching the proof window. A per-process dict passes this test and fails in your cluster, quietly.

**`ath`.** Getting this test to prove anything took a deliberate choice, and the comment in the test says so:

```python
# Reuse the same key deliberately: a different key is caught by the
# thumbprint check first, so the `ath` rule would never be reached and the
# test would prove nothing about `ath`.
```

An attacker with a *different* key trips the thumbprint check before `ath` is ever evaluated. To test `ath` you need the right key and the wrong token. This generalizes: in layered checks, a test can pass because of a check other than the one it claims to exercise. Order your assertions so each one is reachable.

### Break it yourself

Best fifteen minutes in the lab: comment out one check in `verify_proof()` at a time, rerun, and watch exactly one case flip to `BROKEN`. Then try to find a check whose removal breaks nothing, and work out whether you have found redundancy or a test gap.

---

## Hands-on: A Credential That Says Less

_~25 min · Hands-on_

Different question now. The ledger knows the agent may pay invoices. It doesn't know what the agent *is*: who operates it, what model it runs, who to call at 3am when it starts paying the wrong invoices.

The reflex is to stuff those claims into the access token. Resist it. The access token goes to every resource server the agent talks to, so every one of them learns the cost center and the owner's employee id. It also lives five minutes, so provenance that is stable for months gets re-minted constantly.

### One credential, many audiences

```bash
uv run python dump_credential.py
```

```
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

One credential, signed once by the issuer. Two presentations. Neither verifier can open what it was not given, and both can verify the issuer's signature over what they *were* given.

### What is deliberately not hidden

`iss`, `sub`, and `cnf` are always disclosed, and that is a design decision, not an oversight. A verifier that can't see who issued a credential has no trust anchor to check it against, and one that can't see `cnf` can't verify key binding. Hiding those makes the credential unverifiable, not private.

### Decoys, and what selective disclosure does not hide

Look at the digest counts: 10 and 9 unopenable digests for a credential with 7 disclosable claims. The arithmetic doesn't work, and that is the feature.

Selective disclosure hides claim *content*. It doesn't, by itself, hide that further claims exist: the digest array is right there in the payload, and its length leaks the count. A verifier receiving 2 of 7 learns there are 5 more. Often that count alone fingerprints which credential template you hold.

Decoy digests (RFC 9901 §4.2.5) are random hashes that correspond to no claim, added so the array length stops meaning anything. It's real but partial: it blurs a count, it doesn't make the array empty.

### Key binding is what makes it non-transferable

The presentation ends with a **Key Binding JWT** (RFC 9901 §4.3): a small JWT the holder signs over *this* verifier's audience and nonce. Strip it and you have a bearer credential with fewer claims in it: anyone who receives it can present it onward.

The second half of `negative_tests.py` attacks exactly that:

```
  [   HELD] verifier sees only the disclosed claims
            disclosed ['capabilities','cnf','iss','operator','sub'];
            withheld ['cost_center','deployment_env','model',
                      'operator_contact','owner_employee_id']
  [   HELD] count of withheld claims is blurred by decoys
            10 unopenable digests hide 5 real claims
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

The third case is the one to sit with. The attacker is **a legitimate verifier**: you handed it a valid presentation in the normal course of business. It now holds a complete, correctly signed artifact and tries to present it to a second verifier. The audience binding refuses. Without KB-JWT, every verifier you present to becomes able to impersonate you to every other verifier, forever.

Cases four and five are the naive-verifier attack from RFC 9901 §9: the holder edits a disclosed value, then invents a claim outright. A verifier that reads disclosed values without recomputing their digests accepts both. The RFC calls out this exact implementation shortcut, because reading the values is the obvious thing to do and checking the hashes is the extra step.

### The honest tradeoffs

No named breach to cite here, so judge it on these:

**In favor.** Each verifier's compromise exposes only what that verifier was given. Claims stay individually verifiable: the ledger can prove the operator name came from your issuer, not from the agent's own assertion. And it decouples lifetimes: the credential outlives any single token.

**Against.** You now run an issuer, and an issuer is a signing key with an availability requirement. Revocation is genuinely unsolved-ish: status lists and short lifetimes both work, both cost something, and neither is as simple as deleting a session. Verifier implementations are the weak link, as cases four and five show. And the privacy win is partial: unless the credential is re-issued, the same digests appear in every presentation, so colluding verifiers can correlate you even without opening a thing.

That last one is worth saying out loud, because "selective disclosure" sounds like it solves linkability and it doesn't. Unlinkability needs batch issuance or something with more math in it.

---

## What to Take Back to Work

_~14 min · Discussion_

### The order to do this in

1. **Find where your tokens leak.** Grep for tokens in logs. Check whether your
error tracker captures request headers. Look at what your support process asks customers to attach. You will find something, and it will tell you whether any of this is worth doing.
2. **Answer the key storage question before anything else.** No enclave, no KMS,
no non-exportable key? Then DPoP moves your risk from one file to the same file. Fix storage first; the protocol is the easy part.
3. **Make one resource server strict.** Strict means the resource server, not the IdP. Issue
bound tokens broadly if you like, but the acceptance check is the control, and the `ATTACKS` line in this lab exists to prove it.
4. **Only then look at credentials.** SD-JWT solves over-collection, which is a
real problem but rarely the one on fire.

### Questions worth arguing about on the way back

- Where would an agent's private key live in your environment today? If the
answer is "the same secret store as the token", what would it take to change that?
- Your resource servers: how many would notice a token presented with no proof?
How many would notice `Bearer` on a token issued as `DPoP`?
- Is your replay cache shared across replicas, or is it a dict?
- Which of your services receive an access token today and read claims from it
that they have no business reading? That list is your SD-JWT case, written by your own architecture.

### Read the specs

They are unusually readable, and both have a section that is worth the price of admission on its own.

- RFC 9449 (DPoP): §4.3 is a twelve-point checklist. Diff it against your
implementation. https://www.rfc-editor.org/rfc/rfc9449.html
- RFC 9901 (SD-JWT): §9 is the security considerations, including the naive
verifier and Alice-to-Bob. https://www.rfc-editor.org/rfc/rfc9901.html
- Keycloak's DPoP guide, for the preview-feature caveats.
https://www.keycloak.org/securing-apps/dpop

### Tear down

```bash
docker compose down -v
```

---

_Written for the [Zenable Learning Hub](https://www.zenable.app/learn?lab=agent-identity-dpop-sdjwt&utm_source=github&utm_medium=labs_repo&utm_campaign=agent-identity-dpop-sdjwt_readme); published here because the rig lives here. [Browse every lab](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=agent-identity-dpop-sdjwt_readme), or open an issue on this repo if something is broken._
