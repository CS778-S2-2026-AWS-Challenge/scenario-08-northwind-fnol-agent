from fastapi import FastAPI

from backend.adapters.claims_service import (
    AssessorServiceAdapter,
    ClaimsServiceAdapter,
    MockAssessorServiceAdapter,
    MockClaimsServiceAdapter,
)
from backend.adapters.evidence_storage import EvidenceStorage, MockEvidenceStorage
from backend.adapters.policy_history import MockPolicyHistoryAdapter, PolicyHistoryAdapter
from backend.api.claims import router as claims_router
from backend.api.demo import router as demo_router
from backend.api.evidence import router as evidence_router
from backend.api.handoffs import router as handoffs_router
from backend.api.health import router as health_router
from backend.api.integrations import router as integrations_router
from backend.api.legacy import router as legacy_router
from backend.api.workbench import router as workbench_router
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
    claims_service_adapter: ClaimsServiceAdapter | None = None,
    assessor_service_adapter: AssessorServiceAdapter | None = None,
    evidence_storage: EvidenceStorage | None = None,
    policy_history_adapter: PolicyHistoryAdapter | None = None,
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
    app.state.claims_service_adapter = claims_service_adapter or MockClaimsServiceAdapter()
    app.state.assessor_service_adapter = assessor_service_adapter or MockAssessorServiceAdapter()
    app.state.evidence_storage = evidence_storage or MockEvidenceStorage()
    app.state.policy_history_adapter = policy_history_adapter or MockPolicyHistoryAdapter()

    configure_cors(app, resolved_settings)
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(legacy_router)
    app.include_router(claims_router)
    app.include_router(integrations_router)
    app.include_router(evidence_router)
    app.include_router(workbench_router)
    app.include_router(demo_router)
    app.include_router(handoffs_router)
    return app
