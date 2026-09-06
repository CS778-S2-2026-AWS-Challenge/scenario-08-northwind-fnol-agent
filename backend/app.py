from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.adapters.claims_service import (
    AssessorServiceAdapter,
    ClaimsServiceAdapter,
    MockAssessorServiceAdapter,
    MockClaimsServiceAdapter,
)
from backend.adapters.evidence_storage import EvidenceStorage
from backend.adapters.handoff_dispatch import HandoffDispatchAdapter, MockHandoffDispatchAdapter
from backend.adapters.identity import FixtureIdentityRepository, SQLiteIdentityRepository
from backend.adapters.model_gateway import ModelGatewayRegistry
from backend.adapters.policy_history import PolicyHistoryAdapter
from backend.adapters.staff_identity import (
    FixtureStaffIdentityRepository,
    SQLiteStaffIdentityRepository,
)
from backend.api.admin import router as admin_router
from backend.api.admin_release_sets import router as admin_release_sets_router
from backend.api.capabilities import router as capabilities_router
from backend.api.claims import router as claims_router
from backend.api.demo import router as demo_router
from backend.api.evidence import router as evidence_router
from backend.api.handoffs import router as handoffs_router
from backend.api.health import router as health_router
from backend.api.identity import router as identity_router
from backend.api.integrations import router as integrations_router
from backend.api.legacy import router as legacy_router
from backend.api.staff_agent import router as staff_agent_router
from backend.api.staff_identity import router as staff_identity_router
from backend.api.workbench import conversation_router as workbench_conversation_router
from backend.api.workbench import router as workbench_router
from backend.core.config import AgentRuntimeProfile, DataRuntimeProfile, Settings
from backend.core.cors import configure_cors
from backend.core.errors import register_exception_handlers
from backend.core.middleware import RequestIdMiddleware
from backend.core.model_gateway import ConfigurationBackedModelGateway, build_scoped_model_gateway
from backend.core.runtime_profiles import (
    DataRuntimeBundle,
    RuntimeCapabilityStatus,
    build_data_runtime_bundle,
    validate_data_runtime_bundle,
)
from backend.domain.model_gateway import (
    STAFF_AGENT_PRIVACY_CLASS,
    STAFF_AGENT_PURPOSE,
    ModelGatewayError,
    ModelGatewayErrorCode,
)
from backend.prompts import STAFF_ASSISTANT_PROMPT_ID
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.handoff_guard import guarded_handoff_repository
from backend.repositories.identity import IdentityRepository
from backend.repositories.protocols import PersistenceRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.repositories.staff_identity import StaffIdentityRepository
from backend.services.agent import AgentTurnProvider, ControlledAgent, InvariantGuardedAgent
from backend.services.external_service_entry import (
    assert_adapter_matches_entry,
    resolve_external_service_entry,
)
from backend.services.model_agent import GatewayAgent, KnowledgeGroundedAgent
from backend.services.staff_agent import GatewayStaffAgent, StaffAgentTurnProvider


