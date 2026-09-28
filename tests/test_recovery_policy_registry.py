from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.recovery_policy_registry import (
    EXTERNAL_UNKNOWN_RULE,
    INCOMPLETE_CLAIM_FOLLOW_UP_RULE,
    RETENTION_ELIGIBLE_RULE,
    RecoveryEvent,
    RecoverySnapshot,
    RecoveryTrigger,
    UnknownRecoveryTransition,
    UnknownRecoveryTrigger,
    classify_recovery,
    recovery_policy_manifest,
    reduce_recovery,
)


@pytest.mark.parametrize(
    ('trigger', 'policy_id'),
    [
        (RecoveryTrigger(source='model', outcome_code='timeout'), 'recovery.model_timeout'),
        (
            RecoveryTrigger(source='model', outcome_code='malformed_response'),
            'recovery.model_malformed_response',
        ),
        (RecoveryTrigger(source='tool', outcome_code='unavailable'), 'recovery.tool_unavailable'),
        (
            RecoveryTrigger(source='retrieval', outcome_code='unavailable'),
            'recovery.retrieval_unavailable',
        ),
        (
            RecoveryTrigger(source='repository', outcome_code='revision_conflict'),
            'recovery.revision_conflict',
        ),
        (
            RecoveryTrigger(
                source='external',
                outcome_code='retryable_failure',
                delivery_certain=False,
            ),
            'recovery.external_not_submitted_retryable',
        ),
        (
            RecoveryTrigger(
                source='external',
                outcome_code='unknown_outcome',
                delivery_certain=True,
                side_effect_may_have_happened=True,
            ),
            'recovery.external_submitted_unknown',
        ),
        (
            RecoveryTrigger(source='human', outcome_code='high_impact_review_required'),
            'recovery.high_impact_review_required',
        ),
    ],
)
def test_registered_failure_matrix_classifies_to_one_policy(
    trigger: RecoveryTrigger,
    policy_id: str,
) -> None:
    rule = classify_recovery(trigger)

    assert rule.policy_id == policy_id
    assert rule.version == 'v1'


def test_model_failure_keeps_existing_claimant_projection_identity() -> None:
    rule = classify_recovery(RecoveryTrigger(source='model', outcome_code='timeout'))

    assert rule.rule_id == 'claimant_turn.model_dependency_failure'
    assert rule.resume_entrypoint == 'submit_message'
    assert rule.preservation == 'inbound_message_and_checkpoint'
    assert rule.claim_effect == 'revision_unchanged_no_unapproved_write'


def test_unknown_recovery_sources_fail_closed() -> None:
    with pytest.raises(UnknownRecoveryTrigger):
        classify_recovery(RecoveryTrigger(source='timer', outcome_code='not_registered'))


def _p17_snapshot(
    *,
    now: datetime,
    attempts: int = 0,
    status: str = 'pending',
    contact_authorised: bool = True,
    revision: int = 3,
) -> RecoverySnapshot:
    return RecoverySnapshot(
        claim_revision=revision,
        follow_up_status=status,
        follow_up_attempt_count=attempts,
        contact_authorised=contact_authorised,
        due_at=now,
        deadline_at=now + timedelta(days=7),
        source_refs=['follow_up:fup_test'],
    )


def test_p17_deadline_equality_has_expiry_precedence() -> None:
    deadline = datetime(2026, 9, 29, 0, 0, tzinfo=UTC)
    snapshot = RecoverySnapshot(
        claim_revision=4,
        follow_up_status='pending',
        contact_authorised=True,
        due_at=deadline,
        deadline_at=deadline,
    )

    transition = reduce_recovery(
        INCOMPLETE_CLAIM_FOLLOW_UP_RULE,
        snapshot,
        RecoveryEvent(code='follow_up_due', expected_claim_revision=4),
        snapshot,
        deadline,
    )

    assert transition.decision == 'expire'
    assert transition.resolution_code == 'recovery_expired'
    assert transition.operation_action == 'cancel_pending'


def test_p17_due_attempt_is_planned_without_executing_side_effect() -> None:
    now = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    snapshot = _p17_snapshot(now=now)

    transition = reduce_recovery(
        INCOMPLETE_CLAIM_FOLLOW_UP_RULE,
        snapshot,
        RecoveryEvent(code='follow_up_due', expected_claim_revision=3),
        snapshot,
        now,
    )

    assert transition.decision == 'execute_follow_up'
    assert transition.operation_action == 'reserve_and_commit'
    assert transition.attempt_count_delta == 0
    assert transition.preserve_claim_revision == 3


