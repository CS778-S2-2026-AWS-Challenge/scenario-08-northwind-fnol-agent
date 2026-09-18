import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from types import MappingProxyType

import pytest

from backend.domain.agent_action_registry import registered_actions
from backend.domain.agent_context_runtime import (
    ContextBudgetPolicy,
    ContextLoadMode,
    ContextReference,
    ModelRequestBudget,
    RequestProfile,
    TurnTask,
    VerifiedConversationSummary,
)
from backend.domain.agent_runtime_configuration import (
    AgentFeatureSettingsConfiguration,
    AgentInstructionConfiguration,
    AgentToolPolicyConfiguration,
    ControlledRulesConfiguration,
)
from backend.domain.configuration import (
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
    ModelRuntimeConfiguration,
)
from backend.domain.external_service_registry import capability_context
from backend.domain.knowledge import KnowledgeChunk, KnowledgeRetrievalUnavailable, KnowledgeSearch
from backend.domain.knowledge_admin import KnowledgeSourceRecord, KnowledgeVersionState
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelEvidenceContent,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelRequest,
    ModelResponse,
    ModelTextContent,
    ModelToolCall,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    BranchEvaluationResult,
    Channel,
    CustomerNextStep,
    FormSource,
    FormStatus,
    MessageRecord,
    MessageVisibility,
    NeededFor,
    RequirementResolution,
    ResponsibleParty,
    StructuredFormField,
    WorkingClaim,
)
from backend.domain.prompt_pack import (
    PromptApplicability,
    PromptFragmentDefinition,
    PromptPackManifest,
)
from backend.services.agent import AgentEvidenceReference, AgentTurnContext, InvariantGuardedAgent
from backend.services.context_budget import estimate_json_tokens
from backend.services.context_planner import ContextBudgetExceeded, plan_context
from backend.services.context_resolver import TurnContextResolver
from backend.services.model_agent import GatewayAgent, KnowledgeGroundedAgent
from backend.services.model_request_planner import plan_model_turn
from backend.services.prompt_composer import (
    compose_prompt,
    load_fragment_contents,
    load_prompt_manifest,
    load_response_schemas,
)
from backend.services.provider_capability_registry import (
    provider_capability,
    validate_capability_binding,
    validate_profile_compatibility,
)
from backend.services.request_profile_registry import registered_request_profiles, request_profile
from backend.services.runtime_agent_policy import (
    RuntimeAgentPolicySnapshot,
    registered_agent_tool_names,
)
from backend.services.runtime_configuration import RuntimeConfigurationSnapshot
from backend.services.turn_router import route_turn


def _claim(*, incident_type: str | None = 'motor') -> WorkingClaim:
    timestamp = datetime.now(UTC)
    return WorkingClaim(
        claim_id='clm_v7',
        customer_id='cus_v7',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type=incident_type,
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def _model_record(
    *,
    image_input: bool = True,
    document_input: bool = True,
) -> ConfigurationRecord:
    return ConfigurationRecord(
        configuration_id='cfg_model_v7',
        domain='model',
        configuration_key='qwen-local',
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact=ConfigurationImpact.HIGH,
        values={
            'protocol': 'openai_compatible',
            'provider': 'qwen-local',
            'model_identifier': 'qwen3.8-27b',
            'base_url': 'http://model.example.test/v1',
            'credential_environment_variable': None,
            'profile_id': 'qwen-local',
            'purpose': 'agent_turn',
            'privacy_class': 'synthetic_fnol',
            'prompt_version': 'northwind-fnol-claimant-v7',
            'evaluation_status': 'configured',
            'timeout_seconds': 120.0,
            'structured_output': True,
            'tools': True,
            'image_input': image_input,
            'document_input': document_input,
        },
        author='test',
        reason='Test v7 model binding.',
        updated_at=datetime.now(UTC),
    )


def _runtime_policy(snapshot: RuntimeConfigurationSnapshot) -> RuntimeAgentPolicySnapshot:
    manifest = load_prompt_manifest()
    contents = load_fragment_contents(manifest)
    model_record = snapshot.model('qwen-local')
    assert model_record is not None
    model_configuration = ModelRuntimeConfiguration.model_validate(model_record.values)
    return RuntimeAgentPolicySnapshot(
        runtime_snapshot=snapshot,
        instruction=AgentInstructionConfiguration(
            prompt_version='northwind-fnol-claimant-v7',
            composition_mode='fragmented',
            manifest_version=manifest.prompt_pack_version,
            fragments=[
                {
                    **item.model_dump(mode='json'),
                    'content': contents[item.fragment_id],
                }
                for item in manifest.fragments
            ],
        ),
        tool_policy=AgentToolPolicyConfiguration(
            policy_version='test-v7',
            allowed_action_codes=list(registered_actions()),
            allowed_tool_names=list(registered_agent_tool_names()),
            request_profiles=list(registered_request_profiles()),
            provider_capabilities={'qwen-local': provider_capability(model_configuration)},
            schema_registry=load_response_schemas(),
        ),
        controlled_rules=ControlledRulesConfiguration(
            rules_version='test-v7',
            route_policy_version='test-router-v7',
            context_catalogue_version='test-context-v7',
            context_budget_policy=ContextBudgetPolicy(),
            deterministic_responses={
                'unresolved_family': 'Choose motor, home, or contents.',
                'context_budget_exceeded': 'Provide one shorter detail.',
            },
        ),
        features=AgentFeatureSettingsConfiguration(
            feature_version='test-v7',
            fragmented_prompt=True,
            budgeted_context=True,
            narrow_schema=True,
            verified_rolling_summary=True,
            isolated_execution=True,
            cache_layout_version='test-cache-v7',
        ),
    )


def _messages(count: int) -> tuple[MessageRecord, ...]:
    timestamp = datetime.now(UTC)
    return tuple(
        MessageRecord(
            message_id=f'msg_history_{index}',
            claim_id='clm_v7',
            session_id='ses_v7',
            actor=ActorType.CLAIMANT,
            visibility=MessageVisibility.CLAIMANT_VISIBLE,
            content={'type': 'text', 'text': f'History message {index}.'},
            created_at=timestamp,
        )
        for index in range(count)
    )


def _context(
    message: str,
    *,
    incident_type: str | None = 'motor',
    conversation_messages: tuple[MessageRecord, ...] = (),
    evidence: tuple[AgentEvidenceReference, ...] = (),
) -> AgentTurnContext:
    model_record = _model_record()
    snapshot = RuntimeConfigurationSnapshot(
        environment='test',
        runtime_profile='fixture',
        release_set_id='rel_v7',
        configurations=MappingProxyType({'model:qwen-local': model_record}),
        integrations=MappingProxyType({}),
        knowledge=MappingProxyType({}),
    )
    return AgentTurnContext(
        claim=_claim(incident_type=incident_type),
        session_id='ses_v7',
        model_profile_id='qwen-local',
        trigger_message_id='msg_v7',
        message_text=message,
        evidence_refs=[item.evidence_id for item in evidence],
        evidence=evidence,
        evidence_resolver=_EvidenceResolver() if evidence else None,
        runtime_configuration_snapshot=snapshot,
        runtime_policy=_runtime_policy(snapshot),
        conversation_messages=conversation_messages,
    )


class _RecordingGateway:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True, tools=True)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.responses.pop(0)

    def complete_for_snapshot_with_evidence(
        self,
        request: ModelRequest,
        _snapshot: object,
        _resolver: object,
    ) -> ModelResponse:
        return self.complete(request)


