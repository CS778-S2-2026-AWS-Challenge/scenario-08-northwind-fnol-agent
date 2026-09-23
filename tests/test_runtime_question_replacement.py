"""The model's question stands as written; Runtime observes, it does not rewrite.

Asking about a field Runtime already holds is the model's call and is logged for
prompt tuning. The words the claimant reads are never edited by Runtime, and a
model-authored turn never gets a template question appended.
"""

import logging

import pytest

from backend.domain.agent_v8 import V8NextQuestion, V8TurnProposal
from backend.services.turn_field_contract import compile_turn_field_contract
from backend.services.turn_proposal_validation import ValidatedTurn, validate_turn_proposal
from backend.services.turn_reducer import compose_reply
from tests.test_turn_proposal_v8 import v8_context


def validate_question(reply: str, question: V8NextQuestion) -> ValidatedTurn:
    context = v8_context('The bumper was damaged.')
    assert context.branch_evaluation is not None
    assert context.runtime_policy is not None
    return validate_turn_proposal(
        V8TurnProposal(reply=reply, reason_codes=['FACT_RECORDED'], next_question=question),
        branch_evaluation=context.branch_evaluation,
        eligible_service_ids=(),
        safety_interrupt=None,
        field_contract=compile_turn_field_contract(
            context.branch_evaluation, context.runtime_policy.branch_evaluator().registry
        ),
        open_handoffs=(),
        message_text=context.message_text,
    )


def test_question_about_a_held_field_is_observed_not_removed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger='backend.services.turn_proposal_validation')
    wording = 'Are you the owner? Can you explain the cause?'
    reply = f'I noted the damage. {wording} Is there anything else you want to tell me?'
    validated = validate_question(
        reply,
        V8NextQuestion(
            field_codes=['claimant.role', 'incident.cause'],
            wording=wording,
            reason='natural_follow_up',
        ),
    )
    assert validated.reply == reply
    assert validated.next_question is not None
    assert any(
        getattr(record, 'observation', {}).get('note') == 'field_not_missing'
        for record in caplog.records
    )
    assert not any(
        getattr(record, 'rejection', {}).get('part') == 'next_question' for record in caplog.records
    )


def test_model_authored_reply_never_gets_a_template_question_appended() -> None:
    reply = 'I noted the damage. Is there anything else you want to tell me?'
    assert compose_reply(None, (), reply, 'Was anyone injured?', model_authored=True) == reply
    # The controlled (fixture) path keeps its older composition.
    assert compose_reply(None, (), reply, 'Was anyone injured?').endswith('Was anyone injured?')


def test_valid_grouped_model_questions_remain_verbatim_and_are_not_duplicated() -> None:
    wording = 'Was anyone injured? Can the car still be driven?'
    reply = f'I noted the damage. {wording}'
    validated = validate_question(
        reply,
        V8NextQuestion(
            field_codes=['incident.injury_or_danger', 'vehicle.drivable'],
            wording=wording,
            reason='safety_first',
        ),
    )
    assert validated.next_question is not None
    assert validated.reply == reply
    assert (
        compose_reply(
            None, (), validated.reply, validated.next_question.wording, model_authored=True
        )
        == reply
    )
