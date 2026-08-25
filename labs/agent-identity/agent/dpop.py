"""DPoP (RFC 9449) proof minting and verification, written out longhand.

A library would hide the four fields that make DPoP work. Every rule the
verifier enforces here is one line in RFC 9449 section 4.3, and the negative
tests in `scripts/` exist to make each of those lines fail on purpose.
"""

import base64
import hashlib
import json
import time
import uuid

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

# RFC 9449 s4.3: "iat" must be within an acceptable window. The window trades
# clock skew against how long a stolen proof stays usable; 60s is what most
# deployments land on. The replay cache below is what actually stops reuse
# inside the window -- the window alone bounds it, it does not prevent it.
MAX_PROOF_AGE_SECONDS = 60


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def b64u_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def new_key() -> ec.EllipticCurvePrivateKey:
    """A fresh P-256 key. In a real agent this lives in a TPM/KMS/enclave and
    never leaves it -- that non-exportability is the entire security argument
    for DPoP, and it is the one property a workshop on a laptop cannot show."""
    return ec.generate_private_key(ec.SECP256R1())


def public_jwk(key: ec.EllipticCurvePrivateKey) -> dict:
    numbers = key.public_key().public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": b64u(numbers.x.to_bytes(32, "big")),
        "y": b64u(numbers.y.to_bytes(32, "big")),
    }


def jkt(jwk: dict) -> str:
    """JWK SHA-256 thumbprint, RFC 7638.

    The member ordering and the exact member set are normative -- lexical
    order, no whitespace, and ONLY the required members for the key type.
    Include `alg` or `use` here and the thumbprint changes, so the token's
    `cnf.jkt` stops matching a key that is in fact the same key.
    """
    canonical = json.dumps(
        {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"], "y": jwk["y"]},
        separators=(",", ":"),
        sort_keys=True,
    )
    return b64u(hashlib.sha256(canonical.encode()).digest())


def access_token_hash(access_token: str) -> str:
    """The `ath` claim: base64url(SHA-256(access token)).

    Without it a proof is bound to a method and a URL but not to a token, so
    a proof captured from one request can be paired with a different stolen
    token for the same endpoint.
    """
    return b64u(hashlib.sha256(access_token.encode()).digest())


def make_proof(
    key: ec.EllipticCurvePrivateKey,
    htm: str,
    htu: str,
    *,
    access_token: str | None = None,
    nonce: str | None = None,
    iat: int | None = None,
    jti: str | None = None,
) -> str:
    """Mint a DPoP proof JWT.

    The optional arguments exist so the negative tests can produce proofs
    that are wrong in exactly one way each.
    """
    claims: dict = {
        "jti": jti or str(uuid.uuid4()),
        "htm": htm,
        # RFC 9449 s4.2: htu is the request URI *without* query or fragment.
        "htu": htu.split("?")[0].split("#")[0],
        "iat": iat if iat is not None else int(time.time()),
    }
    if access_token is not None:
        claims["ath"] = access_token_hash(access_token)
    if nonce is not None:
        claims["nonce"] = nonce
    return jwt.encode(
        claims,
        key,
        algorithm="ES256",
        headers={"typ": "dpop+jwt", "alg": "ES256", "jwk": public_jwk(key)},
    )


class ProofRejected(Exception):
    """Raised with the specific rule that failed, so tests can assert on it."""


class ReplayCache:
    """Seen `jti` values, with their expiry.

    In-memory and per-process, which is wrong the moment a resource server
    runs more than one replica: an attacker replays against a different
    replica and the cache never sees the collision. Production wants a shared
    store (Redis, a DB unique index) with a TTL matching the proof window.
    """

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def check_and_record(self, jti: str, now: float) -> None:
        self._seen = {k: v for k, v in self._seen.items() if v > now}
        if jti in self._seen:
            raise ProofRejected(f"replayed jti {jti}")
        self._seen[jti] = now + MAX_PROOF_AGE_SECONDS


def verify_proof(
    proof: str,
    *,
    htm: str,
    htu: str,
    access_token: str,
    expected_jkt: str,
    replay_cache: ReplayCache,
    now: float | None = None,
) -> dict:
    """Verify a DPoP proof against RFC 9449 s4.3. Raises ProofRejected."""
    now = time.time() if now is None else now

    header = jwt.get_unverified_header(proof)
    if header.get("typ") != "dpop+jwt":
        raise ProofRejected(f"typ is {header.get('typ')!r}, not 'dpop+jwt'")
    if header.get("alg") in (None, "none", "HS256"):
        # Symmetric or absent alg would let the proof be verified with data the
        # attacker also controls. RFC 9449 requires an asymmetric alg.
        raise ProofRejected(f"alg {header.get('alg')!r} is not an asymmetric alg")
    jwk = header.get("jwk")
    if not jwk:
        raise ProofRejected("no jwk in proof header")
    if "d" in jwk:
        raise ProofRejected("proof header carries a private key")

    # The proof is self-signed by the key it carries. That proves possession
    # of the key and nothing else -- the binding to *this* token comes from
    # comparing the thumbprint to cnf.jkt below, which is the whole point.
    claims = jwt.decode(
        proof,
        jwt.PyJWK.from_dict({**jwk, "alg": "ES256"}).key,
        algorithms=["ES256"],
        options={"verify_aud": False},
    )

    if jkt(jwk) != expected_jkt:
        raise ProofRejected("proof key thumbprint does not match token cnf.jkt")
    if claims.get("htm") != htm:
        raise ProofRejected(f"htm {claims.get('htm')!r} != {htm!r}")
    if claims.get("htu") != htu:
        raise ProofRejected(f"htu {claims.get('htu')!r} != {htu!r}")
    if claims.get("ath") != access_token_hash(access_token):
        raise ProofRejected("ath does not match the presented access token")

    iat = claims.get("iat")
    if not isinstance(iat, int):
        raise ProofRejected("iat missing or not an integer")
    if abs(now - iat) > MAX_PROOF_AGE_SECONDS:
        raise ProofRejected(f"iat is {int(abs(now - iat))}s away from now")

    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti:
        raise ProofRejected("jti missing")
    replay_cache.check_and_record(jti, now)

    return claims