class _FailingRecordingGateway(_RecordingGateway):
    def __init__(self, error: ModelGatewayError) -> None:
        super().__init__([])
        self.error = error

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        raise self.error


class _EvidenceResolver:
    def resolve(self, evidence_id: str, media_type: str) -> bytes | None:
        return f'{evidence_id}:{media_type}'.encode()


class _KnowledgeRetriever:
    def __init__(self, outcome: str) -> None:
        self.outcome = outcome
        self.requests: list[KnowledgeSearch] = []

    def connection_status(self) -> str:
        return 'fixture'

    def search(self, request: KnowledgeSearch) -> list[KnowledgeChunk]:
        self.requests.append(request)
        if self.outcome == 'unavailable':
            raise KnowledgeRetrievalUnavailable('temporary outage')
        return [_knowledge_chunk()] if self.outcome == 'evidence_found' else []


def _answer_output() -> dict[str, object]:
    return {
        'reply': 'Your current claim remains in progress.',
        'next_step': 'Continue when ready.',
        'reason_codes': ['CURRENT_STATUS_REPORTED'],
    }


def _intake_output() -> dict[str, object]:
    return {
        **_answer_output(),
        'field_changes': [],
        'contents_item_changes': [],
        'service_offer_ids': [],
    }


def _knowledge_chunk() -> KnowledgeChunk:
    return KnowledgeChunk(
        document_id='doc_motor_policy',
        chunk_id='chk_motor_policy',
        title='Motor policy guidance',
        document_type='policy',
        version='v1',
        section_path='claims.damage',
        page=1,
        source_uri='https://example.test/motor-policy',
        jurisdiction='NZ',
        insurer='Northwind Insurance',
        product='motor',
        effective_from=None,
        effective_to=None,
        authority='northwind_synthetic_demo',
        visibility='customer_and_staff',
        checksum='0' * 64,
        ingested_at=datetime.now(UTC),
        text='Damage assessment guidance for a motor Claim.',
    )


def _knowledge_source() -> KnowledgeSourceRecord:
    return KnowledgeSourceRecord(
        knowledge_id='knw_motor_policy',
        document_id='doc_motor_policy',
        version='v1',
        source_key='knowledge/motor-policy.md',
        title='Motor policy guidance',
        document_type='policy',
        source_uri='https://example.test/motor-policy',
        jurisdiction='NZ',
        insurer='Northwind Insurance',
        product='motor',
        authority='northwind_synthetic_demo',
        visibility='customer_and_staff',
        state=KnowledgeVersionState.PUBLISHED,
        revision=1,
        author='test',
        chunk_count=1,
        updated_at=datetime.now(UTC),
    )


def _fragment(
    fragment_id: str,
    *,
    requires: list[str] | None = None,
) -> PromptFragmentDefinition:
    return PromptFragmentDefinition(
        fragment_id=fragment_id,
        version='v1',
        path=f'{fragment_id}.md',
        kind='core',
        load_mode=ContextLoadMode.ALWAYS,
        requires=requires or [],
        priority=100,
        max_tokens=100,
    )


def test_router_keeps_authoritative_family_and_resolves_ambiguous_new_claims() -> None:
    authoritative = route_turn(
        _context(
            'My laptop at home was also damaged, but update this collision.', incident_type='motor'
        )
    )
    assert authoritative.product_family == 'motor'
    assert authoritative.family_resolution == 'authoritative'
    assert authoritative.task is TurnTask.CORRECTION

    unresolved = route_turn(_context('My car and furniture were damaged.', incident_type=None))
    assert unresolved.product_family is None
    assert unresolved.model_required is False
    assert unresolved.deterministic_response is not None


def test_prompt_manifest_compiles_one_family_in_stable_order() -> None:
    route = route_turn(_context('I need a damage assessor for my car.'))
    first = compose_prompt(route, load_prompt_manifest())
    second = compose_prompt(route, load_prompt_manifest())
    assert first == second
    assert first.prompt_bundle_id == 'claimant-v7:motor:external_support:assessor'
    refs = [item.fragment_id for item in first.fragment_refs]
    assert 'family.motor' in refs
    assert 'family.home' not in refs
    assert 'capability.assessor' in refs
    assert (
        refs.index('core.authority')
        < refs.index('family.motor')
        < refs.index('task.external-support')
    )


def test_prompt_composer_ignores_external_capability_terms_during_evidence_review() -> None:
    route = route_turn(
        _context(
            'Please review this repair assessment PDF and summarise what it supports.',
            evidence=(
                AgentEvidenceReference(
                    evidence_id='ev_assessment',
                    media_type='application/pdf',
                ),
            ),
        )
    )

    bundle = compose_prompt(route, load_prompt_manifest())

    assert route.task is TurnTask.EVIDENCE_CURRENT
    refs = [item.fragment_id for item in bundle.fragment_refs]
    assert 'task.evidence-current' in refs
    assert 'task.external-support' not in refs
    assert 'capability.assessor' not in refs
    assert 'capability.repair' not in refs


def test_prompt_composer_rejects_a_selected_fragment_outside_its_applicability() -> None:
    route = route_turn(_context('My car was damaged.'))
    manifest = load_prompt_manifest()
    fragments = [
        item.model_copy(update={'applies_when': PromptApplicability(product_family=['home'])})
        if item.fragment_id == 'family.motor'
        else item
        for item in manifest.fragments
    ]

    with pytest.raises(ValueError, match='does not apply to product family'):
        compose_prompt(route, manifest.model_copy(update={'fragments': fragments}))


def test_prompt_composer_rejects_missing_conflicting_and_over_budget_fragments() -> None:
    route = route_turn(_context('My car was damaged.'))
    manifest = load_prompt_manifest()

    without_family = manifest.model_copy(
        update={
            'fragments': [item for item in manifest.fragments if item.fragment_id != 'family.motor']
        }
    )
    with pytest.raises(ValueError, match='unknown fragments'):
        compose_prompt(route, without_family)

    conflicting = manifest.model_copy(
        update={
            'fragments': [
                item.model_copy(update={'conflicts_with': ['task.intake']})
                if item.fragment_id == 'family.motor'
                else item
                for item in manifest.fragments
            ]
        }
    )
    with pytest.raises(ValueError, match='conflict'):
        compose_prompt(route, conflicting)

    over_budget = manifest.model_copy(
        update={
            'fragments': [
                item.model_copy(update={'max_tokens': 1})
                if item.fragment_id == 'core.authority'
                else item
                for item in manifest.fragments
            ]
        }
    )
    with pytest.raises(ValueError, match='token limit'):
        compose_prompt(route, over_budget)


@pytest.mark.parametrize(
    ('fragments', 'expected_error'),
    [
        ([_fragment('core.a'), _fragment('core.a')], 'unique'),
        ([_fragment('core.a', requires=['core.missing'])], 'unknown ID'),
        (
            [
                _fragment('core.a', requires=['core.b']),
                _fragment('core.b', requires=['core.a']),
            ],
            'cycle',
        ),
    ],
)
def test_prompt_manifest_rejects_ambiguous_dependency_graphs(
    fragments: list[PromptFragmentDefinition],
    expected_error: str,
) -> None:
    with pytest.raises(ValueError, match=expected_error):
        PromptPackManifest(prompt_pack_version='test-v1', fragments=fragments)


