"""Pure provider-neutral recovery decision boundary.

This module contains no repository, clock, provider, model or queue access.
It maps one published policy plus authoritative input facts into a typed plan.
The plan is executed by the subsystem that already owns those facts.
"""

from datetime import datetime, timedelta

from pydantic import Field

from backend.domain.models import ContractModel
from backend.domain.recovery_policy_registry import (
    INCOMPLETE_CLAIM_FOLLOW_UP_RULE,
    OLD_SESSION_DENIED_RULE,
    RETENTION_ELIGIBLE_RULE,
    RETENTION_HOLD_RULE,
    REVISION_CONFLICT_RULE,
    RecoveryAction,
    RecoveryAuthority,
    RecoveryContinuation,
    RecoveryDecision,
    RecoveryDecisionCode,
    RecoveryEvent,
    RecoveryRetryMode,
    RecoveryRule,
    RecoverySnapshot,
    RecoveryTrigger,
    RecoveryWorkItemKind,
    UnknownRecoveryTransition,
    classify_recovery,
    recovery_policy,
)
from backend.domain.recovery_policy_registry import (
    RecoveryTransition as LifecycleRecoveryTransition,
)


class NormalizedRecoveryEvent(ContractModel):
    event_id: str = Field(min_length=1, max_length=160)
    trigger: RecoveryTrigger
    expected_claim_revision: int | None = Field(default=None, ge=1)
    operation_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_refs: list[str] = Field(default_factory=list, max_length=100)


class RecoveryAuthoritativeSnapshot(ContractModel):
    """Read-only reducer input, not a persisted recovery state object."""

    claim_id: str = Field(min_length=1, max_length=120)
    claim_revision: int = Field(ge=1)

    accepted_state_preserved: bool = True
    operation_id: str | None = Field(default=None, min_length=1, max_length=160)

    terminal: bool = False
    source_refs: list[str] = Field(default_factory=list, max_length=100)


class RecoveryTransition(ContractModel):
    """Typed plan returned by the pure reducer."""

    event_id: str
    rule_id: str
    policy_version: str

    decision_code: RecoveryDecisionCode
    continuation: RecoveryContinuation
    retry_mode: RecoveryRetryMode
    responsibility: str

    max_auto_retry: int
    requires_reconciliation: bool
    requires_operation_identity: bool

    work_item_kind: RecoveryWorkItemKind | None = None
    blocks_action: str | None = None

    claim_effect: str
    expected_claim_revision: int
    operation_id: str | None = None

    authoritative_records: frozenset[RecoveryAuthority]
    required_actions: tuple[RecoveryAction, ...]

    claimant_projection: str
    staff_projection: str | None = None

    resume_triggers: frozenset[str]
    resume_entrypoint: str

    audit_event_type: str
    source_refs: list[str]

    decided_at: datetime


class RecoveryReductionRejected(ValueError):
    """The event/snapshot cannot safely produce the requested transition."""


