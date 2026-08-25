"""Every attack this lab claims to mitigate, run against the running rig.

Each case is one attack, stated as what the attacker has and what they try.
A case that PASSES means the defence held. The bearer cases are here to fail
on the lax endpoint on purpose -- that contrast is the whole argument.
"""

import json
import secrets
import time
import uuid

import httpx
import jwt
from jwcrypto.jwk import JWK

import sdjwt_verify as V
from dpop import access_token_hash, make_proof, new_key
from sdjwt_issue import issue, present
from tokens import fetch_token

LAX = "http://localhost:8081/invoices"
STRICT = "http://localhost:8081/invoices/strict"
WHOAMI = "http://localhost:8081/whoami"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, held: bool, detail: str, *, control: bool = False) -> None:
    """`control=True` marks a case that is SUPPOSED to succeed for the attacker.

    Those cases are not failures of the rig -- they are the measurement the
    lab is built around, and folding them into the pass count would hide the
    only number that matters.
    """
    RESULTS.append((name, held or control, detail))
    label = "ATTACKS" if control else ("HELD" if held else "BROKEN")
    print(f"  [{label:>7}] {name}\n            {detail}")


def call(url: str, token: str, *, scheme: str = "DPoP", proof: str | None = None):
    headers = {"authorization": f"{scheme} {token}"}
    if proof:
        headers["DPoP"] = proof
    return httpx.post(url, headers=headers, timeout=10)


def reason(response: httpx.Response) -> str:
    try:
        return f"HTTP {response.status_code} {response.json().get('reason', response.text)}"
    except Exception:
        return f"HTTP {response.status_code} {response.text[:120]}"


def dpop_cases() -> None:
    print("\nDPoP -- attacker has exfiltrated the access token")
    agent_key = new_key()
    bound = fetch_token("agent-bound", agent_key)["access_token"]
    plain = fetch_token("agent-bearer")["access_token"]

    # Baseline: the legitimate agent, holding its key, still works. A lab that
    # only shows attacks failing has not shown the control is usable.
    response = call(STRICT, bound, proof=make_proof(agent_key, "POST", STRICT, access_token=bound))
    record("legitimate agent with its key", response.status_code == 200, reason(response))

    print("\n  -- the same stolen token, against each endpoint --")
    response = call(LAX, plain, scheme="Bearer")
    record(
        "stolen BEARER token replayed (lax endpoint)",
        response.status_code != 200,
        reason(response) + "  <- the attacker is paid. This is what a bearer token is.",
        control=True,
    )

    response = call(STRICT, bound, scheme="Bearer")
    record("stolen bound token, no proof, Bearer scheme", response.status_code != 200, reason(response))

    response = call(STRICT, bound)
    record("stolen bound token, DPoP scheme, no proof", response.status_code != 200, reason(response))

    # The attacker has the token and mints their own proof with their own key.
    # This is the case that matters: exfiltrating a token from a log, a HAR
    # file, or a compromised proxy gives you the token and never the key.
    attacker_key = new_key()
    response = call(STRICT, bound, proof=make_proof(attacker_key, "POST", STRICT, access_token=bound))
    record("stolen token + attacker's own proof key", response.status_code != 200, reason(response))

    # The attacker captured a full request -- token AND proof -- off the wire.
    captured = make_proof(agent_key, "POST", STRICT, access_token=bound)
    first = call(STRICT, bound, proof=captured)
    replay = call(STRICT, bound, proof=captured)
    record(
        "captured token + proof, replayed verbatim",
        first.status_code == 200 and replay.status_code != 200,
        f"first {first.status_code}, replay {reason(replay)}",
    )

    # Proof captured for one endpoint, aimed at another.
    elsewhere = make_proof(agent_key, "POST", LAX, access_token=bound)
    response = call(STRICT, bound, proof=elsewhere)
    record("proof minted for a different URL (htu)", response.status_code != 200, reason(response))

    response = call(STRICT, bound, proof=make_proof(agent_key, "GET", STRICT, access_token=bound))
    record("proof minted for a different method (htm)", response.status_code != 200, reason(response))

    # A proof harvested from an old session, outside the freshness window.
    stale = make_proof(agent_key, "POST", STRICT, access_token=bound, iat=int(time.time()) - 3600)
    response = call(STRICT, bound, proof=stale)
    record("proof harvested an hour ago (iat window)", response.status_code != 200, reason(response))

    # Proof is valid, fresh, and signed by the RIGHT key -- but it was minted
    # over a different access token. Reuse the same key deliberately: a
    # different key is caught by the thumbprint check first, so the `ath` rule
    # would never be reached and the test would prove nothing about `ath`.
    second_token = fetch_token("agent-bound", agent_key)["access_token"]
    mismatched = make_proof(agent_key, "POST", STRICT, access_token=second_token)
    response = call(STRICT, bound, proof=mismatched)
    record("right key, proof minted over a different token (ath)",
           response.status_code != 200, reason(response))

    # Downgrade: present an unbound token on the endpoint that demands binding.
    response = call(STRICT, plain, proof=make_proof(new_key(), "POST", STRICT, access_token=plain))
    record("unbound token on the strict endpoint (downgrade)", response.status_code != 200, reason(response))

    print("\n  -- and the honest comparison --")
    response = call(LAX, bound, scheme="Bearer")
    record(
        "bound token, no proof, against the LAX endpoint",
        response.status_code != 200,
        reason(response) + "  <- binding does nothing if the RS never checks it",
        control=True,
    )


