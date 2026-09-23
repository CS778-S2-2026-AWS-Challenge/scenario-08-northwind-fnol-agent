import pytest

from backend.domain.recovery_policy_registry import (
    RecoveryTrigger,
    UnknownRecoveryTrigger,
    classify_recovery,
)


def test_model_failures_use_the_published_claimant_rule() -> None:
    rule = classify_recovery(RecoveryTrigger(source='model', outcome_code='timeout'))

    assert rule.rule_id == 'claimant_turn.model_dependency_failure'
    assert rule.resume_entrypoint == 'submit_message'
    assert rule.preservation == 'inbound_message_and_checkpoint'
    assert rule.claim_effect == 'revision_unchanged_no_unapproved_write'


def test_unknown_recovery_sources_fail_closed() -> None:
    with pytest.raises(UnknownRecoveryTrigger):
        classify_recovery(RecoveryTrigger(source='external', outcome_code='unknown_outcome'))
