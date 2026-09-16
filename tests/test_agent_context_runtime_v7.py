import json
from dataclasses import replace
from datetime import UTC, datetime
from types import MappingProxyType

import pytest

from backend.domain.agent_action_registry import registered_actions
from backend.domain.agent_context_runtime import (
    ContextBudgetPolicy,
    ContextReference,
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
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelRequest,
    ModelResponse,
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
from backend.services.agent import AgentEvidenceReference, AgentTurnContext
from backend.services.context_planner import ContextBudgetExceeded, plan_context
from backend.services.context_resolver import TurnContextResolver
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


def _model_record() -> ConfigurationRecord:
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
            'image_input': True,
            'document_input': True,
        },
        author='test',
        reason='Test v7 model binding.',
        updated_at=datetime.now(UTC),
    )


def _runtime_policy(snapshot: RuntimeConfigurationSnapshot) -> RuntimeAgentPolicySnapshot:
    manifest = load_prompt_manifest()
    contents = load_fragment_contents(manifest)
    model_configuration = ModelRuntimeConfiguration.model_validate(_model_record().values)
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


class _EvidenceResolver:
    def resolve(self, evidence_id: str, media_type: str) -> bytes | None:
        return f'{evidence_id}:{media_type}'.encode()


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
    assert (
        refs.index('core.authority')
        < refs.index('family.motor')
        < refs.index('task.external-support')
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

    assert proposal.customer_next_step.status == 'external_service_consent_required'
    assert proposal.external_service_intents == [
        {'service_identity': service_identity, 'requested_action': 'submit_request'}
    ]
    assert proposal.state_changes == []


def test_request_profiles_fail_closed_against_provider_capabilities() -> None:
    configuration = ModelRuntimeConfiguration.model_validate(_model_record().values)
    capability = provider_capability(configuration)
    validate_profile_compatibility(request_profile('claimant.lookup.v1'), capability)

    no_tools = capability.model_copy(
        update={'tool_call_support': False, 'tool_result_continuation': None}
    )
    with pytest.raises(ValueError, match='tool manifest'):
        validate_profile_compatibility(request_profile('claimant.lookup.v1'), no_tools)


def test_ordinary_model_plan_is_single_call_tool_free_and_budgeted() -> None:
    plan = plan_model_turn(_context('My car was rear-ended this morning.'))
    assert plan is not None
    assert plan.request_profile.profile_id == 'claimant.intake.v1'
    assert plan.request_profile.max_model_invocations == 1
    assert plan.request_profile.tool_names == []
    assert plan.request_budget.raw_input_tokens <= 3000
    assert plan.request_budget.reserved_output_tokens == 180
    assert plan.context_payload['message.latest'] == 'My car was rear-ended this morning.'
    assert plan.cache_plan.segments[0].checkpoint is True
    assert plan.cache_plan.layout_version == 'test-cache-v7'
    assert len(plan.cache_plan.prefix_fingerprint) == 64
    assert plan.cache_plan.tool_manifest_id.endswith(':none')


def test_current_status_uses_one_tool_free_answer_profile_without_older_history() -> None:
    plan = plan_model_turn(_context('What is the status of my claim?'))

    assert plan is not None
    assert plan.request_profile.profile_id == 'claimant.answer.v1'
    assert plan.request_profile.tool_names == []
    assert plan.request_profile.max_model_invocations == 1


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


def test_context_planner_refuses_to_truncate_authority_context() -> None:
    context = _context('A' * 3000)
    route = route_turn(context)
    with pytest.raises(ContextBudgetExceeded, match='message.latest'):
        plan_context(context, route, budget_limit=200, reserved_tokens=100)


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


def test_v7_ordinary_turn_makes_exactly_one_tool_free_bounded_call() -> None:
    gateway = _RecordingGateway(
        [
            ModelResponse(
                structured_output=_intake_output(),
                completion_status=ModelCompletionStatus.COMPLETE,
            )
        ]
    )

    proposal = GatewayAgent(gateway).propose_turn(_context('My car was rear-ended this morning.'))

    assert len(gateway.requests) == 1
    assert gateway.requests[0].tools == []
    assert gateway.requests[0].max_output_tokens == 180
    assert proposal.runtime_trace is not None
    assert proposal.runtime_trace.request_profile_id == 'claimant.intake.v1'
    assert len(proposal.runtime_trace.invocations) == 1


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
    assert proposal.runtime_trace is not None
    assert len(proposal.runtime_trace.invocations) == 2
    assert proposal.runtime_trace.request_budget['turn_cumulative_tokens'] <= 3000


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


def test_v7_authority_budget_overflow_returns_model_free_safe_clarification() -> None:
    gateway = _RecordingGateway([])

    proposal = GatewayAgent(gateway).propose_turn(_context('A' * 20_000))

    assert gateway.requests == []
    assert proposal.reason_codes == ['CONTEXT_BUDGET_EXCEEDED']
    assert proposal.proposal_source.value == 'controlled_agent'
    assert proposal.runtime_trace is None