@pytest.mark.parametrize(
    ('values', 'expected_error'),
    [
        (
            {
                'tool_names': ['context.resolve'],
                'max_model_invocations': 2,
                'max_model_selected_tools': 0,
            },
            'permit one selected tool',
        ),
        (
            {
                'tool_names': ['context.resolve'],
                'max_model_invocations': 1,
                'max_model_selected_tools': 1,
                'requires_tool_continuation': True,
            },
            'second model invocation',
        ),
        (
            {
                'tool_names': [],
                'max_model_invocations': 1,
                'max_model_selected_tools': 1,
            },
            'tool-free profile',
        ),
    ],
)
def test_request_profile_rejects_incoherent_invocation_contracts(
    values: dict[str, object],
    expected_error: str,
) -> None:
    with pytest.raises(ValueError, match=expected_error):
        RequestProfile(
            profile_id='test.profile.v1',
            version='v1',
            schema_id='test.schema.v1',
            input_hard_limit=3000,
            output_limit=180,
            **values,
        )


@pytest.mark.parametrize(
    ('raw_input_tokens', 'turn_cumulative_tokens', 'expected_error'),
    [
        (301, 301, 'request exceeds'),
        (200, 301, 'turn exceeds'),
    ],
)
def test_request_budget_rejects_single_and_cumulative_overflow(
    raw_input_tokens: int,
    turn_cumulative_tokens: int,
    expected_error: str,
) -> None:
    with pytest.raises(ValueError, match=expected_error):
        ModelRequestBudget(
            policy_version='test-v1',
            raw_input_tokens=raw_input_tokens,
            uncached_input_tokens=raw_input_tokens,
            cache_eligible_tokens=0,
            turn_cumulative_tokens=turn_cumulative_tokens,
            reserved_output_tokens=10,
            prompt_tokens=0,
            schema_tokens=0,
            context_tokens=raw_input_tokens,
            tool_definition_tokens=0,
            recent_history_tokens=0,
            retrieved_context_tokens=0,
            hard_limit=300,
            estimate_method='conservative_chars',
        )


@pytest.mark.parametrize(
    ('family', 'message', 'expected_fragment'),
    [
        ('motor', 'My car was damaged.', 'family.motor'),
        ('home', 'A pipe flooded my home.', 'family.home'),
        ('contents', 'My laptop was stolen.', 'family.contents'),
    ],
)
def test_each_product_family_compiles_only_its_own_fragment(
    family: str,
    message: str,
    expected_fragment: str,
) -> None:
    plan = plan_model_turn(_context(message, incident_type=family))

    assert plan is not None
    family_refs = [item for item in plan.fragment_refs if item.startswith('family.')]
    assert family_refs == [f'{expected_fragment}@v1']


@pytest.mark.parametrize(
    ('message', 'service_identity'),
    [
        ('Please arrange a damage assessment.', 'vehicle_damage_assessment_routing'),
        ('Please help me book a repairer.', 'vehicle_repairer_booking'),
        ('I need the police reporting details.', 'police_105_reporting_guidance'),
    ],
)
def test_external_support_offers_only_registry_candidates_pending_consent(
    message: str,
    service_identity: str,
) -> None:
    context = replace(
        _context(message),
        external_services=capability_context('motor'),
        selected_external_service_ids=(service_identity,),
    )
    gateway = _RecordingGateway(
        [
            ModelResponse(
                structured_output={
                    **_answer_output(),
                    'service_offer_ids': [service_identity],
                },
                completion_status=ModelCompletionStatus.COMPLETE,
            )
        ]
    )

    proposal = GatewayAgent(gateway).propose_turn(context)

    request_context = json.loads(gateway.requests[0].messages[1].content or '{}')
    offered_services = request_context['external.services']
    assert service_identity in {item['service_identity'] for item in offered_services}
    assert 1 <= len(offered_services) <= 3
    assert proposal.customer_next_step.status == 'external_service_consent_required'
    assert proposal.external_service_intents == [
        {'service_identity': service_identity, 'requested_action': 'submit_request'}
    ]
    assert proposal.state_changes == []


def test_image_review_does_not_load_unrelated_external_service_context() -> None:
    context = replace(
        _context(
            'Please inspect this damage photo.',
            evidence=(AgentEvidenceReference(evidence_id='ev_photo', media_type='image/jpeg'),),
        ),
        external_services=capability_context('motor'),
    )

    plan = plan_model_turn(context)

    assert plan is not None
    assert plan.route.task is TurnTask.EVIDENCE_CURRENT
    assert plan.request_profile.output_limit == 400
    assert 'external.services' not in plan.context_payload
    assert all(
        entry.resource_id != 'external.services' for entry in plan.context_plan.catalogue_entries
    )


def test_request_profiles_fail_closed_against_provider_capabilities() -> None:
    configuration = ModelRuntimeConfiguration.model_validate(_model_record().values)
    capability = provider_capability(configuration)
    validate_profile_compatibility(request_profile('claimant.lookup.v1'), capability)

    no_tools = capability.model_copy(
        update={'tool_call_support': False, 'tool_result_continuation': None}
    )
    with pytest.raises(ValueError, match='tool manifest'):
        validate_profile_compatibility(request_profile('claimant.lookup.v1'), no_tools)

    false_cache_contract = capability.model_copy(update={'prompt_cache_type': 'explicit'})
    with pytest.raises(ValueError, match='model binding'):
        validate_capability_binding(configuration, false_cache_contract)

    bedrock = provider_capability(configuration.model_copy(update={'protocol': 'bedrock_converse'}))
    assert bedrock.structured_output_method == 'forced_tool'
    assert bedrock.prompt_cache_type == 'none'
    with pytest.raises(ValueError, match='continuation'):
        validate_profile_compatibility(request_profile('claimant.lookup.v1'), bedrock)

    text_only = capability.model_copy(update={'supported_media_types': ['text/plain']})
    with pytest.raises(ValueError, match='media contract'):
        validate_profile_compatibility(request_profile('claimant.media.v1'), text_only)


def test_model_turn_planning_fails_before_transport_when_release_inputs_are_incomplete() -> None:
    context = _context('My car was damaged.')
    with pytest.raises(ValueError, match='configuration snapshot'):
        plan_model_turn(replace(context, runtime_configuration_snapshot=None))

    empty_snapshot = RuntimeConfigurationSnapshot(
        environment='test',
        runtime_profile='fixture',
        release_set_id=None,
        configurations=MappingProxyType({}),
        integrations=MappingProxyType({}),
        knowledge=MappingProxyType({}),
    )
    with pytest.raises(ValueError, match='absent'):
        plan_model_turn(replace(context, runtime_configuration_snapshot=empty_snapshot))

    policy = context.runtime_policy
    assert policy is not None
    missing_schema = replace(
        policy,
        tool_policy=policy.tool_policy.model_copy(update={'schema_registry': {}}),
    )
    with pytest.raises(ValueError, match='schema is absent'):
        plan_model_turn(replace(context, runtime_policy=missing_schema))

    text_only_record = _model_record(image_input=False, document_input=False)
    text_only_snapshot = RuntimeConfigurationSnapshot(
        environment='test',
        runtime_profile='fixture',
        release_set_id='rel_text_only',
        configurations=MappingProxyType({'model:qwen-local': text_only_record}),
        integrations=MappingProxyType({}),
        knowledge=MappingProxyType({}),
    )
    media_context = replace(
        _context(
            'Review this photo.',
            evidence=(AgentEvidenceReference(evidence_id='ev_photo', media_type='image/jpeg'),),
        ),
        runtime_configuration_snapshot=text_only_snapshot,
        runtime_policy=_runtime_policy(text_only_snapshot),
    )
    with pytest.raises(ValueError, match='media contract'):
        plan_model_turn(media_context)


