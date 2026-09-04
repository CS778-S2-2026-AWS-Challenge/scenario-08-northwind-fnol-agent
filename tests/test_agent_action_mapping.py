from datetime import UTC, datetime

import pytest

from backend.domain.agent_action_commands import build_claim_context_command
from backend.domain.agent_action_registry import ActionActorRole, ExecutionAuthority
from backend.domain.audit import AuditActor, AuditEventType, AuditOutcome, AuditVisibility
from backend.domain.models import ActorType, WorkflowState
from backend.services.agent_action_execution import (
    ClaimContextExecutionResult,
    ClaimContextExecutionStatus,
)
from backend.services.agent_action_mapping import (
    build_claim_context_execution_audit_event,
    map_claim_context_execution_to_api,
)


def _command():
    return build_claim_context_command(
        'claim.apply_fact_patch',
        {
            'claim_id': 'clm_123',
            'fact_patches': [],
            'expected_revision': 4,
        },
        proposer_role=ActionActorRole.RUNTIME,
        approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
        authority_reference='published-rule:fact-patch-v1',
        workflow_state=WorkflowState.COLLECTING,
        expected_revision=4,
        idempotency_key='patch-4',
    )


def _actor() -> AuditActor:
    return AuditActor(
        actor_type=ActorType.SYSTEM,
        actor_id='agent-runtime',
        auth_source='internal-runtime',
    )


def test_applied_execution_reuses_revision_and_existing_action_completed_event() -> None:
    command = _command()
    result = ClaimContextExecutionResult(
        action_code=command.action_code,
        status=ClaimContextExecutionStatus.APPLIED,
        claim_id='clm_123',
        resulting_revision=5,
        reason_code='APPLIED',
    )

    api_mapping = map_claim_context_execution_to_api(result)
    assert api_mapping.error is None
    assert api_mapping.claim_id == 'clm_123'
    assert api_mapping.resulting_revision == 5

    event = build_claim_context_execution_audit_event(
        command,
        result,
        event_id='aud_action_patch_4',
        actor=_actor(),
        created_at=datetime(2026, 9, 4, 1, 0, tzinfo=UTC),
        correlation_id='req_patch_4',
    )
    assert event is not None
    assert event.event_type is AuditEventType.ACTION_COMPLETED
    assert event.outcome is AuditOutcome.SUCCEEDED
    assert event.subject.claim_id == 'clm_123'
    assert event.claim_revision == 5
    assert event.idempotency_key == 'patch-4'
    assert event.source_refs == ['published-rule:fact-patch-v1']
    assert event.visibility is AuditVisibility.AUDIT_ONLY


def test_revision_conflict_maps_to_existing_public_error_and_rejected_event() -> None:
    command = _command()
    result = ClaimContextExecutionResult(
        action_code=command.action_code,
        status=ClaimContextExecutionStatus.REJECTED,
        claim_id='clm_123',
        resulting_revision=6,
        reason_code='REVISION_CONFLICT',
        retryable=True,
        failure_policy=command.failure_policy,
    )

    api_mapping = map_claim_context_execution_to_api(result)
    assert api_mapping.error is not None
    assert api_mapping.error.status_code == 409
    assert api_mapping.error.code == 'REVISION_CONFLICT'
    assert api_mapping.error.retryable is True
    assert api_mapping.error.current_revision == 6

    event = build_claim_context_execution_audit_event(
        command,
        result,
        event_id='aud_action_patch_conflict',
        actor=_actor(),
        created_at=datetime(2026, 9, 4, 1, 1, tzinfo=UTC),
    )
    assert event is not None
    assert event.event_type is AuditEventType.ACTION_FAILED
    assert event.outcome is AuditOutcome.REJECTED
    assert event.claim_revision == 6


def test_dependency_failure_maps_to_retryable_dependency_error_without_fake_audit_revision() -> None:
    command = _command()
    result = ClaimContextExecutionResult(
        action_code=command.action_code,
        status=ClaimContextExecutionStatus.FAILED,
        claim_id='clm_123',
        resulting_revision=None,
        reason_code='DEPENDENCY_FAILURE',
        retryable=True,
        failure_policy=command.failure_policy,
    )

    api_mapping = map_claim_context_execution_to_api(result)
    assert api_mapping.error is not None
    assert api_mapping.error.status_code == 503
    assert api_mapping.error.code == 'DEPENDENCY_UNAVAILABLE'
    assert api_mapping.error.retryable is True

    assert (
        build_claim_context_execution_audit_event(
            command,
            result,
            event_id='aud_action_patch_dependency',
            actor=_actor(),
            created_at=datetime(2026, 9, 4, 1, 2, tzinfo=UTC),
        )
        is None
    )


def test_internal_execution_reason_does_not_become_a_public_error_code() -> None:
    result = ClaimContextExecutionResult(
        action_code='claim.apply_fact_patch',
        status=ClaimContextExecutionStatus.REJECTED,
        claim_id='clm_123',
        resulting_revision=4,
        reason_code='TOOL_NOT_ALLOWED',
    )

    api_mapping = map_claim_context_execution_to_api(result)
    assert api_mapping.error is not None
    assert api_mapping.error.status_code == 500
    assert api_mapping.error.code == 'INTERNAL_ERROR'
    assert 'TOOL_NOT_ALLOWED' not in api_mapping.error.message


def test_applied_result_without_persisted_identity_fails_closed() -> None:
    result = ClaimContextExecutionResult(
        action_code='claim.apply_fact_patch',
        status=ClaimContextExecutionStatus.APPLIED,
        claim_id='clm_123',
        resulting_revision=None,
        reason_code='APPLIED',
    )

    api_mapping = map_claim_context_execution_to_api(result)
    assert api_mapping.error is not None
    assert api_mapping.error.status_code == 500
    assert api_mapping.error.code == 'INTERNAL_ERROR'


def test_audit_mapping_rejects_action_or_claim_scope_mismatch() -> None:
    command = _command()
    timestamp = datetime(2026, 9, 4, 1, 3, tzinfo=UTC)

    with pytest.raises(ValueError, match='action does not match'):
        build_claim_context_execution_audit_event(
            command,
            ClaimContextExecutionResult(
                action_code='claim.correct_fact',
                status=ClaimContextExecutionStatus.APPLIED,
                claim_id='clm_123',
                resulting_revision=5,
                reason_code='APPLIED',
            ),
            event_id='aud_action_mismatch',
            actor=_actor(),
            created_at=timestamp,
        )

    with pytest.raises(ValueError, match='Claim scope'):
        build_claim_context_execution_audit_event(
            command,
            ClaimContextExecutionResult(
                action_code=command.action_code,
                status=ClaimContextExecutionStatus.APPLIED,
                claim_id='clm_other',
                resulting_revision=5,
                reason_code='APPLIED',
            ),
            event_id='aud_claim_mismatch',
            actor=_actor(),
            created_at=timestamp,
        )
