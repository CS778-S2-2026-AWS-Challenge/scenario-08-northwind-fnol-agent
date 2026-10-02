"""v8 operational output ceilings and their existing persist-first safety net."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.domain.agent_v8 import (
    V8ContentsItemChange,
    V8FieldChange,
    V8MoneyAmount,
    V8NextQuestion,
    V8TurnProposal,
)
from backend.domain.model_gateway import ModelCompletionStatus, ModelResponse
from backend.domain.models import MoneyAmount
from backend.repositories.fixture import FixtureRepository
from backend.services.context_budget import estimate_json_tokens
from backend.services.request_profile_registry import request_profile
from backend.services.turn_field_contract import compile_turn_field_contract
from backend.services.turn_proposal_validation import validate_turn_proposal
from tests.journey_v8_support import CLAIMANT, V8JourneyProvider, envelope, fact
from tests.test_claim_api import create_claim, submit_message
from tests.test_turn_proposal_v8 import v8_context


def test_dense_new_item_response_fits_the_operating_cap_without_reducing_fact_count() -> None:
    codes = [
        'incident.description',
        'incident.location',
        'incident.occurred_at',
        'loss.description',
        'vehicle.damage_description',
        'vehicle.registration',
        'policy.policy_number',
        'claimant.role',
    ]
    raw = envelope(fields=[fact(code, 'x' * 300, 'x' * 200) for code in codes])
    raw.update(
        reply='x' * 500,
        reason_codes=['x' * 50] * 5,
        contents_item_changes=[
            {
                'item_id': None,
                'description': 'x' * 300,
                'category': 'x' * 100,
                'quantity': 999,
                'brand': 'x' * 100,
                'model': 'x' * 100,
                'loss_type': 'damaged',
                'ownership': 'owned',
                'estimated_value': {'amount': 10000000, 'currency': 'NZD'},
                'reported_text': 'x' * 200,
            }
            for _ in range(6)
        ],
        next_question={
            'field_codes': ['vehicle.drivable'],
            'wording': 'x' * 250,
            'reason': 'natural_follow_up',
        },
        service_suggestions=[
            {'service_identity': identity, 'rationale': 'x' * 150}
            for identity in (
                'vehicle_damage_assessment_routing',
                'vehicle_recovery_request',
                'vehicle_repairer_booking',
            )
        ],
        state_proposals=[
            {'path': 'claim_state.customer_support', 'to': 'guided', 'reason': 'x' * 150},
            {'path': 'claim_state.urgency', 'to': 'urgent', 'reason': 'x' * 150},
        ],
        escalation={'kind': 'professional_review', 'reason': 'x' * 150},
        document_requests=[
            {'document_kind': 'x' * 100, 'stance': 'third_party', 'service_identity': 'x' * 100}
            for _ in range(2)
        ],
        northwind_questions=[
            {'question': 'x' * 200, 'claimant_wording': 'x' * 300, 'model_view': 'x' * 300}
            for _ in range(2)
        ],
        turn_ending='question',
        scope_note='x' * 150,
        evidence_interpretations=[
            {'evidence_id': 'x' * 100, 'document_kind': 'x' * 100} for _ in range(4)
        ],
        summary_fields=['x' * 100] * 30,
    )
    for change in raw['field_changes']:
        change['service_identity'] = 'x' * 100
    V8TurnProposal.model_validate(raw)
    assert len(raw['field_changes']) == 8
    assert len(raw['contents_item_changes']) == 6
    assert estimate_json_tokens(raw) <= request_profile('claimant.turn.v1').output_limit == 7500
    assert request_profile('claimant.lookup.v1').output_limit == 7500
    for change in raw['field_changes']:
        change['source_evidence_id'] = 'evd_' + 'f' * 20
    assert estimate_json_tokens(raw) <= request_profile('claimant.media.v1').output_limit == 8000


@pytest.mark.parametrize(
    ('code', 'value'),
    [
        ('incident.description', 'x' * 301),
        ('property.affected_areas', ['x' * 101]),
        ('property.affected_areas', ['wall'] * 51),
    ],
)
def test_provider_length_violation_is_dropped_while_valid_fact_is_preserved(
    code: str, value: Any
) -> None:
    context = v8_context('It happened in Wellington.')
    assert context.runtime_policy is not None
    claim = context.claim.model_copy(update={'incident_type': 'home'})
    evaluator = context.runtime_policy.branch_evaluator()
    evaluation = evaluator.evaluate(
        claim, latest_message=context.message_text, recomputation_reason='limits'
    )
    proposal = V8TurnProposal(
        reply='Recorded.',
        reason_codes=['FACT_RECORDED'],
        field_changes=[
            V8FieldChange(field_code=code, value=value),
            V8FieldChange(
                field_code='incident.location', value='Wellington', reported_text='Wellington'
            ),
        ],
    )
    result = validate_turn_proposal(
        proposal,
        branch_evaluation=evaluation,
        eligible_service_ids=(),
        safety_interrupt=None,
        field_contract=compile_turn_field_contract(evaluation, evaluator.registry),
        open_handoffs=(),
        message_text=context.message_text,
    )
    assert [change.field_code for change in result.form_changes] == ['incident.location']
    assert result.rejected[0]['reason'] == 'length_limit_exceeded'


@pytest.mark.parametrize('amount', [float('inf'), float('nan'), 10000001])
def test_v8_money_is_bounded_without_changing_shared_money(amount: float) -> None:
    with pytest.raises(ValueError):
        V8MoneyAmount(amount=amount, currency='NZD')
    assert MoneyAmount(amount=10000001, currency='NZD').amount == 10000001


def test_quantity_and_question_identifier_bounds_are_enforced() -> None:
    with pytest.raises(ValueError):
        V8ContentsItemChange(
            description='Laptop',
            category='electronics',
            quantity=1000,
            loss_type='stolen',
            ownership='owned',
        )
    with pytest.raises(ValueError):
        V8NextQuestion(
            field_codes=['x' * 101], wording='What happened?', reason='natural_follow_up'
        )


@pytest.fixture
def agent_turn_provider() -> V8JourneyProvider:
    provider = V8JourneyProvider([])
    provider.gateway.responses.append(
        ModelResponse(
            completion_status=ModelCompletionStatus.INCOMPLETE,
            finish_reason='length',
            structured_output={'reply': 'This is incomplete', 'field_changes': []},
        )
    )
    return provider


def test_truncated_v8_output_keeps_message_and_enters_existing_recovery(
    client: TestClient, repository: FixtureRepository
) -> None:
    created = create_claim(client, CLAIMANT, key='v8-output-cap').json()
    claim_id, session_id = created['claim']['claim_id'], created['session']['session_id']
    response = submit_message(
        client,
        CLAIMANT,
        claim_id,
        session_id,
        text='My car was rear-ended.',
        key='v8-output-cap-message',
    )
    assert response.status_code == 200
    body = response.json()
    assert body['agent_message'] is None
    assert body['recovery']['rule_id'] == 'claimant_turn.model_invalid_response'
    assert body['form_changes'] == []
    assert len(repository.list_messages(claim_id, session_id, 'cus_demo')) == 1
