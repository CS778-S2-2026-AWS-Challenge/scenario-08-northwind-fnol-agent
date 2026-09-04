"""Map approved Claim Context execution outcomes to existing backend contracts."""

from datetime import datetime

from backend.core.errors import ApiError
from backend.domain.agent_action_commands import ClaimContextCommand
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.services.agent_action_execution import (
    ClaimContextExecutionResult,
    ClaimContextExecutionStatus,
)

_API_ERRORS: dict[str, tuple[int, str, str, bool]] = {
    'REVISION_CONFLICT': (
        409,
        'REVISION_CONFLICT',
        'The claim changed before the approved action could be applied.',
        True,
    ),
    'IDEMPOTENCY_CONFLICT': (
        409,
        'IDEMPOTENCY_CONFLICT',
        'The approved action conflicts with an earlier request.',
        False,
    ),
    'CLAIM_NOT_FOUND': (404, 'RESOURCE_NOT_FOUND', 'The claim was not found.', False),
    'RESOURCE_NOT_FOUND': (404, 'RESOURCE_NOT_FOUND', 'The claim resource was not found.', False),
    'WORKFLOW_STATE_CHANGED': (
        409,
        'INVALID_STATE_TRANSITION',
        'The claim state changed before the approved action could be applied.',
        False,
    ),
    'INVALID_STATE_TRANSITION': (
        409,
        'INVALID_STATE_TRANSITION',
        'The approved action is not valid for the current claim state.',
        False,
    ),
    'ACCESS_DENIED': (403, 'ACCESS_DENIED', 'The approved action is not permitted.', False),
    'VALIDATION_ERROR': (
        422,
        'VALIDATION_ERROR',
        'The approved action did not match the required contract.',
        False,
    ),
    'DEPENDENCY_FAILURE': (
        503,
        'DEPENDENCY_UNAVAILABLE',
        'A required service is temporarily unavailable. The claim was not reported as completed.',
        True,
    ),
    'DEPENDENCY_UNAVAILABLE': (
        503,
        'DEPENDENCY_UNAVAILABLE',
        'A required service is temporarily unavailable. The claim was not reported as completed.',
        True,
    ),
    'DEPENDENCY_FAILED': (
        502,
        'DEPENDENCY_FAILED',
        'A required service could not complete the approved action.',
        False,
    ),
}


def map_claim_context_execution_to_api(result: ClaimContextExecutionResult) -> ApiError | None:
    """Map one execution result to the existing public API error vocabulary.

    Args:
        result: Provider-neutral outcome returned by the approved command execution gate.

    Returns:
        ``None`` for a verifiable applied result, otherwise a bounded existing ``ApiError``.

    Raises:
        TypeError: The supplied result has the wrong runtime type.
    """

    if not isinstance(result, ClaimContextExecutionResult):
        raise TypeError('result must be a ClaimContextExecutionResult.')
    if result.status is ClaimContextExecutionStatus.APPLIED:
        if (
            result.claim_id is not None
            and result.claim_id.strip()
            and result.resulting_revision is not None
            and result.resulting_revision >= 1
        ):
            return None
        return ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The approved action did not produce a verifiable persisted result.',
        )

    mapped = _API_ERRORS.get(result.reason_code)
    if mapped is None:
        return ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The approved action could not be mapped to a completed state.',
            retryable=result.retryable,
        )
    status_code, code, message, retryable = mapped
    return ApiError(
        status_code=status_code,
        code=code,
        message=message,
        retryable=retryable or result.retryable,
        current_revision=(
            result.resulting_revision if result.reason_code == 'REVISION_CONFLICT' else None
        ),
    )


def build_claim_context_execution_audit_event(
    command: ClaimContextCommand,
    result: ClaimContextExecutionResult,
    *,
    event_id: str,
    actor: AuditActor,
    created_at: datetime,
    correlation_id: str | None = None,
) -> AuditEventEnvelope | None:
    """Map a revision-backed execution result to the existing audit envelope.

    Args:
        command: Immutable approved command that produced the result.
        result: Provider-neutral execution outcome.
        event_id: Stable audit identity supplied by the owning action boundary.
        actor: Authenticated identity responsible for execution.
        created_at: Server-recorded event timestamp.
        correlation_id: Optional request or operation correlation identity.

    Returns:
        An audit event when an authoritative Claim revision is known, otherwise ``None``.

    Raises:
        TypeError: A command, result, actor, or timestamp has the wrong runtime type.
        ValueError: The result does not belong to the supplied command or Claim scope.
    """

    if not isinstance(command, ClaimContextCommand):
        raise TypeError('command must be a ClaimContextCommand.')
    if not isinstance(result, ClaimContextExecutionResult):
        raise TypeError('result must be a ClaimContextExecutionResult.')
    if not isinstance(actor, AuditActor):
        raise TypeError('actor must be an AuditActor.')
    if not isinstance(created_at, datetime):
        raise TypeError('created_at must be a datetime.')
    if command.action_code != result.action_code:
        raise ValueError('Execution result action does not match the approved command.')
    if result.claim_id is not None and not result.claim_id.strip():
        return None
    if result.resulting_revision is None or result.resulting_revision < 1:
        return None
    if result.status is ClaimContextExecutionStatus.APPLIED and result.claim_id is None:
        return None
    if command.claim_id is not None and result.claim_id not in {None, command.claim_id}:
        raise ValueError('Execution result Claim scope does not match the approved command.')

    claim_id = result.claim_id if result.claim_id is not None else command.claim_id
    if claim_id is None or not claim_id.strip():
        return None
    event_type = (
        AuditEventType.ACTION_COMPLETED
        if result.status is ClaimContextExecutionStatus.APPLIED
        else AuditEventType.ACTION_FAILED
    )
    outcome = {
        ClaimContextExecutionStatus.APPLIED: AuditOutcome.SUCCEEDED,
        ClaimContextExecutionStatus.REJECTED: AuditOutcome.REJECTED,
        ClaimContextExecutionStatus.FAILED: AuditOutcome.FAILED,
    }[result.status]
    return AuditEventEnvelope(
        event_id=event_id,
        event_type=event_type,
        outcome=outcome,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim_id,
            claim_id=claim_id,
        ),
        actor=actor,
        reason=f'{result.action_code} execution {result.status.value}: {result.reason_code}.',
        source_refs=[command.authority_reference],
        visibility=AuditVisibility.AUDIT_ONLY,
        correlation_id=correlation_id,
        idempotency_key=command.idempotency_key,
        claim_revision=result.resulting_revision,
        created_at=created_at,
    )
