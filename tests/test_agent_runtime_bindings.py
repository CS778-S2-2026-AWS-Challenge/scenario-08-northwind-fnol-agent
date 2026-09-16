from typing import cast

import pytest

from backend.domain.agent_action_commands import build_claim_context_command
from backend.domain.agent_action_registry import ActionActorRole, ExecutionAuthority
from backend.domain.agent_tool_registry import tool_contract
from backend.domain.model_gateway import ModelRuntimeProposal
from backend.domain.models import CustomerNextStep, WorkflowState
from backend.repositories.protocols import ClaimRepository
from backend.services.agent_action_execution import (
    ActionBindingStatus,
    ClaimantRuntimeActionDispatcher,
    ClaimContextExecutionStatus,
    ClaimContextHandlerBinding,
    ClaimContextHandlerOutcome,
    action_binding_table,
)


def _binding_handler(_command: object) -> ClaimContextHandlerOutcome:
    return ClaimContextHandlerOutcome(claim_id='claim-test', resulting_revision=1)


def test_binding_table_distinguishes_registered_actions_from_runtime_handlers() -> None:
    table = action_binding_table()
    assert len(table) >= 40
    assert all(item.status is ActionBindingStatus.UNAVAILABLE for item in table)

    executable = action_binding_table(
        {
            'claim.apply_fact_patch': ClaimContextHandlerBinding(
                tool_name='claim_store.compare_and_set',
                handler=_binding_handler,
            )
        }
    )
    row = next(item for item in executable if item.action_code == 'claim.apply_fact_patch')
    assert row.status is ActionBindingStatus.RUNTIME_EXECUTABLE
    assert row.tool_name == 'claim_store.compare_and_set'
    assert row.handler_name == '_binding_handler'


def test_binding_table_rejects_unknown_or_overlapping_status_labels() -> None:
    with pytest.raises(ValueError, match='Unknown action bindings'):
        action_binding_table(
            {'claim.not_registered': ClaimContextHandlerBinding(None, _binding_handler)}
        )
    with pytest.raises(ValueError, match='both test-only and standalone API'):
        action_binding_table(
            test_only_actions={'conversation.answer'},
            standalone_api_actions={'conversation.answer'},
        )


def test_live_claimant_dispatcher_publishes_only_real_production_bindings() -> None:
    rows = ClaimantRuntimeActionDispatcher().binding_table()
    executable = {
        row.action_code: row.tool_name
        for row in rows
        if row.status is ActionBindingStatus.RUNTIME_EXECUTABLE
    }

    assert executable == {
        'claim.apply_fact_patch': 'claim_store.compare_and_set',
        'claim.create': 'claims_service.create_claim',
        'claim.prepare_creation': None,
        'claim.register_evidence': 'claim_store.compare_and_set',
        'human.create_handoff': 'handoff_store.create',
    }
    assert next(row for row in rows if row.action_code == 'external.submit_request').status is (
        ActionBindingStatus.UNAVAILABLE
    )


def test_live_claimant_dispatcher_rejects_invalid_or_unbound_actions() -> None:
    with pytest.raises(ValueError, match='Unknown live claimant action bindings'):
        ClaimantRuntimeActionDispatcher({'claim.not_registered': None})
    with pytest.raises(ValueError, match='does not match claim.prepare_creation tool contract'):
        ClaimantRuntimeActionDispatcher({'claim.prepare_creation': 'claim_store.compare_and_set'})

    command = build_claim_context_command(
        'claim.prepare_creation',
        {'claim_id': 'clm_unbound', 'expected_revision': 1},
        proposer_role=ActionActorRole.RUNTIME,
        approved_authority=ExecutionAuthority.RUNTIME_VALIDATION,
        authority_reference='test:unbound-live-action',
        workflow_state=WorkflowState.READY_FOR_NEXT,
        expected_revision=1,
    )
    result = ClaimantRuntimeActionDispatcher({}).execute(
        cast(ClaimRepository, object()),
        command,
        _binding_handler,
    )

    assert result.status is ClaimContextExecutionStatus.REJECTED
    assert result.reason_code == 'UNSUPPORTED_ACTION'


def test_tool_contract_accepts_canonical_and_compatibility_names() -> None:
    assert tool_contract('knowledge_search').name == 'knowledge.search'
    assert tool_contract('knowledge.search').name == 'knowledge.search'
    assert tool_contract('external_service.submit_request').name == (
        'external_service.submit_request'
    )
    assert tool_contract('external_service.submit_request').read_only is False
    assert tool_contract('external_service.track_request').read_only is True


def test_runtime_proposal_accepts_all_registered_runtime_directives() -> None:
    next_step = CustomerNextStep(
        status='continue_current_report',
        summary='Continue the report.',
        responsible_party='claimant',
        required_items=[],
    )
    pairs = (
        ('conversation.answer', 'runtime.continue'),
        ('conversation.answer', 'runtime.wait_for_user'),
        ('human.create_handoff', 'runtime.pause_for_review'),
        ('claim.prepare_creation', 'runtime.continue'),
        ('claim.create', 'runtime.continue'),
        ('claim.create', 'runtime.wait_for_external'),
        ('runtime.stop_no_claim', 'runtime.stop_no_claim'),
        ('runtime.fail_safe', 'runtime.fail_safe'),
    )
    for action_code, directive in pairs:
        proposal = ModelRuntimeProposal(
            action_code=action_code,
            runtime_action_code=directive,
            reason_codes=['TEST'],
            customer_reason='A bounded reason.',
            customer_response='A bounded response.',
            customer_next_step=next_step,
        )
        assert proposal.runtime_action_code == directive


def test_runtime_proposal_rejects_protected_or_mismatched_directives() -> None:
    next_step = CustomerNextStep(
        status='continue_current_report',
        summary='Continue the report.',
        responsible_party='claimant',
        required_items=[],
    )
    with pytest.raises(ValueError, match='published-rule-only'):
        ModelRuntimeProposal(
            action_code='conversation.answer',
            runtime_action_code='runtime.interrupt_urgent',
            reason_codes=['TEST'],
            customer_reason='A bounded reason.',
            customer_response='A bounded response.',
            customer_next_step=next_step,
        )
    with pytest.raises(ValueError, match='not valid'):
        ModelRuntimeProposal(
            action_code='conversation.answer',
            runtime_action_code='runtime.pause_for_review',
            reason_codes=['TEST'],
            customer_reason='A bounded reason.',
            customer_response='A bounded response.',
            customer_next_step=next_step,
        )
