import pytest

from backend.domain.recovery_policy_registry import (
    RECOVERY_POLICY_REGISTRY_VERSION,
    RecoveryTrigger,
    UnknownRecoveryTrigger,
    claimant_recovery_projection,
    classify_recovery,
    recovery_policy_manifest,
)


def test_model_timeout_uses_specific_published_rule() -> None:
    rule = classify_recovery(
        RecoveryTrigger(
            source='model',
            outcome_code='timeout',
            retryable=True,
        )
    )

    assert rule.rule_id == 'claimant_turn.model_timeout'
    assert rule.resume_entrypoint == 'submit_message'
    assert rule.preservation == 'inbound_message_and_checkpoint'
    assert rule.claim_effect == 'revision_unchanged_no_unapproved_write'


def test_invalid_model_output_is_distinct_from_timeout() -> None:
    rule = classify_recovery(
        RecoveryTrigger(
            source='model',
            outcome_code='malformed_response',
            retryable=False,
        )
    )

    assert rule.rule_id == 'claimant_turn.model_invalid_response'
    assert rule.required_actions == (
        'message.preserve_checkpoint',
        'claim.preserve_revision',
        'audit.append',
    )


def test_provider_retryability_is_part_of_the_policy_coordinate() -> None:
    retryable = classify_recovery(
        RecoveryTrigger(
            source='model',
            outcome_code='provider',
            retryable=True,
        )
    )
    terminal = classify_recovery(
        RecoveryTrigger(
            source='model',
            outcome_code='provider',
            retryable=False,
        )
    )

    assert retryable.rule_id == 'claimant_turn.model_provider_retryable'
    assert retryable.retry_mode == 'claimant_initiated'

    assert terminal.rule_id == 'claimant_turn.model_provider_terminal'
    assert terminal.retry_mode == 'none'
    assert terminal.responsibility == 'system'


def test_tool_and_retrieval_rules_require_blocking_semantics() -> None:
    non_blocking = classify_recovery(
        RecoveryTrigger(
            source='tool',
            outcome_code='unavailable',
            blocking=False,
        )
    )
    blocking = classify_recovery(
        RecoveryTrigger(
            source='tool',
            outcome_code='unavailable',
            blocking=True,
        )
    )

    assert non_blocking.continuation == 'runtime.continue'
    assert blocking.continuation == 'runtime.fail_safe'
    assert blocking.work_item_kind == 'system'

    with pytest.raises(UnknownRecoveryTrigger):
        classify_recovery(
            RecoveryTrigger(
                source='retrieval',
                outcome_code='unavailable',
            )
        )


def test_external_unknown_requires_explicit_delivery_evidence() -> None:
    rule = classify_recovery(
        RecoveryTrigger(
            source='external',
            outcome_code='unknown_outcome',
            delivery_state='submitted',
        )
    )

    assert rule.rule_id == 'external.submitted_unknown'
    assert rule.requires_reconciliation is True
    assert rule.requires_operation_identity is True
    assert rule.retry_mode == 'reconcile_before_retry'

    with pytest.raises(UnknownRecoveryTrigger):
        classify_recovery(
            RecoveryTrigger(
                source='external',
                outcome_code='unknown_outcome',
            )
        )


def test_p17_rules_use_the_existing_follow_up_authority() -> None:
    due = classify_recovery(
        RecoveryTrigger(
            source='timer',
            outcome_code='follow_up_due',
        )
    )
    exhausted = classify_recovery(
        RecoveryTrigger(
            source='timer',
            outcome_code='attempt_limit_reached',
        )
    )

    assert 'follow_up' in due.authoritative_records
    assert due.required_actions == ('follow_up.execute', 'audit.append')
    assert exhausted.decision_code == 'block_follow_up'
    assert 'claim.expire' not in exhausted.required_actions


def test_legacy_model_policy_coordinate_remains_projectable() -> None:
    projection = claimant_recovery_projection(
        'claimant_turn.model_dependency_failure'
    )

    assert projection is not None
    assert projection.rule_id == 'claimant_turn.model_dependency_failure'
    assert projection.resume_entrypoint == 'submit_message'


def test_registry_manifest_is_deterministic_and_versioned() -> None:
    first = recovery_policy_manifest()
    second = recovery_policy_manifest()

    assert first == second
    assert first['registry_version'] == RECOVERY_POLICY_REGISTRY_VERSION

    rules = first['rules']
    assert isinstance(rules, list)
    assert len(rules) >= 15


def test_unknown_recovery_sources_fail_closed() -> None:
    with pytest.raises(UnknownRecoveryTrigger):
        classify_recovery(
            RecoveryTrigger(
                source='external',
                outcome_code='invented_outcome',
                delivery_state='unknown',
            )
        )