def test_ordinary_model_plan_is_single_call_tool_free_and_budgeted() -> None:
    context = _context('My car was rear-ended this morning.')
    plan = plan_model_turn(context)
    assert plan is not None
    assert plan.request_profile.profile_id == 'claimant.intake.v1'
    assert plan.request_profile.max_model_invocations == 1
    assert plan.request_profile.tool_names == []
    assert plan.request_budget.raw_input_tokens <= 3000
    assert plan.request_budget.reserved_output_tokens == 180
    assert plan.context_payload['message.latest'] == 'My car was rear-ended this morning.'
    assert plan.context_plan.estimated_tokens == estimate_json_tokens(plan.context_payload)
    assert all(
        'inline_value' not in item.model_dump(mode='json')
        for item in plan.context_plan.catalogue_entries
    )
    assert plan.cache_plan.segments[0].checkpoint is True
    assert plan.cache_plan.layout_version == 'test-cache-v7'
    assert len(plan.cache_plan.prefix_fingerprint) == 64
    assert plan.cache_plan.tool_manifest_id.endswith(':none')
    repeated = plan_model_turn(context)
    assert repeated is not None
    assert plan.cache_plan == repeated.cache_plan


def test_cache_prefix_fingerprint_tracks_actual_published_schema_content() -> None:
    context = _context('My car was rear-ended this morning.')
    original = plan_model_turn(context)
    assert original is not None
    policy = context.runtime_policy
    assert policy is not None
    schemas = deepcopy(policy.tool_policy.schema_registry)
    schemas['claimant.intake-patch.v1'] = {
        **schemas['claimant.intake-patch.v1'],
        'description': 'A distinct published schema revision.',
    }
    changed_policy = replace(
        policy,
        tool_policy=policy.tool_policy.model_copy(update={'schema_registry': schemas}),
    )

    changed = plan_model_turn(replace(context, runtime_policy=changed_policy))

    assert changed is not None
    assert changed.cache_plan.prefix_fingerprint != original.cache_plan.prefix_fingerprint


def test_current_status_uses_one_tool_free_answer_profile_without_older_history() -> None:
    plan = plan_model_turn(_context('What is the status of my claim?'))

    assert plan is not None
    assert plan.request_profile.profile_id == 'claimant.answer.v1'
    assert plan.request_profile.tool_names == []
    assert plan.request_profile.max_model_invocations == 1


def test_recent_history_does_not_repeat_the_trigger_message() -> None:
    current = _messages(1)[0].model_copy(
        update={'message_id': 'msg_v7', 'content': {'type': 'text', 'text': 'Current status?'}}
    )
    plan = plan_model_turn(
        _context(
            'Current status?',
            conversation_messages=(*_messages(4), current),
        )
    )

    assert plan is not None
    recent = plan.context_payload['conversation.recent']
    assert isinstance(recent, list)
    assert [item['content']['text'] for item in recent] == [
        'History message 0.',
        'History message 1.',
        'History message 2.',
        'History message 3.',
    ]


def test_policy_and_rag_lookup_resolves_only_the_published_turn_reference() -> None:
    calls: list[tuple[str, int]] = []

    def load_policy(limit: int) -> dict[str, object]:
        calls.append(('policy', limit))
        return {'status': 'evidence_found', 'facts': {'coverage_sections': ['damage']}}

    def load_knowledge(limit: int) -> dict[str, object]:
        calls.append(('knowledge', limit))
        return {'status': 'evidence_found', 'chunks': [{'chunk_id': 'chk_policy'}]}

    context = replace(
        _context('Does my policy cover this collision?'),
        policy_context_loader=load_policy,
        knowledge_context_loader=load_knowledge,
    )
    plan = plan_model_turn(context)
    assert plan is not None
    reference = next(
        item for item in plan.context_plan.references if item.resource_type == 'policy_version'
    )
    assert calls == []
    gateway = _RecordingGateway(
        [
            ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        call_id='call_policy',
                        name='context.resolve',
                        arguments={
                            'ref': reference.ref,
                            'selector': 'matching_facts_and_guidance',
                            'max_tokens': 300,
                        },
                    )
                ],
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
            ModelResponse(
                structured_output=_answer_output(),
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
        ]
    )

    proposal = GatewayAgent(gateway).propose_turn(context)

    assert [item[0] for item in calls] == ['policy', 'knowledge']
    assert proposal.runtime_trace is not None
    assert proposal.runtime_trace.resolved_ref_count == 1
    assert proposal.runtime_trace.tool_calls == 1


@pytest.mark.parametrize(
    ('outcome', 'published', 'expected_status'),
    [
        ('evidence_found', True, 'evidence_found'),
        ('empty', True, 'no_evidence'),
        ('unavailable', True, 'unavailable'),
        ('evidence_found', False, 'unavailable'),
    ],
)
def test_v7_knowledge_lookup_uses_only_the_release_selected_source(
    outcome: str,
    published: bool,
    expected_status: str,
) -> None:
    context = _context('Does my policy cover this collision?')
    snapshot = context.runtime_configuration_snapshot
    assert snapshot is not None
    if published:
        context = replace(
            context,
            runtime_configuration_snapshot=replace(
                snapshot,
                knowledge=MappingProxyType({'motor': _knowledge_source()}),
            ),
        )
    reference = 'ctxref:ses_v7:policy.current'
    gateway = _RecordingGateway(
        [
            ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        call_id='call_release_knowledge',
                        name='context.resolve',
                        arguments={
                            'ref': reference,
                            'selector': 'matching_facts_and_guidance',
                            'max_tokens': 300,
                        },
                    )
                ],
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
            ModelResponse(
                structured_output=_answer_output(),
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
        ]
    )
    retriever = _KnowledgeRetriever(outcome)

    proposal = KnowledgeGroundedAgent(GatewayAgent(gateway), retriever).propose_turn(context)

    tool_message = gateway.requests[1].messages[-1]
    assert tool_message.content is not None
    resolved = json.loads(tool_message.content)
    assert resolved['content']['approved_guidance']['status'] == expected_status
    assert proposal.runtime_trace is not None
    assert len(retriever.requests) == (1 if published else 0)


