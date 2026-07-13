"""Router aggregator: every route module registers itself on ``api_router``,
which ``main.create_app`` mounts under the ``/api`` prefix."""

from fastapi import APIRouter

from app.api.routes import health

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
