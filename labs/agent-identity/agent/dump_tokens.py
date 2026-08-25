"""Print both tokens side by side, decoded. The `cnf` line is the lab."""

import json

import jwt

from dpop import jkt, new_key, public_jwk
from tokens import fetch_token

key = new_key()
print(f"Agent's DPoP public key thumbprint (RFC 7638): {jkt(public_jwk(key))}\n")

for client, arg in (("agent-bound", key), ("agent-bearer", None)):
    response = fetch_token(client, arg)
    claims = jwt.decode(response["access_token"], options={"verify_signature": False})
    print(f"--- {client} ---")
    print(f"token_type: {response['token_type']}")
    print(f"expires_in: {response['expires_in']}")
    for claim in ("iss", "aud", "azp", "scope", "cnf"):
        print(f"{claim}: {json.dumps(claims.get(claim))}")
    print()