def reduce_recovery(
    policy: RecoveryRule,
    event: NormalizedRecoveryEvent,
    authoritative_snapshot: RecoveryAuthoritativeSnapshot,
    now: datetime,
) -> RecoveryTransition:
    """Reduce one normalised event without performing any side effect."""

    if now.tzinfo is None:
        raise RecoveryReductionRejected('Recovery decision time must be timezone-aware.')

    published = classify_recovery(event.trigger)

    if published != policy:
        raise RecoveryReductionRejected(
            'The supplied policy coordinate does not match the published event policy.'
        )

    expected_revision = event.expected_claim_revision

    if policy.rule_id == 'runtime.revision_conflict':
        if expected_revision is None:
            raise RecoveryReductionRejected(
                'Revision-conflict recovery requires the stale expected revision.'
            )

        if expected_revision == authoritative_snapshot.claim_revision:
            raise RecoveryReductionRejected('A revision-conflict event must name a stale revision.')

    elif (
        expected_revision is not None and expected_revision != authoritative_snapshot.claim_revision
    ):
        raise RecoveryReductionRejected(
            'The recovery event is stale against authoritative Claim state.'
        )

    if (
        policy.preservation == 'inbound_message_and_checkpoint'
        and not authoritative_snapshot.accepted_state_preserved
    ):
        raise RecoveryReductionRejected(
            'The accepted claimant input/checkpoint must be durable before recovery.'
        )

    operation_id = event.operation_id or authoritative_snapshot.operation_id

    if policy.requires_operation_identity and operation_id is None:
        raise RecoveryReductionRejected(
            'This recovery policy requires the existing logical operation identity.'
        )

    if policy.requires_reconciliation and operation_id is None:
        raise RecoveryReductionRejected(
            'Reconciliation cannot proceed without the original operation identity.'
        )

    source_refs = list(
        dict.fromkeys(
            [
                *authoritative_snapshot.source_refs,
                *event.source_refs,
                f'recovery-policy:{policy.rule_id}@{policy.version}',
            ]
        )
    )

    return RecoveryTransition(
        event_id=event.event_id,
        rule_id=policy.rule_id,
        policy_version=policy.version,
        decision_code=policy.decision_code,
        continuation=policy.continuation,
        retry_mode=policy.retry_mode,
        responsibility=policy.responsibility,
        max_auto_retry=policy.max_auto_retry,
        requires_reconciliation=policy.requires_reconciliation,
        requires_operation_identity=policy.requires_operation_identity,
        work_item_kind=policy.work_item_kind,
        blocks_action=policy.blocks_action,
        claim_effect=policy.claim_effect,
        expected_claim_revision=authoritative_snapshot.claim_revision,
        operation_id=operation_id,
        authoritative_records=policy.authoritative_records,
        required_actions=policy.required_actions,
        claimant_projection=policy.claimant_projection,
        staff_projection=policy.staff_projection,
        resume_triggers=policy.resume_triggers,
        resume_entrypoint=policy.resume_entrypoint,
        audit_event_type=policy.audit_event_type,
        source_refs=source_refs,
        decided_at=now,
    )


def _base_transition(
    rule: RecoveryRule,
    snapshot: RecoverySnapshot,
    *,
    decision: RecoveryDecision,
    source_refs: list[str],
    **updates: object,
) -> LifecycleRecoveryTransition:
    payload: dict[str, object] = {
        'policy_id': rule.policy_id,
        'policy_version': rule.version,
        'decision': decision,
        'runtime_directive': rule.continuation,
        'preserve_claim_revision': snapshot.claim_revision,
        'responsibility': rule.responsibility,
        'work_item_kind': rule.work_item_kind,
        'blocks_action': rule.blocks_action,
        'claimant_projection': rule.claimant_projection,
        'staff_projection': rule.staff_projection,
        'audit_event_type': rule.audit_event_type,
        'source_refs': source_refs,
    }
    payload.update(updates)
    return LifecycleRecoveryTransition.model_validate(payload)


