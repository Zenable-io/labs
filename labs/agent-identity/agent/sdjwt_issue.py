"""Issue an SD-JWT agent credential, and present a subset of it.

The credential answers "what is this agent, and who stands behind it". That
is a different question from the access token's "may this caller do X", and
the reason it is a different artifact is lifetime: an access token lives for
minutes, an agent's provenance is stable for its whole deployment.
"""

import json

from jwcrypto.jwk import JWK
from sd_jwt.common import SDObj
from sd_jwt.holder import SDJWTHolder
from sd_jwt.issuer import SDJWTIssuer

ISSUER_ID = "https://issuer.agent-identity.test"


def agent_claims(holder_jwk: dict) -> dict:
    """The credential's claims. `SDObj` marks a claim selectively disclosable.

    What is NOT wrapped matters as much as what is. `iss`, `cnf`, and the
    agent's own id are always disclosed, because a verifier that cannot see
    who issued the credential or which key holds it cannot verify anything.
    Everything a verifier might legitimately not need is disclosable.
    """
    return {
        "iss": ISSUER_ID,
        "sub": "agent://acme/invoice-clerk/7",
        "cnf": {"jwk": holder_jwk},
        SDObj("operator"): "Acme Corp",
        SDObj("operator_contact"): "soc@acme.example",
        SDObj("model"): "claude-opus-5",
        SDObj("deployment_env"): "production",
        SDObj("cost_center"): "FIN-2291",
        SDObj("owner_employee_id"): "E-88213",
        SDObj("capabilities"): ["invoice:read", "invoice:pay"],
    }


def issue(issuer_key: JWK, holder_key: JWK) -> str:
    """Issue the credential, bound to the holder's key via `cnf`.

    `add_decoy_claims` pads the digest array so its LENGTH stops leaking how
    many claims were withheld. Without decoys a verifier receiving two of
    seven digests learns there are five more; it still learns nothing about
    their content, but the count alone is often enough to fingerprint.
    """
    issued = SDJWTIssuer(
        agent_claims(json.loads(holder_key.export_public())),
        issuer_key,
        holder_key,
        sign_alg="ES256",
        add_decoy_claims=True,
    )
    return issued.sd_jwt_issuance


def present(credential: str, disclose: list[str], *, nonce: str, audience: str,
            holder_key: JWK) -> str:
    """Build a presentation revealing only `disclose`, plus a KB-JWT.

    The key-binding JWT is what makes a presentation non-transferable: it is
    signed by the holder key over this verifier's audience and nonce, so a
    verifier that receives a presentation cannot turn around and replay it
    to a second verifier. A presentation without KB is just a bearer
    credential with fewer claims in it.
    """
    holder = SDJWTHolder(credential)
    holder.create_presentation(
        {claim: True for claim in disclose},
        nonce,
        audience,
        holder_key,
        sign_alg="ES256",
    )
    return holder.sd_jwt_presentation