def create_app(
    settings: Settings | None = None,
    repository: PersistenceRepository | None = None,
    agent_turn_provider: AgentTurnProvider | None = None,
    claims_service_adapter: ClaimsServiceAdapter | None = None,
    assessor_service_adapter: AssessorServiceAdapter | None = None,
    evidence_storage: EvidenceStorage | None = None,
    policy_history_adapter: PolicyHistoryAdapter | None = None,
    handoff_dispatch_adapter: HandoffDispatchAdapter | None = None,
    data_runtime_bundle: DataRuntimeBundle | None = None,
    model_gateway_registry: ModelGatewayRegistry | None = None,
    identity_repository: IdentityRepository | None = None,
    configuration_repository: ConfigurationRepository | None = None,
    staff_identity_repository: StaffIdentityRepository | None = None,
    staff_agent_turn_provider: StaffAgentTurnProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()
    injected_data_dependencies = any(
        dependency is not None
        for dependency in (repository, evidence_storage, policy_history_adapter)
    )
    if data_runtime_bundle is not None and injected_data_dependencies:
        raise ValueError(
            'Pass either data_runtime_bundle or individual test data dependencies, not both.'
        )
    if data_runtime_bundle is not None:
        validate_data_runtime_bundle(resolved_settings, data_runtime_bundle)
    if injected_data_dependencies:
        if resolved_settings.data_runtime_profile is not DataRuntimeProfile.FIXTURE:
            raise ValueError(
                'Individual data dependency injection is allowed only for the fixture profile.'
            )
        fixture_bundle = build_data_runtime_bundle(resolved_settings)
        bundle = DataRuntimeBundle(
            profile=resolved_settings.data_runtime_profile,
            repository=repository or fixture_bundle.repository,
            evidence_storage=evidence_storage or fixture_bundle.evidence_storage,
            policy_history=policy_history_adapter or fixture_bundle.policy_history,
            knowledge_documents=fixture_bundle.knowledge_documents,
            knowledge_retrieval=fixture_bundle.knowledge_retrieval,
        )
    else:
        bundle = data_runtime_bundle or build_data_runtime_bundle(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            bundle.close()

    app = FastAPI(
        title='Northwind FNOL Backend',
        version='0.1.0',
        docs_url='/docs' if resolved_settings.expose_api_docs else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    if identity_repository is not None:
        app.state.identity_repository = identity_repository
    elif resolved_settings.developer_mode:
        app.state.identity_repository = FixtureIdentityRepository()
    else:
        app.state.identity_repository = SQLiteIdentityRepository(resolved_settings.identity_db_path)
    if staff_identity_repository is not None:
        app.state.staff_identity_repository = staff_identity_repository
    elif resolved_settings.developer_mode:
        app.state.staff_identity_repository = FixtureStaffIdentityRepository()
    else:
        staff_repository = SQLiteStaffIdentityRepository(resolved_settings.staff_identity_db_path)
        if resolved_settings.staff_bootstrap_email:
            staff_repository.provision_account(
                resolved_settings.staff_bootstrap_email,
                resolved_settings.staff_bootstrap_password,
                resolved_settings.staff_bootstrap_display_name,
                ('claims_professional',),
            )
        app.state.staff_identity_repository = staff_repository
    app.state.configuration_repository = configuration_repository or ConfigurationRepository()
    app.state.release_set_repository = ReleaseSetRepository()
    app.state.data_runtime_bundle = bundle
    app.state.knowledge_document_store = bundle.knowledge_documents
    app.state.knowledge_retriever = bundle.knowledge_retrieval
    # Every application consumer reads the repository from app.state, so the
    # handoff lifecycle and ownership invariants are applied once here rather
    # than by individual routers.  No router, service, seed path, or adapter
    # can reach an unguarded handoff write.
    app.state.claim_repository = guarded_handoff_repository(bundle.repository)
    if resolved_settings.agent_runtime_profile is AgentRuntimeProfile.MODEL_GATEWAY:
        if agent_turn_provider is not None:
            raise ValueError(
                'agent_turn_provider cannot override the configured model gateway runtime.'
            )
        model_gateway = ConfigurationBackedModelGateway(
            resolved_settings,
            app.state.configuration_repository,
            model_gateway_registry,
        )
        if not model_gateway.capabilities.structured_output:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)
        base_agent_turn_provider: AgentTurnProvider = KnowledgeGroundedAgent(
            GatewayAgent(model_gateway),
            bundle.knowledge_retrieval,
        )
        app.state.agent_runtime_status = 'configured'
        app.state.staff_agent_turn_provider = staff_agent_turn_provider or GatewayStaffAgent(
            build_scoped_model_gateway(
                resolved_settings,
                purpose=STAFF_AGENT_PURPOSE,
                privacy_class=STAFF_AGENT_PRIVACY_CLASS,
                prompt_version=STAFF_ASSISTANT_PROMPT_ID,
                profile_suffix='staff-assistant',
                registry=model_gateway_registry,
            )
        )
    else:
        base_agent_turn_provider = agent_turn_provider or ControlledAgent()
        app.state.agent_runtime_status = 'not_configured'
        app.state.staff_agent_turn_provider = staff_agent_turn_provider
    app.state.agent_turn_provider = InvariantGuardedAgent(base_agent_turn_provider)
    app.state.claims_service_adapter = claims_service_adapter or MockClaimsServiceAdapter()
    resolved_assessor_adapter = assessor_service_adapter or MockAssessorServiceAdapter()
    fixture_assessor = resolved_settings.data_runtime_profile is DataRuntimeProfile.FIXTURE
    assessor_service_entry = resolve_external_service_entry(
        capability_status=(
            RuntimeCapabilityStatus.USING_FIXTURE
            if fixture_assessor
            else RuntimeCapabilityStatus.PENDING_CONFIRMATION
        ),
        allow_test_fixture=fixture_assessor,
    )
    # The entry and the adapter are chosen independently above, so the composition
    # is checked rather than assumed: a runtime that would answer through one
    # source class while recording another must not assemble at all.
    assert_adapter_matches_entry(
        resolved_assessor_adapter.integration_source,
        assessor_service_entry,
    )
    app.state.assessor_service_adapter = resolved_assessor_adapter
    app.state.assessor_service_entry = assessor_service_entry
    app.state.evidence_storage = bundle.evidence_storage
    app.state.policy_history_adapter = bundle.policy_history
    app.state.handoff_dispatch_adapter = handoff_dispatch_adapter or MockHandoffDispatchAdapter()

    configure_cors(app, resolved_settings)
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(identity_router)
    app.include_router(staff_identity_router)
    app.include_router(staff_agent_router)
    app.include_router(legacy_router)
    app.include_router(capabilities_router)
    app.include_router(claims_router)
    app.include_router(integrations_router)
    app.include_router(evidence_router)
    app.include_router(workbench_router)
    app.include_router(workbench_conversation_router)
    app.include_router(demo_router)
    app.include_router(handoffs_router)
    app.include_router(admin_router)
    app.include_router(admin_release_sets_router)
    return app