def test_evidence_history_uses_claimant_scoped_lazy_source_and_narrow_proposal() -> None:
    calls: list[int] = []

    def load_history(limit: int) -> dict[str, object]:
        calls.append(limit)
        return {
            'status': 'succeeded',
            'items': [{'evidence_id': 'ev_old', 'claim_id': 'clm_old'}],
            'source_refs': ['ev_old'],
            'limitations': [],
        }

    context = replace(
        _context('Show me a previous uploaded file.'),
        evidence_history_context_loader=load_history,
    )
    plan = plan_model_turn(context)
    assert plan is not None
    assert plan.request_profile.profile_id == 'claimant.evidence-history.v1'
    reference = next(
        item for item in plan.context_plan.references if item.ref.endswith(':evidence.history')
    )
    gateway = _RecordingGateway(
        [
            ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        call_id='call_evidence_history',
                        name='context.resolve',
                        arguments={
                            'ref': reference.ref,
                            'selector': 'history',
                            'max_tokens': 240,
                        },
                    )
                ],
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
            ModelResponse(
                structured_output={
                    **_answer_output(),
                    'action': 'reuse',
                    'evidence_id': 'ev_old',
                    'source_claim_id': 'clm_old',
                    'removal_scope': None,
                },
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
        ]
    )

    proposal = GatewayAgent(gateway).propose_turn(context)

    assert calls == [reference.max_resolve_tokens]
    assert proposal.action_code == 'claim.propose_evidence_reuse'
    assert proposal.evidence_id == 'ev_old'
    assert proposal.source_claim_id == 'clm_old'


def test_cross_claim_review_uses_only_customer_scoped_isolated_source() -> None:
    calls: list[int] = []

    def load_claim_history(limit: int) -> dict[str, object]:
        calls.append(limit)
        return {
            'status': 'evidence_found',
            'claims': [{'claim_id': 'clm_old', 'revision': 3}],
            'source_refs': ['claim:clm_old:revision:3'],
            'limitations': [],
        }

    context = replace(
        _context('Compare this with all previous claims.'),
        claim_history_context_loader=load_claim_history,
    )
    plan = plan_model_turn(context)
    assert plan is not None
    assert plan.request_profile.profile_id == 'claimant.deep-review.v1'
    reference = next(
        item for item in plan.context_plan.references if item.resource_type == 'claim_history'
    )
    gateway = _RecordingGateway(
        [
            ModelResponse(
                structured_output={
                    'summary': 'One earlier motor Claim is available for bounded comparison.',
                    'source_refs': [reference.ref],
                    'truncated': False,
                    'limitations': [],
                },
                completion_status=ModelCompletionStatus.COMPLETE,
            )
        ]
    )

    proposal = GatewayAgent(gateway).propose_turn(context)

    assert calls == [reference.max_resolve_tokens]
    assert proposal.form_changes == []
    assert proposal.external_service_intents == []
    assert proposal.runtime_trace is not None
    assert proposal.runtime_trace.request_profile_id == 'claimant.deep-review.v1'


def test_pdf_uses_isolated_long_document_profile() -> None:
    context = _context(
        'Review this policy document.',
        evidence=(AgentEvidenceReference(evidence_id='ev_pdf', media_type='application/pdf'),),
    )

    plan = plan_model_turn(context)

    assert plan is not None
    assert plan.request_profile.profile_id == 'claimant.deep-review.v1'
    assert plan.context_plan.isolated_tasks == ['evidence.current']


def test_conflicting_rolling_summary_is_omitted_in_favour_of_claim_state() -> None:
    timestamp = datetime.now(UTC)
    claim = _claim().model_copy(
        update={
            'form': {
                'incident.location': StructuredFormField(
                    value='Symonds Street',
                    source=FormSource.CLAIMANT,
                    status=FormStatus.CONFIRMED,
                    needed_for=NeededFor.CURRENT_ACTION,
                    updated_at=timestamp,
                    updated_by=ActorReference(
                        actor_id='cus_v7',
                        actor_type=ActorType.CLAIMANT,
                    ),
                )
            }
        }
    )
    summary = VerifiedConversationSummary(
        summary_id='sum_conflict',
        claim_id=claim.claim_id,
        session_id='ses_v7',
        source_message_ids=['msg_old'],
        covered_message_range='msg_old..msg_old',
        generator_profile_and_version='qwen-local@v7',
        claim_revision_at_generation=claim.revision,
        summary=json.dumps({'confirmed_claim_facts': {'incident.location': 'Queen Street'}}),
        verified_against_claim_revision=claim.revision,
        created_at=timestamp.isoformat(),
    )
    context = replace(_context('Continue my motor claim.'), claim=claim, rolling_summary=summary)

    plan = plan_model_turn(context)

    assert plan is not None
    assert plan.context_plan.summary_state_mismatch is True
    assert 'conversation.summary' not in plan.context_payload


def test_summary_fact_removed_from_claim_state_is_not_reintroduced() -> None:
    timestamp = datetime.now(UTC)
    claim = _claim()
    summary = VerifiedConversationSummary(
        summary_id='sum_removed_fact',
        claim_id=claim.claim_id,
        session_id='ses_v7',
        source_message_ids=['msg_old'],
        covered_message_range='msg_old..msg_old',
        generator_profile_and_version='deterministic-verified-compactor@v1',
        claim_revision_at_generation=claim.revision,
        summary=json.dumps(
            {'confirmed_claim_facts': {'incident.location': 'An obsolete location'}}
        ),
        verified_against_claim_revision=claim.revision,
        created_at=timestamp.isoformat(),
    )

    plan = plan_model_turn(
        replace(_context('Continue my motor claim.'), claim=claim, rolling_summary=summary)
    )

    assert plan is not None
    assert plan.context_plan.summary_state_mismatch is True
    assert 'conversation.summary' not in plan.context_payload


def test_verified_summary_and_knowledge_stay_separate_bounded_context_resources() -> None:
    timestamp = datetime.now(UTC)
    summary = VerifiedConversationSummary(
        summary_id='sum_current',
        claim_id='clm_v7',
        session_id='ses_v7',
        source_message_ids=['msg_old'],
        covered_message_range='msg_old..msg_old',
        generator_profile_and_version='deterministic-verified-compactor@v1',
        claim_revision_at_generation=1,
        summary=json.dumps({'confirmed_claim_facts': {}}),
        verified_against_claim_revision=1,
        created_at=timestamp.isoformat(),
    )
    context = replace(
        _context('Does my policy cover this collision?'),
        rolling_summary=summary,
        knowledge_results=(_knowledge_chunk(),),
    )

    plan = plan_model_turn(context)

    assert plan is not None
    assert plan.context_payload['conversation.summary']['summary_id'] == 'sum_current'
    knowledge_reference = next(
        item for item in plan.context_plan.references if item.resource_type == 'knowledge_chunk'
    )
    assert knowledge_reference.available_selectors == ['matching_chunks']
    assert 'knowledge.results' not in plan.context_payload


def test_context_planner_refuses_to_truncate_authority_context() -> None:
    context = _context('A' * 3000)
    route = route_turn(context)
    with pytest.raises(ContextBudgetExceeded, match='message.latest'):
        plan_context(context, route, budget_limit=200, reserved_tokens=100)


def test_context_planner_omits_oversized_optional_history_but_keeps_authority() -> None:
    messages = tuple(
        item.model_copy(update={'content': {'type': 'text', 'text': 'history ' * 1000}})
        for item in _messages(4)
    )
    context = _context('Continue my motor claim.', conversation_messages=messages)

    plan = plan_context(
        context,
        route_turn(context),
        budget_limit=1400,
        reserved_tokens=200,
    )

    assert 'claim.current' in plan.inline_context
    assert 'message.latest' in plan.inline_context
    assert 'conversation.recent' not in plan.inline_context
    assert plan.omitted_sections == ['conversation.recent']
    assert plan.estimated_tokens == estimate_json_tokens(plan.inline_context)


