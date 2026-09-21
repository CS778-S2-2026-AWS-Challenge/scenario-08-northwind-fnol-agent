"""A rejected question loses its matching prose; valid grouped questions survive."""

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


def test_rejected_field_question_is_removed_exactly_before_runtime_fallback() -> None:
    rejected_wording = 'Are you the owner? Can you explain the cause?'
    validated = validate_question(
        f'I noted the damage. {rejected_wording} Is there anything else you want to tell me?',
        V8NextQuestion(
            field_codes=['claimant.role', 'incident.cause'],
            wording=rejected_wording,
            reason='natural_follow_up',
        ),
    )
    assert validated.next_question is None
    assert rejected_wording not in validated.reply
    assert validated.reply == 'I noted the damage. Is there anything else you want to tell me?'
    assert compose_reply(None, (), validated.reply, 'Was anyone injured?').endswith(
        'Was anyone injured?'
    )


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
    assert compose_reply(None, (), validated.reply, validated.next_question.wording) == reply
