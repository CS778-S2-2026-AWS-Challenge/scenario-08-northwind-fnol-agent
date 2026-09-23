"""Provider-neutral request budgeting before Model Gateway transport."""

import json
import logging

from backend.domain.agent_context_runtime import (
    ContextBudgetPolicy,
    ModelRequestBudget,
    RequestProfile,
)
from backend.services.prompt_composer import estimate_tokens

logger = logging.getLogger(__name__)


def request_input_limit(profile: RequestProfile, policy: ContextBudgetPolicy) -> int:
    """Use the versioned per-request bound for claimant turn profiles."""
    if profile.isolated:
        return profile.input_hard_limit
    return min(profile.input_hard_limit, policy.ordinary_input_hard_limit)


def estimate_json_tokens(value: object) -> int:
    return estimate_tokens(
        json.dumps(value, separators=(',', ':'), sort_keys=True, ensure_ascii=False)
    )


def build_request_budget(
    *,
    policy: ContextBudgetPolicy,
    profile: RequestProfile,
    prompt: str,
    schema: dict[str, object],
    context: dict[str, object],
    tools: list[dict[str, object]],
    recent_history_tokens: int = 0,
    retrieved_context_tokens: int = 0,
    prior_turn_tokens: int = 0,
) -> ModelRequestBudget:
    prompt_tokens = estimate_tokens(prompt)
    schema_tokens = estimate_json_tokens(schema)
    context_tokens = estimate_json_tokens(context)
    tool_tokens = estimate_json_tokens(tools) if tools else 0
    framing_tokens = 32
    raw_input = prompt_tokens + schema_tokens + context_tokens + tool_tokens + framing_tokens
    cache_eligible = prompt_tokens + schema_tokens + tool_tokens
    hard_limit = request_input_limit(profile, policy)
    if profile.schema_id == 'claimant.turn.v1' and raw_input > 3000:
        logger.info(
            'agent_turn_input_budget_soft_exceeded',
            extra={
                'request_profile_id': profile.profile_id,
                'raw_input_tokens': raw_input,
                'soft_limit': 3000,
                'hard_limit': hard_limit,
            },
        )
    return ModelRequestBudget(
        policy_version=policy.policy_version,
        raw_input_tokens=raw_input,
        uncached_input_tokens=raw_input,
        cache_eligible_tokens=cache_eligible,
        turn_cumulative_tokens=prior_turn_tokens + raw_input,
        reserved_output_tokens=profile.output_limit,
        prompt_tokens=prompt_tokens,
        schema_tokens=schema_tokens,
        context_tokens=context_tokens,
        tool_definition_tokens=tool_tokens,
        recent_history_tokens=recent_history_tokens,
        retrieved_context_tokens=retrieved_context_tokens,
        hard_limit=hard_limit,
        estimate_method='conservative_chars',
    )