def test_context_reference_resolver_enforces_manifest_selector_and_limit() -> None:
    reference = ContextReference(
        ref='ctxref:ses_v7:conversation.older',
        resource_type='message_range',
        version='claim-revision-1',
        summary='Older messages are available.',
        available_selectors=['page'],
        max_resolve_tokens=10,
    )
    resolver = TurnContextResolver(
        [reference],
        {(reference.ref, 'page'): 'one two three four five six seven eight nine ten eleven'},
    )
    result = resolver.resolve(reference.ref, 'page', 8)
    assert result.truncated is True
    assert result.actual_tokens <= 8
    with pytest.raises(ValueError, match='not permitted'):
        resolver.resolve(reference.ref, 'all', 8)
    with pytest.raises(ValueError, match='not permitted'):
        resolver.resolve('ctxref:ses_v7:unknown', 'page', 8)

    structured = TurnContextResolver(
        [reference],
        {(reference.ref, 'page'): {'messages': ['large value ' * 100]}},
    )
    with pytest.raises(ValueError, match='exceeds'):
        structured.resolve(reference.ref, 'page', 8)

    stale = TurnContextResolver(
        [reference],
        {(reference.ref, 'page'): 'bounded history'},
        expected_version='claim-revision-2',
    )
    with pytest.raises(ValueError, match='stale'):
        stale.resolve(reference.ref, 'page', 8)


def test_provider_gateway_capabilities_remain_separate_from_v7_profiles() -> None:
    assert ModelCapabilities(structured_output=True, tools=True).tools is True
    assert request_profile('claimant.intake.v1').tool_names == []


@pytest.mark.parametrize(
    ('message', 'expected_task'),
    [
        ('My car was rear-ended this morning.', TurnTask.INTAKE),
        ('Actually, change the location to Queen Street.', TurnTask.CORRECTION),
        ('Yes, that is right.', TurnTask.CONFIRMATION),
    ],
)
def test_v7_ordinary_turn_makes_exactly_one_tool_free_bounded_call(
    message: str,
    expected_task: TurnTask,
) -> None:
    gateway = _RecordingGateway(
        [
            ModelResponse(
                structured_output=_intake_output(),
                completion_status=ModelCompletionStatus.COMPLETE,
            )
        ]
    )

    proposal = GatewayAgent(gateway).propose_turn(_context(message))

    assert len(gateway.requests) == 1
    assert gateway.requests[0].tools == []
    assert gateway.requests[0].max_output_tokens == 180
    assert proposal.runtime_trace is not None
    assert proposal.runtime_trace.request_profile_id == 'claimant.intake.v1'
    assert proposal.runtime_trace.route == f'motor:{expected_task.value}'
    assert len(proposal.runtime_trace.invocations) == 1
    assert all(
        item.get('authority_scope') == 'claim:clm_v7:revision:1'
        for item in proposal.runtime_trace.context_load_decisions
    )


@pytest.mark.parametrize(
    ('ready', 'expected_action', 'expected_status'),
    [
        (True, 'claim.prepare_creation', 'ready_to_create'),
        (False, 'conversation.answer', 'more_information_required'),
    ],
)
def test_v7_claim_creation_route_keeps_readiness_under_runtime_control(
    ready: bool,
    expected_action: str,
    expected_status: str,
) -> None:
    branch_evaluation = BranchEvaluationResult(
        claim_id='clm_v7',
        evaluated_against_claim_revision=1,
        field_registry_version='test-fields-v1',
        branch_rules_version='test-branches-v1',
        selected_family='motor',
        requirements=RequirementResolution(ready=True),
        recomputation_reason='test',
    )
    gateway = _RecordingGateway(
        [
            ModelResponse(
                structured_output={**_answer_output(), 'ready': ready},
                completion_status=ModelCompletionStatus.COMPLETE,
            )
        ]
    )
    context = replace(_context('Proceed with this report.'), branch_evaluation=branch_evaluation)

    proposal = GatewayAgent(gateway).propose_turn(context)

    assert proposal.action_code == expected_action
    assert proposal.customer_next_step.status == expected_status
    assert proposal.state_changes == []


def test_intake_field_contract_uses_the_runtime_policy_registry() -> None:
    context = _context('My car was rear-ended this morning.')
    assert context.runtime_policy is not None
    branch_evaluation = context.runtime_policy.branch_evaluator().evaluate(
        context.claim,
        latest_message=context.message_text,
        recomputation_reason='test',
    )
    context = replace(context, branch_evaluation=branch_evaluation)

    plan = plan_model_turn(context)

    assert plan is not None
    assert plan.route.task is TurnTask.INTAKE
    assert plan.field_contract is not None
    assert plan.field_contract.registry_version == branch_evaluation.field_registry_version
    assert plan.field_contract.branch_rules_version == branch_evaluation.branch_rules_version


def test_intake_field_contract_rejects_a_mismatched_branch_registry() -> None:
    branch_evaluation = BranchEvaluationResult(
        claim_id='clm_v7',
        evaluated_against_claim_revision=1,
        field_registry_version='5',
        branch_rules_version='unrelated-branch-rules-v7',
        selected_family='motor',
        requirements=RequirementResolution(ready=False),
        recomputation_reason='test',
    )
    context = replace(
        _context('My car was rear-ended this morning.'),
        branch_evaluation=branch_evaluation,
    )

    with pytest.raises(ValueError, match='branch-rule versions do not match'):
        plan_model_turn(context)


@pytest.mark.parametrize(
    ('case', 'expected_code'),
    [
        ('unsupported_tool', ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY),
        ('invalid_resolver_limit', ModelGatewayErrorCode.MALFORMED_RESPONSE),
        ('incomplete', ModelGatewayErrorCode.INCOMPLETE_RESPONSE),
        ('refused', ModelGatewayErrorCode.REFUSED_RESPONSE),
        ('unknown_completion', ModelGatewayErrorCode.MALFORMED_RESPONSE),
        ('missing_output', ModelGatewayErrorCode.MALFORMED_RESPONSE),
        ('invalid_output', ModelGatewayErrorCode.MALFORMED_RESPONSE),
    ],
)
def test_v7_provider_failures_do_not_escape_the_published_turn_contract(
    case: str,
    expected_code: ModelGatewayErrorCode,
) -> None:
    context = _context('My car was rear-ended this morning.')
    response = ModelResponse(
        structured_output=_intake_output(),
        completion_status=ModelCompletionStatus.COMPLETE,
    )
    if case == 'unsupported_tool':
        response = ModelResponse(
            tool_calls=[ModelToolCall(call_id='call_wrong', name='claim.read', arguments={})],
            completion_status=ModelCompletionStatus.COMPLETE,
        )
    elif case == 'invalid_resolver_limit':
        context = _context(
            'What is the status of my claim?',
            conversation_messages=_messages(6),
        )
        response = ModelResponse(
            tool_calls=[
                ModelToolCall(
                    call_id='call_invalid_limit',
                    name='context.resolve',
                    arguments={
                        'ref': 'ctxref:ses_v7:conversation.older',
                        'selector': 'page',
                        'max_tokens': True,
                    },
                )
            ],
            completion_status=ModelCompletionStatus.COMPLETE,
        )
    elif case in {'incomplete', 'refused', 'unknown_completion'}:
        status = {
            'incomplete': ModelCompletionStatus.INCOMPLETE,
            'refused': ModelCompletionStatus.REFUSED,
            'unknown_completion': ModelCompletionStatus.UNKNOWN,
        }[case]
        response = response.model_copy(update={'completion_status': status})
    elif case == 'missing_output':
        response = ModelResponse(completion_status=ModelCompletionStatus.COMPLETE)
    elif case == 'invalid_output':
        response = ModelResponse(
            structured_output={'reply': ''},
            completion_status=ModelCompletionStatus.COMPLETE,
        )

    with pytest.raises(ModelGatewayError) as error:
        GatewayAgent(_RecordingGateway([response])).propose_turn(context)

    assert error.value.code is expected_code


