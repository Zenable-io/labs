"""Copyright (c) 2026 Zenable, Inc. Agent B -- the trip planner.

Calls Agent A for a forecast, then composes an itinerary. Also serves a
`trip.replan` skill that Agent A calls back into, so traffic runs both ways
between two peers that never share a process, a database, or a framework --
only a card and an issuer.
"""

from __future__ import annotations

import os

import uvicorn
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
from starlette.applications import Starlette

PORT = int(os.environ.get("PLANNER_PORT", "9002"))
FORECAST_URL = os.environ.get("FORECAST_URL", "http://localhost:9001")

ACTIVITIES = {
    "storm": "indoor: thermal pools, museum, long lunch",
    "clear": "outdoor: coastal walk, viewpoint at sunset",
    "default": "flexible: morning market, afternoon decided on the day",
}


def build_agent_card() -> AgentCard:
    return AgentCard(
        name="Trip Planner Agent",
        description="Plans a one-day itinerary, consulting the forecast agent for weather.",
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(
                url=f"http://localhost:{PORT}/",
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version="1.0",
            )
        ],
        capabilities=AgentCapabilities(streaming=True),
        security_schemes={
            "keycloak": SecurityScheme(
                open_id_connect_security_scheme=OpenIdConnectSecurityScheme(
                    description="Keycloak service-account tokens for the a2a-workshop realm",
                    open_id_connect_url=DISCOVERY_URL,
                )
            )
        },
        security_requirements=[
            SecurityRequirement(schemes={"keycloak": StringList(list=["trip:plan"])})
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="trip.plan",
                name="Plan a day trip",
                description="Builds a one-day itinerary for a city, weather-aware.",
                tags=["travel", "planning"],
                examples=["plan a day in Lisbon", "plan Reykjavik"],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
                security_requirements=[
                    SecurityRequirement(
                        schemes={"keycloak": StringList(list=["trip:plan"])}
                    )
                ],
            ),
            AgentSkill(
                id="trip.replan",
                name="Revise a plan after a weather alert",
                description="Accepts a severe-weather alert and returns a revised itinerary.",
                tags=["travel", "planning", "alerts"],
                examples=["replan reykjavik: Storm force winds"],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
                security_requirements=[
                    SecurityRequirement(
                        schemes={"keycloak": StringList(list=["trip:plan"])}
                    )
                ],
            ),
        ],
    )


class PlannerExecutor(AgentExecutor):
    def __init__(self) -> None:
        self.credentials = ClientCredentials(
            client_id=os.environ.get("PLANNER_CLIENT_ID", "agent-b-planner"),
            client_secret=os.environ.get("PLANNER_CLIENT_SECRET", "agent-b-secret"),
        )

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = (context.get_user_input() or "").strip()

        if query.lower().startswith("replan"):
            await event_queue.enqueue_event(
                new_text_message(
                    f"Revised plan: {ACTIVITIES['storm']} (weather alert accepted)"
                )
            )
            return

        city = query.lower().replace("plan a day in", "").replace("plan", "").strip()
        if not city:
            await event_queue.enqueue_event(
                new_text_message("Tell me a city, e.g. 'plan a day in Lisbon'.")
            )
            return

        # Agent B presents its OWN service-account token here. It is not
        # forwarding the token it was called with -- that token's audience is
        # Agent B, and replaying it at Agent A is exactly what the audience
        # check exists to stop.
        token = await self.credentials.token()
        forecast = await send_text(FORECAST_URL, f"forecast for {city}", token=token)

        lowered = forecast.lower()
        if "storm" in lowered:
            activities = ACTIVITIES["storm"]
        elif "clear" in lowered or "sunny" in lowered:
            activities = ACTIVITIES["clear"]
        else:
            activities = ACTIVITIES["default"]

        await event_queue.enqueue_event(
            new_text_message(
                f"Plan for {city.title()}\n  forecast: {forecast}\n  {activities}"
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("planning is not long-running")


def build_app() -> Starlette:
    card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=PlannerExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    app = Starlette(
        routes=[
            *create_agent_card_routes(card),
            *create_jsonrpc_routes(handler, rpc_url="/"),
        ]
    )
    app.add_middleware(
        RequireOIDCScope,
        audience="agent-b-planner",
        required_scope="trip:plan",
        public_paths=("/.well-known/agent-card.json",),
    )
    return app


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=PORT, log_level="warning")
