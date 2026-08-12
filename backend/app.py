from fastapi import FastAPI

from backend.api.claims import router as claims_router
from backend.api.health import router as health_router
from backend.api.legacy import router as legacy_router
from backend.core.config import Settings
from backend.core.cors import configure_cors
from backend.core.errors import register_exception_handlers
from backend.core.middleware import RequestIdMiddleware
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services.agent import AgentTurnProvider, ControlledAgent


def create_app(
    settings: Settings | None = None,
    repository: PersistenceRepository | None = None,
    agent_turn_provider: AgentTurnProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()
    app = FastAPI(
        title='Northwind FNOL Backend',
        version='0.1.0',
        docs_url='/docs' if resolved_settings.expose_api_docs else None,
        redoc_url=None,
    )
    app.state.settings = resolved_settings
    app.state.claim_repository = repository or FixtureRepository()
    app.state.agent_turn_provider = agent_turn_provider or ControlledAgent()

    configure_cors(app, resolved_settings)
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(legacy_router)
    app.include_router(claims_router)
    return app
