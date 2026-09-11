from backend.domain.models import (
    HandoffPacket,
    HandoffPriority,
    HandoffRecord,
    HandoffStatus,
    HandoffTrigger,
    HandoffType,
    StaffActionRecord,
    StaffActionStatus,
)
from backend.domain.workbench_action_registry import (
    WORK_ITEM_TYPE_REGISTRY,
    WORKBENCH_ACTION_REGISTRY,
    WORKBENCH_ACTION_REGISTRY_VERSION,
    handoff_resolution_defaults,
    work_item_defaults,
)
from backend.services.support import now_utc


def test_action_registry_owns_every_projected_action_contract_dimension() -> None:
    assert WORKBENCH_ACTION_REGISTRY_VERSION == '2026-09-11.1'
    assert set(WORKBENCH_ACTION_REGISTRY) == {
        'claim.reopen',
        'conversation.send_claimant_message',
        'human.accept_handoff',
        'human.resolve_handoff',
        'ownership.decide_cowork',
        'ownership.decide_transfer',
        'ownership.invite_cowork',
        'ownership.request_cowork',
        'ownership.request_transfer',
        'ownership.requeue',
        'signal.record_decision',
        'work_item.create',
        'work_item.update',
    }
    for action_code, definition in WORKBENCH_ACTION_REGISTRY.items():
        assert definition.action_code == action_code
        assert definition.target_type
        assert definition.permission
        assert definition.confirmation_level
        assert definition.expected_effects
        assert definition.failure_codes
        assert {'action_code', 'target_ref', 'actor_id', 'resulting_revision'} <= set(
            definition.audit_requirements
        )


def test_registry_owns_ownership_inputs_and_conditional_completion_requirements() -> None:
    expected_ownership_fields = {
        'ownership.request_cowork': ['reason'],
        'ownership.invite_cowork': ['staff_id', 'reason'],
        'ownership.request_transfer': ['target_staff_id', 'reason'],
        'ownership.requeue': ['reason'],
        'ownership.decide_cowork': ['decision'],
        'ownership.decide_transfer': ['decision'],
    }
    for action_code, field_codes in expected_ownership_fields.items():
        inputs = WORKBENCH_ACTION_REGISTRY[action_code].inputs
        assert [item.field_code for item in inputs] == field_codes
        assert all(item.required for item in inputs)

    result_summary = next(
        item
        for item in WORKBENCH_ACTION_REGISTRY['work_item.update'].inputs
        if item.field_code == 'result.summary'
    )
    assert result_summary.required is False
    assert result_summary.required_when == ('status', 'completed')

    reopen = WORKBENCH_ACTION_REGISTRY['claim.reopen']
    assert [item.field_code for item in reopen.inputs] == ['reason']
    assert reopen.expected_effects == (
        'terminal_disposition.clear',
        'claim.revision.advance',
        'audit.append',
    )


def test_registered_target_variants_own_fixed_completion_effects() -> None:
    timestamp = now_utc()
    handoff = HandoffRecord(
        handoff_id='hnd_registry',
        claim_id='clm_registry',
        type=HandoffType.PROFESSIONAL_REVIEW,
        status=HandoffStatus.ACCEPTED,
        priority=HandoffPriority.STANDARD,
        queue='professional_review',
        trigger=HandoffTrigger.PROFESSIONAL_REVIEW_REQUIRED,
        reason_codes=['POLICY_AMBIGUITY'],
        reason='Review the applicable policy wording.',
        requested_action='Resolve the policy ambiguity.',
        applied_rule='fixture.registry',
        packet=HandoffPacket(
            form_revision=1,
            source_refs=['pol_registry'],
            promised_next_step='A claims professional will review the policy wording.',
        ),
        assigned_to='stf_demo',
        created_at=timestamp,
        accepted_at=timestamp,
    )
    handoff_defaults = handoff_resolution_defaults(handoff)
    assert handoff_defaults['result'] == {
        'outcome': 'professional_review_completed',
        'reason_codes': ['POLICY_SECTION_CONFIRMED'],
        'source_refs': ['pol_registry'],
    }
    assert handoff_defaults['state_changes'] == [
        {'path': 'claim_state.coverage', 'to': 'clear'},
        {'path': 'claim_state.workflow_state', 'to': 'ready_for_next'},
    ]

    work_item = StaffActionRecord(
        action_id='act_registry',
        claim_id='clm_registry',
        action_type='coverage_review',
        status=StaffActionStatus.OPEN,
        assigned_to='stf_demo',
        requested_outcome=WORK_ITEM_TYPE_REGISTRY['coverage_review'].requested_outcome,
        source_refs=['pol_registry'],
        created_at=timestamp,
    )
    item_defaults = work_item_defaults(work_item)
    assert item_defaults['result'] == {
        'outcome': 'professional_review_completed',
        'reason_codes': ['POLICY_SECTION_CONFIRMED'],
        'source_refs': ['pol_registry'],
    }
    assert item_defaults['customer_update'] == {
        'responsible_party': 'claimant',
        'related_refs': ['act_registry'],
    }