def test_v7_rejects_an_unregistered_optional_offer_without_rejecting_safe_prose() -> None:
    context = replace(
        _context('Please arrange a damage assessment.'),
        external_services=capability_context('motor'),
    )
    response = ModelResponse(
        structured_output={**_answer_output(), 'service_offer_ids': ['not_registered']},
        completion_status=ModelCompletionStatus.COMPLETE,
    )

    proposal = GatewayAgent(_RecordingGateway([response])).propose_turn(context)

    assert proposal.customer_response == _answer_output()['reply']
    assert proposal.external_service_intents == []
    assert proposal.customer_next_step.status == 'continue_current_report'


def test_v7_replaces_executional_prose_before_consent_with_runtime_owned_copy() -> None:
    service_identity = 'vehicle_damage_assessment_routing'
    context = replace(
        _context('Please arrange a damage assessment.'),
        external_services=capability_context('motor'),
        selected_external_service_ids=(service_identity,),
    )
    response = ModelResponse(
        structured_output={
            **_answer_output(),
            'reply': 'I have arranged a damage assessment for you.',
        },
        completion_status=ModelCompletionStatus.COMPLETE,
    )

    proposal = GatewayAgent(_RecordingGateway([response])).propose_turn(context)

    assert proposal.customer_response == (
        'I found a registered support option. Review what would be shared and give your '
        'consent before Northwind sends anything.'
    )
    assert proposal.external_service_intents == [
        {'service_identity': service_identity, 'requested_action': 'submit_request'}
    ]


def test_v7_human_handoff_interrupts_before_any_provider_invocation() -> None:
    gateway = _RecordingGateway([])

    proposal = InvariantGuardedAgent(GatewayAgent(gateway)).propose_turn(
        _context('I want to speak to a person.')
    )

    assert proposal.action is AgentAction.HANDOFF
    assert proposal.reason_codes == ['HUMAN_SUPPORT_REQUESTED']
    assert gateway.requests == []


def test_v7_timeout_stops_after_one_request_and_returns_no_proposal() -> None:
    gateway = _FailingRecordingGateway(
        ModelGatewayError(ModelGatewayErrorCode.TIMEOUT, retryable=True)
    )

    with pytest.raises(ModelGatewayError) as error:
        GatewayAgent(gateway).propose_turn(_context('My car was rear-ended this morning.'))

    assert error.value.code is ModelGatewayErrorCode.TIMEOUT
    assert len(gateway.requests) == 1


