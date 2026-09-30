"""Stable request profiles for the claimant Runtime.

The v8 claimant route uses one result envelope for ordinary, media, and lookup
turns.  The older task profiles remain registered solely for the explicit v7
rollback set.
"""

from backend.domain.agent_context_runtime import RequestProfile, TurnTask

# The earlier v7 Home intake baseline was 3955, before the vocabulary expansion.
# The claimant schema includes the registered branch field vocabulary. Keep a
# bounded ceiling while allowing the complete commercial FNOL contract.
V7_INPUT_HARD_LIMIT = 8000
# Interactive latency is dominated by output tokens (about 120 tokens/s measured
# on openrouter-gpt4o); input prefill is a small share. Input ceilings therefore
# leave headroom for long conversations while output limits stay tight.
V8_INPUT_HARD_LIMIT = 12_000

_PROFILES = {
    'claimant.turn.v1': RequestProfile(
        profile_id='claimant.turn.v1',
        version='v1',
        schema_id='claimant.turn.v1',
        max_model_invocations=1,
        max_model_selected_tools=0,
        input_hard_limit=V8_INPUT_HARD_LIMIT,
        # Dense envelope with every list at its cap estimates 6361 tokens
        # (tests/test_request_profile_budgets.py); operating cap, not a proof.
        output_limit=6500,
    ),
    'claimant.intake.v1': RequestProfile(
        profile_id='claimant.intake.v1',
        version='v1',
        schema_id='claimant.intake-patch.v1',
        max_model_invocations=1,
        max_model_selected_tools=0,
        input_hard_limit=V7_INPUT_HARD_LIMIT,
        output_limit=4500,
    ),
    'claimant.answer.v1': RequestProfile(
        profile_id='claimant.answer.v1',
        version='v1',
        schema_id='claimant.answer.v1',
        max_model_invocations=1,
        max_model_selected_tools=0,
        input_hard_limit=V7_INPUT_HARD_LIMIT,
        output_limit=4500,
    ),
    'claimant.media.v1': RequestProfile(
        profile_id='claimant.media.v1',
        version='v1',
        schema_id='claimant.turn.v1',
        max_model_invocations=1,
        max_model_selected_tools=0,
        input_hard_limit=V8_INPUT_HARD_LIMIT,
        output_limit=7500,
        requires_media_types=['image/*', 'application/pdf'],
    ),
    'claimant.lookup.v1': RequestProfile(
        profile_id='claimant.lookup.v1',
        version='v1',
        schema_id='claimant.turn.v1',
        tool_names=['context.resolve'],
        max_model_invocations=2,
        max_model_selected_tools=1,
        input_hard_limit=V8_INPUT_HARD_LIMIT,
        output_limit=6500,
        requires_tool_continuation=True,
    ),
    'claimant.evidence-history.v1': RequestProfile(
        profile_id='claimant.evidence-history.v1',
        version='v1',
        schema_id='claimant.evidence-action.v1',
        tool_names=['context.resolve'],
        max_model_invocations=2,
        max_model_selected_tools=1,
        input_hard_limit=3000,
        output_limit=300,
        requires_tool_continuation=True,
    ),
    'claimant.external.v1': RequestProfile(
        profile_id='claimant.external.v1',
        version='v1',
        schema_id='claimant.external-offer.v1',
        max_model_invocations=1,
        max_model_selected_tools=0,
        input_hard_limit=V7_INPUT_HARD_LIMIT,
        output_limit=4500,
    ),
    'claimant.deep-review.v1': RequestProfile(
        profile_id='claimant.deep-review.v1',
        version='v1',
        schema_id='claimant.sourced-summary.v1',
        max_model_invocations=1,
        max_model_selected_tools=0,
        input_hard_limit=20_000,
        output_limit=1200,
        isolated=True,
    ),
    'claimant.creation.v1': RequestProfile(
        profile_id='claimant.creation.v1',
        version='v1',
        schema_id='claimant.claim-creation.v1',
        max_model_invocations=1,
        max_model_selected_tools=0,
        input_hard_limit=V7_INPUT_HARD_LIMIT,
        output_limit=4500,
    ),
    'claimant.handoff.v1': RequestProfile(
        profile_id='claimant.handoff.v1',
        version='v1',
        schema_id='claimant.handoff.v1',
        max_model_invocations=1,
        max_model_selected_tools=0,
        input_hard_limit=V7_INPUT_HARD_LIMIT,
        output_limit=4500,
    ),
}

