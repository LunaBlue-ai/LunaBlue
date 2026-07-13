"""Router aggregator: every route module registers itself on ``api_router``,
which ``main.create_app`` mounts under the ``/api`` prefix."""

from fastapi import APIRouter

from app.api.routes import debug, health, prompt

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(prompt.router, tags=["prompt"])
# Temporary Step 7 bring-up route; removed when Step 9 wires the pipeline.
api_router.include_router(debug.router, tags=["debug"])