def _reduce_incomplete_claim(
    rule: RecoveryRule,
    event: RecoveryEvent,
    snapshot: RecoverySnapshot,
    now: datetime,
    source_refs: list[str],
) -> LifecycleRecoveryTransition:
    if snapshot.follow_up_status == 'resolved':
        return _base_transition(rule, snapshot, decision='no_op', source_refs=source_refs)
    if snapshot.deadline_at is None:
        return _base_transition(
            rule,
            snapshot,
            decision='block_follow_up',
            source_refs=source_refs,
            next_follow_up_status='blocked',
            blocked_reason='policy_binding_invalid',
        )
    if now >= snapshot.deadline_at:
        return _base_transition(
            rule,
            snapshot,
            decision='expire',
            source_refs=source_refs,
            next_follow_up_status='resolved',
            resolution_code='recovery_expired',
            operation_action='cancel_pending',
        )
    if event.code == 'claimant_resume':
        return _base_transition(
            rule,
            snapshot,
            decision='resume',
            source_refs=source_refs,
            next_follow_up_status='resolved',
            resolution_code='claimant_resumed',
            operation_action='cancel_pending',
        )
    if event.code == 'contact_withdrawn' or snapshot.contact_authorised is False:
        return _base_transition(
            rule,
            snapshot,
            decision='block_follow_up',
            source_refs=source_refs,
            next_follow_up_status='blocked',
            blocked_reason='contact_not_authorised',
        )
    if snapshot.follow_up_attempt_count >= rule.max_auto_retry:
        return _base_transition(
            rule,
            snapshot,
            decision='block_follow_up',
            source_refs=source_refs,
            next_follow_up_status='blocked',
            blocked_reason='attempt_limit_reached',
        )
    if event.code == 'follow_up_due':
        if snapshot.follow_up_status != 'pending' or snapshot.due_at is None:
            return _base_transition(
                rule,
                snapshot,
                decision='block_follow_up',
                source_refs=source_refs,
                next_follow_up_status='blocked',
                blocked_reason='source_state_inconsistent',
            )
        if now < snapshot.due_at:
            raise UnknownRecoveryTransition('Follow-up due event arrived before its due time.')
        return _base_transition(
            rule,
            snapshot,
            decision='execute_follow_up',
            source_refs=source_refs,
            next_follow_up_status='pending',
            operation_action='reserve_and_commit',
        )
    if event.code == 'follow_up_committed_no_response':
        next_count = snapshot.follow_up_attempt_count + 1
        if next_count >= rule.max_auto_retry:
            return _base_transition(
                rule,
                snapshot,
                decision='block_follow_up',
                source_refs=source_refs,
                next_follow_up_status='blocked',
                blocked_reason='attempt_limit_reached',
                attempt_count_delta=1,
            )
        if snapshot.due_at is None or rule.retry_interval_seconds is None:
            return _base_transition(
                rule,
                snapshot,
                decision='block_follow_up',
                source_refs=source_refs,
                next_follow_up_status='blocked',
                blocked_reason='source_state_inconsistent',
                attempt_count_delta=1,
            )
        next_due_at = snapshot.due_at + timedelta(seconds=rule.retry_interval_seconds)
        if next_due_at >= snapshot.deadline_at:
            return _base_transition(
                rule,
                snapshot,
                decision='block_follow_up',
                source_refs=source_refs,
                next_follow_up_status='blocked',
                blocked_reason='attempt_limit_reached',
                attempt_count_delta=1,
            )
        return _base_transition(
            rule,
            snapshot,
            decision='retry',
            source_refs=source_refs,
            next_follow_up_status='pending',
            attempt_count_delta=1,
            next_due_at=next_due_at,
        )
    raise UnknownRecoveryTransition(f'Unsupported incomplete-Claim event {event.code}.')


