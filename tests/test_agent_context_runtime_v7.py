import json
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
    Channel,
    CustomerNextStep,
    FormSource,
    FormStatus,
    MessageRecord,
    MessageVisibility,
    NeededFor,
    ResponsibleParty,
    StructuredFormField,
    WorkingClaim,
)
from backend.domain.prompt_pack import (
    PromptApplicability,
    PromptFragmentDefinition,
    PromptPackManifest,
)
from backend.services.agent import AgentEvidenceReference, AgentTurnContext
from backend.services.context_budget import estimate_json_tokens
from backend.services.context_planner import ContextBudgetExceeded, plan_context
from backend.services.context_resolver import TurnContextResolver
from backend.services.isolated_context_executor import _validation_path
from backend.services.model_agent import GatewayAgent
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
from backend.services.request_profile_registry import (
    registered_request_profiles,
    request_profile,
)
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
            'prompt_version': 'northwind-fnol-claimant-v8',
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
            prompt_version='northwind-fnol-claimant-v8',
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
            request_profiles=list(registered_request_profiles('northwind-fnol-claimant-v8')),
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
    assert unresolved.model_required is True
    assert unresolved.deterministic_response is None


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
        (200, 301, None),
    ],
)
def test_request_budget_rejects_single_and_cumulative_overflow(
    raw_input_tokens: int,
    turn_cumulative_tokens: int,
    expected_error: str | None,
) -> None:
    def budget() -> ModelRequestBudget:
        return ModelRequestBudget(
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

    if expected_error is not None:
        with pytest.raises(ValueError, match=expected_error):
            budget()
    else:
        assert budget().turn_cumulative_tokens == 301


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


@pytest.mark.parametrize(
    ('message', 'task'),
    [
        ('The car was parked.', TurnTask.INTAKE),
        ('Actually it was blue.', TurnTask.CORRECTION),
        ('Compare these two addresses.', TurnTask.INTAKE),
    ],
)
def test_history_is_discoverable_without_claimant_keywords(message: str, task: TurnTask) -> None:
    calls: list[int] = []

    def load_history(limit: int) -> dict[str, object]:
        calls.append(limit)
        return {'status': 'empty', 'source_refs': []}

    context = replace(_context(message), claim_history_context_loader=load_history)
    plan = plan_model_turn(context)
    assert plan is not None
    assert plan.route.task is task
    assert plan.request_profile.profile_id == 'claimant.lookup.v1'
    assert any(item.resource_type == 'claim_history' for item in plan.context_plan.references)
    assert calls == []  # The model chooses whether to resolve the reference.

    anonymous = replace(
        context, claim=context.claim.model_copy(update={'customer_id': 'anonymous:session'})
    )
    anonymous_plan = plan_model_turn(anonymous)
    assert anonymous_plan is not None
    assert not any(
        item.resource_type == 'claim_history' for item in anonymous_plan.context_plan.references
    )


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


def test_context_planner_refuses_to_truncate_authority_context() -> None:
    context = _context('A' * 3000)
    route = route_turn(context)
    with pytest.raises(ContextBudgetExceeded, match=r'message.latest'):
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


def test_v7_timeout_stops_after_one_request_and_returns_no_proposal() -> None:
    gateway = _FailingRecordingGateway(
        ModelGatewayError(ModelGatewayErrorCode.TIMEOUT, retryable=True)
    )

    with pytest.raises(ModelGatewayError) as error:
        GatewayAgent(gateway).propose_turn(_context('My car was rear-ended this morning.'))

    assert error.value.code is ModelGatewayErrorCode.TIMEOUT
    assert len(gateway.requests) == 1


def test_evidence_action_rejects_a_missing_required_context_continuation() -> None:
    response = ModelResponse(
        structured_output=_answer_output(),
        completion_status=ModelCompletionStatus.COMPLETE,
    )
    gateway = _RecordingGateway([response])

    with pytest.raises(ModelGatewayError) as error:
        GatewayAgent(gateway).propose_turn(
            replace(
                _context('Show my previous uploads.'),
                evidence_history_context_loader=lambda _: {'status': 'empty'},
            )
        )

    assert error.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY
    assert len(gateway.requests) == 1
    assert gateway.requests[0].required_tool_name == 'context.resolve'


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
    assert error.value.diagnostic_code == 'source_reference_scope'
    assert error.value.diagnostic_path == 'source_refs'


@pytest.mark.parametrize(
    ('errors', 'expected'),
    [
        ([object()], None),
        ([{}], None),
        ([{'loc': ('items', 0)}], 'items.[0]'),
        ([{'loc': ('items', object())}], None),
        ([{'loc': ('field', 'x' * 120)}], None),
        ([{'loc': ('model_chosen_key',), 'type': 'extra_forbidden'}], None),
        ([{'loc': ('reply', 'model_chosen_key'), 'type': 'extra_forbidden'}], 'reply'),
    ],
)
def test_validation_path_is_bounded_for_untrusted_error_shapes(
    errors: list[object], expected: str | None
) -> None:
    assert _validation_path(errors) == expected


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
    if expected_code is ModelGatewayErrorCode.MALFORMED_RESPONSE:
        assert error.value.diagnostic_code == 'output_schema_validation'
