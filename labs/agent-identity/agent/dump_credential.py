"""Issue one agent credential, present two different subsets of it."""

import json
import secrets

from jwcrypto.jwk import JWK

import sdjwt_verify as V
from sdjwt_issue import agent_claims, issue, present

issuer_key = JWK.generate(kty="EC", crv="P-256", alg="ES256")
holder_key = JWK.generate(kty="EC", crv="P-256", alg="ES256")
V.ISSUER_KEY_FILE.write_text(issuer_key.export_public())

everything = agent_claims(json.loads(holder_key.export_public()))
print("What the issuer signed:")
for key, value in everything.items():
    # SDObj wraps a claim name to mark it selectively disclosable; unwrap it
    # so this reads as a claim list rather than as library internals.
    name = getattr(key, "value", key)
    kind = "selectively disclosable" if name is not key else "always disclosed"
    print(f"  {name:<20} {kind}")

credential = issue(issuer_key, holder_key)
disclosable = sum(1 for k in everything if hasattr(k, "value"))
print(f"\nIssued: {disclosable} disclosable claims, plus decoy digests to blur that count\n")

audience = "http://localhost:8081/whoami"
for label, disclose in (
    ("the ledger, which only needs to know who runs this agent",
     ["operator", "capabilities"]),
    ("the incident responder, who needs to reach a human",
     ["operator", "operator_contact", "deployment_env"]),
):
    nonce = secrets.token_urlsafe(16)
    presentation = present(credential, disclose, nonce=nonce, audience=audience,
                           holder_key=holder_key)
    seen = V.verify_presentation(presentation, expected_audience=audience,
                                 expected_nonce=nonce)
    print(f"--- presented to {label} ---")
    print(f"verifier sees:  {sorted(seen)}")
    print(f"verifier cannot open: {V.undisclosed_digest_count(presentation)} digests")
    print()