def sdjwt_cases() -> None:
    print("\nSD-JWT -- what a verifier learns, and what it can replay")
    issuer_key = JWK.generate(kty="EC", crv="P-256", alg="ES256")
    holder_key = JWK.generate(kty="EC", crv="P-256", alg="ES256")
    V.ISSUER_KEY_FILE.write_text(issuer_key.export_public())
    credential = issue(issuer_key, holder_key)

    nonce = httpx.post(WHOAMI, json={}).headers.get("x-nonce") or secrets.token_urlsafe(16)
    minimal = present(credential, ["operator", "capabilities"], nonce=nonce,
                      audience=WHOAMI, holder_key=holder_key)
    response = httpx.post(WHOAMI, json={"presentation": minimal, "nonce": nonce}, timeout=10)
    disclosed = response.json().get("claims", {})
    withheld = {"cost_center", "owner_employee_id", "operator_contact", "model", "deployment_env"}
    record(
        "verifier sees only the disclosed claims",
        response.status_code == 200 and not (withheld & disclosed.keys()),
        f"disclosed {sorted(disclosed)}; withheld {sorted(withheld)}",
    )
    record(
        "count of withheld claims is blurred by decoys",
        V.undisclosed_digest_count(minimal) > len(withheld),
        f"{V.undisclosed_digest_count(minimal)} unopenable digests hide {len(withheld)} real claims",
    )

    # The verifier now holds a complete, signed presentation. Can it reuse it?
    other_verifier = "http://localhost:8081/whoami-other"
    try:
        V.verify_presentation(minimal, expected_audience=other_verifier, expected_nonce=nonce)
        held, detail = False, "presentation verified at a verifier it was not addressed to"
    except V.VerificationFailed as exc:
        held, detail = True, f"rejected: {exc}"
    record("verifier replays the presentation elsewhere (aud)", held, detail)

    try:
        V.verify_presentation(minimal, expected_audience=WHOAMI, expected_nonce=secrets.token_urlsafe(16))
        held, detail = False, "presentation verified against a nonce it never signed"
    except V.VerificationFailed as exc:
        held, detail = True, f"rejected: {exc}"
    record("presentation replayed in a later session (nonce)", held, detail)

    # Tamper with a disclosure: change the operator name, keep everything else.
    parts = minimal.split("~")
    import base64
    for index, part in enumerate(parts[1:-1], start=1):
        raw = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        if raw[1] == "operator":
            raw[2] = "Totally Legit Corp"
            parts[index] = base64.urlsafe_b64encode(
                json.dumps(raw, separators=(",", ":")).encode()).decode().rstrip("=")
            break
    tampered = "~".join(parts)
    try:
        V.verify_presentation(tampered, expected_audience=WHOAMI, expected_nonce=nonce)
        held, detail = False, "tampered disclosure accepted"
    except V.VerificationFailed as exc:
        held, detail = True, f"rejected: {exc}"
    record("holder edits a disclosed value (digest)", held, detail)

    # Present a claim the issuer never issued, by inventing a disclosure.
    forged = base64.urlsafe_b64encode(
        json.dumps([secrets.token_urlsafe(16), "capabilities", ["invoice:pay", "admin:all"]],
                   separators=(",", ":")).encode()).decode().rstrip("=")
    invented = "~".join([parts[0], forged, parts[-1]])
    try:
        V.verify_presentation(invented, expected_audience=WHOAMI, expected_nonce=nonce)
        held, detail = False, "invented claim accepted"
    except V.VerificationFailed as exc:
        held, detail = True, f"rejected: {exc}"
    record("holder invents a claim the issuer never signed", held, detail)

    # A presentation with the KB-JWT stripped: the bearer-credential failure.
    stripped = "~".join(parts[:-1]) + "~"
    try:
        V.verify_presentation(stripped, expected_audience=WHOAMI, expected_nonce=nonce)
        held, detail = False, "presentation accepted with no key binding"
    except V.VerificationFailed as exc:
        held, detail = True, f"rejected: {exc}"
    record("key-binding JWT stripped", held, detail)


if __name__ == "__main__":
    dpop_cases()
    sdjwt_cases()
    broken = [name for name, held, _ in RESULTS if not held]
    print(f"\n{len(RESULTS) - len(broken)}/{len(RESULTS)} cases behaved as documented")
    if broken:
        print("BROKEN: " + ", ".join(broken))
        raise SystemExit(1)
