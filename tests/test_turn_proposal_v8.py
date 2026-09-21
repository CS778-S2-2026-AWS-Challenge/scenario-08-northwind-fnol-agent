"""Durable v8 contract tests: facts, optional proposals, and provider envelope."""

from dataclasses import replace
from types import MappingProxyType
from typing import Any, cast

import pytest

from backend.adapters.model_gateway import OpenAICompatibleModelGateway
from backend.domain.agent_runtime_configuration import AgentInstructionConfiguration
from backend.domain.agent_v8 import V8Escalation, V8TurnProposal
from backend.domain.external_service_registry import capability_context
from backend.domain.model_gateway import ModelCompletionStatus, ModelResponse
from backend.domain.models import FormSource, FormStatus
from backend.services.agent import AgentTurnContext
from backend.services.model_agent import GatewayAgent
from backend.services.model_request_planner import plan_model_turn
from backend.services.prompt_composer import load_fragment_contents, load_prompt_manifest
from backend.services.request_profile_registry import registered_request_profiles
from backend.services.turn_field_contract import compile_turn_field_contract
from backend.services.turn_proposal_validation import parse_turn_proposal, validate_turn_proposal
from backend.services.turn_router import route_turn
from tests.test_agent_context_runtime_v7 import _context, _RecordingGateway


def v8_context(message: str) -> AgentTurnContext:
    context = _context(message)
    snapshot = context.runtime_configuration_snapshot
    assert snapshot is not None
    assert context.runtime_policy is not None
    record = snapshot.model('qwen-local')
    assert record is not None
    record = record.model_copy(
        update={'values': {**record.values, 'prompt_version': 'northwind-fnol-claimant-v8'}}
    )
    snapshot = replace(snapshot, configurations=MappingProxyType({'model:qwen-local': record}))
    manifest = load_prompt_manifest('northwind-fnol-claimant-v8')
    contents = load_fragment_contents(manifest)
    policy = replace(
        context.runtime_policy,
        runtime_snapshot=snapshot,
        instruction=AgentInstructionConfiguration.model_validate(
            {
                **context.runtime_policy.instruction.model_dump(),
                'prompt_version': manifest.prompt_pack_version,
                'manifest_version': manifest.prompt_pack_version,
                'fragments': [
                    {**item.model_dump(), 'content': contents[item.fragment_id]}
                    for item in manifest.fragments
                ],
            }
        ),
        tool_policy=context.runtime_policy.tool_policy.model_copy(
            update={'request_profiles': list(registered_request_profiles())}
        ),
    )
    return replace(
        context,
        runtime_configuration_snapshot=snapshot,
        runtime_policy=policy,
        branch_evaluation=policy.branch_evaluator().evaluate(
            context.claim, latest_message=message, recomputation_reason='test_v8'
        ),
        external_services=capability_context('motor'),
    )


