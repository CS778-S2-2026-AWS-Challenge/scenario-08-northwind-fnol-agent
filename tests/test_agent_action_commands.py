import pytest

from backend.domain.agent_action_commands import (
    AgentActionCommandError,
    ClaimContextCommand,
    UnknownAgentActionError,
    build_claim_context_command,
)
from backend.domain.agent_action_registry import (
    ActionActorRole,
    ActionIdempotencyPolicy,
    ActionStateEffect,
    ActionVisibility,
    ExecutionAuthority,
)
from backend.domain.models import WorkflowState


def test_approved_fact_patch_becomes_revision_safe_idempotent_command() -> None:
    command = build_claim_context_command(
        'claim.apply_fact_patch',
        {
            'claim_id': 'clm_123',
            'fact_patches': [{'field_code': 'incident.location', 'value': 'Auckland'}],
            'expected_revision': 7,
        },
        proposer_role=ActionActorRole.RUNTIME,
        approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
        authority_reference='published-rule:fact-patch-v1',
        workflow_state=WorkflowState.COLLECTING,
        idempotency_key='action-turn-123',
    )

    assert command.claim_id == 'clm_123'
    assert command.expected_revision == 7
    assert command.idempotency_key == 'action-turn-123'
    assert command.idempotency_policy is ActionIdempotencyPolicy.REQUIRED
    assert command.state_effect is ActionStateEffect.CLAIM_MUTATION
    assert command.permitted_tools == ('claim_store.compare_and_set',)
    assert 'preserve Claim State' in command.failure_policy


def test_command_payload_is_deeply_immutable_snapshot() -> None:
    location: dict[str, object] = {'region': 'Auckland'}
    fact_patch: dict[str, object] = {
        'field_code': 'incident.location',
        'value': location,
    }
    fact_patches: list[object] = [fact_patch]
    payload: dict[str, object] = {
        'claim_id': 'clm_123',
        'fact_patches': fact_patches,
        'expected_revision': 7,
    }

    command = build_claim_context_command(
        'claim.apply_fact_patch',
        payload,
        proposer_role=ActionActorRole.RUNTIME,
        approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
        authority_reference='published-rule:fact-patch-v1',
        workflow_state=WorkflowState.COLLECTING,
        idempotency_key='action-turn-immutable',
    )

    location['region'] = 'Wellington'
    fact_patches.append({'field_code': 'incident.description', 'value': 'Changed later'})

    assert command.payload['fact_patches'] == (
        {
            'field_code': 'incident.location',
            'value': {'region': 'Auckland'},
        },
    )


def test_open_draft_does_not_invent_a_prior_claim_revision() -> None:
    command = build_claim_context_command(
        'claim.open_draft',
        {
            'claimant_id': 'customer-1',
            'claim_intent': {'incident_type': 'motor'},
            'idempotency_key': 'open-draft-1',
        },
        proposer_role=ActionActorRole.MODEL,
        approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
        authority_reference='published-rule:credible-claim-intent-v1',
        workflow_state=WorkflowState.COLLECTING,
    )

    assert command.claim_id is None
    assert command.expected_revision is None
    assert command.idempotency_key == 'open-draft-1'


def test_unknown_and_non_context_actions_fail_closed() -> None:
    with pytest.raises(UnknownAgentActionError, match='Unknown Agent action'):
        build_claim_context_command(
            'claim.invent_authority',
            {'claim_id': 'clm_123'},
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.RUNTIME_VALIDATION,
            authority_reference='runtime-validation:turn-1',
            workflow_state=WorkflowState.COLLECTING,
        )

    with pytest.raises(AgentActionCommandError, match='not a Claim Context command'):
        build_claim_context_command(
            'conversation.ask',
            {'field_code': 'incident.location', 'question': 'Where did this happen?'},
            proposer_role=ActionActorRole.MODEL,
            approved_authority=ExecutionAuthority.RUNTIME_VALIDATION,
            authority_reference='runtime-validation:turn-1',
            workflow_state=WorkflowState.COLLECTING,
        )

    with pytest.raises(AgentActionCommandError, match='not a Claim Context command'):
        build_claim_context_command(
            'external.discover_capability',
            {'claim_id': 'clm_123', 'request_type': 'assessor'},
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.RUNTIME_VALIDATION,
            authority_reference='runtime-validation:turn-1',
            workflow_state=WorkflowState.COLLECTING,
        )


