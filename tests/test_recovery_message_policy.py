from typing import Any, NoReturn, cast

import pytest

import backend.services.messages as messages_service
from backend.domain.models import AgentProposalSource


def test_message_boundary_accepts_non_blocking_retrieval_recovery() -> None:
    messages_service._validate_unavailable_context_recovery(
        claim_id='clm_message_retrieval',
        claim_revision=5,
        tool_results=[
            {
                'tool': 'knowledge_search',
                'status': 'unavailable',
                'source_refs': [],
                'limitations': ['Approved knowledge retrieval is temporarily unavailable.'],
            }
        ],
    )


def test_message_boundary_accepts_explicit_blocking_tool_recovery() -> None:
    work_items = messages_service._validate_unavailable_context_recovery(
        claim_id='clm_message_tool',
        claim_revision=5,
        tool_results=[
            {
                'tool': 'evidence.history',
                'status': 'unavailable',
                'blocking': True,
                'source_refs': [],
            }
        ],
    )

    assert len(work_items) == 1
    assert work_items[0].kind == 'system'
    assert work_items[0].owner == 'system'
    assert work_items[0].status == 'open'
    assert work_items[0].subject_ref == 'dependency:evidence.history'


def test_message_boundary_does_not_reclassify_external_task_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def reject_if_called(**kwargs: object) -> NoReturn:
        calls.append(dict(kwargs))
        raise AssertionError('ExternalTask recovery must not use generic tool policy.')

    monkeypatch.setattr(
        messages_service,
        'reduce_dependency_unavailable_recovery',
        reject_if_called,
    )

    messages_service._validate_unavailable_context_recovery(
        claim_id='clm_external_authority',
        claim_revision=5,
        tool_results=[
            {
                'tool': 'external_service.submit_request',
                'status': 'unavailable',
                'source_refs': ['external-task:ext_1'],
            }
        ],
    )

    assert calls == []


def test_message_boundary_accepts_high_impact_review_policy() -> None:
    messages_service._validate_professional_review_recovery(
        claim_id='clm_review',
        claim_revision=7,
        source_refs=['retrieval:pol_1', 'signal:sig_1'],
    )


def test_dependency_recovery_work_item_uses_owning_runtime_turn_id() -> None:
    from datetime import UTC, datetime

    from backend.domain.runtime import (
        AgentProposalRecord,
        ExecutionPlanRecord,
        RuntimeTurnRecords,
        TurnPlanRecord,
        TurnResultRecord,
        validate_runtime_turn_links,
    )

    now = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)

    recovery_items = messages_service._validate_unavailable_context_recovery(
        claim_id='clm_runtime_link',
        claim_revision=5,
        tool_results=[
            {
                'tool': 'evidence.history',
                'status': 'unavailable',
                'blocking': True,
                'source_refs': [],
            }
        ],
    )

    assert len(recovery_items) == 1
    assert recovery_items[0].turn_id.startswith('recovery_')

    plan = TurnPlanRecord.model_construct(
        turn_id='trn_runtime_link',
        claim_id='clm_runtime_link',
        session_id='ses_runtime_link',
        trigger_message_id='msg_runtime_link',
        model_profile_id='profile_runtime_link',
        runtime_directive='runtime.fail_safe',
        created_at=now,
    )

    proposal = AgentProposalRecord.model_construct(
        proposal_id='prp_runtime_link',
        turn_id='trn_runtime_link',
        claim_id='clm_runtime_link',
        session_id='ses_runtime_link',
        action_code='conversation.respond',
        runtime_directive='runtime.fail_safe',
        reason_codes=['DEPENDENCY_UNAVAILABLE'],
        customer_reason='Required capability is unavailable.',
        customer_response='The step cannot safely continue.',
        customer_next_step=cast(Any, None),
        proposal_source=AgentProposalSource.MODEL_GATEWAY,
        model_profile_id='profile_runtime_link',
        created_at=now,
    )

    execution = ExecutionPlanRecord.model_construct(
        execution_plan_id='exp_runtime_link',
        turn_id='trn_runtime_link',
        claim_id='clm_runtime_link',
        expected_revision=5,
        envelope_ids=[],
        approved_envelope_ids=[],
        rejected_envelope_ids=[],
        status='executed',
        created_at=now,
    )

    result = TurnResultRecord.model_construct(
        result_id='res_runtime_link',
        turn_id='trn_runtime_link',
        claim_id='clm_runtime_link',
        session_id='ses_runtime_link',
        trigger_message_id='msg_runtime_link',
        agent_message_id='amsg_runtime_link',
        execution_plan_id='exp_runtime_link',
        status='blocked',
        resulting_claim_revision=5,
        customer_response='The step cannot safely continue.',
        tool_result_refs=[],
        work_item_refs=[],
        created_at=now,
    )

    records = RuntimeTurnRecords.model_construct(
        turn_plan=plan,
        proposal=proposal,
        execution_plan=execution,
        action_envelopes=[],
        tool_results=[],
        result=result,
        work_items=[],
    )

    merged = messages_service._merge_dependency_recovery_work_items(
        records,
        recovery_items,
    )

    assert len(merged.work_items) == 1
    assert merged.work_items[0].turn_id == plan.turn_id
    assert merged.result.work_item_refs == [merged.work_items[0].work_item_id]

    validate_runtime_turn_links(
        merged,
        claim_id='clm_runtime_link',
        session_id='ses_runtime_link',
        trigger_message_id='msg_runtime_link',
        agent_message_id='amsg_runtime_link',
        expected_revision=5,
        resulting_revision=5,
    )
