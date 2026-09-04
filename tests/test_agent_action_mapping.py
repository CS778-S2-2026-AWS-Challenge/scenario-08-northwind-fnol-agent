from datetime import UTC, datetime

import pytest

from backend.domain.agent_action_commands import ClaimContextCommand, build_claim_context_command
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


def _command() -> ClaimContextCommand:
    return build_claim_context_command(
        'claim.apply_fact_patch',
        {'claim_id': 'clm_123', 'fact_patches': [], 'expected_revision': 4},
        proposer_role=ActionActorRole.RUNTIME,
        approved_authority=ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE,
        authority_reference='published-rule:fact-patch-v1',
        workflow_state=WorkflowState.COLLECTING,
        expected_revision=4,
        idempotency_key='patch-4',
    )


def _result(
    status: ClaimContextExecutionStatus,
    reason: str,
    *,
    claim_id: str | None = 'clm_123',
    revision: int | None = 5,
    retryable: bool = False,
) -> ClaimContextExecutionResult:
    return ClaimContextExecutionResult(
        action_code='claim.apply_fact_patch',
        status=status,
        claim_id=claim_id,
        resulting_revision=revision,
        reason_code=reason,
        retryable=retryable,
        failure_policy=None if status is ClaimContextExecutionStatus.APPLIED else 'fail closed',
    )


def _actor() -> AuditActor:
    return AuditActor(
        actor_type=ActorType.SYSTEM,
        actor_id='agent-runtime',
        auth_source='internal-runtime',
    )


def test_applied_execution_reuses_revision_and_existing_audit_vocabulary() -> None:
    command = _command()
    result = _result(ClaimContextExecutionStatus.APPLIED, 'APPLIED')

    assert map_claim_context_execution_to_api(result) is None
    event = build_claim_context_execution_audit_event(
        command,
        result,
        event_id='aud_action_patch_4',
        actor=_actor(),
        created_at=datetime(2026, 9, 4, 1, 0, tzinfo=UTC),
        correlation_id='req_patch_4',
    )

    assert event is not None
    assert (event.event_type, event.outcome) == (
        AuditEventType.ACTION_COMPLETED,
        AuditOutcome.SUCCEEDED,
    )
    assert event.claim_revision == 5
    assert event.idempotency_key == 'patch-4'
    assert event.source_refs == ['published-rule:fact-patch-v1']
    assert event.visibility is AuditVisibility.AUDIT_ONLY


@pytest.mark.parametrize(
    ('claim_id', 'revision'),
    [
        ('', 5),
        ('   ', 5),
        (None, 5),
        ('clm_123', 0),
        ('clm_123', -1),
    ],
)
def test_applied_mapping_fails_closed_for_invalid_persisted_identity(
    claim_id: str | None,
    revision: int,
) -> None:
    command = _command()
    result = _result(
        ClaimContextExecutionStatus.APPLIED,
        'APPLIED',
        claim_id=claim_id,
        revision=revision,
    )

    error = map_claim_context_execution_to_api(result)
    assert error is not None
    assert (error.status_code, error.code) == (500, 'INTERNAL_ERROR')

    assert (
        build_claim_context_execution_audit_event(
            command,
            result,
            event_id='aud_invalid_execution_identity',
            actor=_actor(),
            created_at=datetime(2026, 9, 4, 1, 4, tzinfo=UTC),
        )
        is None
    )


@pytest.mark.parametrize(
    ('reason', 'status_code', 'code', 'retryable'),
    [
        ('REVISION_CONFLICT', 409, 'REVISION_CONFLICT', True),
        ('IDEMPOTENCY_CONFLICT', 409, 'IDEMPOTENCY_CONFLICT', False),
        ('CLAIM_NOT_FOUND', 404, 'RESOURCE_NOT_FOUND', False),
        ('WORKFLOW_STATE_CHANGED', 409, 'INVALID_STATE_TRANSITION', False),
        ('DEPENDENCY_FAILURE', 503, 'DEPENDENCY_UNAVAILABLE', True),
    ],
)
def test_execution_reuses_existing_public_error_vocabulary(
    reason: str,
    status_code: int,
    code: str,
    retryable: bool,
) -> None:
    status = (
        ClaimContextExecutionStatus.FAILED
        if reason == 'DEPENDENCY_FAILURE'
        else ClaimContextExecutionStatus.REJECTED
    )
    error = map_claim_context_execution_to_api(
        _result(status, reason, revision=6, retryable=retryable)
    )

    assert error is not None
    assert (error.status_code, error.code, error.retryable) == (status_code, code, retryable)
    assert error.current_revision == (6 if reason == 'REVISION_CONFLICT' else None)


def test_internal_reason_stays_internal_and_missing_revision_does_not_create_audit_event() -> None:
    command = _command()
    internal = _result(ClaimContextExecutionStatus.REJECTED, 'TOOL_NOT_ALLOWED', revision=4)
    error = map_claim_context_execution_to_api(internal)
    assert error is not None
    assert (error.status_code, error.code) == (500, 'INTERNAL_ERROR')
    assert 'TOOL_NOT_ALLOWED' not in error.message

    dependency = _result(
        ClaimContextExecutionStatus.FAILED,
        'DEPENDENCY_FAILURE',
        revision=None,
        retryable=True,
    )
    assert (
        build_claim_context_execution_audit_event(
            command,
            dependency,
            event_id='aud_no_revision',
            actor=_actor(),
            created_at=datetime(2026, 9, 4, 1, 1, tzinfo=UTC),
        )
        is None
    )


def test_revision_conflict_uses_rejected_action_event() -> None:
    event = build_claim_context_execution_audit_event(
        _command(),
        _result(ClaimContextExecutionStatus.REJECTED, 'REVISION_CONFLICT', revision=6),
        event_id='aud_conflict',
        actor=_actor(),
        created_at=datetime(2026, 9, 4, 1, 2, tzinfo=UTC),
    )
    assert event is not None
    assert (event.event_type, event.outcome, event.claim_revision) == (
        AuditEventType.ACTION_FAILED,
        AuditOutcome.REJECTED,
        6,
    )


def test_mapping_fails_closed_for_unverifiable_or_mismatched_results() -> None:
    missing_revision = _result(ClaimContextExecutionStatus.APPLIED, 'APPLIED', revision=None)
    error = map_claim_context_execution_to_api(missing_revision)
    assert error is not None and error.code == 'INTERNAL_ERROR'

    with pytest.raises(ValueError, match='action does not match'):
        build_claim_context_execution_audit_event(
            _command(),
            ClaimContextExecutionResult(
                action_code='claim.correct_fact',
                status=ClaimContextExecutionStatus.APPLIED,
                claim_id='clm_123',
                resulting_revision=5,
                reason_code='APPLIED',
            ),
            event_id='aud_mismatch',
            actor=_actor(),
            created_at=datetime(2026, 9, 4, 1, 3, tzinfo=UTC),
        )
