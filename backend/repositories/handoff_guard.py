from typing import Any, Protocol, cast, runtime_checkable

from backend.domain.audit import AuditEventEnvelope
from backend.domain.models import (
    ActorType,
    AgentAction,
    AgentDecisionRecord,
    AuthorityOutcome,
    BranchEvaluationRecord,
    ClaimCollaborationRequest,
    ClaimCoworkerRecord,
    FormSource,
    FormStatus,
    HandoffPriority,
    HandoffRecord,
    HandoffStatus,
    MessageRecord,
    SupportNeed,
    WorkingClaim,
)
from backend.domain.staff_agent import StaffAgentExecutionRecord
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
    validate_handoff_audit_link,
)


class HandoffPersistenceConflict(IdempotencyConflict):
    """A handoff write would bypass lifecycle, ownership, or revision invariants."""


@runtime_checkable
class _ResettableRepository(Protocol):
    """Structural view of the controlled demo-reset opt-in.

    Declared here so the guard does not depend on the service that owns the
    reset boundary.
    """

    def reset_demo_state(self) -> dict[str, int]:
        raise NotImplementedError


_ALLOWED_TRANSITIONS: dict[HandoffStatus, set[HandoffStatus]] = {
    HandoffStatus.REQUESTED: {HandoffStatus.QUEUED, HandoffStatus.CANCELLED},
    HandoffStatus.QUEUED: {HandoffStatus.ACCEPTED, HandoffStatus.CANCELLED},
    HandoffStatus.ACCEPTED: {HandoffStatus.IN_PROGRESS, HandoffStatus.RESOLVED},
    HandoffStatus.IN_PROGRESS: {HandoffStatus.IN_PROGRESS, HandoffStatus.RESOLVED},
    HandoffStatus.RESOLVED: set(),
    HandoffStatus.CANCELLED: set(),
}

_IMMUTABLE_FIELDS = (
    'claim_id',
    'type',
    'priority',
    'queue',
    'support_need',
    'preferred_channel',
    'reason_codes',
    'reason',
    'requested_action',
    'applied_rule',
    'packet',
    'source_message_id',
    'created_at',
)


def _conflict(message: str) -> HandoffPersistenceConflict:
    return HandoffPersistenceConflict(message)


def _validate_parent_revision(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    expected_revision: int,
) -> None:
    stored_claim = repository.get_claim_internal(claim.claim_id)
    if stored_claim is None:
        raise KeyError(claim.claim_id)
    if stored_claim.revision != expected_revision:
        raise RevisionConflict(stored_claim.revision)
    if claim.customer_id != stored_claim.customer_id:
        raise KeyError(claim.claim_id)
    if claim.revision != expected_revision + 1:
        raise _conflict('A handoff mutation must advance the parent claim revision exactly once.')


def _validate_handoff_audit(
    claim: WorkingClaim,
    handoff: HandoffRecord,
    idempotency: IdempotencyRecord,
    audit_event: AuditEventEnvelope,
) -> None:
    try:
        validate_handoff_audit_link(claim, handoff, idempotency, audit_event)
    except ValueError as error:
        raise _conflict('The handoff audit fact does not match the authorised mutation.') from error


def _validate_creation(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    expected_revision: int,
    handoff: HandoffRecord,
    idempotency: IdempotencyRecord,
) -> None:
    _validate_parent_revision(repository, claim, expected_revision)
    if handoff.claim_id != claim.claim_id or idempotency.handoff_id != handoff.handoff_id:
        raise _conflict('The handoff write is not linked to the parent claim and retry record.')
    if handoff.assigned_to is not None:
        raise _conflict('A newly requested handoff cannot already have a staff owner.')
    if handoff.status not in {HandoffStatus.REQUESTED, HandoffStatus.QUEUED}:
        raise _conflict('A new handoff must begin in requested or queued state.')
    if repository.get_handoff(claim.claim_id, handoff.handoff_id, claim.customer_id) is not None:
        raise _conflict('The handoff already exists and cannot be recreated.')


