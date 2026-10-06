from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

from fastapi import FastAPI, Request, Response

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
from backend.adapters.policy_history import (
    MockPolicyHistoryAdapter,
    MongoClaimHistoryAdapter,
    PolicyHistoryAdapter,
)
from backend.adapters.staff_identity import (
    FixtureStaffIdentityRepository,
    SQLiteStaffIdentityRepository,
)
from backend.api.admin import router as admin_router
from backend.api.admin_access import router as admin_access_router
from backend.api.admin_accounts import router as admin_accounts_router
from backend.api.admin_agent_rules import router as admin_agent_rules_router
from backend.api.admin_audit import router as admin_audit_router
from backend.api.admin_evaluations import router as admin_evaluations_router
from backend.api.admin_integrations import router as admin_integrations_router
from backend.api.admin_knowledge import router as admin_knowledge_router
from backend.api.admin_operations import router as admin_operations_router
from backend.api.admin_release_sets import router as admin_release_sets_router
from backend.api.capabilities import router as capabilities_router
from backend.api.claims import router as claims_router
from backend.api.demo import router as demo_router
from backend.api.evidence import account_router as evidence_account_router
from backend.api.evidence import router as evidence_router
from backend.api.feedback import admin_router as admin_feedback_router
from backend.api.feedback import staff_router as staff_feedback_router
from backend.api.handoffs import router as handoffs_router
from backend.api.health import router as health_router
from backend.api.identity import router as identity_router
from backend.api.integrations import router as integrations_router
from backend.api.realtime import claimant_router as realtime_claimant_router
from backend.api.realtime import workbench_router as realtime_workbench_router
from backend.api.staff_agent import router as staff_agent_router
from backend.api.staff_identity import router as staff_identity_router
from backend.api.staff_presence import router as staff_presence_router
from backend.api.workbench import conversation_router as workbench_conversation_router
from backend.api.workbench import router as workbench_router
from backend.core.config import (
    AgentRuntimeProfile,
    DataRuntimeProfile,
    ObjectStorageAdapter,
    Settings,
)
from backend.core.cors import configure_cors
from backend.core.errors import ApiError, register_exception_handlers
from backend.core.middleware import RequestIdMiddleware
from backend.core.model_gateway import ConfigurationBackedModelGateway, build_scoped_model_gateway
from backend.core.runtime_profiles import (
    DataRuntimeBundle,
    RuntimeCapabilityStatus,
    RuntimeProfileConfigurationError,
    build_data_runtime_bundle,
    validate_data_runtime_bundle,
)
from backend.domain.configuration import (
    DataProfileConfiguration,
    IntegrationSourceValue,
)
from backend.domain.model_gateway import (
    CLAIMANT_AGENT_PRIVACY_CLASS,
    STAFF_AGENT_PRIVACY_CLASS,
    STAFF_AGENT_PURPOSE,
    ModelEvidenceContentResolver,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
)
from backend.prompts import STAFF_ASSISTANT_PROMPT_ID
from backend.repositories.configuration import (
    ConfigurationRepository,
    SQLiteConfigurationRepository,
)
from backend.repositories.evaluations import EvaluationRepository, SQLiteEvaluationRepository
from backend.repositories.feedback import FeedbackRepository, SQLiteFeedbackRepository
from backend.repositories.handoff_guard import guarded_handoff_repository
from backend.repositories.identity import IdentityRepository
from backend.repositories.integration_health import (
    IntegrationHealthRepository,
    SQLiteIntegrationHealthRepository,
)
from backend.repositories.knowledge_admin import (
    KnowledgeAdminRepository,
    SQLiteKnowledgeAdminRepository,
)
from backend.repositories.operations import OperationRepository, SQLiteOperationRepository
from backend.repositories.protocols import PersistenceRepository
from backend.repositories.release_set import ReleaseSetRepository, SQLiteReleaseSetRepository
from backend.repositories.staff_identity import StaffIdentityRepository
from backend.services.agent import (
    AgentTurnProvider,
    ControlledAgent,
    FeatureControlledAgent,
    InvariantGuardedAgent,
    UnavailableAgent,
)
from backend.services.agent_action_execution import ClaimantRuntimeActionDispatcher
from backend.services.business_seed import (
    BUSINESS_SEED_PATH,
    load_business_seed,
    provision_business_claims,
    provision_business_identities,
    provision_business_policies,
)
from backend.services.external_capability_dispatcher import (
    ExternalCapabilityDispatcher,
    controlled_external_capability_dispatcher,
)
from backend.services.external_service_entry import (
    assert_adapter_matches_entry,
    resolve_external_service_entry,
)
from backend.services.image_recovery import EvidenceProcessingWorker
from backend.services.initial_runtime_release import install_initial_runtime_release
from backend.services.model_agent import GatewayAgent, KnowledgeGroundedAgent
from backend.services.model_operations import ModelOperationsRecorder
from backend.services.model_profiles import model_configuration
from backend.services.pdf_processing import (
    PDF_PROCESSING_PRIVACY_CLASS,
    PDF_PROCESSING_PROMPT_VERSION,
    PDF_PROCESSING_PURPOSE,
    PdfEvidenceProcessor,
)
from backend.services.protected_values import (
    ProtectedValueAdapter,
    protected_value_adapter_for,
)
from backend.services.realtime import RealtimeDispatcher
from backend.services.reply_judge import (
    REPLY_JUDGE_TIMEOUT_SECONDS,
    REPLY_REVIEW_PROMPT_VERSION,
    REPLY_REVIEW_PURPOSE,
    ReplyJudge,
)
from backend.services.runtime_agent_policy import RuntimeAgentPolicyResolver
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
)
from backend.services.runtime_integrations import (
    RuntimeIntegrationConfigurationError,
    RuntimeIntegrationPolicy,
)
from backend.services.staff_agent import (
    ProfileSelectingStaffAgent,
    StaffAgentTurnProvider,
)
from backend.services.staff_seed import load_staff_seed, provision_staff_seed, staff_seed_banner
from backend.services.workbench import TRIAGE_AMOUNT_THRESHOLD