def test_role_authority_and_closed_input_schema_are_enforced() -> None:
    payload: dict[str, object] = {'claim_id': 'clm_123', 'expected_revision': 2}
    with pytest.raises(AgentActionCommandError, match='may not propose'):
        build_claim_context_command(
            'claim.save_progress',
            payload,
            proposer_role=ActionActorRole.CLAIMANT,
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference='claimant:customer-1',
            workflow_state=WorkflowState.COLLECTING,
            idempotency_key='save-1',
        )
    with pytest.raises(AgentActionCommandError, match='requires'):
        build_claim_context_command(
            'claim.save_progress',
            payload,
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.RUNTIME_VALIDATION,
            authority_reference='runtime-validation:turn-1',
            workflow_state=WorkflowState.COLLECTING,
            idempotency_key='save-1',
        )
    with pytest.raises(AgentActionCommandError, match='Unexpected action input'):
        build_claim_context_command(
            'claim.apply_fact_patch',
            {'claim_id': 'clm_123', 'fact_patches': [], 'expected_revision': 2, 'force': True},
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference='published-rule:fact-patch-v1',
            workflow_state=WorkflowState.COLLECTING,
            idempotency_key='patch-2',
        )


def test_mutations_require_matching_revision_and_idempotency_metadata() -> None:
    payload: dict[str, object] = {
        'claim_id': 'clm_123',
        'reason_codes': ['POLICY_REVIEW_REQUIRED'],
    }
    with pytest.raises(AgentActionCommandError, match='expected_revision'):
        build_claim_context_command(
            'human.request_professional_review',
            payload,
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.RUNTIME_VALIDATION,
            authority_reference='runtime-validation:turn-9',
            workflow_state=WorkflowState.PROFESSIONAL_REVIEW,
            idempotency_key='review-9',
        )
    with pytest.raises(AgentActionCommandError, match='idempotency_key'):
        build_claim_context_command(
            'human.request_professional_review',
            payload,
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.RUNTIME_VALIDATION,
            authority_reference='runtime-validation:turn-9',
            workflow_state=WorkflowState.PROFESSIONAL_REVIEW,
            expected_revision=9,
        )
    with pytest.raises(AgentActionCommandError, match='does not match'):
        build_claim_context_command(
            'claim.apply_fact_patch',
            {'claim_id': 'clm_123', 'fact_patches': [], 'expected_revision': 5},
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference='published-rule:fact-patch-v1',
            workflow_state=WorkflowState.COLLECTING,
            expected_revision=6,
            idempotency_key='patch-5',
        )


def test_fact_patch_execution_metadata_fails_closed() -> None:
    def build(
        payload: dict[str, object],
        authority: str = 'rule',
        key: str = 'patch',
    ) -> ClaimContextCommand:
        return build_claim_context_command(
            'claim.apply_fact_patch',
            payload,
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference=authority,
            workflow_state=WorkflowState.COLLECTING,
            idempotency_key=key,
        )

    valid: dict[str, object] = {
        'claim_id': 'clm_123',
        'fact_patches': [],
        'expected_revision': 1,
    }
    with pytest.raises(AgentActionCommandError, match='Missing action input'):
        build({})
    with pytest.raises(AgentActionCommandError, match='must be integer'):
        build({**valid, 'expected_revision': True})
    with pytest.raises(AgentActionCommandError, match='must not be negative'):
        build({**valid, 'expected_revision': -1})
    with pytest.raises(AgentActionCommandError, match='authority reference'):
        build(valid, authority=' ')
    with pytest.raises(AgentActionCommandError, match='idempotency_key must not be blank'):
        build(valid, key=' ')


def test_handoff_command_preserves_revision_and_visibility_contract() -> None:
    command = build_claim_context_command(
        'human.create_handoff',
        {
            'claim_id': 'clm_123',
            'reason_codes': ['CLAIMANT_REQUESTED_SUPPORT'],
            'handoff_packet': {'summary': 'Claimant asked for staff support.'},
            'expected_revision': 8,
        },
        proposer_role=ActionActorRole.RUNTIME,
        approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
        authority_reference='claimant-request:turn-8',
        workflow_state=WorkflowState.COLLECTING,
        idempotency_key='handoff-8',
    )

    assert command.state_effect is ActionStateEffect.HANDOFF
    assert command.expected_revision == 8
    assert command.permitted_tools == ('handoff_store.create',)
    assert command.visibility == (ActionVisibility.CLAIMANT, ActionVisibility.STAFF)


