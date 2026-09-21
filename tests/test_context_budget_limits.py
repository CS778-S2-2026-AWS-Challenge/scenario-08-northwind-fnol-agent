"""Production input limits, soft telemetry and unescaped Unicode estimation."""

import json
import logging
from dataclasses import replace

import pytest

from backend.domain.agent_context_runtime import ContextBudgetPolicy
from backend.services.context_budget import build_request_budget, estimate_json_tokens
from backend.services.context_planner import ContextBudgetExceeded
from backend.services.model_request_planner import plan_model_turn
from backend.services.prompt_composer import estimate_tokens
from backend.services.request_profile_registry import V7_INPUT_HARD_LIMIT, request_profile
from tests.test_agent_context_runtime_v7 import _context
from tests.test_turn_proposal_v8 import v8_context


def test_unicode_cost_counts_decoded_utf8_instead_of_json_escapes() -> None:
    payload = {'message': '车辆追尾申请定损' * 40}
    expected = estimate_tokens(
        json.dumps(payload, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    )
    inflated = estimate_tokens(
        json.dumps(payload, separators=(',', ':'), sort_keys=True, ensure_ascii=True)
    )
    assert estimate_json_tokens(payload) == expected
    assert expected < inflated


def test_soft_limit_is_observable_without_refusing_a_legal_turn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger='backend.services.context_budget')
    plan = plan_model_turn(v8_context('My car was rear-ended yesterday.'))
    assert plan is not None
    assert 3000 < plan.request_budget.raw_input_tokens <= 6000
    assert plan.request_budget.hard_limit == 6000
    assert any(
        record.message == 'agent_turn_input_budget_soft_exceeded' for record in caplog.records
    )


def test_hard_limit_rejects_oversized_authoritative_input_without_truncating() -> None:
    context = v8_context('A' * 20000)
    with pytest.raises(ContextBudgetExceeded):
        plan_model_turn(context)
    assert context.message_text == 'A' * 20000


def test_lookup_hard_limit_is_per_request_not_cumulative_input_plus_output() -> None:
    profile = request_profile('claimant.lookup.v1')
    result = build_request_budget(
        policy=ContextBudgetPolicy(),
        profile=profile,
        prompt='x' * 9500,
        schema={},
        context={},
        tools=[],
        prior_turn_tokens=4000,
    )
    assert result.raw_input_tokens <= 6000
    assert result.turn_cumulative_tokens > 6000
    assert result.reserved_output_tokens == 4500


@pytest.mark.parametrize(
    ('family', 'message'),
    [
        (
            'motor',
            'My car was rear-ended on Queen Street yesterday at 3pm; '
            'the bumper is damaged and nobody is injured.',
        ),
        (
            'home',
            'A bathroom pipe burst last night at 12 Example Street, Wellington. '
            'The kitchen and ceiling are wet, the water is off, and we can live here.',
        ),
        (
            'contents',
            'My laptop was stolen through the back window yesterday afternoon in Wellington. '
            'Nobody was injured.',
        ),
    ],
)
def test_v7_rollback_three_family_context_fits_measured_compensation(
    family: str, message: str
) -> None:
    context = _context(message, incident_type=family)
    assert context.runtime_policy is not None
    evaluation = context.runtime_policy.branch_evaluator().evaluate(
        context.claim, latest_message=message, recomputation_reason='v7_rollback_budget_observation'
    )
    plan = plan_model_turn(replace(context, branch_evaluation=evaluation))
    assert plan is not None
    assert plan.request_budget.raw_input_tokens <= V7_INPUT_HARD_LIMIT
    assert plan.request_budget.hard_limit == V7_INPUT_HARD_LIMIT == 4549
