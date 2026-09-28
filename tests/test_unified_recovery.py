from datetime import UTC, datetime

import pytest

from backend.domain.recovery import (
    NormalizedRecoveryEvent,
    RecoveryAuthoritativeSnapshot,
    RecoveryReductionRejected,
    reduce_recovery,
)
from backend.domain.recovery_policy_registry import (
    RecoveryTrigger,
    classify_recovery,
)

NOW = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)


def _snapshot(
    *,
    revision: int = 7,
    operation_id: str | None = None,
    preserved: bool = True,
) -> RecoveryAuthoritativeSnapshot:
    return RecoveryAuthoritativeSnapshot(
        claim_id='clm_recovery',
        claim_revision=revision,
        accepted_state_preserved=preserved,
        operation_id=operation_id,
        source_refs=[f'claim:clm_recovery:revision:{revision}'],
    )


def test_model_timeout_reduction_is_pure_and_deterministic() -> None:
    trigger = RecoveryTrigger(
        source='model',
        outcome_code='timeout',
        retryable=True,
    )
    rule = classify_recovery(trigger)
    event = NormalizedRecoveryEvent(
        event_id='rev_model_timeout',
        trigger=trigger,
        expected_claim_revision=7,
        source_refs=['message:msg_timeout'],
    )

    first = reduce_recovery(rule, event, _snapshot(), NOW)
    second = reduce_recovery(rule, event, _snapshot(), NOW)

    assert first == second
    assert first.rule_id == 'claimant_turn.model_timeout'
    assert first.decision_code == 'fail_safe'
    assert first.expected_claim_revision == 7
    assert first.required_actions == (
        'message.preserve_checkpoint',
        'claim.preserve_revision',
        'audit.append',
    )
    assert first.operation_id is None


def test_model_recovery_refuses_unpreserved_accepted_input() -> None:
    trigger = RecoveryTrigger(
        source='model',
        outcome_code='timeout',
        retryable=True,
    )
    rule = classify_recovery(trigger)
    event = NormalizedRecoveryEvent(
        event_id='rev_model_unpreserved',
        trigger=trigger,
        expected_claim_revision=7,
    )

    with pytest.raises(
        RecoveryReductionRejected,
        match='must be durable',
    ):
        reduce_recovery(
            rule,
            event,
            _snapshot(preserved=False),
            NOW,
        )


def test_submitted_unknown_external_result_requires_same_operation() -> None:
    trigger = RecoveryTrigger(
        source='external',
        outcome_code='unknown_outcome',
        delivery_state='submitted',
    )
    rule = classify_recovery(trigger)
    event = NormalizedRecoveryEvent(
        event_id='rev_external_unknown',
        trigger=trigger,
        expected_claim_revision=7,
        source_refs=['external-task:ext_1'],
    )

    with pytest.raises(
        RecoveryReductionRejected,
        match='logical operation identity',
    ):
        reduce_recovery(rule, event, _snapshot(), NOW)

    transition = reduce_recovery(
        rule,
        event,
        _snapshot(operation_id='ext_op_1'),
        NOW,
    )

    assert transition.operation_id == 'ext_op_1'
    assert transition.requires_reconciliation is True
    assert transition.retry_mode == 'reconcile_before_retry'
    assert 'external.reconcile' in transition.required_actions
    assert 'work_item.ensure' in transition.required_actions


def test_not_submitted_external_failure_retries_same_operation_only() -> None:
    trigger = RecoveryTrigger(
        source='external',
        outcome_code='retryable_failure',
        delivery_state='not_submitted',
    )
    rule = classify_recovery(trigger)
    event = NormalizedRecoveryEvent(
        event_id='rev_external_retry',
        trigger=trigger,
        expected_claim_revision=7,
        operation_id='ext_op_retry',
    )

    transition = reduce_recovery(
        rule,
        event,
        _snapshot(),
        NOW,
    )

    assert transition.decision_code == 'retry_same_operation'
    assert transition.operation_id == 'ext_op_retry'
    assert transition.required_actions == (
        'external.retry_same_operation',
        'audit.append',
    )


def test_revision_conflict_discards_stale_revision_and_requires_reload() -> None:
    trigger = RecoveryTrigger(
        source='repository',
        outcome_code='revision_conflict',
    )
    rule = classify_recovery(trigger)

    stale = NormalizedRecoveryEvent(
        event_id='rev_conflict',
        trigger=trigger,
        expected_claim_revision=6,
    )

    transition = reduce_recovery(
        rule,
        stale,
        _snapshot(revision=7),
        NOW,
    )

    assert transition.decision_code == 'reload_authoritative_state'
    assert transition.required_actions == ('claim.reload', 'audit.append')
    assert transition.expected_claim_revision == 7

    not_stale = stale.model_copy(update={'expected_claim_revision': 7})

    with pytest.raises(
        RecoveryReductionRejected,
        match='must name a stale revision',
    ):
        reduce_recovery(
            rule,
            not_stale,
            _snapshot(revision=7),
            NOW,
        )