def test_p17_committed_no_response_reschedules_from_policy_schedule() -> None:
    due_at = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    snapshot = _p17_snapshot(now=due_at, attempts=1)

    transition = reduce_recovery(
        INCOMPLETE_CLAIM_FOLLOW_UP_RULE,
        snapshot,
        RecoveryEvent(code='follow_up_committed_no_response'),
        snapshot,
        due_at,
    )

    assert transition.decision == 'retry'
    assert transition.attempt_count_delta == 1
    assert transition.next_due_at == due_at + timedelta(hours=24)
    assert transition.next_follow_up_status == 'pending'


def test_p17_third_committed_attempt_stops_contact_without_abandoning_claim() -> None:
    now = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    snapshot = _p17_snapshot(now=now, attempts=2)

    transition = reduce_recovery(
        INCOMPLETE_CLAIM_FOLLOW_UP_RULE,
        snapshot,
        RecoveryEvent(code='follow_up_committed_no_response'),
        snapshot,
        now,
    )

    assert transition.decision == 'block_follow_up'
    assert transition.blocked_reason == 'attempt_limit_reached'
    assert transition.next_follow_up_status == 'blocked'
    assert transition.resolution_code is None
    assert transition.attempt_count_delta == 1


def test_p17_contact_withdrawal_does_not_resolve_or_abandon() -> None:
    now = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    snapshot = _p17_snapshot(now=now, contact_authorised=False)

    transition = reduce_recovery(
        INCOMPLETE_CLAIM_FOLLOW_UP_RULE,
        snapshot,
        RecoveryEvent(code='contact_withdrawn'),
        snapshot,
        now,
    )

    assert transition.decision == 'block_follow_up'
    assert transition.blocked_reason == 'contact_not_authorised'
    assert transition.resolution_code is None


def test_stale_revision_reloads_instead_of_replaying_transition() -> None:
    now = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    loaded = _p17_snapshot(now=now, revision=3)
    authoritative = loaded.model_copy(update={'claim_revision': 4})

    transition = reduce_recovery(
        INCOMPLETE_CLAIM_FOLLOW_UP_RULE,
        loaded,
        RecoveryEvent(code='claimant_resume', expected_claim_revision=3),
        authoritative,
        now,
    )

    assert transition.policy_id == 'recovery.revision_conflict'
    assert transition.decision == 'reload'
    assert transition.preserve_claim_revision == 4


def test_submitted_external_unknown_requires_same_operation_reconciliation() -> None:
    now = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    snapshot = RecoverySnapshot(
        claim_revision=5,
        external_operation_state='submitted_unknown',
        source_refs=['external_task:ext_test'],
    )

    transition = reduce_recovery(
        EXTERNAL_UNKNOWN_RULE,
        snapshot,
        RecoveryEvent(code='scheduled_reconciliation'),
        snapshot,
        now,
    )

    assert transition.decision == 'reconcile'
    assert transition.operation_action == 'reconcile_same'
    assert transition.blocks_action == 'external.retry'


def test_retention_hold_blocks_destructive_transition() -> None:
    now = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    snapshot = RecoverySnapshot(
        claim_revision=8,
        retention_hold=True,
        source_refs=['terminal:td_test', 'hold:hold_test'],
    )

    transition = reduce_recovery(
        RETENTION_ELIGIBLE_RULE,
        snapshot,
        RecoveryEvent(code='retention_execute'),
        snapshot,
        now,
    )

    assert transition.policy_id == 'retention.hold'
    assert transition.decision == 'wait'
    assert transition.responsibility == 'staff'


def test_access_closure_denies_a_stale_recovery_event() -> None:
    now = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    snapshot = RecoverySnapshot(
        claim_revision=9,
        access_closed=True,
        source_refs=['retention:rop_test'],
    )

    transition = reduce_recovery(
        INCOMPLETE_CLAIM_FOLLOW_UP_RULE,
        snapshot,
        RecoveryEvent(code='claimant_resume'),
        snapshot,
        now,
    )

    assert transition.policy_id == 'retention.old_session_denied'
    assert transition.decision == 'deny'


def test_unregistered_event_for_policy_fails_closed() -> None:
    now = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    snapshot = _p17_snapshot(now=now)

    with pytest.raises(UnknownRecoveryTransition):
        reduce_recovery(
            INCOMPLETE_CLAIM_FOLLOW_UP_RULE,
            snapshot,
            RecoveryEvent(code='provider_webhook'),
            snapshot,
            now,
        )


def test_manifest_is_generated_from_unique_typed_policy_coordinates() -> None:
    manifest = recovery_policy_manifest()
    policies = manifest['policies']
    assert isinstance(policies, list)

    coordinates = [(item['policy_id'], item['version']) for item in policies]
    assert len(coordinates) == len(set(coordinates))
    assert ('incomplete_claim_follow_up', 'v1') in coordinates
    assert ('recovery.external_submitted_unknown', 'v1') in coordinates
    assert ('retention.old_session_denied', 'v1') in coordinates
