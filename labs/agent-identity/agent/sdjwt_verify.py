"""Verify an SD-JWT presentation. The verifier half of the credential story."""

import json
from pathlib import Path

from jwcrypto.jwk import JWK
from sd_jwt.verifier import SDJWTVerifier

ISSUER_KEY_FILE = Path(__file__).parent / "issuer-public-key.json"


class VerificationFailed(Exception):
    pass


def issuer_public_key() -> JWK:
    """In production this is a JWKS fetched over HTTPS from the issuer and
    cached. A file keeps the lab offline and keeps the trust decision visible:
    a verifier trusts this credential because it trusts THIS key, not because
    the credential says who issued it."""
    return JWK.from_json(ISSUER_KEY_FILE.read_text())


def verify_presentation(presentation: str, *, expected_audience: str,
                        expected_nonce: str) -> dict:
    """Return only the claims the holder chose to disclose.

    The audience and nonce are not optional niceties: pass None for either and
    the reference implementation still verifies the signatures, so a replayed
    presentation from another verifier's session validates cleanly.
    """

    def get_issuer_key(issuer: str, header: dict) -> JWK:
        # Pinning on `iss` is the trust decision. Skipping this check and
        # reading the key from the token's own header is the classic JWT
        # confusion bug -- the credential would then attest to itself.
        if issuer != "https://issuer.agent-identity.test":
            raise VerificationFailed(f"unknown issuer {issuer!r}")
        return issuer_public_key()

    try:
        verifier = SDJWTVerifier(
            presentation,
            get_issuer_key,
            expected_aud=expected_audience,
            expected_nonce=expected_nonce,
        )
        return verifier.get_verified_payload()
    except VerificationFailed:
        raise
    except Exception as exc:
        raise VerificationFailed(str(exc)) from exc


def undisclosed_digest_count(presentation: str) -> int:
    """How many digests the verifier can see but cannot open.

    Useful for showing that selective disclosure hides content, not the
    existence of further claims -- which is exactly what decoy digests blur.
    """
    import base64

    body = presentation.split("~")[0].split(".")[1]
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    total = len(payload.get("_sd", []))
    disclosed = len([part for part in presentation.split("~")[1:] if part])
    # The trailing element is the KB-JWT, not a disclosure.
    return total - max(disclosed - 1, 0)
