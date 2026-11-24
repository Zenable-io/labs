"""Copyright (c) 2026 Zenable, Inc. Client helper: resolve a peer's card, then call it the way the card says.

The important property is that nothing here hardcodes how to authenticate.
`StaticTokenCredentials.get_credentials` is handed the security-scheme *name
from the peer's card*, and the SDK attaches whatever it returns. Point the
same code at an agent that declares a different scheme and the flow changes
without an edit.
"""

from __future__ import annotations

import httpx
from a2a.client import (
    A2ACardResolver,
    AuthInterceptor,
    ClientCallContext,
    ClientConfig,
    CredentialService,
    create_client,
)
from a2a.helpers import get_stream_response_text, new_text_message
from a2a.types import AgentCard, SendMessageRequest
from card_signing import build_card_verifier


class StaticTokenCredentials(CredentialService):
    """Supplies one already-fetched token for whichever scheme the card names."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def get_credentials(
        self, security_scheme_name: str, context: ClientCallContext | None
    ) -> str | None:
        print(f"[client] card asked for scheme '{security_scheme_name}'", flush=True)
        return self._token


async def fetch_card(base_url: str) -> AgentCard:
    """Read a peer's public card. Deliberately unauthenticated."""
    async with httpx.AsyncClient(timeout=10) as http:
        resolver = A2ACardResolver(httpx_client=http, base_url=base_url)
        return await resolver.get_agent_card()


async def send_text(
    base_url: str,
    text: str,
    *,
    token: str | None = None,
    verify_signature: bool = False,
) -> str:
    """Send one message to a peer agent and return its text response.

    `verify_signature` is off by default so the lab can show what an
    unverified client hands to a stranger before turning the check on.
    """
    async with httpx.AsyncClient(timeout=30) as http:
        interceptors = [AuthInterceptor(StaticTokenCredentials(token))] if token else []
        # Pass the URL, never a card you fetched yourself. `create_client`
        # only applies `signature_verifier` on the path where it resolves the
        # card, so handing it an AgentCard object silently skips verification
        # and still accepts the argument.
        client = await create_client(
            base_url,
            client_config=ClientConfig(httpx_client=http, streaming=False),
            interceptors=interceptors,
            signature_verifier=build_card_verifier() if verify_signature else None,
        )
        request = SendMessageRequest(message=new_text_message(text))
        chunks = [
            get_stream_response_text(response)
            async for response in client.send_message(request)
        ]
        return "\n".join(chunk for chunk in chunks if chunk).strip()
