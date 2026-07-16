"""Router aggregator: every route module registers itself on ``api_router``,
which ``main.create_app`` mounts under the ``/api`` prefix."""

from fastapi import APIRouter

from app.api.routes import agents, health, prompt, state

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(prompt.router, tags=["prompt"])
api_router.include_router(state.router, tags=["state"])
api_router.include_router(agents.router, tags=["agents"])