def test_blocking_and_non_blocking_tool_failures_reduce_differently() -> None:
    non_blocking_trigger = RecoveryTrigger(
        source='tool',
        outcome_code='unavailable',
        blocking=False,
    )
    blocking_trigger = RecoveryTrigger(
        source='tool',
        outcome_code='unavailable',
        blocking=True,
    )

    non_blocking = reduce_recovery(
        classify_recovery(non_blocking_trigger),
        NormalizedRecoveryEvent(
            event_id='rev_tool_limit',
            trigger=non_blocking_trigger,
            expected_claim_revision=7,
        ),
        _snapshot(),
        NOW,
    )
    blocking = reduce_recovery(
        classify_recovery(blocking_trigger),
        NormalizedRecoveryEvent(
            event_id='rev_tool_blocked',
            trigger=blocking_trigger,
            expected_claim_revision=7,
        ),
        _snapshot(),
        NOW,
    )

    assert non_blocking.continuation == 'runtime.continue'
    assert 'work_item.ensure' not in non_blocking.required_actions

    assert blocking.continuation == 'runtime.fail_safe'
    assert blocking.work_item_kind == 'system'
    assert 'work_item.ensure' in blocking.required_actions


def test_attempt_exhaustion_does_not_become_claim_abandonment() -> None:
    trigger = RecoveryTrigger(
        source='timer',
        outcome_code='attempt_limit_reached',
    )
    rule = classify_recovery(trigger)

    transition = reduce_recovery(
        rule,
        NormalizedRecoveryEvent(
            event_id='rev_p17_exhausted',
            trigger=trigger,
            expected_claim_revision=7,
        ),
        _snapshot(),
        NOW,
    )

    assert transition.decision_code == 'block_follow_up'
    assert transition.claim_effect == 'existing_authority_only'
    assert transition.required_actions == (
        'follow_up.block',
        'audit.append',
    )


def test_naive_reducer_time_fails_closed() -> None:
    trigger = RecoveryTrigger(
        source='model',
        outcome_code='timeout',
        retryable=True,
    )
    rule = classify_recovery(trigger)

    with pytest.raises(
        RecoveryReductionRejected,
        match='timezone-aware',
    ):
        reduce_recovery(
            rule,
            NormalizedRecoveryEvent(
                event_id='rev_naive_time',
                trigger=trigger,
                expected_claim_revision=7,
            ),
            _snapshot(),
            datetime(2026, 9, 28, 9, 0),
        )


@pytest.mark.parametrize('decision_code', ['continue', 'wait_for_user'])
def test_published_policy_coordinates_cannot_hide_modified_decisions(decision_code: str) -> None:
    trigger = RecoveryTrigger(source='model', outcome_code='timeout', retryable=True)
    policy = classify_recovery(trigger)
    modified = policy.model_copy(update={'decision_code': decision_code})
    event = NormalizedRecoveryEvent(event_id='tampered-policy', trigger=trigger)
    with pytest.raises(RecoveryReductionRejected, match='published'):
        reduce_recovery(modified, event, _snapshot(), NOW)


def test_checked_in_replay_matrix_reduces_without_mutating_sources() -> None:
    """The #1076 matrix is repeatable contract evidence, not a copied success label."""
    import json
    from pathlib import Path

    from backend.domain.recovery import reduce_lifecycle_recovery
    from backend.domain.recovery_policy_registry import (
        RecoveryEvent,
        RecoverySnapshot,
        UnknownRecoveryTransition,
        recovery_policy,
    )

    matrix = json.loads(
        (
            Path(__file__).resolve().parents[1] / 'docs/contracts/recovery-replay-matrix.json'
        ).read_text(encoding='utf-8')
    )
    assert len(matrix['vectors']) >= 20
    for vector in matrix['vectors']:
        now = datetime.fromisoformat(vector['now'])
        policy = recovery_policy(vector['policy_id'], vector.get('version', 'v1'))
        if 'trigger' in vector['event']:
            event = NormalizedRecoveryEvent.model_validate(vector['event'])
            snapshot = RecoveryAuthoritativeSnapshot.model_validate(vector['snapshot'])
            before = snapshot.model_dump_json()
            first = reduce_recovery(policy, event, snapshot, now)
            assert first == reduce_recovery(policy, event, snapshot, now)
            assert first == type(first).model_validate(vector['transition'])
            assert snapshot.model_dump_json() == before
        else:
            lifecycle_event = RecoveryEvent.model_validate(vector['event'])
            lifecycle_snapshot = RecoverySnapshot.model_validate(vector['snapshot'])
            if 'rejected' in vector:
                with pytest.raises(UnknownRecoveryTransition):
                    reduce_lifecycle_recovery(
                        policy,
                        lifecycle_snapshot,
                        lifecycle_event,
                        lifecycle_snapshot,
                        now,
                    )
            else:
                transition = reduce_lifecycle_recovery(
                    policy,
                    lifecycle_snapshot,
                    lifecycle_event,
                    lifecycle_snapshot,
                    now,
                )
                assert transition == type(transition).model_validate(vector['transition'])
