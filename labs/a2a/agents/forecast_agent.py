"""Copyright (c) 2026 Zenable, Inc. Agent A -- the forecast agent.

Serves one public skill (`forecast.lookup`) behind a Keycloak-issued token,
and calls Agent B when it produces a severe forecast. That callback is the
point: an A2A participant is a server and a client at the same time, holding
one identity it enforces and a different one it presents.

Deterministic by construction -- a fixed lookup table, no model, no API key.
The lab is teaching the protocol, and a lab that fails on somebody's quota
teaches nothing.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import uvicorn
from a2a.client import A2AClientError
from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    OpenIdConnectSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils import TransportProtocol
from a2a_auth import DISCOVERY_URL, ClientCredentials, RequireOIDCScope
from a2a_client_util import send_text
from card_signing import build_card_signer
from starlette.applications import Starlette

PORT = int(os.environ.get("FORECAST_PORT", "9001"))
PLANNER_URL = os.environ.get("PLANNER_URL", "http://localhost:9002")

# The whole "model". Same input, same output, every run.
FORECASTS: dict[str, tuple[str, bool]] = {
    "reykjavik": ("Storm force winds, 4C, horizontal rain", True),
    "lisbon": ("Clear, 24C, light breeze from the Atlantic", False),
    "denver": ("Sunny, 18C, afternoon thunderstorms possible", False),
    "singapore": ("Humid, 31C, thunderstorms after 16:00", False),
}


def build_agent_card(*, extended: bool = False) -> AgentCard:
    """The public card, or the richer one a verified caller receives.

    The public card is an advertisement to strangers; the extended card is
    what a caller earns by authenticating. Splitting them lets an agent be
    discoverable without publishing its whole internal surface.
    """
    skills = [
        AgentSkill(
            id="forecast.lookup",
            name="Look up a forecast",
            description="Returns the current forecast for a supported city.",
            tags=["weather", "forecast"],
            examples=["What is the weather in Lisbon?", "forecast for Reykjavik"],
            input_modes=["text/plain"],
            output_modes=["text/plain"],
            # Per-skill requirements: A2A 1.0 lets one endpoint expose skills
            # with different authorization, so the scope lives on the skill
            # rather than only on the agent.
            security_requirements=[
                SecurityRequirement(
                    schemes={"keycloak": StringList(list=["forecast:read"])}
                )
            ],
        )
    ]
    if extended:
        skills.append(
            AgentSkill(
                id="forecast.stations",
                name="List observation stations",
                description="Internal station inventory. Not advertised publicly.",
                tags=["weather", "internal"],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
                security_requirements=[
                    SecurityRequirement(
                        schemes={"keycloak": StringList(list=["forecast:read"])}
                    )
                ],
            )
        )

    return AgentCard(
        name="Forecast Agent",
        description="Deterministic weather forecasts for a small set of cities.",
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(
                url=f"http://localhost:{PORT}/",
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version="1.0",
            )
        ],
        capabilities=AgentCapabilities(streaming=True, extended_agent_card=True),
        # What the card promises about authentication. A caller reads this
        # and knows to go to Keycloak before knocking.
        security_schemes={
            "keycloak": SecurityScheme(
                open_id_connect_security_scheme=OpenIdConnectSecurityScheme(
                    description="Keycloak service-account tokens for the a2a-workshop realm",
                    open_id_connect_url=DISCOVERY_URL,
                )
            )
        },
        security_requirements=[
            SecurityRequirement(
                schemes={"keycloak": StringList(list=["forecast:read"])}
            )
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=skills,
    )


class ForecastExecutor(AgentExecutor):
    def __init__(self) -> None:
        # Agent A's own workload identity, used only when it calls Agent B.
        self.credentials = ClientCredentials(
            client_id=os.environ.get("FORECAST_CLIENT_ID", "agent-a-forecast"),
            client_secret=os.environ.get("FORECAST_CLIENT_SECRET", "agent-a-secret"),
        )

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = (context.get_user_input() or "").strip().lower()
        city = next((name for name in FORECASTS if name in query), None)

        if city is None:
            await event_queue.enqueue_event(
                new_text_message(
                    f"No forecast for that location. Known cities: "
                    f"{', '.join(sorted(FORECASTS))}."
                )
            )
            return

        summary, severe = FORECASTS[city]
        await event_queue.enqueue_event(new_text_message(f"{city.title()}: {summary}"))

        if severe:
            # The reverse call. Fire-and-forget so a slow peer cannot stall
            # the response the original caller is waiting on.
            asyncio.create_task(self._alert_planner(city, summary))

    async def _alert_planner(self, city: str, summary: str) -> None:
        try:
            token = await self.credentials.token()
            reply = await send_text(
                PLANNER_URL,
                f"replan {city}: {summary}",
                token=token,
            )
            print(f"[forecast] planner acknowledged: {reply}", flush=True)
        except (httpx.HTTPError, A2AClientError) as exc:
            # The caller waiting on the forecast is already served; a peer that
            # is down must not turn their success into a failure.
            print(f"[forecast] alert to planner failed: {exc}", flush=True)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("forecast lookups are not long-running")


def build_app() -> Starlette:
    public_card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=ForecastExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=public_card,
        extended_agent_card=build_agent_card(extended=True),
    )
    app = Starlette(
        routes=[
            *create_agent_card_routes(public_card, card_modifier=build_card_signer()),
            *create_jsonrpc_routes(handler, rpc_url="/"),
        ]
    )
    app.add_middleware(
        RequireOIDCScope,
        audience="agent-a-forecast",
        required_scope="forecast:read",
        # The card must stay readable by an unauthenticated stranger.
        public_paths=("/.well-known/agent-card.json",),
    )
    return app


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=PORT, log_level="warning")