def _validate_staff_update(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    expected_revision: int,
    handoff: HandoffRecord,
    idempotency: IdempotencyRecord,
) -> None:
    _validate_parent_revision(repository, claim, expected_revision)
    if idempotency.handoff_id != handoff.handoff_id:
        raise _conflict('The staff retry record does not identify the mutated handoff.')

    stored = repository.get_handoff(claim.claim_id, handoff.handoff_id, claim.customer_id)
    if stored is None:
        raise _conflict('A staff handoff mutation must update an existing handoff.')

    for field in _IMMUTABLE_FIELDS:
        if getattr(handoff, field) != getattr(stored, field):
            raise _conflict(f'Handoff field {field} is immutable after creation.')

    if handoff.status not in _ALLOWED_TRANSITIONS[stored.status]:
        raise _conflict(
            f'Invalid handoff transition: {stored.status.value} -> {handoff.status.value}.'
        )

    if stored.assigned_to is not None and handoff.assigned_to != stored.assigned_to:
        raise _conflict('An accepted handoff cannot be reassigned by overwriting its owner.')

    active_coworker_ids = {
        item.staff_id for item in repository.list_claim_coworkers(claim.claim_id)
    }
    coworker_progress = (
        idempotency.actor_id in active_coworker_ids
        and handoff.status is HandoffStatus.IN_PROGRESS
        and stored.status in {HandoffStatus.ACCEPTED, HandoffStatus.IN_PROGRESS}
    )
    if (
        stored.status in {HandoffStatus.ACCEPTED, HandoffStatus.IN_PROGRESS}
        and stored.assigned_to is not None
        and idempotency.actor_id != stored.assigned_to
        and not coworker_progress
    ):
        raise _conflict('Only the persisted handoff owner can continue or resolve the work.')

    if (
        handoff.status
        in {
            HandoffStatus.ACCEPTED,
            HandoffStatus.IN_PROGRESS,
            HandoffStatus.RESOLVED,
        }
        and handoff.assigned_to is None
    ):
        raise _conflict('An accepted or active handoff must retain a staff owner.')

    if stored.accepted_at is not None and handoff.accepted_at != stored.accepted_at:
        raise _conflict('The original handoff acceptance timestamp cannot be rewritten.')
    if (
        handoff.status
        in {
            HandoffStatus.ACCEPTED,
            HandoffStatus.IN_PROGRESS,
            HandoffStatus.RESOLVED,
        }
        and handoff.accepted_at is None
    ):
        raise _conflict('Accepted handoff states require an acceptance timestamp.')
    if handoff.status is HandoffStatus.RESOLVED and handoff.resolved_at is None:
        raise _conflict('A resolved handoff requires a resolution timestamp.')
    if stored.resolved_at is not None and handoff.resolved_at != stored.resolved_at:
        raise _conflict('The original handoff resolution timestamp cannot be rewritten.')


def validate_runtime_handoff_update(
    stored: HandoffRecord | None,
    handoff: HandoffRecord,
    claim: WorkingClaim,
    message: MessageRecord,
    decision: AgentDecisionRecord,
) -> None:
    """Permit only an evidence-backed urgency upgrade of the same open handoff.

    Runtime turn commits do not use the staff lifecycle route. All its immutable
    identity, ownership, packet, lifecycle and timestamps still stay unchanged;
    the only allowed change is the explicitly documented urgency escalation.
    """
    if stored is None or stored == handoff:
        return
    if stored.status in {HandoffStatus.RESOLVED, HandoffStatus.CANCELLED}:
        raise _conflict('Runtime cannot change a closed handoff.')
    unchanged = handoff.model_copy(
        update={'priority': stored.priority, 'support_need': stored.support_need}
    )
    if unchanged != stored:
        raise _conflict('Runtime urgency escalation must preserve handoff identity and ownership.')
    ranks = {
        HandoffPriority.STANDARD: 0,
        HandoffPriority.HIGH: 1,
        HandoffPriority.URGENT: 2,
        HandoffPriority.IMMEDIATE: 3,
    }
    if (
        handoff.support_need is not SupportNeed.URGENT
        or ranks[handoff.priority] < ranks[stored.priority]
        or ranks[handoff.priority] < ranks[HandoffPriority.URGENT]
    ):
        raise _conflict('Runtime can only upgrade an open handoff to urgent support.')
    fact = claim.form.get('incident.injury_or_danger')
    source_backed_signal = fact is not None and (
        (
            fact.value is True
            and fact.status is FormStatus.CONFIRMED
            and fact.source is FormSource.CLAIMANT
            and message.message_id in fact.source_refs
        )
        or any(
            assertion.normalized_value is True and message.message_id in assertion.source_refs
            for assertion in fact.assertions
        )
    )
    if (
        message.actor is not ActorType.CLAIMANT
        or message.claim_id != claim.claim_id
        or stored.claim_id != claim.claim_id
        or decision.claim_id != claim.claim_id
        or decision.trigger_message_id != message.message_id
        or decision.handoff_id != handoff.handoff_id
        or decision.action is not AgentAction.URGENT_HANDOFF
        or decision.authority.outcome is not AuthorityOutcome.AUTHORISED
        or not source_backed_signal
    ):
        raise _conflict(
            'Runtime urgency escalation requires an authorised source-backed safety fact.'
        )