def test_lifecycle_and_idempotency_payload_metadata_fail_closed() -> None:
    with pytest.raises(AgentActionCommandError, match='not allowed'):
        build_claim_context_command(
            'claim.apply_fact_patch',
            {'claim_id': 'clm_123', 'fact_patches': [], 'expected_revision': 2},
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference='published-rule:fact-patch-v1',
            workflow_state=WorkflowState.CREATED,
            idempotency_key='patch-created',
        )

    with pytest.raises(AgentActionCommandError, match='does not match'):
        build_claim_context_command(
            'claim.open_draft',
            {
                'claimant_id': 'customer-1',
                'claim_intent': {'incident_type': 'motor'},
                'idempotency_key': 'payload-key',
            },
            proposer_role=ActionActorRole.MODEL,
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference='published-rule:credible-claim-intent-v1',
            workflow_state=WorkflowState.COLLECTING,
            idempotency_key='metadata-key',
        )


def test_non_string_action_code_fails_closed() -> None:
    with pytest.raises(UnknownAgentActionError, match='Action code must be a string'):
        build_claim_context_command(
            ['claim.apply_fact_patch'],  # type: ignore[arg-type]
            {
                'claim_id': 'clm_123',
                'fact_patches': [],
                'expected_revision': 2,
            },
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference='published-rule:fact-patch-v1',
            workflow_state=WorkflowState.COLLECTING,
            idempotency_key='patch-invalid-action',
        )


def test_non_mapping_payload_fails_closed() -> None:
    with pytest.raises(AgentActionCommandError, match='Action payload must be a mapping'):
        build_claim_context_command(
            'claim.apply_fact_patch',
            ['claim_id', 'fact_patches', 'expected_revision'],  # type: ignore[arg-type]
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference='published-rule:fact-patch-v1',
            workflow_state=WorkflowState.COLLECTING,
            expected_revision=2,
            idempotency_key='patch-invalid-payload',
        )


def test_malformed_runtime_boundary_types_fail_closed() -> None:
    payload: dict[str, object] = {
        'claim_id': 'clm_123',
        'fact_patches': [],
        'expected_revision': 2,
    }

    with pytest.raises(
        AgentActionCommandError,
        match='proposer_role must be an ActionActorRole',
    ):
        build_claim_context_command(
            'claim.apply_fact_patch',
            payload,
            proposer_role='runtime',  # type: ignore[arg-type]
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference='published-rule:fact-patch-v1',
            workflow_state=WorkflowState.COLLECTING,
            idempotency_key='patch-invalid-role',
        )

    with pytest.raises(
        AgentActionCommandError,
        match='authority_reference must be a string',
    ):
        build_claim_context_command(
            'claim.apply_fact_patch',
            payload,
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference=None,  # type: ignore[arg-type]
            workflow_state=WorkflowState.COLLECTING,
            idempotency_key='patch-invalid-authority-reference',
        )

    with pytest.raises(
        AgentActionCommandError,
        match='workflow_state must be a WorkflowState',
    ):
        build_claim_context_command(
            'claim.apply_fact_patch',
            payload,
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference='published-rule:fact-patch-v1',
            workflow_state='collecting',  # type: ignore[arg-type]
            idempotency_key='patch-invalid-state',
        )

    with pytest.raises(
        AgentActionCommandError,
        match='approved_authority must be an ExecutionAuthority',
    ):
        build_claim_context_command(
            'claim.apply_fact_patch',
            payload,
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority='claimant_staff_or_published_rule',  # type: ignore[arg-type]
            authority_reference='published-rule:fact-patch-v1',
            workflow_state=WorkflowState.COLLECTING,
            idempotency_key='patch-invalid-authority',
        )

    with pytest.raises(
        AgentActionCommandError,
        match='expected_revision must be an integer',
    ):
        build_claim_context_command(
            'claim.apply_fact_patch',
            payload,
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference='published-rule:fact-patch-v1',
            workflow_state=WorkflowState.COLLECTING,
            expected_revision='2',  # type: ignore[arg-type]
            idempotency_key='patch-invalid-revision',
        )

    with pytest.raises(
        AgentActionCommandError,
        match='idempotency_key must be a string',
    ):
        build_claim_context_command(
            'claim.apply_fact_patch',
            payload,
            proposer_role=ActionActorRole.RUNTIME,
            approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
            authority_reference='published-rule:fact-patch-v1',
            workflow_state=WorkflowState.COLLECTING,
            idempotency_key=123,  # type: ignore[arg-type]
        )
