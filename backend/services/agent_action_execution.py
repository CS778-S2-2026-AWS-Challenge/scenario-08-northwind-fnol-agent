"""Execute approved Claim Context commands through explicit backend handlers."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from backend.core.errors import ApiError
from backend.domain.agent_action_commands import ClaimContextCommand
from backend.domain.agent_action_registry import (
    AGENT_ACTION_REGISTRY,
    ActionStateEffect,
    action_contract,
)
from backend.domain.agent_tool_registry import tool_contract
from backend.repositories.protocols import ClaimRepository, IdempotencyConflict, RevisionConflict


class ClaimContextExecutionStatus(str, Enum):
    """Internal outcome for one approved Claim Context command."""

    APPLIED = 'applied'
    REJECTED = 'rejected'
    FAILED = 'failed'


class ActionBindingStatus(str, Enum):
    """Evidence status for a registered action in the application composition root."""

    RUNTIME_EXECUTABLE = 'runtime-executable'
    TEST_ONLY = 'test-only'
    STANDALONE_API = 'standalone-api'
    UNAVAILABLE = 'unavailable'


@dataclass(frozen=True, slots=True)
class ActionBindingDescriptor:
    """Machine-readable binding evidence for one namespaced action."""

    action_code: str
    status: ActionBindingStatus
    handler_name: str | None
    tool_name: str | None
    reason: str


def action_binding_table(
    handlers: Mapping[str, 'ClaimContextHandlerBinding'] | None = None,
    *,
    test_only_actions: set[str] | frozenset[str] = frozenset(),
    standalone_api_actions: set[str] | frozenset[str] = frozenset(),
) -> tuple[ActionBindingDescriptor, ...]:
    """Describe every registered action without implying unsupported execution.

    The table is intentionally derived from the immutable registry.  The
    composition root supplies only real handlers; all other actions remain
    explicitly unavailable (or are labelled as test-only/standalone API when
    the deployment says so).  This makes registry membership and production
    executability separately auditable.
    """

    supplied = handlers or {}
    unknown = sorted(set(supplied) - set(AGENT_ACTION_REGISTRY))
    if unknown:
        raise ValueError(f'Unknown action bindings: {", ".join(unknown)}.')
    overlap = set(test_only_actions) & set(standalone_api_actions)
    if overlap:
        raise ValueError(
            f'An action cannot be both test-only and standalone API: {", ".join(sorted(overlap))}.'
        )
    unknown_labels = (set(test_only_actions) | set(standalone_api_actions)) - set(
        AGENT_ACTION_REGISTRY
    )
    if unknown_labels:
        raise ValueError(f'Unknown action status labels: {", ".join(sorted(unknown_labels))}.')

    rows: list[ActionBindingDescriptor] = []
    for action_code in sorted(AGENT_ACTION_REGISTRY):
        contract = action_contract(action_code)
        binding = supplied.get(action_code)
        if binding is not None:
            if not isinstance(binding, ClaimContextHandlerBinding):
                raise TypeError('handler bindings must be ClaimContextHandlerBinding values.')
            if binding.tool_name is not None:
                tool_contract(binding.tool_name)
            status = ActionBindingStatus.RUNTIME_EXECUTABLE
            handler_name = getattr(binding.handler, '__qualname__', None) or getattr(
                binding.handler, '__name__', type(binding.handler).__name__
            )
            reason = 'A composition-root handler is bound and validated at execution time.'
        elif action_code in test_only_actions:
            status, handler_name = ActionBindingStatus.TEST_ONLY, None
            reason = 'Covered by tests only; no production Runtime handler is bound.'
        elif action_code in standalone_api_actions:
            status, handler_name = ActionBindingStatus.STANDALONE_API, None
            reason = 'Reachable through a standalone service/API boundary only.'
        else:
            status, handler_name = ActionBindingStatus.UNAVAILABLE, None
            reason = 'No production Runtime handler is currently bound.'
        rows.append(
            ActionBindingDescriptor(
                action_code=contract.action_code,
                status=status,
                handler_name=handler_name,
                tool_name=binding.tool_name if binding is not None else None,
                reason=reason,
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class ClaimContextHandlerOutcome:
    """Persisted state identity returned by an explicit command handler."""

    claim_id: str
    resulting_revision: int


ClaimContextCommandHandler = Callable[[ClaimContextCommand], ClaimContextHandlerOutcome]


@dataclass(frozen=True, slots=True)
class ClaimContextHandlerBinding:
    """Bind one approved action to its internal handler and optional registered tool."""

    tool_name: str | None
    handler: ClaimContextCommandHandler


_CLAIMANT_RUNTIME_BINDINGS: Mapping[str, str | None] = MappingProxyType(
    {
        'claim.apply_fact_patch': 'claim_store.compare_and_set',
        'claim.register_evidence': 'claim_store.compare_and_set',
        'claim.prepare_creation': None,
        'claim.create': 'claims_service.create_claim',
        'human.create_handoff': 'handoff_store.create',
    }
)


class ClaimantRuntimeActionDispatcher:
    """Bind live claimant actions to their existing application handlers.

    The dispatcher owns the production action/tool allow-list. The application service
    supplies the request-scoped handler closure because that closure owns the existing
    transaction and its authenticated inputs. Registry membership alone never enables an
    action, and an unbound action is rejected before the closure can run.
    """

    def __init__(self, bindings: Mapping[str, str | None] = _CLAIMANT_RUNTIME_BINDINGS) -> None:
        unknown = sorted(set(bindings) - set(AGENT_ACTION_REGISTRY))
        if unknown:
            raise ValueError(f'Unknown live claimant action bindings: {", ".join(unknown)}.')
        for action_code, tool_name in bindings.items():
            contract = action_contract(action_code)
            if tool_name is not None:
                tool_contract(tool_name)
            if contract.permitted_tools != (() if tool_name is None else (tool_name,)):
                raise ValueError(f'Live binding does not match {action_code} tool contract.')
        self._bindings = MappingProxyType(dict(bindings))

    def execute(
        self,
        repository: ClaimRepository,
        command: ClaimContextCommand,
        handler: ClaimContextCommandHandler,
    ) -> 'ClaimContextExecutionResult':
        """Dispatch one approved command through its configured production binding."""

        if command.action_code not in self._bindings:
            return execute_claim_context_command(repository, command, {})
        return execute_claim_context_command(
            repository,
            command,
            {
                command.action_code: ClaimContextHandlerBinding(
                    tool_name=self._bindings[command.action_code],
                    handler=handler,
                )
            },
        )

    def binding_table(self) -> tuple[ActionBindingDescriptor, ...]:
        """Describe exactly which registered actions the live claimant path can dispatch."""

        def request_scoped_handler(_command: ClaimContextCommand) -> ClaimContextHandlerOutcome:
            raise RuntimeError('A request-scoped production handler was not supplied.')

        return action_binding_table(
            {
                action_code: ClaimContextHandlerBinding(
                    tool_name=tool_name,
                    handler=request_scoped_handler,
                )
                for action_code, tool_name in self._bindings.items()
            }
        )


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
    if command.permitted_tools:
        if binding.tool_name not in command.permitted_tools:
            return _result(
                command,
                status=ClaimContextExecutionStatus.REJECTED,
                reason_code='TOOL_NOT_ALLOWED',
            )
    elif binding.tool_name is not None:
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
