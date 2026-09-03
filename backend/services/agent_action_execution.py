"""Execute approved Claim Context commands through explicit backend handlers."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from backend.core.errors import ApiError
from backend.domain.agent_action_commands import ClaimContextCommand
from backend.domain.agent_action_registry import ActionStateEffect
from backend.repositories.protocols import ClaimRepository, IdempotencyConflict, RevisionConflict


class ClaimContextExecutionStatus(str, Enum):
    """Internal outcome for one approved Claim Context command."""

    APPLIED = 'applied'
    REJECTED = 'rejected'
    FAILED = 'failed'


@dataclass(frozen=True, slots=True)
class ClaimContextHandlerOutcome:
    """Persisted state identity returned by an explicit command handler."""

    claim_id: str
    resulting_revision: int


ClaimContextCommandHandler = Callable[[ClaimContextCommand], ClaimContextHandlerOutcome]


@dataclass(frozen=True, slots=True)
class ClaimContextHandlerBinding:
    """Bind one approved action to the exact internal tool used to execute it."""

    tool_name: str
    handler: ClaimContextCommandHandler


@dataclass(frozen=True, slots=True)
class ClaimContextExecutionResult:
    """Provider-neutral internal result for the bounded command execution gate."""

    action_code: str
    status: ClaimContextExecutionStatus
    claim_id: str | None
    resulting_revision: int | None
    reason_code: str
    retryable: bool = False
    failure_policy: str | None = None


def _result(
    command: ClaimContextCommand,
    *,
    status: ClaimContextExecutionStatus,
    reason_code: str,
    claim_id: str | None = None,
    resulting_revision: int | None = None,
    retryable: bool = False,
) -> ClaimContextExecutionResult:
    return ClaimContextExecutionResult(
        action_code=command.action_code,
        status=status,
        claim_id=claim_id if claim_id is not None else command.claim_id,
        resulting_revision=resulting_revision,
        reason_code=reason_code,
        retryable=retryable,
        failure_policy=(
            None if status is ClaimContextExecutionStatus.APPLIED else command.failure_policy
        ),
    )


def execute_claim_context_command(
    repository: ClaimRepository,
    command: ClaimContextCommand,
    handlers: Mapping[str, ClaimContextHandlerBinding],
) -> ClaimContextExecutionResult:
    """Execute one already-approved Claim Context command through an explicit handler.

    Args:
        repository: Authoritative Claim repository used for execution-time state checks.
        command: Immutable approved command produced by ``build_claim_context_command``.
        handlers: Explicit action-to-handler bindings owned by the application composition layer.

    Returns:
        An internal provider-neutral result describing applied, rejected, or safely failed
        execution. This is not the target Agent Runtime ``TurnResult``.

    Raises:
        TypeError: The supplied command or handler mapping has the wrong runtime type.
    """

    if not isinstance(command, ClaimContextCommand):
        raise TypeError('command must be a ClaimContextCommand.')
    if not isinstance(handlers, Mapping):
        raise TypeError('handlers must be a mapping.')

    binding = handlers.get(command.action_code)
    if binding is None:
        return _result(
            command,
            status=ClaimContextExecutionStatus.REJECTED,
            reason_code='UNSUPPORTED_ACTION',
        )
    if not isinstance(binding, ClaimContextHandlerBinding):
        raise TypeError('handler bindings must be ClaimContextHandlerBinding values.')
    if binding.tool_name not in command.permitted_tools:
        return _result(
            command,
            status=ClaimContextExecutionStatus.REJECTED,
            reason_code='TOOL_NOT_ALLOWED',
        )

    before_revision: int | None = None
    if command.claim_id is not None:
        try:
            claim = repository.get_claim_internal(command.claim_id)
        except RuntimeError:
            return _result(
                command,
                status=ClaimContextExecutionStatus.FAILED,
                reason_code='DEPENDENCY_FAILURE',
                retryable=True,
            )
        if claim is None:
            return _result(
                command,
                status=ClaimContextExecutionStatus.REJECTED,
                reason_code='CLAIM_NOT_FOUND',
            )
        before_revision = claim.revision
        if claim.claim_state.workflow_state is not command.workflow_state:
            return _result(
                command,
                status=ClaimContextExecutionStatus.REJECTED,
                reason_code='WORKFLOW_STATE_CHANGED',
                resulting_revision=claim.revision,
            )
        if command.expected_revision is not None and claim.revision != command.expected_revision:
            return _result(
                command,
                status=ClaimContextExecutionStatus.REJECTED,
                reason_code='REVISION_CONFLICT',
                resulting_revision=claim.revision,
                retryable=True,
            )
    elif command.action_code != 'claim.open_draft':
        return _result(
            command,
            status=ClaimContextExecutionStatus.REJECTED,
            reason_code='CLAIM_SCOPE_REQUIRED',
        )

    try:
        outcome = binding.handler(command)
    except RevisionConflict as conflict:
        return _result(
            command,
            status=ClaimContextExecutionStatus.REJECTED,
            reason_code='REVISION_CONFLICT',
            resulting_revision=conflict.current_revision,
            retryable=True,
        )
    except IdempotencyConflict:
        return _result(
            command,
            status=ClaimContextExecutionStatus.REJECTED,
            reason_code='IDEMPOTENCY_CONFLICT',
        )
    except ApiError as error:
        return _result(
            command,
            status=(
                ClaimContextExecutionStatus.FAILED
                if error.status_code >= 500
                else ClaimContextExecutionStatus.REJECTED
            ),
            reason_code=error.code,
            resulting_revision=error.current_revision,
            retryable=error.retryable,
        )
    except KeyError:
        return _result(
            command,
            status=ClaimContextExecutionStatus.REJECTED,
            reason_code='RESOURCE_NOT_FOUND',
        )
    except RuntimeError:
        return _result(
            command,
            status=ClaimContextExecutionStatus.FAILED,
            reason_code='DEPENDENCY_FAILURE',
            retryable=True,
        )

    if not isinstance(outcome, ClaimContextHandlerOutcome):
        return _result(
            command,
            status=ClaimContextExecutionStatus.FAILED,
            reason_code='INVALID_EXECUTION_RESULT',
        )
    if (
        not outcome.claim_id.strip()
        or outcome.resulting_revision < 0
        or (command.claim_id is not None and outcome.claim_id != command.claim_id)
    ):
        return _result(
            command,
            status=ClaimContextExecutionStatus.FAILED,
            reason_code='INVALID_EXECUTION_RESULT',
        )

    try:
        persisted = repository.get_claim_internal(outcome.claim_id)
    except RuntimeError:
        return _result(
            command,
            status=ClaimContextExecutionStatus.FAILED,
            reason_code='DEPENDENCY_FAILURE',
            retryable=True,
        )
    if persisted is None or persisted.revision != outcome.resulting_revision:
        return _result(
            command,
            status=ClaimContextExecutionStatus.FAILED,
            reason_code='INVALID_EXECUTION_RESULT',
        )

    if command.state_effect in {
        ActionStateEffect.CLAIM_MUTATION,
        ActionStateEffect.HANDOFF,
    }:
        if before_revision is not None and persisted.revision <= before_revision:
            return _result(
                command,
                status=ClaimContextExecutionStatus.FAILED,
                reason_code='MISSING_STATE_TRANSITION',
            )
    elif before_revision is not None and persisted.revision != before_revision:
        return _result(
            command,
            status=ClaimContextExecutionStatus.FAILED,
            reason_code='UNEXPECTED_STATE_MUTATION',
        )

    return _result(
        command,
        status=ClaimContextExecutionStatus.APPLIED,
        reason_code='APPLIED',
        claim_id=outcome.claim_id,
        resulting_revision=outcome.resulting_revision,
    )
