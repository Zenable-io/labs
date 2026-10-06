"""Copyright (c) 2026 Zenable, Inc. Agent card signing and verification.

The card is the document that tells a caller where to send data and what
credential to attach. Trusting an unsigned one means trusting whoever
answered the DNS query. A signature moves that trust to a key you already
hold.

Keys live on disk here for the workshop. In production the private key
belongs in a KMS/HSM and the public half is published at a `jku` the
verifier already trusts.
"""

from __future__ import annotations

from pathlib import Path

from a2a.types import AgentCard
from a2a.utils.signing import (
    ProtectedHeader,
    create_agent_card_signer,
    create_signature_verifier,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_DIR = Path(__file__).parent / ".keys"
PRIVATE_KEY_PATH = KEY_DIR / "card-signing-private.pem"
PUBLIC_KEY_PATH = KEY_DIR / "card-signing-public.pem"
SIGNING_KID = "forecast-card-key-1"


def ensure_keypair() -> tuple[bytes, bytes]:
    """Create the signing keypair on first use; reuse it afterwards."""
    if not PRIVATE_KEY_PATH.exists():
        KEY_DIR.mkdir(exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        PRIVATE_KEY_PATH.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        PUBLIC_KEY_PATH.write_bytes(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
    return PRIVATE_KEY_PATH.read_bytes(), PUBLIC_KEY_PATH.read_bytes()


def build_card_signer():
    """Returns an async card modifier that signs the served card."""
    private_key, _ = ensure_keypair()
    sign = create_agent_card_signer(
        signing_key=private_key,
        protected_header=ProtectedHeader(alg="RS256", kid=SIGNING_KID),
    )

    # The route expects an awaitable modifier; the SDK's signer is sync.
    async def modifier(card: AgentCard) -> AgentCard:
        return sign(card)

    return modifier


def build_card_verifier():
    """Returns a verifier that rejects any card not signed by our key."""
    _, public_key = ensure_keypair()

    def key_provider(kid: str | None, jku: str | None):
        # Pinned to one key on purpose. A verifier that fetches whatever key
        # the card's own `jku` points at verifies that the card signed
        # itself, which is not a trust decision.
        if kid != SIGNING_KID:
            raise ValueError(f"unknown signing key id: {kid!r}")
        return public_key

    return create_signature_verifier(key_provider=key_provider, algorithms=["RS256"])