def reduce_lifecycle_recovery(
    policy: RecoveryRule,
    recovery_state: RecoverySnapshot,
    incoming_event: RecoveryEvent,
    authoritative_snapshot: RecoverySnapshot,
    now: datetime,
) -> LifecycleRecoveryTransition:
    """Reduce one recovery event into a deterministic transition plan.

    The function performs no I/O and reads no global clock. recovery_state is
    the caller's previously loaded coordination view; authoritative_snapshot is
    the fresh commit-time source snapshot. A mismatch therefore fails closed
    instead of replaying stale work.

    Args:
        policy: Immutable policy selected from the Registry.
        recovery_state: Previously loaded recovery coordination facts.
        incoming_event: Deduplicated event being evaluated.
        authoritative_snapshot: Fresh authoritative facts for commit-time decisions.
        now: Explicit UTC comparison time supplied by the caller.

    Returns:
        A typed transition plan containing no executed side effects.

    Raises:
        UnknownRecoveryTransition: The event is not permitted or the policy is incomplete.
    """

    if now.tzinfo is None:
        raise UnknownRecoveryTransition('Recovery decision time must be timezone-aware.')
    if recovery_policy(policy.policy_id, policy.version) != policy:
        raise UnknownRecoveryTransition(
            'The supplied policy differs from its published definition.'
        )
    if incoming_event.code not in policy.permitted_events:
        raise UnknownRecoveryTransition(
            f'Event {incoming_event.code} is not permitted by {policy.policy_id}.{policy.version}.'
        )

    source_refs = list(
        dict.fromkeys(
            [
                *recovery_state.source_refs,
                *authoritative_snapshot.source_refs,
                *incoming_event.source_refs,
            ]
        )
    )

    if authoritative_snapshot.access_closed:
        return _base_transition(
            OLD_SESSION_DENIED_RULE,
            authoritative_snapshot,
            decision='deny',
            source_refs=source_refs,
        )

    if (
        incoming_event.expected_claim_revision is not None
        and incoming_event.expected_claim_revision != authoritative_snapshot.claim_revision
    ):
        return _base_transition(
            REVISION_CONFLICT_RULE,
            authoritative_snapshot,
            decision='reload',
            source_refs=source_refs,
        )

    if recovery_state.claim_revision != authoritative_snapshot.claim_revision:
        return _base_transition(
            REVISION_CONFLICT_RULE,
            authoritative_snapshot,
            decision='reload',
            source_refs=source_refs,
        )

    if policy.policy_id == INCOMPLETE_CLAIM_FOLLOW_UP_RULE.policy_id:
        return _reduce_incomplete_claim(
            policy,
            incoming_event,
            authoritative_snapshot,
            now,
            source_refs,
        )

    if policy.reconciliation_required:
        return _base_transition(
            policy,
            authoritative_snapshot,
            decision='reconcile',
            source_refs=source_refs,
            operation_action='reconcile_same' if policy.trigger_source == 'external' else 'none',
        )

    if policy.policy_id == REVISION_CONFLICT_RULE.policy_id:
        return _base_transition(
            policy,
            authoritative_snapshot,
            decision='reload',
            source_refs=source_refs,
        )

    if policy.retry_mode == 'same_operation':
        return _base_transition(
            policy,
            authoritative_snapshot,
            decision='retry',
            source_refs=source_refs,
            operation_action='retry_same',
        )

    if policy.retry_mode == 'staff_authorised':
        return _base_transition(
            policy,
            authoritative_snapshot,
            decision='review',
            source_refs=source_refs,
        )

    if policy.policy_id == RETENTION_ELIGIBLE_RULE.policy_id:
        if authoritative_snapshot.retention_hold:
            return _base_transition(
                RETENTION_HOLD_RULE,
                authoritative_snapshot,
                decision='wait',
                source_refs=source_refs,
            )
        return _base_transition(
            policy,
            authoritative_snapshot,
            decision='retain',
            source_refs=source_refs,
        )

    if policy.retry_mode in {'claimant_initiated', 'bounded_auto', 'scheduled_policy'}:
        return _base_transition(
            policy,
            authoritative_snapshot,
            decision='retry',
            source_refs=source_refs,
        )

    return _base_transition(
        policy,
        authoritative_snapshot,
        decision='wait',
        source_refs=source_refs,
    )


def reduce_owned_recovery(
    trigger: RecoveryTrigger,
    claim_id: str,
    claim_revision: int,
    event_id: str,
    now: datetime,
    source_refs: list[str],
    operation_id: str | None = None,
) -> RecoveryTransition:
    """Route subsystem-owned lifecycle facts through the shared pure boundary."""
    return reduce_recovery(
        classify_recovery(trigger),
        NormalizedRecoveryEvent(
            event_id=event_id,
            trigger=trigger,
            expected_claim_revision=claim_revision,
            operation_id=operation_id,
            source_refs=source_refs,
        ),
        RecoveryAuthoritativeSnapshot(
            claim_id=claim_id,
            claim_revision=claim_revision,
            operation_id=operation_id,
            source_refs=source_refs,
        ),
        now,
    )