def create_app(
    settings: Settings | None = None,
    repository: PersistenceRepository | None = None,
    agent_turn_provider: AgentTurnProvider | None = None,
    claims_service_adapter: ClaimsServiceAdapter | None = None,
    assessor_service_adapter: AssessorServiceAdapter | None = None,
    evidence_storage: EvidenceStorage | None = None,
    policy_history_adapter: PolicyHistoryAdapter | None = None,
    claim_history_adapter: PolicyHistoryAdapter | None = None,
    handoff_dispatch_adapter: HandoffDispatchAdapter | None = None,
    data_runtime_bundle: DataRuntimeBundle | None = None,
    model_gateway_registry: ModelGatewayRegistry | None = None,
    identity_repository: IdentityRepository | None = None,
    configuration_repository: ConfigurationRepository | None = None,
    release_set_repository: ReleaseSetRepository | None = None,
    staff_identity_repository: StaffIdentityRepository | None = None,
    staff_agent_turn_provider: StaffAgentTurnProvider | None = None,
    integration_health_repository: IntegrationHealthRepository | None = None,
    operation_repository: OperationRepository | None = None,
    evaluation_repository: EvaluationRepository | None = None,
    feedback_repository: FeedbackRepository | None = None,
    knowledge_admin_repository: KnowledgeAdminRepository | None = None,
    external_capability_dispatcher: ExternalCapabilityDispatcher | None = None,
    protected_value_adapter: ProtectedValueAdapter | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()
    resolved_configuration_repository = configuration_repository or (
        ConfigurationRepository()
        if resolved_settings.developer_mode
        else SQLiteConfigurationRepository(resolved_settings.control_plane_db_path)
    )
    resolved_release_set_repository = release_set_repository or (
        ReleaseSetRepository()
        if resolved_settings.developer_mode
        else SQLiteReleaseSetRepository(resolved_settings.control_plane_db_path)
    )
    resolved_knowledge_admin_repository = knowledge_admin_repository or (
        KnowledgeAdminRepository()
        if resolved_settings.developer_mode
        else SQLiteKnowledgeAdminRepository(resolved_settings.control_plane_db_path)
    )
    if (
        resolved_settings.agent_runtime_profile is AgentRuntimeProfile.MODEL_GATEWAY
        and resolved_settings.model_runtime_bindings
    ):
        install_initial_runtime_release(
            resolved_settings,
            resolved_configuration_repository,
            resolved_release_set_repository,
            resolved_knowledge_admin_repository,
        )
    runtime_configuration_resolver = RuntimeConfigurationResolver(
        resolved_configuration_repository,
        resolved_release_set_repository,
        resolved_knowledge_admin_repository,
        environment=resolved_settings.environment,
        runtime_profile=resolved_settings.data_runtime_profile.value,
    )
    try:
        runtime_snapshot = runtime_configuration_resolver.snapshot()
    except RuntimeConfigurationResolutionError as error:
        raise RuntimeProfileConfigurationError(
            'The active Control Plane Release Set cannot be resolved safely.'
        ) from error
    data_profile_record = (
        runtime_snapshot.configurations.get('data_profile')
        if runtime_snapshot.release_set_id is not None
        else None
    )
    if data_profile_record is not None:
        try:
            data_profile = DataProfileConfiguration.model_validate(data_profile_record.values)
            configured_profile = DataRuntimeProfile(data_profile.data_runtime_profile.value)
            configured_storage = ObjectStorageAdapter(data_profile.object_storage_adapter.value)
        except (TypeError, ValueError) as error:
            raise RuntimeProfileConfigurationError(
                'The active Control Plane data_profile configuration is invalid.'
            ) from error
        if configured_profile is not resolved_settings.data_runtime_profile:
            raise RuntimeProfileConfigurationError(
                'The active Control Plane data_profile does not match DATA_RUNTIME_PROFILE.'
            )
        resolved_settings = replace(
            resolved_settings,
            object_storage_adapter=configured_storage,
        )
    injected_data_dependencies = any(
        dependency is not None
        for dependency in (
            repository,
            evidence_storage,
            policy_history_adapter,
            claim_history_adapter,
        )
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
        resolved_repository = repository if repository is not None else fixture_bundle.repository
        provision_business_policies(resolved_repository, load_business_seed(BUSINESS_SEED_PATH))
        bundle = DataRuntimeBundle(
            profile=resolved_settings.data_runtime_profile,
            repository=resolved_repository,
            evidence_storage=evidence_storage or fixture_bundle.evidence_storage,
            policy_history=(
                policy_history_adapter
                if policy_history_adapter is not None
                else MockPolicyHistoryAdapter(resolved_repository)
            ),
            knowledge_documents=fixture_bundle.knowledge_documents,
            knowledge_retrieval=fixture_bundle.knowledge_retrieval,
            claim_history=(
                claim_history_adapter
                if claim_history_adapter is not None
                else MongoClaimHistoryAdapter(resolved_repository)
            ),
        )
    else:
        bundle = data_runtime_bundle or build_data_runtime_bundle(resolved_settings)

    realtime_dispatcher = RealtimeDispatcher(bundle.repository)
    evidence_processing_worker: EvidenceProcessingWorker | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        realtime_dispatcher.start()
        try:
            if evidence_processing_worker is not None:
                evidence_processing_worker.start()
            yield
        finally:
            if evidence_processing_worker is not None:
                evidence_processing_worker.stop()
            realtime_dispatcher.stop()
            bundle.close()

    app = FastAPI(
        title='Northwind FNOL Backend',
        version='0.1.0',
        docs_url='/docs' if resolved_settings.expose_api_docs else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.protected_value_adapter = protected_value_adapter or protected_value_adapter_for(
        resolved_settings.environment
    )
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
        if resolved_settings.staff_seed_path:
            # Staff cannot register and nobody manages accounts in the Control Plane: the
            # seeded accounts are how the Workbench is signed into.
            seed = load_staff_seed(resolved_settings.staff_seed_path)
            provision_staff_seed(staff_repository, seed)
            print(staff_seed_banner(seed), flush=True)
        app.state.staff_identity_repository = staff_repository
    app.state.configuration_repository = resolved_configuration_repository
    app.state.integration_health_repository = integration_health_repository or (
        IntegrationHealthRepository()
        if resolved_settings.developer_mode
        else SQLiteIntegrationHealthRepository(resolved_settings.control_plane_db_path)
    )
    app.state.operation_repository = operation_repository or (
        OperationRepository()
        if resolved_settings.developer_mode
        else SQLiteOperationRepository(resolved_settings.control_plane_db_path)
    )
    model_operations = ModelOperationsRecorder(app.state.operation_repository)
    app.state.evaluation_repository = evaluation_repository or (
        EvaluationRepository()
        if resolved_settings.developer_mode
        else SQLiteEvaluationRepository(resolved_settings.control_plane_db_path)
    )
    app.state.feedback_repository = feedback_repository or (
        FeedbackRepository()
        if resolved_settings.developer_mode
        else SQLiteFeedbackRepository(resolved_settings.control_plane_db_path)
    )
    app.state.knowledge_admin_repository = resolved_knowledge_admin_repository
    app.state.release_set_repository = resolved_release_set_repository
    app.state.runtime_configuration_resolver = runtime_configuration_resolver
    app.state.runtime_agent_policy_resolver = RuntimeAgentPolicyResolver(
        runtime_configuration_resolver
    )
    app.state.data_runtime_bundle = bundle
    app.state.knowledge_document_store = bundle.knowledge_documents
    app.state.knowledge_object_store = bundle.knowledge_documents
    app.state.knowledge_retriever = bundle.knowledge_retrieval
    # Every application consumer reads the repository from app.state, so the
    # handoff lifecycle and ownership invariants are applied once here rather
    # than by individual routers.  No router, service, seed path, or adapter
    # can reach an unguarded handoff write.
    app.state.claim_repository = guarded_handoff_repository(bundle.repository)
    if resolved_settings.business_seed_path:
        try:
            business_seed = load_business_seed(resolved_settings.business_seed_path)
            provision_business_identities(app.state.identity_repository, business_seed)
            provision_business_policies(app.state.claim_repository, business_seed)
            provision_business_claims(app.state.claim_repository, business_seed)
        except Exception:
            bundle.close()
            raise
    app.state.realtime_dispatcher = realtime_dispatcher
    app.state.claimant_runtime_action_dispatcher = ClaimantRuntimeActionDispatcher()
    pdf_processor: PdfEvidenceProcessor | None = None
    if resolved_settings.agent_runtime_profile is AgentRuntimeProfile.MODEL_GATEWAY:
        if agent_turn_provider is not None:
            raise ValueError(
                'agent_turn_provider cannot override the configured model gateway runtime.'
            )
        model_gateway = ConfigurationBackedModelGateway(
            resolved_settings,
            app.state.configuration_repository,
            model_gateway_registry,
            release_set_repository=app.state.release_set_repository,
            runtime_configuration_resolver=app.state.runtime_configuration_resolver,
        )
        if not model_gateway.capabilities.structured_output:
            raise ModelGatewayError(ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY)

        def pdf_gateway(
            evidence_resolver: ModelEvidenceContentResolver,
        ) -> ModelGateway:
            if not resolved_settings.pdf_model_profile_id:
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
            try:
                configuration = model_configuration(
                    SimpleNamespace(app=app), resolved_settings.pdf_model_profile_id
                )
            except (RuntimeConfigurationResolutionError, ValueError):
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from None
            if (
                configuration is None
                or configuration.provider != 'openrouter'
                or configuration.model_identifier != 'openai/gpt-4o'
                or not configuration.document_input
            ):
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
            return build_scoped_model_gateway(
                resolved_settings,
                purpose=PDF_PROCESSING_PURPOSE,
                privacy_class=PDF_PROCESSING_PRIVACY_CLASS,
                prompt_version=PDF_PROCESSING_PROMPT_VERSION,
                profile_suffix='evidence-pdf',
                registry=model_gateway_registry,
                runtime_configuration=configuration,
                evidence_resolver=evidence_resolver,
            )

        pdf_processor = PdfEvidenceProcessor(
            bundle.repository,
            bundle.evidence_storage,
            pdf_gateway,
            resolved_settings.pdf_model_profile_id,
        )

        def reply_judge_gateway() -> ModelGateway:
            # The review model shares the turn model's provider connection; only
            # the model identifier, purpose and a short timeout differ.
            try:
                configuration = model_configuration(
                    SimpleNamespace(app=app), resolved_settings.model_profile_id
                )
            except (RuntimeConfigurationResolutionError, ValueError):
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from None
            if configuration is None:
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
            return build_scoped_model_gateway(
                resolved_settings,
                purpose=REPLY_REVIEW_PURPOSE,
                privacy_class=CLAIMANT_AGENT_PRIVACY_CLASS,
                prompt_version=REPLY_REVIEW_PROMPT_VERSION,
                profile_suffix='reply-review',
                registry=model_gateway_registry,
                runtime_configuration=configuration.model_copy(
                    update={
                        'model_identifier': resolved_settings.reply_judge_model,
                        'timeout_seconds': min(
                            configuration.timeout_seconds, REPLY_JUDGE_TIMEOUT_SECONDS
                        ),
                        'image_input': False,
                        'document_input': False,
                    }
                ),
            )

        reply_judge = (
            ReplyJudge(reply_judge_gateway) if resolved_settings.reply_judge_model else None
        )
        base_agent_turn_provider: AgentTurnProvider = FeatureControlledAgent(
            KnowledgeGroundedAgent(
                GatewayAgent(
                    model_gateway,
                    model_operations,
                    reply_judge,
                    resolved_settings.turn_time_limit_seconds or None,
                ),
                bundle.knowledge_retrieval,
                app.state.knowledge_admin_repository,
                app.state.runtime_configuration_resolver,
            ),
            UnavailableAgent(),
        )
        app.state.agent_runtime_status = 'configured'
        if staff_agent_turn_provider is not None:
            app.state.staff_agent_turn_provider = staff_agent_turn_provider
        else:

            def staff_gateway_for_profile(profile_id: str) -> ModelGateway:
                try:
                    configuration = model_configuration(SimpleNamespace(app=app), profile_id)
                except (RuntimeConfigurationResolutionError, ValueError):
                    raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from None
                if configuration is None:
                    raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
                return build_scoped_model_gateway(
                    resolved_settings,
                    purpose=STAFF_AGENT_PURPOSE,
                    privacy_class=STAFF_AGENT_PRIVACY_CLASS,
                    prompt_version=STAFF_ASSISTANT_PROMPT_ID,
                    profile_suffix='staff-assistant',
                    registry=model_gateway_registry,
                    runtime_configuration=configuration,
                )

            app.state.staff_agent_turn_provider = ProfileSelectingStaffAgent(
                staff_gateway_for_profile, model_operations
            )
    else:
        base_agent_turn_provider = agent_turn_provider or ControlledAgent()
        app.state.agent_runtime_status = 'not_configured'
        app.state.staff_agent_turn_provider = staff_agent_turn_provider
    app.state.agent_turn_provider = InvariantGuardedAgent(base_agent_turn_provider)
    if bundle.profile is not DataRuntimeProfile.FIXTURE:
        evidence_processing_worker = EvidenceProcessingWorker(
            bundle.repository,
            bundle.evidence_storage,
            pdf_processor,
        )
    app.state.evidence_processing_worker = evidence_processing_worker
    # Compatibility state name retained for existing operator/tests; both names are one worker.
    app.state.image_recovery_worker = evidence_processing_worker
    app.state.claims_service_adapter = claims_service_adapter or MockClaimsServiceAdapter()
    resolved_assessor_adapter = assessor_service_adapter or MockAssessorServiceAdapter()
    app.state.evidence_storage = bundle.evidence_storage
    app.state.policy_history_adapter = bundle.policy_history
    app.state.claim_history_adapter = bundle.claim_history
    app.state.handoff_dispatch_adapter = handoff_dispatch_adapter or MockHandoffDispatchAdapter()
    readiness = bundle.readiness_checks()
    actual_integration_sources = {
        service_id: _integration_source_from_status(readiness[service_id])
        for service_id in (
            'persistence',
            'evidence_storage',
            'policy',
            'claim_history',
            'knowledge_documents',
            'knowledge_retrieval',
        )
    }
    actual_integration_sources.update(
        {
            'claims_service': IntegrationSourceValue(
                app.state.claims_service_adapter.integration_source.value
            ),
            'assessor_service': IntegrationSourceValue(
                resolved_assessor_adapter.integration_source.value
            ),
            'handoff_dispatch': IntegrationSourceValue(
                app.state.handoff_dispatch_adapter.integration_source.value
            ),
        }
    )
    runtime_integration_policy = RuntimeIntegrationPolicy(
        runtime_configuration_resolver,
        actual_integration_sources,
    )
    try:
        runtime_integration_policy.validate_selected()
    except RuntimeIntegrationConfigurationError as error:
        raise RuntimeProfileConfigurationError(
            'The active Control Plane integration configuration does not match the runtime.'
        ) from error
    app.state.runtime_integration_policy = runtime_integration_policy
    try:
        assessor_configuration = runtime_integration_policy.require('assessor_service')
    except ApiError:
        assessor_status = RuntimeCapabilityStatus.UNAVAILABLE
        fixture_assessor = False
    else:
        fixture_assessor = (
            assessor_configuration is not None
            and assessor_configuration.source is IntegrationSourceValue.FIXTURE
        ) or (
            assessor_configuration is None
            and resolved_settings.data_runtime_profile
            in {DataRuntimeProfile.FIXTURE, DataRuntimeProfile.LOCAL_MVP}
        )
        assessor_status = (
            RuntimeCapabilityStatus.USING_FIXTURE
            if fixture_assessor
            else RuntimeCapabilityStatus.VERIFIED
        )
    assessor_service_entry = resolve_external_service_entry(
        capability_status=assessor_status,
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
    app.state.external_capability_dispatcher = (
        external_capability_dispatcher or controlled_external_capability_dispatcher()
    )

    configure_cors(app, resolved_settings)
    app.add_middleware(RequestIdMiddleware)

    @app.middleware('http')
    async def apply_triage_settings(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        token = TRIAGE_AMOUNT_THRESHOLD.set(resolved_settings.triage_amount_threshold_nzd)
        try:
            return await call_next(request)
        finally:
            TRIAGE_AMOUNT_THRESHOLD.reset(token)

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(identity_router)
    app.include_router(staff_identity_router)
    app.include_router(staff_feedback_router)
    app.include_router(staff_presence_router)
    app.include_router(staff_agent_router)
    app.include_router(capabilities_router)
    app.include_router(claims_router)
    app.include_router(realtime_claimant_router)
    app.include_router(realtime_workbench_router)
    app.include_router(integrations_router)
    app.include_router(evidence_router)
    app.include_router(evidence_account_router)
    app.include_router(workbench_router)
    app.include_router(workbench_conversation_router)
    app.include_router(demo_router)
    app.include_router(handoffs_router)
    app.include_router(admin_router)
    app.include_router(admin_accounts_router)
    app.include_router(admin_audit_router)
    app.include_router(admin_access_router)
    app.include_router(admin_agent_rules_router)
    app.include_router(admin_integrations_router)
    app.include_router(admin_operations_router)
    app.include_router(admin_evaluations_router)
    app.include_router(admin_knowledge_router)
    app.include_router(admin_release_sets_router)
    app.include_router(admin_feedback_router)
    return app


def _integration_source_from_status(status: str) -> IntegrationSourceValue:
    if status == RuntimeCapabilityStatus.USING_FIXTURE.value:
        return IntegrationSourceValue.FIXTURE
    if status in {
        RuntimeCapabilityStatus.VERIFIED.value,
        'configured_service',
    }:
        return IntegrationSourceValue.CONFIGURED_SERVICE
    raise RuntimeProfileConfigurationError(
        f'Runtime integration source cannot be derived from readiness state {status!r}.'
    )
