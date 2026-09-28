from datetime import UTC, datetime

from backend.services.recovery_decisions import (
    reduce_external_unknown_recovery,
    reduce_revision_conflict_recovery,
)

NOW = datetime(2026, 9, 28, 9, 30, tzinfo=UTC)


def test_revision_conflict_adapter_requires_authoritative_reload() -> None:
    transition = reduce_revision_conflict_recovery(
        claim_id='clm_revision_conflict',
        expected_revision=4,
        current_revision=5,
        event_id='recovery-revision-conflict',
        source_refs=['message:msg_conflict'],
        now=NOW,
    )

    assert transition.rule_id == 'runtime.revision_conflict'
    assert transition.decision_code == 'reload_authoritative_state'
    assert transition.retry_mode == 'reload_authoritative'
    assert transition.expected_claim_revision == 5
    assert transition.required_actions == (
        'claim.reload',
        'audit.append',
    )


def test_external_unknown_adapter_preserves_original_operation() -> None:
    transition = reduce_external_unknown_recovery(
        claim_id='clm_external_unknown',
        claim_revision=8,
        operation_id='op_assessor_1',
        delivery_state='submitted',
        event_id='recovery-external-unknown',
        source_refs=[
            'external-task:ext_1',
            'external-request:req_1',
        ],
        now=NOW,
    )

    assert transition.rule_id == 'external.submitted_unknown'
    assert transition.decision_code == 'reconcile_existing_operation'
    assert transition.retry_mode == 'reconcile_before_retry'
    assert transition.requires_reconciliation is True
    assert transition.operation_id == 'op_assessor_1'
    assert transition.blocks_action == 'external.retry'
    assert 'external.reconcile' in transition.required_actions


def test_interrupted_external_dispatch_is_also_reconciliation_not_resend() -> None:
    transition = reduce_external_unknown_recovery(
        claim_id='clm_external_reserved',
        claim_revision=3,
        operation_id='op_reserved_1',
        delivery_state='unknown',
        event_id='recovery-external-reserved',
        source_refs=['external-request:req_reserved'],
        now=NOW,
    )

    assert transition.decision_code == 'reconcile_existing_operation'
    assert transition.operation_id == 'op_reserved_1'
    assert 'external.retry_same_operation' not in transition.required_actions


def test_non_blocking_retrieval_unavailable_continues_with_limitation() -> None:
    from backend.services.recovery_decisions import (
        reduce_dependency_unavailable_recovery,
    )

    transition = reduce_dependency_unavailable_recovery(
        source='retrieval',
        blocking=False,
        claim_id='clm_retrieval_unavailable',
        claim_revision=4,
        event_id='recovery-retrieval-unavailable',
        source_refs=['context-tool:knowledge_search'],
        now=NOW,
    )

    assert transition.rule_id == ('runtime.retrieval_unavailable.non_blocking')
    assert transition.decision_code == 'continue_with_limitation'
    assert transition.continuation == 'runtime.continue'
    assert 'work_item.ensure' not in transition.required_actions


def test_blocking_tool_unavailable_fails_safe_with_existing_work_item() -> None:
    from backend.services.recovery_decisions import (
        reduce_dependency_unavailable_recovery,
    )

    transition = reduce_dependency_unavailable_recovery(
        source='tool',
        blocking=True,
        claim_id='clm_tool_unavailable',
        claim_revision=6,
        event_id='recovery-tool-unavailable',
        source_refs=['context-tool:evidence.history'],
        now=NOW,
    )

    assert transition.rule_id == 'runtime.tool_unavailable.blocking'
    assert transition.decision_code == 'fail_safe'
    assert transition.continuation == 'runtime.fail_safe'
    assert transition.work_item_kind == 'system'
    assert 'work_item.ensure' in transition.required_actions


def test_high_impact_review_requires_work_item_and_handoff_authority() -> None:
    from backend.services.recovery_decisions import (
        reduce_high_impact_review_recovery,
    )

    transition = reduce_high_impact_review_recovery(
        claim_id='clm_high_impact',
        claim_revision=9,
        event_id='recovery-high-impact',
        source_refs=['retrieval:pol_1', 'signal:sig_1'],
        now=NOW,
    )

    assert transition.rule_id == 'runtime.high_impact_review_required'
    assert transition.decision_code == 'pause_for_review'
    assert transition.continuation == 'runtime.pause_for_review'
    assert transition.responsibility == 'staff'
    assert transition.work_item_kind is None
    assert 'work_item.ensure' not in transition.required_actions
    assert 'handoff.ensure' in transition.required_actions


def test_external_terminal_failure_materialises_staff_responsibility() -> None:
    from backend.services.recovery_decisions import (
        build_recovery_work_item,
        reduce_external_terminal_recovery,
    )

    transition = reduce_external_terminal_recovery(
        claim_id='clm_external_terminal',
        claim_revision=5,
        operation_id='op_terminal',
        event_id='external-terminal-test',
        source_refs=['external-task:tsk_terminal'],
        now=NOW,
    )

    item = build_recovery_work_item(
        transition,
        claim_id='clm_external_terminal',
        subject_ref='external-task:tsk_terminal',
        now=NOW,
    )

    assert item is not None
    assert item.kind == 'external'
    assert item.owner == 'staff'
    assert item.status == 'open'
    assert item.blocks_action == 'external.retry'
