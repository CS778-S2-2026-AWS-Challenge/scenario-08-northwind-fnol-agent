"""Deterministic compatibility binding for legacy P17.1 Follow-ups.

The migration never invents an interruption clock.  The sole recovery clock
origin is SessionRecoveryContext.interrupted_at.
"""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal

from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.models import (
    ActorType,
    FollowUpContactPermission,
    FollowUpReasonCode,
    FollowUpRecord,
    FollowUpStatus,
    SessionRecord,
)
from backend.domain.recovery_policy_registry import (
    INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_ID,
    INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION,
    INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE,
)


@dataclass(frozen=True)
class FollowUpBackfillDecision:
    record: FollowUpRecord
    audit_event: AuditEventEnvelope | None
    outcome: Literal['noop', 'bound', 'failed']


def follow_up_backfill_subject(
    follow_up: FollowUpRecord,
) -> AuditSubject:
    return AuditSubject(
        subject_type=AuditSubjectType.CONFIGURATION,
        subject_id=f'p17-follow-up:{follow_up.follow_up_id}',
        claim_id=follow_up.claim_id,
    )


def _audit_id(
    follow_up: FollowUpRecord,
    outcome: str,
) -> str:
    digest = sha256(
        (
            f'{follow_up.claim_id}:'
            f'{follow_up.follow_up_id}:'
            f'{outcome}'
        ).encode()
    ).hexdigest()[:24]
    return f'aud_p17_backfill_{digest}'


def _audit_event(
    follow_up: FollowUpRecord,
    *,
    outcome: Literal['bound', 'failed'],
    recorded_at: datetime,
    reason: str,
) -> AuditEventEnvelope:
    refs = list(
        dict.fromkeys(
            [
                f'follow-up:{follow_up.follow_up_id}',
                f'session:{follow_up.source_session_id}',
                *follow_up.source_refs,
            ]
        )
    )

    return AuditEventEnvelope(
        event_id=_audit_id(follow_up, outcome),
        event_type=(
            AuditEventType.ACTION_COMPLETED
            if outcome == 'bound'
            else AuditEventType.ACTION_FAILED
        ),
        outcome=(
            AuditOutcome.SUCCEEDED
            if outcome == 'bound'
            else AuditOutcome.FAILED
        ),
        subject=follow_up_backfill_subject(follow_up),
        actor=AuditActor(
            actor_type=ActorType.SYSTEM,
            actor_id='p17-recovery-migration',
            auth_source='repository:migration',
        ),
        reason=reason,
        source_refs=refs,
        visibility=AuditVisibility.AUDIT_ONLY,
        created_at=recorded_at,
    )


def backfill_legacy_follow_up_record(
    follow_up: FollowUpRecord,
    source_session: SessionRecord | None,
    *,
    recorded_at: datetime,
) -> FollowUpBackfillDecision:
    """Bind one open legacy Follow-up or fail it closed without guessing."""

    if recorded_at.tzinfo is None:
        raise ValueError('Backfill audit time must be timezone-aware.')

    if follow_up.status not in {
        FollowUpStatus.PENDING,
        FollowUpStatus.BLOCKED,
    }:
        return FollowUpBackfillDecision(
            record=follow_up,
            audit_event=None,
            outcome='noop',
        )

    already_bound = (
        follow_up.policy_id is not None
        and follow_up.policy_version is not None
        and follow_up.deadline_at is not None
    )

    blocked_reason_bound = (
        follow_up.status is not FollowUpStatus.BLOCKED
        or follow_up.reason_code is not None
    )

    if already_bound and blocked_reason_bound:
        return FollowUpBackfillDecision(
            record=follow_up,
            audit_event=None,
            outcome='noop',
        )

    recovery = (
        source_session.recovery_context
        if source_session is not None
        else None
    )

    source_consistent = (
        source_session is not None
        and source_session.session_id == follow_up.source_session_id
        and source_session.claim_id == follow_up.claim_id
        and recovery is not None
        and follow_up.created_at == recovery.interrupted_at
    )

    expected_deadline = (
        recovery.interrupted_at
        + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
        if recovery is not None
        else None
    )

    binding_conflict = (
        (
            follow_up.policy_id is not None
            and follow_up.policy_id
            != INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_ID
        )
        or (
            follow_up.policy_version is not None
            and follow_up.policy_version
            != INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION
        )
        or (
            follow_up.deadline_at is not None
            and expected_deadline is not None
            and follow_up.deadline_at != expected_deadline
        )
    )

    pending_schedule_conflict = (
        follow_up.status is FollowUpStatus.PENDING
        and (
            follow_up.due_at is None
            or expected_deadline is None
            or follow_up.due_at >= expected_deadline
        )
    )

    legacy_blocked_shape_invalid = (
        follow_up.status is FollowUpStatus.BLOCKED
        and follow_up.reason_code is None
        and (
            follow_up.contact_permission
            is not FollowUpContactPermission.NOT_AUTHORISED
            or follow_up.channel is not None
            or follow_up.due_at is not None
        )
    )

    if (
        not source_consistent
        or binding_conflict
        or pending_schedule_conflict
        or legacy_blocked_shape_invalid
    ):
        failure_reason_code = (
            FollowUpReasonCode.POLICY_BINDING_INVALID
            if binding_conflict
            else FollowUpReasonCode.SOURCE_STATE_INCONSISTENT
        )

        failed = follow_up.model_copy(
            update={
                'status': FollowUpStatus.BLOCKED,
                'reason_code': failure_reason_code,
            }
        )

        # Re-validate after model_copy, which intentionally skips validators.
        failed = FollowUpRecord.model_validate(
            failed.model_dump()
        )

        audit = _audit_event(
            follow_up,
            outcome='failed',
            recorded_at=recorded_at,
            reason=(
                'P17.1 Follow-up policy binding failed closed. '
                'No replacement interruption time was invented; original '
                'created_at, due_at, source references and attempt evidence '
                'were preserved for reconciliation.'
            ),
        )

        return FollowUpBackfillDecision(
            record=failed,
            audit_event=audit,
            outcome='failed',
        )

    assert expected_deadline is not None

    bound_reason_code: FollowUpReasonCode | None = follow_up.reason_code

    if (
        follow_up.status is FollowUpStatus.BLOCKED
        and bound_reason_code is None
    ):
        bound_reason_code = FollowUpReasonCode.CONTACT_NOT_AUTHORISED

    bound = follow_up.model_copy(
        update={
            'policy_id': INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_ID,
            'policy_version': INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION,
            'deadline_at': expected_deadline,
            'reason_code': bound_reason_code,
        }
    )

    bound = FollowUpRecord.model_validate(
        bound.model_dump()
    )

    audit = _audit_event(
        follow_up,
        outcome='bound',
        recorded_at=recorded_at,
        reason=(
            'P17.1 Follow-up deterministically bound to '
            'incomplete_claim_follow_up v1 using '
            'SessionRecoveryContext.interrupted_at as the recovery clock '
            'origin; existing due/source/attempt evidence was preserved.'
        ),
    )

    return FollowUpBackfillDecision(
        record=bound,
        audit_event=audit,
        outcome='bound',
    )