def test_v8_multi_intent_turn_uses_one_complete_envelope_and_preserves_facts() -> None:
    context = v8_context('My car cannot be driven. Please help with repairs.')
    # This contract test isolates the provider/reducer interface from the
    # separately recorded input-budget decision; it does not prove production
    # default budget acceptance.
    policy = context.runtime_policy
    assert policy is not None
    budget_policy = policy.controlled_rules.context_budget_policy
    assert budget_policy is not None
    context = replace(
        context,
        runtime_policy=replace(
            policy,
            tool_policy=policy.tool_policy.model_copy(
                update={
                    'request_profiles': [
                        profile.model_copy(update={'input_hard_limit': 5000})
                        for profile in policy.tool_policy.request_profiles
                    ]
                }
            ),
            controlled_rules=policy.controlled_rules.model_copy(
                update={
                    'context_budget_policy': budget_policy.model_copy(
                        update={'ordinary_input_hard_limit': 5000}
                    )
                }
            ),
        ),
    )
    plan = plan_model_turn(context)
    assert plan is not None
    assert plan.schema_id == 'claimant.turn.v1'
    assert {'intake', 'external'} <= route_turn(context).intents
    raw: dict[str, Any] = {
        'reply': 'I understand the car cannot be driven.',
        'reason_codes': ['FACT_RECORDED'],
        'field_changes': [
            {
                'field_code': 'vehicle.drivable',
                'value': False,
                'reported_text': 'cannot be driven',
                'precision': 'exact',
            }
        ],
        'contents_item_changes': [],
        'next_question': None,
        'service_suggestions': [
            {
                'service_identity': 'vehicle_recovery_request',
                'rationale': 'The car cannot be driven.',
            }
        ],
        'state_proposals': [],
        'escalation': None,
        'ready_to_create': False,
        'confirms_batch': False,
    }
    strict = cast(
        dict[str, Any], OpenAICompatibleModelGateway._strict_response_schema(plan.response_schema)
    )
    variants = strict['properties']['field_changes']['items']['anyOf']
    boolean_variant = next(
        item for item in variants if item['properties']['value'].get('type') == 'boolean'
    )
    assert set(boolean_variant['properties']) == {
        'field_code',
        'value',
        'reported_text',
        'precision',
    }
    assert set(boolean_variant['required']) == set(raw['field_changes'][0])
    V8TurnProposal.model_validate(raw)
    gateway = _RecordingGateway(
        [ModelResponse(completion_status=ModelCompletionStatus.COMPLETE, structured_output=raw)]
    )
    result = GatewayAgent(gateway).propose_turn(context)
    assert len(gateway.requests) == 1
    assert gateway.requests[0].prompt_version == 'northwind-fnol-claimant-v8'
    assert result.validated_turn is not None
    assert result.form_changes[0].value is False
    assert result.form_changes[0].source is FormSource.CLAIMANT
    assert result.external_service_intents[0]['service_identity'] == 'vehicle_recovery_request'


@pytest.mark.parametrize(
    'suppression', ['existing_handoff', 'safety_interrupt', 'model_escalation']
)
def test_v8_optional_invalid_parts_are_dropped_without_losing_core_facts(suppression: str) -> None:
    context = v8_context('It happened yesterday afternoon.')
    assert context.branch_evaluation is not None
    assert context.runtime_policy is not None
    proposal, rejected = parse_turn_proposal(
        {
            'reply': 'I have recorded that time.',
            'reason_codes': ['FACT_RECORDED'],
            'field_changes': [
                {
                    'field_code': 'incident.occurred_at',
                    'value': '2026-09-20T15:00:00+12:00',
                    'reported_text': 'yesterday afternoon',
                    'precision': 'approximate',
                }
            ],
            'state_proposals': [
                {'path': 'claim_state.severity', 'to': 'clear', 'reason': 'Not allowed.'}
            ],
            'service_suggestions': [
                {'service_identity': 'vehicle_recovery_request', 'rationale': 'Need help.'}
            ],
        }
    )
    if suppression == 'model_escalation':
        proposal = proposal.model_copy(
            update={
                'escalation': V8Escalation(kind='human_requested', reason='Please get a person.')
            }
        )
    validated = validate_turn_proposal(
        proposal,
        branch_evaluation=context.branch_evaluation,
        eligible_service_ids={'vehicle_recovery_request'},
        safety_interrupt=object() if suppression == 'safety_interrupt' else None,
        field_contract=compile_turn_field_contract(
            context.branch_evaluation, context.runtime_policy.branch_evaluator().registry
        ),
        open_handoffs=('handoff_active',) if suppression == 'existing_handoff' else (),
        message_text=context.message_text,
    )
    assert rejected[0]['part'] == 'state_proposals'
    assert validated.service_identities == ()
    assert validated.rejected[0]['reason'] == 'suppressed_during_handoff'
    assert validated.form_changes[0].source is FormSource.CLAIMANT
    assert validated.form_changes[0].status is FormStatus.CONFIRMED


@pytest.mark.parametrize('message', ['I also hit a wall.', 'Actually my phone was inside the car.'])
def test_authoritative_motor_family_survives_other_family_words(message: str) -> None:
    route = route_turn(v8_context(message))
    assert route.product_family == 'motor'
    assert route.family_resolution == 'authoritative'


def test_v8_reason_codes_and_contents_lengths_are_bounded() -> None:
    with pytest.raises(ValueError):
        V8TurnProposal(reply='Recorded.', reason_codes=['x' * 51])