def test_v7_field_contract_uses_one_bounded_repair_without_tools() -> None:
    invalid = {
        **_intake_output(),
        'field_changes': [
            {
                'field_code': 'incident.injury_or_danger',
                'value': 'maybe',
                'reported_text': 'I am not injured.',
            }
        ],
    }
    corrected = {
        **invalid,
        'reply': 'An attempted rewrite that Runtime must ignore.',
        'field_changes': [
            {
                'field_code': 'incident.injury_or_danger',
                'value': False,
                'reported_text': 'I am not injured.',
            }
        ],
    }
    gateway = _RecordingGateway(
        [
            ModelResponse(
                structured_output=invalid,
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
            ModelResponse(
                structured_output=corrected,
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
        ]
    )

    proposal = GatewayAgent(gateway).propose_turn(
        _context('My car was rear-ended and I am not injured.')
    )

    assert len(gateway.requests) == 2
    assert gateway.requests[1].tools == []
    assert proposal.form_changes[0].value is False
    assert proposal.customer_response == invalid['reply']
    assert proposal.runtime_trace is not None
    assert proposal.runtime_trace.repair_attempted is True
    assert proposal.runtime_trace.repair_outcome == 'corrected'


def test_v7_field_contract_fails_after_one_unsuccessful_repair() -> None:
    invalid = {
        **_intake_output(),
        'field_changes': [{'field_code': 'incident.injury_or_danger', 'value': 'maybe'}],
    }
    gateway = _RecordingGateway(
        [
            ModelResponse(
                structured_output=invalid,
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
            ModelResponse(
                structured_output=invalid,
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
        ]
    )

    with pytest.raises(ModelGatewayError) as error:
        GatewayAgent(gateway).propose_turn(_context('My car was rear-ended.'))

    assert error.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE
    assert len(gateway.requests) == 2


def test_v7_lookup_allows_one_bounded_resolve_and_one_continuation() -> None:
    reference = 'ctxref:ses_v7:conversation.older'
    gateway = _RecordingGateway(
        [
            ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        call_id='call_v7',
                        name='context.resolve',
                        arguments={'ref': reference, 'selector': 'page', 'max_tokens': 120},
                    )
                ],
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
            ModelResponse(
                structured_output=_answer_output(),
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
        ]
    )

    proposal = GatewayAgent(gateway).propose_turn(
        _context('What is the status of my claim?', conversation_messages=_messages(6))
    )

    assert len(gateway.requests) == 2
    assert [tool.name for tool in gateway.requests[0].tools] == ['context.resolve']
    assert gateway.requests[1].tools == []
    continuation_payload = json.loads(gateway.requests[1].messages[-1].content or '{}')
    assert 'content' in continuation_payload
    assert proposal.runtime_trace is not None
    assert len(proposal.runtime_trace.invocations) == 2
    assert set(proposal.runtime_trace.tool_output) == {
        'ref',
        'selector',
        'next_cursor',
        'truncated',
        'actual_tokens',
    }
    assert proposal.runtime_trace.tool_output['ref'] == reference
    assert proposal.runtime_trace.tool_output['selector'] == 'page'
    assert proposal.runtime_trace.tool_output['actual_tokens'] > 0
    assert 'content' not in proposal.runtime_trace.tool_output
    assert proposal.runtime_trace.request_budget['turn_cumulative_tokens'] <= 3000


def test_v7_lookup_rejects_a_missing_required_context_continuation() -> None:
    response = ModelResponse(
        structured_output=_answer_output(),
        completion_status=ModelCompletionStatus.COMPLETE,
    )
    gateway = _RecordingGateway([response])

    with pytest.raises(ModelGatewayError) as error:
        GatewayAgent(gateway).propose_turn(
            _context('What is the status of my claim?', conversation_messages=_messages(6))
        )

    assert error.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY
    assert len(gateway.requests) == 1


def test_v7_lookup_rejects_a_recursive_tool_call() -> None:
    reference = 'ctxref:ses_v7:conversation.older'
    tool_call = ModelToolCall(
        call_id='call_v7',
        name='context.resolve',
        arguments={'ref': reference, 'selector': 'page', 'max_tokens': 120},
    )
    gateway = _RecordingGateway(
        [
            ModelResponse(
                tool_calls=[tool_call],
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
            ModelResponse(
                tool_calls=[tool_call.model_copy(update={'call_id': 'call_again'})],
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
        ]
    )

    with pytest.raises(ModelGatewayError) as error:
        GatewayAgent(gateway).propose_turn(
            _context('What is the status of my claim?', conversation_messages=_messages(6))
        )
    assert error.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY


def test_v7_multi_evidence_review_uses_one_isolated_read_only_request() -> None:
    evidence = tuple(
        AgentEvidenceReference(evidence_id=f'ev_{index}', media_type='image/jpeg')
        for index in range(5)
    )
    reference = 'ctxref:ses_v7:evidence.current'
    gateway = _RecordingGateway(
        [
            ModelResponse(
                structured_output={
                    'summary': 'The bounded images show visible vehicle damage.',
                    'source_refs': [reference],
                    'truncated': False,
                    'limitations': ['No repair cost was inferred.'],
                },
                completion_status=ModelCompletionStatus.COMPLETE,
            )
        ]
    )

    proposal = GatewayAgent(gateway).propose_turn(
        _context('Compare these damage photos.', evidence=evidence)
    )

    assert len(gateway.requests) == 1
    assert gateway.requests[0].tools == []
    assert gateway.requests[0].max_output_tokens == 1200
    assert proposal.form_changes == []
    assert proposal.external_service_intents == []
    assert proposal.runtime_trace is not None
    assert proposal.runtime_trace.request_profile_id == 'claimant.deep-review.v1'


def test_v7_pdf_review_is_labelled_long_document() -> None:
    reference = 'ctxref:ses_v7:evidence.current'
    gateway = _RecordingGateway(
        [
            ModelResponse(
                structured_output={
                    'summary': 'The bounded PDF contains a repair estimate.',
                    'source_refs': [reference],
                    'truncated': False,
                    'limitations': [],
                },
                completion_status=ModelCompletionStatus.COMPLETE,
            )
        ]
    )

    GatewayAgent(gateway).propose_turn(
        _context(
            'Review this document.',
            evidence=(
                AgentEvidenceReference(
                    evidence_id='ev_pdf',
                    media_type='application/pdf',
                ),
            ),
        )
    )

    user_message = gateway.requests[0].messages[1]
    text_block = user_message.content_blocks[0]
    assert isinstance(text_block, ModelTextContent)
    payload = json.loads(text_block.text)
    assert payload['task']['task_type'] == 'long_document'
    assert [item['ref'] for item in payload['task']['input_refs']] == [reference]


def test_v7_cross_claim_review_does_not_send_unrelated_current_evidence() -> None:
    reference = 'ctxref:ses_v7:claim-history.customer'

    def load_claim_history(_limit: int) -> dict[str, object]:
        return {
            'status': 'evidence_found',
            'claims': [{'claim_id': 'clm_old', 'revision': 3}],
            'source_refs': ['claim:clm_old:revision:3'],
            'limitations': [],
        }

    model_record = _model_record(image_input=False, document_input=False)
    snapshot = RuntimeConfigurationSnapshot(
        environment='test',
        runtime_profile='fixture',
        release_set_id='rel_v7',
        configurations=MappingProxyType({'model:qwen-local': model_record}),
        integrations=MappingProxyType({}),
        knowledge=MappingProxyType({}),
    )
    context = replace(
        _context(
            'Compare this with all previous claims.',
            evidence=(AgentEvidenceReference(evidence_id='ev_new', media_type='image/jpeg'),),
        ),
        claim_history_context_loader=load_claim_history,
        runtime_configuration_snapshot=snapshot,
        runtime_policy=_runtime_policy(snapshot),
    )
    gateway = _RecordingGateway(
        [
            ModelResponse(
                structured_output={
                    'summary': 'One earlier Claim is available.',
                    'source_refs': [reference],
                    'truncated': False,
                    'limitations': [],
                },
                completion_status=ModelCompletionStatus.COMPLETE,
            )
        ]
    )

    GatewayAgent(gateway).propose_turn(context)

    request = gateway.requests[0]
    text_block = request.messages[1].content_blocks[0]
    assert isinstance(text_block, ModelTextContent)
    payload = json.loads(text_block.text)
    assert payload['task']['task_type'] == 'cross_claim'
    assert [item['ref'] for item in payload['task']['input_refs']] == [reference]
    assert not any(
        isinstance(item, ModelEvidenceContent) for item in request.messages[1].content_blocks
    )
    assert request.required_capabilities.image_input is False


def test_v7_isolated_review_rejects_an_unscoped_source_reference() -> None:
    evidence = tuple(
        AgentEvidenceReference(evidence_id=f'ev_{index}', media_type='image/jpeg')
        for index in range(5)
    )
    gateway = _RecordingGateway(
        [
            ModelResponse(
                structured_output={
                    'summary': 'Unscoped result.',
                    'source_refs': ['ctxref:another-claim:all'],
                    'truncated': False,
                    'limitations': [],
                },
                completion_status=ModelCompletionStatus.COMPLETE,
            )
        ]
    )

    with pytest.raises(ModelGatewayError) as error:
        GatewayAgent(gateway).propose_turn(
            _context('Compare these damage photos.', evidence=evidence)
        )
    assert error.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE


@pytest.mark.parametrize(
    ('response', 'expected_code'),
    [
        (
            ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        call_id='isolated_tool',
                        name='context.resolve',
                        arguments={},
                    )
                ],
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
            ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY,
        ),
        (
            ModelResponse(completion_status=ModelCompletionStatus.INCOMPLETE),
            ModelGatewayErrorCode.INCOMPLETE_RESPONSE,
        ),
        (
            ModelResponse(
                structured_output={'summary': 'Missing required source references.'},
                completion_status=ModelCompletionStatus.COMPLETE,
            ),
            ModelGatewayErrorCode.MALFORMED_RESPONSE,
        ),
    ],
)
def test_v7_isolated_review_rejects_tools_incomplete_and_unsourced_results(
    response: ModelResponse,
    expected_code: ModelGatewayErrorCode,
) -> None:
    evidence = tuple(
        AgentEvidenceReference(evidence_id=f'ev_{index}', media_type='image/jpeg')
        for index in range(5)
    )

    with pytest.raises(ModelGatewayError) as error:
        GatewayAgent(_RecordingGateway([response])).propose_turn(
            _context('Compare these damage photos.', evidence=evidence)
        )

    assert error.value.code is expected_code


def test_v7_authority_budget_overflow_returns_model_free_safe_clarification() -> None:
    gateway = _RecordingGateway([])

    proposal = GatewayAgent(gateway).propose_turn(_context('A' * 20_000))

    assert gateway.requests == []
    assert proposal.reason_codes == ['CONTEXT_BUDGET_EXCEEDED']
    assert proposal.proposal_source.value == 'controlled_agent'
    assert proposal.action_code is None
    assert proposal.runtime_trace is None