class HandoffPersistenceGuard:
    """Provider-neutral guard for handoff lifecycle writes.

    WorkingClaim.revision remains the only optimistic-concurrency token. The
    guard adds handoff ownership and lifecycle invariants without introducing a
    second revision counter.

    The application wraps its repository once, when the app is constructed, so
    every router, service, seed path, and adapter that reads the repository
    from application state writes through these invariants.
    """

    def __init__(self, repository: PersistenceRepository) -> None:
        self._repository = repository

    def __getattr__(self, name: str) -> Any:
        return getattr(self._repository, name)

    def save_handoff(self, handoff: HandoffRecord, customer_id: str) -> None:
        existing = self._repository.get_handoff(handoff.claim_id, handoff.handoff_id, customer_id)
        if existing is not None and existing != handoff:
            raise _conflict(
                'Existing handoffs must be changed through a revision-checked mutation.'
            )
        self._repository.save_handoff(handoff, customer_id)

    def save_handoff_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        handoff: HandoffRecord,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        _validate_creation(self._repository, claim, expected_revision, handoff, idempotency)
        _validate_handoff_audit(claim, handoff, idempotency, audit_event)
        self._repository.save_handoff_mutation(
            claim,
            expected_revision,
            handoff,
            idempotency,
            audit_event,
            branch_evaluation,
        )

    def save_staff_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        **records: Any,
    ) -> None:
        handoff = records.get('handoff')
        if handoff is not None:
            if not isinstance(handoff, HandoffRecord):
                raise _conflict('The handoff mutation payload is invalid.')
            _validate_staff_update(
                self._repository,
                claim,
                expected_revision,
                handoff,
                idempotency,
            )
            audit_event = records.get('audit_event')
            if not isinstance(audit_event, AuditEventEnvelope):
                raise _conflict('A handoff staff mutation requires its atomic audit fact.')
            _validate_handoff_audit(claim, handoff, idempotency, audit_event)
        self._repository.save_staff_mutation(
            claim,
            expected_revision,
            idempotency,
            **records,
        )

    def save_ownership_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        collaboration_request: ClaimCollaborationRequest,
        coworkers: list[ClaimCoworkerRecord] | None = None,
        handoff: HandoffRecord | None = None,
        audit_event: AuditEventEnvelope | None = None,
        staff_agent_execution: StaffAgentExecutionRecord | None = None,
    ) -> None:
        if handoff is not None:
            _validate_parent_revision(self._repository, claim, expected_revision)
            stored = self._repository.get_handoff(
                claim.claim_id,
                handoff.handoff_id,
                claim.customer_id,
            )
            if stored is None or handoff.claim_id != claim.claim_id:
                raise _conflict('An ownership mutation can change only an existing Claim handoff.')
            if idempotency.handoff_id != handoff.handoff_id:
                raise _conflict(
                    'A handoff ownership mutation requires idempotency to reference that handoff.'
                )
            if audit_event is None:
                raise _conflict('A handoff ownership mutation requires its atomic audit fact.')
            _validate_handoff_audit(claim, handoff, idempotency, audit_event)
        self._repository.save_ownership_mutation(
            claim,
            expected_revision,
            idempotency,
            collaboration_request,
            coworkers=coworkers,
            handoff=handoff,
            audit_event=audit_event,
            staff_agent_execution=staff_agent_execution,
        )


class ResettableHandoffPersistenceGuard(HandoffPersistenceGuard):
    """Guard for a repository that also opts in to controlled demo reset.

    Runtime protocol checks read the class rather than resolving attributes
    through ``__getattr__``, so a repository that offers demo reset needs that
    method declared on its wrapper too. The plain guard deliberately does not
    declare it, which keeps the reset boundary fail-closed for a repository
    that never offered reset.
    """

    def reset_demo_state(self) -> dict[str, int]:
        return cast(_ResettableRepository, self._repository).reset_demo_state()


def guarded_handoff_repository(repository: PersistenceRepository) -> HandoffPersistenceGuard:
    if isinstance(repository, HandoffPersistenceGuard):
        return repository
    if isinstance(repository, _ResettableRepository):
        return ResettableHandoffPersistenceGuard(repository)
    return HandoffPersistenceGuard(repository)