_TASK_PROFILE = {
    TurnTask.INTAKE: 'claimant.intake.v1',
    TurnTask.CORRECTION: 'claimant.intake.v1',
    TurnTask.CONFIRMATION: 'claimant.intake.v1',
    TurnTask.STATUS_QUESTION: 'claimant.answer.v1',
    TurnTask.CLAIM_CREATION: 'claimant.creation.v1',
    TurnTask.EVIDENCE_CURRENT: 'claimant.media.v1',
    TurnTask.EVIDENCE_HISTORY: 'claimant.evidence-history.v1',
    TurnTask.EXTERNAL_SUPPORT: 'claimant.external.v1',
    TurnTask.HUMAN_HANDOFF: 'claimant.handoff.v1',
}


def request_profile(profile_id: str) -> RequestProfile:
    try:
        return _PROFILES[profile_id]
    except KeyError as error:
        raise ValueError(f'Unknown request profile: {profile_id}.') from error


def request_profile_for_task(
    task: TurnTask,
    *,
    has_current_media: bool = False,
    isolated_review: bool = False,
    needs_lookup: bool = False,
    profiles: tuple[RequestProfile, ...] | list[RequestProfile] | None = None,
) -> RequestProfile:
    registry = {
        item.profile_id: item
        for item in (
            profiles
            if profiles is not None
            else registered_request_profiles('northwind-fnol-claimant-v7')
        )
    }

    def profile(name: str) -> RequestProfile:
        try:
            return registry[name]
        except KeyError as error:
            raise ValueError(f'The published request profile is missing: {name}.') from error

    if isolated_review:
        return profile('claimant.deep-review.v1')
    if needs_lookup:
        return profile('claimant.lookup.v1').model_copy(update={'schema_id': 'claimant.answer.v1'})
    if has_current_media and task in {TurnTask.INTAKE, TurnTask.CORRECTION}:
        return profile('claimant.media.v1').model_copy(
            update={'schema_id': 'claimant.intake-patch.v1'}
        )
    selected = profile(_TASK_PROFILE[task])
    if task is TurnTask.EVIDENCE_CURRENT:
        selected = selected.model_copy(update={'schema_id': 'claimant.intake-patch.v1'})
    return selected


def request_profile_for_intents(
    intents: frozenset[str] | set[str],
    *,
    has_current_media: bool = False,
    isolated_review: bool = False,
    needs_lookup: bool = False,
    profiles: tuple[RequestProfile, ...] | list[RequestProfile] | None = None,
) -> RequestProfile:
    """Select the v8 profile without narrowing the claimant result envelope.

    Evidence-history and deep-review remain deliberately narrow legacy profiles;
    every ordinary claimant turn, including external support and creation, uses
    ``claimant.turn.v1`` so facts, suggestions, and the next question cannot be
    discarded by a task-specific schema.
    """

    registry = {item.profile_id: item for item in profiles} if profiles is not None else _PROFILES

    def profile(name: str) -> RequestProfile:
        try:
            return registry[name]
        except KeyError as error:
            raise ValueError(f'The published request profile is missing: {name}.') from error

    if isolated_review:
        return profile('claimant.deep-review.v1')
    if 'evidence_history' in intents and not has_current_media:
        return profile('claimant.evidence-history.v1')
    if needs_lookup or 'policy_lookup' in intents or 'history_lookup' in intents:
        return profile('claimant.lookup.v1')
    if has_current_media or 'evidence_current' in intents:
        return profile('claimant.media.v1')
    return profile('claimant.turn.v1')


def registered_request_profiles(
    prompt_version: str = 'northwind-fnol-claimant-v8',
) -> tuple[RequestProfile, ...]:
    if prompt_version == 'northwind-fnol-claimant-v7':
        legacy = []
        for key in sorted(_PROFILES):
            if key == 'claimant.turn.v1':
                continue
            profile = _PROFILES[key]
            if key not in {'claimant.evidence-history.v1', 'claimant.deep-review.v1'}:
                profile = profile.model_copy(
                    update={'input_hard_limit': V7_INPUT_HARD_LIMIT, 'output_limit': 180}
                )
            if key == 'claimant.lookup.v1':
                profile = profile.model_copy(
                    update={'schema_id': 'claimant.answer.v1', 'output_limit': 300}
                )
            elif key == 'claimant.media.v1':
                profile = profile.model_copy(
                    update={'schema_id': 'claimant.intake-patch.v1', 'output_limit': 400}
                )
            legacy.append(profile)
        return tuple(legacy)
    active = {
        'claimant.turn.v1',
        'claimant.media.v1',
        'claimant.lookup.v1',
        'claimant.evidence-history.v1',
        'claimant.deep-review.v1',
    }
    return tuple(_PROFILES[key] for key in sorted(active))
