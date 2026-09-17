"""Stable request profiles for Agent Context Runtime v7."""

from backend.domain.agent_context_runtime import RequestProfile, TurnTask

_PROFILES = {
    'claimant.intake.v1': RequestProfile(
        profile_id='claimant.intake.v1',
        version='v1',
        schema_id='claimant.intake-patch.v1',
        max_model_invocations=1,
        max_model_selected_tools=0,
        input_hard_limit=3000,
        output_limit=180,
    ),
    'claimant.answer.v1': RequestProfile(
        profile_id='claimant.answer.v1',
        version='v1',
        schema_id='claimant.answer.v1',
        max_model_invocations=1,
        max_model_selected_tools=0,
        input_hard_limit=3000,
        output_limit=180,
    ),
    'claimant.media.v1': RequestProfile(
        profile_id='claimant.media.v1',
        version='v1',
        schema_id='claimant.intake-patch.v1',
        max_model_invocations=1,
        max_model_selected_tools=0,
        input_hard_limit=3000,
        output_limit=180,
        requires_media_types=['image/*', 'application/pdf'],
    ),
    'claimant.lookup.v1': RequestProfile(
        profile_id='claimant.lookup.v1',
        version='v1',
        schema_id='claimant.answer.v1',
        tool_names=['context.resolve'],
        max_model_invocations=2,
        max_model_selected_tools=1,
        input_hard_limit=3000,
        output_limit=300,
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
        input_hard_limit=3000,
        output_limit=180,
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
        input_hard_limit=3000,
        output_limit=180,
    ),
    'claimant.handoff.v1': RequestProfile(
        profile_id='claimant.handoff.v1',
        version='v1',
        schema_id='claimant.handoff.v1',
        max_model_invocations=1,
        max_model_selected_tools=0,
        input_hard_limit=3000,
        output_limit=180,
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
    registry = {item.profile_id: item for item in profiles} if profiles is not None else _PROFILES
    if isolated_review:
        return registry['claimant.deep-review.v1']
    if needs_lookup:
        return registry['claimant.lookup.v1']
    if has_current_media and task in {TurnTask.INTAKE, TurnTask.CORRECTION}:
        return registry['claimant.media.v1']
    return registry[_TASK_PROFILE[task]]


def registered_request_profiles() -> tuple[RequestProfile, ...]:
    return tuple(_PROFILES[key] for key in sorted(_PROFILES))
