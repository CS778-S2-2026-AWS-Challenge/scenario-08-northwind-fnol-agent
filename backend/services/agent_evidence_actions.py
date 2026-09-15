"""Execute confirmed Evidence actions through a provider-neutral backend port."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from backend.domain.agent_action_commands import ClaimContextCommand
from backend.domain.agent_action_registry import ActionActorRole, ExecutionAuthority
from backend.domain.models import EvidenceFileStatus, EvidenceSource, EvidenceStatus
from backend.repositories.protocols import PersistenceRepository


class EvidenceActionStatus(str, Enum):
    """Truthful outcome classes returned to the Agent Runtime."""

    SUCCEEDED = 'succeeded'
    REJECTED = 'rejected'
    UNAVAILABLE = 'unavailable'
    FAILED = 'failed'
    UNKNOWN = 'unknown'


@dataclass(frozen=True, slots=True)
class EvidenceActionConfirmation:
    """Authenticated confirmation of one exact Evidence proposal."""

    claimant_id: str
    action_code: str
    claim_id: str
    evidence_id: str
    source_claim_id: str
    proposal_ref: str
    confirmation_ref: str
    confirmed: bool


@dataclass(frozen=True, slots=True)
class EvidenceActionRequest:
    """Provider-neutral request passed to the backend Evidence capability."""

    action_code: str
    claimant_id: str
    claim_id: str
    evidence_id: str
    source_claim_id: str
    expected_revision: int
    idempotency_key: str
    proposal_ref: str
    confirmation_ref: str


@dataclass(frozen=True, slots=True)
class EvidenceActionBackendResult:
    """Typed result returned by the authoritative backend handler."""

    action_code: str
    status: EvidenceActionStatus
    claim_id: str
    evidence_id: str
    source_claim_id: str
    idempotency_key: str
    reason_code: str
    resulting_revision: int | None = None
    state_change_refs: tuple[str, ...] = ()
    retryable: bool = False


class EvidenceActionBackend(Protocol):
    """Backend port required for persisted reuse and removal."""

    def find_result(self, request: EvidenceActionRequest) -> EvidenceActionBackendResult | None:
        """Return an existing result for an identical idempotency key.

        Args:
            request: Fully scoped and confirmed Runtime request.

        Returns:
            The prior typed result, or ``None`` when this request has not run.
        """
        ...

    def execute(self, request: EvidenceActionRequest) -> EvidenceActionBackendResult:
        """Execute one authorised Evidence action.

        Args:
            request: Fully scoped and confirmed Runtime request.

        Returns:
            The authoritative typed backend outcome.
        """
        ...


@dataclass(frozen=True, slots=True)
class EvidenceActionExecutionResult:
    """Runtime-safe result with claimant wording derived from actual execution state."""

    action_code: str
    status: EvidenceActionStatus
    reason_code: str
    claim_id: str
    evidence_id: str
    resulting_revision: int | None
    state_change_refs: tuple[str, ...]
    retryable: bool
    claimant_message: str


_ACTIONS = frozenset({'claim.reuse_evidence', 'claim.remove_evidence'})
_REUSE_BLOCKED_STATUSES = frozenset(
    {EvidenceStatus.INVALID, EvidenceStatus.EXPIRED, EvidenceStatus.SUPERSEDED}
)


def _result(
    request: EvidenceActionRequest,
    status: EvidenceActionStatus,
    reason_code: str,
    *,
    resulting_revision: int | None = None,
    state_change_refs: tuple[str, ...] = (),
    retryable: bool = False,
) -> EvidenceActionExecutionResult:
    verb = 'reused' if request.action_code == 'claim.reuse_evidence' else 'removed'
    messages = {
        EvidenceActionStatus.SUCCEEDED: f'The Evidence was {verb} for this Claim.',
        EvidenceActionStatus.REJECTED: 'The Evidence action was not applied.',
        EvidenceActionStatus.UNAVAILABLE: 'The Evidence action is not available right now.',
        EvidenceActionStatus.FAILED: 'Northwind could not complete the Evidence action.',
        EvidenceActionStatus.UNKNOWN: (
            'Northwind cannot confirm the Evidence action outcome. Check its current state '
            'before retrying with the same request key.'
        ),
    }
    return EvidenceActionExecutionResult(
        action_code=request.action_code,
        status=status,
        reason_code=reason_code,
        claim_id=request.claim_id,
        evidence_id=request.evidence_id,
        resulting_revision=resulting_revision,
        state_change_refs=state_change_refs,
        retryable=retryable,
        claimant_message=messages[status],
    )


def _request(
    command: ClaimContextCommand,
    confirmation: EvidenceActionConfirmation,
) -> EvidenceActionRequest:
    values = {
        name: command.payload.get(name)
        for name in ('claim_id', 'evidence_id', 'source_claim_id', 'proposal_ref')
    }
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise ValueError('Evidence action command identifiers must be non-empty strings.')
    if command.expected_revision is None or command.idempotency_key is None:
        raise ValueError('Evidence actions require revision and idempotency metadata.')
    return EvidenceActionRequest(
        action_code=command.action_code,
        claimant_id=confirmation.claimant_id,
        claim_id=str(values['claim_id']),
        evidence_id=str(values['evidence_id']),
        source_claim_id=str(values['source_claim_id']),
        expected_revision=command.expected_revision,
        idempotency_key=command.idempotency_key,
        proposal_ref=str(values['proposal_ref']),
        confirmation_ref=confirmation.confirmation_ref,
    )


def _confirmation_matches(
    request: EvidenceActionRequest,
    confirmation: EvidenceActionConfirmation,
    command: ClaimContextCommand,
) -> bool:
    return confirmation.confirmed and (
        confirmation.action_code,
        confirmation.claim_id,
        confirmation.evidence_id,
        confirmation.source_claim_id,
        confirmation.proposal_ref,
        confirmation.confirmation_ref,
    ) == (
        request.action_code,
        request.claim_id,
        request.evidence_id,
        request.source_claim_id,
        request.proposal_ref,
        command.authority_reference,
    )


def _validated_backend_result(
    repository: PersistenceRepository,
    request: EvidenceActionRequest,
    result: EvidenceActionBackendResult,
    *,
    replayed: bool,
) -> EvidenceActionExecutionResult:
    identity = (
        result.action_code,
        result.claim_id,
        result.evidence_id,
        result.source_claim_id,
        result.idempotency_key,
    )
    expected = (
        request.action_code,
        request.claim_id,
        request.evidence_id,
        request.source_claim_id,
        request.idempotency_key,
    )
    if identity != expected or not result.reason_code.strip():
        return _result(request, EvidenceActionStatus.FAILED, 'INVALID_BACKEND_RESULT')
    if result.status is not EvidenceActionStatus.SUCCEEDED:
        return _result(
            request,
            result.status,
            result.reason_code,
            resulting_revision=result.resulting_revision,
            state_change_refs=result.state_change_refs,
            retryable=result.retryable,
        )
    if (
        result.resulting_revision is None
        or result.resulting_revision <= request.expected_revision
        or not result.state_change_refs
    ):
        return _result(request, EvidenceActionStatus.FAILED, 'INVALID_BACKEND_RESULT')
    try:
        persisted = repository.get_claim_internal(request.claim_id)
    except RuntimeError:
        return _result(request, EvidenceActionStatus.FAILED, 'DEPENDENCY_FAILURE', retryable=True)
    if persisted is None or (
        persisted.revision < result.resulting_revision
        if replayed
        else persisted.revision != result.resulting_revision
    ):
        return _result(request, EvidenceActionStatus.FAILED, 'UNVERIFIED_PERSISTED_RESULT')
    return _result(
        request,
        result.status,
        result.reason_code,
        resulting_revision=result.resulting_revision,
        state_change_refs=result.state_change_refs,
    )


def execute_confirmed_evidence_action(
    repository: PersistenceRepository,
    command: ClaimContextCommand,
    confirmation: EvidenceActionConfirmation,
    backend: EvidenceActionBackend | None,
) -> EvidenceActionExecutionResult:
    """Validate and execute one confirmed Evidence action without storage access.

    Args:
        repository: Authoritative Claim and Evidence read boundary.
        command: Registry-validated Runtime command carrying revision and retry identity.
        confirmation: Authenticated confirmation bound to the exact prior proposal.
        backend: Optional persisted Evidence capability supplied by the composition root.

    Returns:
        A typed, claimant-safe outcome that never infers success from model wording.

    Raises:
        ValueError: The command is not a registered Runtime-owned Evidence action.
    """

    if command.action_code not in _ACTIONS:
        raise ValueError('Unsupported confirmed Evidence action.')
    if command.proposer_role is not ActionActorRole.RUNTIME or (
        command.authority_requirement is not ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE
    ):
        raise ValueError('Evidence execution requires Runtime and claimant authority.')
    request = _request(command, confirmation)
    if not _confirmation_matches(request, confirmation, command):
        return _result(request, EvidenceActionStatus.REJECTED, 'CONFIRMATION_MISMATCH')

    try:
        claim = repository.get_claim_internal(request.claim_id)
    except RuntimeError:
        return _result(request, EvidenceActionStatus.FAILED, 'DEPENDENCY_FAILURE', retryable=True)
    if claim is None or claim.customer_id != request.claimant_id:
        return _result(request, EvidenceActionStatus.REJECTED, 'EVIDENCE_SCOPE_DENIED')
    try:
        evidence = next(
            (
                item
                for item in repository.list_evidence_for_customer(request.claimant_id)
                if item.evidence_id == request.evidence_id
                and item.claim_id == request.source_claim_id
            ),
            None,
        )
    except RuntimeError:
        return _result(request, EvidenceActionStatus.FAILED, 'DEPENDENCY_FAILURE', retryable=True)
    if evidence is None or evidence.source is not EvidenceSource.CLAIMANT:
        return _result(request, EvidenceActionStatus.REJECTED, 'EVIDENCE_SCOPE_DENIED')
    if backend is None:
        return _result(request, EvidenceActionStatus.UNAVAILABLE, 'BACKEND_HANDLER_UNAVAILABLE')

    try:
        replay = backend.find_result(request)
    except TimeoutError:
        return _result(request, EvidenceActionStatus.UNKNOWN, 'RECONCILIATION_TIMEOUT')
    except ConnectionError:
        return _result(request, EvidenceActionStatus.UNAVAILABLE, 'BACKEND_UNAVAILABLE')
    except RuntimeError:
        return _result(request, EvidenceActionStatus.FAILED, 'DEPENDENCY_FAILURE', retryable=True)
    if replay is not None:
        if not isinstance(replay, EvidenceActionBackendResult):
            return _result(request, EvidenceActionStatus.FAILED, 'INVALID_BACKEND_RESULT')
        return _validated_backend_result(repository, request, replay, replayed=True)
    if claim.claim_state.workflow_state is not command.workflow_state:
        return _result(request, EvidenceActionStatus.REJECTED, 'WORKFLOW_STATE_CHANGED')
    if claim.revision != request.expected_revision:
        return _result(request, EvidenceActionStatus.REJECTED, 'REVISION_CONFLICT', retryable=True)
    if request.action_code == 'claim.reuse_evidence' and (
        evidence.file_status is not EvidenceFileStatus.READY
        or evidence.status in _REUSE_BLOCKED_STATUSES
    ):
        return _result(request, EvidenceActionStatus.REJECTED, 'EVIDENCE_NOT_REUSABLE')

    try:
        result = backend.execute(request)
    except TimeoutError:
        return _result(request, EvidenceActionStatus.UNKNOWN, 'BACKEND_TIMEOUT')
    except ConnectionError:
        return _result(request, EvidenceActionStatus.UNAVAILABLE, 'BACKEND_UNAVAILABLE')
    except RuntimeError:
        return _result(request, EvidenceActionStatus.FAILED, 'DEPENDENCY_FAILURE', retryable=True)
    if not isinstance(result, EvidenceActionBackendResult):
        return _result(request, EvidenceActionStatus.FAILED, 'INVALID_BACKEND_RESULT')
    return _validated_backend_result(repository, request, result, replayed=False)
