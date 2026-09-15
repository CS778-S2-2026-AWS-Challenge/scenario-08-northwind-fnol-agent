"""Execute confirmed Evidence actions through a provider-neutral backend port."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

from backend.domain.agent_action_commands import ClaimContextCommand
from backend.domain.agent_action_registry import ActionActorRole, ExecutionAuthority
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditPermission,
    AuditPermissionOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.evidence import evidence_state_for, evidence_summary_for
from backend.domain.ids import new_id
from backend.domain.models import (
    ActorType,
    EvidenceClaimLink,
    EvidenceClaimLinkState,
    EvidenceFileStatus,
    EvidenceHistoryState,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    WorkingClaim,
)
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.branching import build_applied_branch_evaluation
from backend.services.support import request_fingerprint


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


def _backend_route(request: EvidenceActionRequest) -> str:
    return f'/internal/v1/claims/{request.claim_id}/evidence-actions/{request.action_code}'


def _backend_fingerprint(request: EvidenceActionRequest) -> str:
    return request_fingerprint(
        {
            'action_code': request.action_code,
            'claim_id': request.claim_id,
            'evidence_id': request.evidence_id,
            'source_claim_id': request.source_claim_id,
            'expected_revision': request.expected_revision,
            'proposal_ref': request.proposal_ref,
            'confirmation_ref': request.confirmation_ref,
        }
    )


def _stored_backend_result(payload: dict[str, object]) -> EvidenceActionBackendResult:
    revision_value = payload.get('resulting_revision')
    raw_refs = payload.get('state_change_refs')
    return EvidenceActionBackendResult(
        action_code=str(payload['action_code']),
        status=EvidenceActionStatus(str(payload['status'])),
        claim_id=str(payload['claim_id']),
        evidence_id=str(payload['evidence_id']),
        source_claim_id=str(payload['source_claim_id']),
        idempotency_key=str(payload['idempotency_key']),
        reason_code=str(payload['reason_code']),
        resulting_revision=(int(revision_value) if isinstance(revision_value, int | str) else None),
        state_change_refs=(
            tuple(str(item) for item in raw_refs) if isinstance(raw_refs, list) else ()
        ),
        retryable=bool(payload.get('retryable', False)),
    )


class RepositoryEvidenceActionBackend:
    """Persist Evidence reuse/removal through the authoritative repository."""

    def __init__(self, repository: PersistenceRepository) -> None:
        self._repository = repository

    def find_result(self, request: EvidenceActionRequest) -> EvidenceActionBackendResult | None:
        stored = self._repository.find_idempotency(
            request.claimant_id,
            _backend_route(request),
            request.idempotency_key,
        )
        if stored is None:
            return None
        if stored.request_fingerprint != _backend_fingerprint(request):
            return _result_for_backend(
                request, EvidenceActionStatus.REJECTED, 'IDEMPOTENCY_CONFLICT'
            )
        if stored.response_payload is None:
            return _result_for_backend(
                request, EvidenceActionStatus.FAILED, 'INVALID_BACKEND_RESULT'
            )
        return _stored_backend_result(stored.response_payload)

    def execute(self, request: EvidenceActionRequest) -> EvidenceActionBackendResult:
        claim = self._repository.get_claim_internal(request.claim_id)
        if claim is None or claim.customer_id != request.claimant_id:
            return _result_for_backend(
                request, EvidenceActionStatus.REJECTED, 'EVIDENCE_SCOPE_DENIED'
            )
        evidence = next(
            (
                item
                for item in self._repository.list_evidence_for_customer(request.claimant_id)
                if item.evidence_id == request.evidence_id
                and item.claim_id == request.source_claim_id
            ),
            None,
        )
        if evidence is None:
            return _result_for_backend(
                request, EvidenceActionStatus.REJECTED, 'EVIDENCE_SCOPE_DENIED'
            )
        if evidence.source is not EvidenceSource.CLAIMANT:
            return _result_for_backend(
                request, EvidenceActionStatus.REJECTED, 'EVIDENCE_SCOPE_DENIED'
            )

        timestamp = datetime.now(UTC)
        updated_claim = claim.model_copy(
            update={'revision': claim.revision + 1, 'updated_at': timestamp}
        )
        link: EvidenceClaimLink | None = None
        updated_evidence = None
        if request.action_code == 'claim.reuse_evidence':
            if request.claim_id == request.source_claim_id:
                return _result_for_backend(
                    request, EvidenceActionStatus.REJECTED, 'ALREADY_ATTACHED'
                )
            prior_link = self._repository.get_evidence_claim_link(
                request.claim_id, request.evidence_id, request.claimant_id
            )
            if prior_link is not None and prior_link.state is EvidenceClaimLinkState.ACTIVE:
                return _result_for_backend(
                    request, EvidenceActionStatus.REJECTED, 'ALREADY_ATTACHED'
                )
            link = (
                prior_link.model_copy(
                    update={
                        'state': EvidenceClaimLinkState.ACTIVE,
                        'updated_at': timestamp,
                        'detached_at': None,
                    }
                )
                if prior_link is not None
                else EvidenceClaimLink(
                    link_id=new_id('evl'),
                    evidence_id=request.evidence_id,
                    source_claim_id=request.source_claim_id,
                    target_claim_id=request.claim_id,
                    customer_id=request.claimant_id,
                    state=EvidenceClaimLinkState.ACTIVE,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            reason_code = 'EVIDENCE_REUSED'
            state_change_ref = f'evidence-link:{link.link_id}'
        else:
            if request.claim_id == request.source_claim_id:
                if evidence.claimant_history_state is EvidenceHistoryState.REMOVED:
                    return _result_for_backend(
                        request, EvidenceActionStatus.REJECTED, 'EVIDENCE_ALREADY_REMOVED'
                    )
                if evidence.file_status is EvidenceFileStatus.PROCESSING:
                    return _result_for_backend(
                        request, EvidenceActionStatus.REJECTED, 'EVIDENCE_PROCESSING'
                    )
                if evidence.file_status is not EvidenceFileStatus.READY:
                    return _result_for_backend(
                        request, EvidenceActionStatus.REJECTED, 'EVIDENCE_NOT_REMOVABLE'
                    )
                if evidence.status in {
                    EvidenceStatus.INVALID,
                    EvidenceStatus.EXPIRED,
                    EvidenceStatus.SUPERSEDED,
                }:
                    return _result_for_backend(
                        request, EvidenceActionStatus.REJECTED, 'EVIDENCE_RETENTION_BLOCKED'
                    )
                updated_evidence = evidence.model_copy(
                    update={
                        'claimant_history_state': EvidenceHistoryState.REMOVED,
                        'claimant_history_removed_at': timestamp,
                        'updated_at': timestamp,
                    }
                )
                reason_code = 'EVIDENCE_HISTORY_REMOVED_CONTENT_RETAINED'
                state_change_ref = f'evidence-history:{request.evidence_id}:removed'
            else:
                prior_link = self._repository.get_evidence_claim_link(
                    request.claim_id, request.evidence_id, request.claimant_id
                )
                if prior_link is None or prior_link.state is EvidenceClaimLinkState.DETACHED:
                    return _result_for_backend(
                        request, EvidenceActionStatus.REJECTED, 'EVIDENCE_NOT_ATTACHED'
                    )
                link = prior_link.model_copy(
                    update={
                        'state': EvidenceClaimLinkState.DETACHED,
                        'updated_at': timestamp,
                        'detached_at': timestamp,
                    }
                )
                reason_code = 'EVIDENCE_DETACHED'
                state_change_ref = f'evidence-link:{link.link_id}:detached'

        updated_claim = _claim_with_action_projection(
            self._repository,
            updated_claim,
            evidence,
            link,
            request.action_code,
        )
        branch_evaluation = build_applied_branch_evaluation(
            updated_claim,
            repository=self._repository,
            recomputation_reason='evidence_changed',
            trigger_source_refs=[
                request.evidence_id,
                *([link.link_id] if link is not None else []),
            ],
        )
        result = _result_for_backend(
            request,
            EvidenceActionStatus.SUCCEEDED,
            reason_code,
            resulting_revision=updated_claim.revision,
            state_change_refs=(state_change_ref,),
        )
        idempotency = IdempotencyRecord(
            actor_id=request.claimant_id,
            route=_backend_route(request),
            key=request.idempotency_key,
            request_fingerprint=_backend_fingerprint(request),
            claim_id=request.claim_id,
            session_id=claim.active_session_id or '',
            action_code=request.action_code,
            target_ref=request.evidence_id,
            response_payload={
                'action_code': result.action_code,
                'claim_id': result.claim_id,
                'evidence_id': result.evidence_id,
                'source_claim_id': result.source_claim_id,
                'idempotency_key': result.idempotency_key,
                'reason_code': result.reason_code,
                'resulting_revision': result.resulting_revision,
                'status': result.status.value,
                'state_change_refs': list(result.state_change_refs),
                'retryable': result.retryable,
            },
        )
        audit_event = AuditEventEnvelope(
            event_id=new_id('aud'),
            event_type=AuditEventType.ACTION_COMPLETED,
            outcome=AuditOutcome.SUCCEEDED,
            subject=AuditSubject(
                subject_type=AuditSubjectType.CLAIM,
                subject_id=request.claim_id,
                claim_id=request.claim_id,
            ),
            actor=AuditActor(
                actor_type=ActorType.CLAIMANT,
                actor_id=request.claimant_id,
                auth_source='claimant_session',
            ),
            reason=reason_code,
            source_refs=[
                request.evidence_id,
                request.source_claim_id,
                request.proposal_ref,
                request.confirmation_ref,
            ],
            permission=AuditPermission(
                required_permission='claimant_evidence_mutation',
                outcome=AuditPermissionOutcome.AUTHORISED,
            ),
            visibility=AuditVisibility.CLAIMANT_VISIBLE,
            correlation_id=request.confirmation_ref,
            idempotency_key=request.idempotency_key,
            claim_revision=updated_claim.revision,
            created_at=timestamp,
        )
        try:
            self._repository.save_evidence_action_mutation(
                updated_claim,
                request.expected_revision,
                updated_evidence,
                link,
                idempotency,
                audit_event,
                branch_evaluation,
            )
        except RevisionConflict:
            return _result_for_backend(
                request, EvidenceActionStatus.REJECTED, 'REVISION_CONFLICT', retryable=True
            )
        except (IdempotencyConflict, KeyError):
            return _result_for_backend(
                request, EvidenceActionStatus.REJECTED, 'PERSISTENCE_CONFLICT'
            )
        return result


def _claim_with_action_projection(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    source_evidence: EvidenceRecord,
    link: EvidenceClaimLink | None,
    action_code: str,
) -> WorkingClaim:
    """Recompute the target Claim's evidence aggregate for one action."""

    # The caller supplies a WorkingClaim; keeping this helper below the backend class
    # avoids coupling the provider port to the public Evidence service.
    target_claim = claim
    records = [
        record
        for record in repository.list_evidence(target_claim.claim_id, target_claim.customer_id)
        if record.claimant_history_state is EvidenceHistoryState.AVAILABLE
    ]
    links = repository.list_evidence_claim_links(target_claim.customer_id, target_claim.claim_id)
    if action_code == 'claim.reuse_evidence' and link is not None:
        records.append(source_evidence)
    elif action_code == 'claim.remove_evidence' and link is not None:
        source_records = {
            item.evidence_id: item
            for item in repository.list_evidence_for_customer(target_claim.customer_id)
        }
        records = [
            *records,
            *[
                source_records[active.evidence_id]
                for active in links
                if active.state is EvidenceClaimLinkState.ACTIVE
                and active.link_id != link.link_id
                and active.evidence_id in source_records
                and source_records[active.evidence_id].claimant_history_state
                is EvidenceHistoryState.AVAILABLE
            ],
        ]
    return target_claim.model_copy(
        update={
            'evidence_summary': evidence_summary_for(records),
            'claim_state': target_claim.claim_state.model_copy(
                update={'evidence': evidence_state_for(records)}
            ),
        }
    )


def _result_for_backend(
    request: EvidenceActionRequest,
    status: EvidenceActionStatus,
    reason_code: str,
    *,
    resulting_revision: int | None = None,
    state_change_refs: tuple[str, ...] = (),
    retryable: bool = False,
) -> EvidenceActionBackendResult:
    return EvidenceActionBackendResult(
        action_code=request.action_code,
        status=status,
        claim_id=request.claim_id,
        evidence_id=request.evidence_id,
        source_claim_id=request.source_claim_id,
        idempotency_key=request.idempotency_key,
        reason_code=reason_code,
        resulting_revision=resulting_revision,
        state_change_refs=state_change_refs,
        retryable=retryable,
    )


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
        or evidence.claimant_history_state is EvidenceHistoryState.REMOVED
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
