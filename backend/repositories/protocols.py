from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from threading import Event
from typing import Any, Literal, Protocol

from backend.domain.agent_context_runtime import VerifiedConversationSummary
from backend.domain.audit import (
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditPermissionOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.claim_creation import ClaimCreationOperationRecord
from backend.domain.external_services import (
    ExternalTaskAttempt,
    ExternalTaskEvidenceLink,
    ExternalTaskRecord,
    ExternalTaskRequest,
    ExternalTaskResult,
)
from backend.domain.models import (
    ActorType,
    AgentDecisionRecord,
    AssessorRoutingOperation,
    BranchEvaluationRecord,
    ClaimCollaborationRequest,
    ClaimCoworkerRecord,
    ClaimDecisionRecord,
    ContentsItemEvidenceAssociation,
    CustomerUpdateRecord,
    EvidenceClaimLink,
    EvidenceRecord,
    FollowUpOperation,
    FollowUpRecord,
    HandoffRecord,
    MessageRecord,
    MotorOtherDriverRecord,
    RuntimeTraceRecord,
    SessionRecord,
    SessionStatus,
    SignalDecisionRecord,
    StaffActionRecord,
    WorkingClaim,
)
from backend.domain.realtime import (
    AgentTurnProgressPublication,
    RealtimeCursor,
    RealtimeEvent,
    RealtimePublication,
)
from backend.domain.retention import (
    ObjectDeletionOutcome,
    RetentionDeleteAuthorization,
    RetentionHoldRecord,
    RetentionOperation,
    RetentionRecordTombstone,
    RetentionStepStatus,
)
from backend.domain.retrieval import RetrievalRecord, ReviewSignalRecord
from backend.domain.runtime import RuntimeTurnRecords, RuntimeWorkItemRecord
from backend.domain.staff_agent import (
    StaffAgentExecutionRecord,
    StaffAgentMessage,
    StaffAgentMessageRole,
    StaffAgentSession,
)
from backend.domain.staff_agent_tools import (
    StaffClaimSearchCandidate,
    StaffSessionSearchCandidate,
)
from backend.domain.staff_identity import StaffPresenceRecord


class RepositoryConflict(Exception):
    """Base class for persistence conflicts exposed by the application layer."""


class RevisionConflict(RepositoryConflict):
    def __init__(self, current_revision: int) -> None:
        super().__init__(f'Current revision is {current_revision}.')
        self.current_revision = current_revision


class RecoveryDeadlineConflict(RuntimeError):
    """A recovery mutation lost to the authoritative absolute deadline."""


class IdempotencyConflict(RepositoryConflict):
    pass


class DemoSeedConflict(RepositoryConflict):
    """The controlled validation seed cannot run against a populated queue."""

    pass


class RepositorySearchLimitExceeded(RuntimeError):
    """A bounded repository search cannot prove a complete result."""

    pass


@dataclass(frozen=True)
class StaffAgentDraftSource:
    """Durable provenance of a Workbench action proposed by Staff Agent."""

    session_id: str
    message_id: str
    draft_id: str


@dataclass(frozen=True)
class IdempotencyRecord:
    actor_id: str
    route: str
    key: str
    request_fingerprint: str
    claim_id: str
    session_id: str
    message_id: str | None = None
    agent_message_id: str | None = None
    decision_id: str | None = None
    claim_decision_id: str | None = None
    runtime_trace_id: str | None = None
    runtime_result_id: str | None = None
    handoff_id: str | None = None
    follow_up_id: str | None = None
    action_registry_version: str | None = None
    action_code: str | None = None
    target_ref: str | None = None
    staff_agent_session_id: str | None = None
    staff_agent_message_id: str | None = None
    staff_agent_draft_id: str | None = None
    staff_agent_execution_id: str | None = None
    message_turn_kind: Literal['legacy_agent', 'message_only'] | None = None
    message_turn_revision: int | None = None
    response_payload: dict[str, Any] | None = None
    revision_before_message: int | None = None
    confirmation_checkpoint: dict[str, Any] | None = None
    inbound_checkpoint: bool = False
    response_status: int | None = None
    retired: bool = False

    def __post_init__(self) -> None:
        if (self.message_turn_kind is None) != (self.message_turn_revision is None):
            raise ValueError('Message turn kind and revision must be persisted together.')
        if self.message_turn_revision is not None and self.message_turn_revision < 1:
            raise ValueError('Message turn revision must be positive.')


def message_turn_result_priority(record: IdempotencyRecord) -> tuple[int, int]:
    """Prefer a committed response over earlier failures or an in-flight checkpoint."""
    committed = (record.response_status or 0) < 400 and (
        record.message_turn_kind in {'legacy_agent', 'runtime'}
        or record.decision_id is not None
        or record.runtime_trace_id is not None
    )
    rank = 2 if committed else 1 if record.response_payload is not None else 0
    revision = record.message_turn_revision
    if revision is None and record.response_payload is not None:
        value = record.response_payload.get('claim_revision')
        revision = value if isinstance(value, int) else None
    return rank, revision or 0


def validate_handoff_audit_link(
    claim: WorkingClaim,
    handoff: HandoffRecord,
    idempotency: IdempotencyRecord,
    audit_event: AuditEventEnvelope,
) -> None:
    """Validate the cross-record identity for an audited Handoff mutation."""

    if (
        handoff.claim_id != claim.claim_id
        or idempotency.claim_id != claim.claim_id
        or idempotency.handoff_id != handoff.handoff_id
        or audit_event.event_type is not AuditEventType.ACTION_COMPLETED
        or audit_event.outcome is not AuditOutcome.SUCCEEDED
        or audit_event.subject.subject_type is not AuditSubjectType.CLAIM
        or audit_event.subject.subject_id != claim.claim_id
        or audit_event.subject.claim_id != claim.claim_id
        or audit_event.claim_revision != claim.revision
        or audit_event.actor.actor_id != idempotency.actor_id
        or audit_event.idempotency_key != idempotency.key
        or audit_event.correlation_id != idempotency.key
        or handoff.handoff_id not in audit_event.source_refs
        or audit_event.permission is None
        or audit_event.permission.outcome is not AuditPermissionOutcome.AUTHORISED
        or audit_event.visibility not in {AuditVisibility.INTERNAL_ONLY, AuditVisibility.AUDIT_ONLY}
    ):
        raise ValueError('The Handoff audit fact does not match the persisted mutation.')


def validate_handoff_mutation_audit(
    claim: WorkingClaim,
    handoff: HandoffRecord | None,
    idempotency: IdempotencyRecord,
    audit_event: AuditEventEnvelope | None,
) -> None:
    """Require and validate the audit fact only when a mutation changes a Handoff."""

    if handoff is None:
        return
    if audit_event is None:
        raise ValueError('A Handoff mutation requires its atomic audit fact.')
    validate_handoff_audit_link(claim, handoff, idempotency, audit_event)


def validate_staff_message_mutation_audit(
    claim: WorkingClaim,
    message: MessageRecord | None,
    idempotency: IdempotencyRecord,
    audit_event: AuditEventEnvelope | None,
) -> None:
    """Require one matching audit fact for every staff-to-claimant message.

    A message is sent either as a plain reply to the session, or as the answer to
    a waiting-list item, in which case it targets that item and names it.
    """

    if message is None:
        return
    answering = idempotency.action_code == 'conversation.answer_claimant_question'
    expected_target = message.content.get('answers_item_id') if answering else message.session_id
    if (
        audit_event is None
        or message.actor is not ActorType.STAFF
        or message.claim_id != claim.claim_id
        or idempotency.claim_id != claim.claim_id
        or idempotency.session_id != message.session_id
        or idempotency.message_id != message.message_id
        or idempotency.action_code
        not in {'conversation.send_claimant_message', 'conversation.answer_claimant_question'}
        or not expected_target
        or idempotency.target_ref != expected_target
        or audit_event.event_type is not AuditEventType.ACTION_COMPLETED
        or audit_event.outcome is not AuditOutcome.SUCCEEDED
        or audit_event.subject.subject_type is not AuditSubjectType.CLAIM
        or audit_event.subject.subject_id != claim.claim_id
        or audit_event.subject.claim_id != claim.claim_id
        or audit_event.claim_revision != claim.revision
        or audit_event.actor.actor_id != idempotency.actor_id
        or audit_event.idempotency_key != idempotency.key
        or audit_event.correlation_id != idempotency.key
        or message.message_id not in audit_event.source_refs
        or audit_event.permission is None
        or audit_event.permission.required_permission != idempotency.action_code
        or audit_event.permission.outcome is not AuditPermissionOutcome.AUTHORISED
        or audit_event.visibility not in {AuditVisibility.INTERNAL_ONLY, AuditVisibility.AUDIT_ONLY}
    ):
        raise ValueError('The staff message audit fact does not match the persisted mutation.')


def validate_claim_decision_mutation_audit(
    claim: WorkingClaim,
    decision: ClaimDecisionRecord | None,
    idempotency: IdempotencyRecord,
    audit_event: AuditEventEnvelope | None,
) -> None:
    """Require the immutable audit fact committed with a Claim decision."""

    if decision is None:
        return
    if (
        audit_event is None
        or decision.claim_id != claim.claim_id
        or claim.claim_decision_id != decision.decision_id
        or idempotency.claim_decision_id != decision.decision_id
        or audit_event.event_type is not AuditEventType.ACTION_COMPLETED
        or audit_event.outcome is not AuditOutcome.SUCCEEDED
        or audit_event.subject.subject_type is not AuditSubjectType.CLAIM
        or audit_event.subject.subject_id != claim.claim_id
        or audit_event.subject.claim_id != claim.claim_id
        or audit_event.claim_revision != claim.revision
        or audit_event.actor.actor_id != idempotency.actor_id
        or audit_event.idempotency_key != idempotency.key
        or audit_event.correlation_id != idempotency.key
        or decision.decision_id not in audit_event.source_refs
        or audit_event.permission is None
        or audit_event.permission.required_permission != 'claim.record_decision'
        or audit_event.permission.outcome is not AuditPermissionOutcome.AUTHORISED
        or audit_event.visibility not in {AuditVisibility.INTERNAL_ONLY, AuditVisibility.AUDIT_ONLY}
    ):
        raise ValueError('The Claim decision audit fact does not match the persisted mutation.')


def with_staff_agent_source(
    record: IdempotencyRecord,
    source: StaffAgentDraftSource | None,
) -> IdempotencyRecord:
    """Attach explicit Staff Agent provenance before an atomic mutation."""

    if source is None:
        return record
    return replace(
        record,
        staff_agent_session_id=source.session_id,
        staff_agent_message_id=source.message_id,
        staff_agent_draft_id=source.draft_id,
        staff_agent_execution_id=f'sax_{source.draft_id}',
    )


def idempotency_source_matches(
    record: IdempotencyRecord,
    source: StaffAgentDraftSource | None,
) -> bool:
    """Require replay to use the same explicit source, including no source."""

    return (
        record.staff_agent_session_id == (source.session_id if source else None)
        and record.staff_agent_message_id == (source.message_id if source else None)
        and record.staff_agent_draft_id == (source.draft_id if source else None)
    )


@dataclass(frozen=True)
class ValidationSeedGraph:
    """Provider-neutral records for one atomic validation-data seed operation."""

    claims: tuple[WorkingClaim, ...]
    sessions: tuple[SessionRecord, ...]
    messages: tuple[MessageRecord, ...]
    evidence: tuple[EvidenceRecord, ...]
    staff_presence: StaffPresenceRecord
    expected_presence_revision: int | None
    idempotency: IdempotencyRecord
    # The rule evaluation of each seeded Claim, written with it so the claimant's dynamic form
    # exists from the first read.
    branch_evaluations: tuple[BranchEvaluationRecord, ...] = ()


def seeded_branch_evaluations(graph: ValidationSeedGraph) -> dict[str, BranchEvaluationRecord]:
    """Index the seed graph's branch evaluations by Claim, one per seeded Claim at most."""
    claim_ids = {claim.claim_id for claim in graph.claims}
    evaluations = {evaluation.claim_id: evaluation for evaluation in graph.branch_evaluations}
    if len(evaluations) != len(graph.branch_evaluations) or not set(evaluations) <= claim_ids:
        raise ValueError('Each validation seed branch evaluation needs its own seeded Claim.')
    return evaluations


def validate_validation_seed_session(claim: WorkingClaim, session: SessionRecord) -> None:
    """Validate the active Claim/Session relationship before persistence."""
    if (
        session.claim_id != claim.claim_id
        or session.customer_id != claim.customer_id
        or claim.active_session_id != session.session_id
        or session.status is not SessionStatus.ACTIVE
        or session.context_revision != claim.revision
    ):
        raise ValueError(f'Validation seed active session does not match claim {claim.claim_id}.')


def staff_agent_execution_for(
    claim: WorkingClaim,
    expected_revision: int,
    idempotency: IdempotencyRecord,
    source: StaffAgentDraftSource | None,
) -> StaffAgentExecutionRecord | None:
    """Build immutable execution evidence from an authorised staff mutation."""

    if source is None:
        return None
    if (
        idempotency.action_code is None
        or idempotency.target_ref is None
        or idempotency.response_payload is None
    ):
        raise ValueError('Staff Agent execution requires a registered action result.')
    return StaffAgentExecutionRecord(
        execution_id=f'sax_{source.draft_id}',
        session_id=source.session_id,
        message_id=source.message_id,
        draft_id=source.draft_id,
        staff_id=idempotency.actor_id,
        claim_id=claim.claim_id,
        action_code=idempotency.action_code,
        target_ref=idempotency.target_ref,
        expected_revision=expected_revision,
        resulting_revision=claim.revision,
        outcome='executed',
        result=idempotency.response_payload,
        source_refs=[
            f'staff-agent-session:{source.session_id}',
            f'staff-agent-message:{source.message_id}',
            f'staff-agent-draft:{source.draft_id}',
            f'claim:{claim.claim_id}:revision:{claim.revision}',
        ],
        created_at=claim.updated_at,
    )


def validate_staff_agent_execution(
    execution: StaffAgentExecutionRecord | None,
    claim: WorkingClaim,
    expected_revision: int,
    idempotency: IdempotencyRecord,
) -> None:
    """Require execution evidence to describe exactly the persisted mutation."""

    if execution is None:
        if idempotency.staff_agent_execution_id is not None:
            raise ValueError('Staff Agent provenance requires execution evidence.')
        return
    if (
        idempotency.staff_agent_execution_id != execution.execution_id
        or idempotency.staff_agent_session_id != execution.session_id
        or idempotency.staff_agent_message_id != execution.message_id
        or idempotency.staff_agent_draft_id != execution.draft_id
        or idempotency.actor_id != execution.staff_id
        or idempotency.claim_id != execution.claim_id
        or idempotency.action_code != execution.action_code
        or idempotency.target_ref != execution.target_ref
        or idempotency.response_payload != execution.result
        or claim.claim_id != execution.claim_id
        or expected_revision != execution.expected_revision
        or claim.revision != execution.resulting_revision
    ):
        raise ValueError('Staff Agent execution evidence does not match the mutation.')


def validate_staff_agent_execution_source(
    execution: StaffAgentExecutionRecord | None,
    session: StaffAgentSession | None,
    message: StaffAgentMessage | None,
) -> None:
    """Require execution evidence to resolve to its immutable assistant draft."""

    if execution is None:
        return
    if (
        session is None
        or message is None
        or execution.execution_id != f'sax_{execution.draft_id}'
        or session.session_id != execution.session_id
        or session.staff_id != execution.staff_id
        or message.message_id != execution.message_id
        or message.session_id != session.session_id
        or message.staff_id != session.staff_id
        or message.role is not StaffAgentMessageRole.ASSISTANT
        or execution.claim_id not in message.claim_ids
    ):
        raise ValueError('Staff Agent execution source does not match its owned assistant message.')
    matching_drafts = [draft for draft in message.drafts if draft.draft_id == execution.draft_id]
    if len(matching_drafts) != 1:
        raise ValueError('Staff Agent execution source does not identify one saved draft.')
    draft = matching_drafts[0]
    if (
        draft.claim_id != execution.claim_id
        or draft.action_code != execution.action_code
        or draft.target_ref != execution.target_ref
    ):
        raise ValueError('Staff Agent execution source does not match its saved draft contract.')
    required_refs = {
        f'staff-agent-session:{execution.session_id}',
        f'staff-agent-message:{execution.message_id}',
        f'staff-agent-draft:{execution.draft_id}',
    }
    if not required_refs.issubset(execution.source_refs):
        raise ValueError('Staff Agent execution evidence is missing source references.')


class ClaimRepository(Protocol):
    def create_claim(
        self,
        claim: WorkingClaim,
        session: SessionRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        raise NotImplementedError

    def claimant_resource_access_open(
        self,
        claim_id: str,
        customer_id: str,
    ) -> bool:
        """Return claimant resource eligibility without exposing existence details."""
        raise NotImplementedError

    def get_claim(self, claim_id: str, customer_id: str) -> WorkingClaim | None:
        raise NotImplementedError

    def get_claim_internal(self, claim_id: str) -> WorkingClaim | None:
        """Return the internal claim projection to an authorised service only."""
        raise NotImplementedError

    def list_claims_for_customer(self, customer_id: str) -> list[WorkingClaim]:
        raise NotImplementedError

    def list_claims_internal(self) -> list[WorkingClaim]:
        """Return claims for an authorised staff projection."""
        raise NotImplementedError

    def search_claims_internal(
        self, filters: dict[str, object], limit: int
    ) -> list[StaffClaimSearchCandidate]:
        """Return only bounded Claim candidates matching registered staff filters."""
        raise NotImplementedError

    def promote_claim_owner(
        self,
        claim_id: str,
        anonymous_customer_id: str,
        customer_id: str,
    ) -> WorkingClaim | None:
        """Atomically attach an anonymous claim and its records to an account."""
        raise NotImplementedError

    def save_claim(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        raise NotImplementedError

    def save_claim_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        """Atomically persist a claim revision and its retry metadata."""
        raise NotImplementedError

    def get_session(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> SessionRecord | None:
        raise NotImplementedError

    def save_session(self, session: SessionRecord) -> None:
        raise NotImplementedError

    def save_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
        resolved_follow_up: FollowUpRecord | None = None,
        reconciled_follow_up_operation: FollowUpOperation | None = None,
        replaced_active_session: SessionRecord | None = None,
        audit_event: AuditEventEnvelope | None = None,
    ) -> None:
        """Atomically replace/activate a session and resolve recovery work when supplied."""
        raise NotImplementedError

    def get_follow_up(
        self,
        claim_id: str,
        follow_up_id: str,
        customer_id: str,
    ) -> FollowUpRecord | None:
        raise NotImplementedError

    def list_follow_ups(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[FollowUpRecord]:
        raise NotImplementedError

    def get_follow_up_operation(
        self,
        claim_id: str,
        operation_id: str,
        customer_id: str,
    ) -> FollowUpOperation | None:
        raise NotImplementedError

    def list_follow_up_operations(
        self,
        claim_id: str,
        follow_up_id: str,
        customer_id: str,
    ) -> list[FollowUpOperation]:
        raise NotImplementedError

    def save_follow_up_operation(
        self,
        operation: FollowUpOperation,
        customer_id: str,
    ) -> None:
        """Create or advance one durable P17 execution identity.

        Exact replay is idempotent. Identity/sequence rewrites and invalid
        lifecycle transitions are conflicts.
        """
        raise NotImplementedError

    def backfill_incomplete_claim_recovery(
        self,
        *,
        recorded_at: datetime | None = None,
    ) -> tuple[int, int]:
        """Deterministically bind open legacy P17.1 Follow-ups.

        Returns ``(bound_count, failed_closed_count)``.
        """
        raise NotImplementedError

    def commit_recovery_staff_abandonment(
        self,
        expected_claim_revision: int,
        expected_follow_up: FollowUpRecord,
        updated_claim: WorkingClaim,
        updated_follow_up: FollowUpRecord,
        reconciled_operation: FollowUpOperation | None,
        customer_id: str,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
    ) -> None:
        """Atomically abandon one P17 recovery obligation and its Claim."""
        raise NotImplementedError

    def commit_follow_up_contact_withdrawal(
        self,
        expected_claim_revision: int,
        expected_follow_up: FollowUpRecord,
        updated_follow_up: FollowUpRecord,
        reconciled_operation: FollowUpOperation | None,
        customer_id: str,
        audit_event: AuditEventEnvelope,
    ) -> None:
        """Atomically block automatic P17 contact and record immutable Audit."""
        raise NotImplementedError

    def commit_recovery_expiry(
        self,
        expected_claim_revision: int,
        expected_follow_up: FollowUpRecord,
        updated_claim: WorkingClaim,
        updated_follow_up: FollowUpRecord,
        reconciled_operation: FollowUpOperation | None,
        customer_id: str,
        audit_event: AuditEventEnvelope,
    ) -> None:
        """Atomically terminalise one open P17 obligation at its deadline."""
        raise NotImplementedError

    def commit_due_follow_up_attempt(
        self,
        expected_follow_up: FollowUpRecord,
        updated_follow_up: FollowUpRecord,
        operation: FollowUpOperation,
        settled_previous_operation: FollowUpOperation | None,
        in_app_message: MessageRecord,
        customer_id: str,
        audit_event: AuditEventEnvelope,
    ) -> None:
        """Atomically commit one in-app P17 attempt, visible message and aggregate.

        Candidate discovery is not authority. Implementations must reload and
        revalidate Claim, Session, Follow-up, deadline, contact authority,
        operation history, and Claim revision before committing.
        """
        raise NotImplementedError

    def list_due_follow_ups(
        self,
        due_before: datetime,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[FollowUpRecord], str | None]:
        """Return one bounded page of executable P17 Follow-ups.

        This is candidate discovery only. Execution must revalidate the
        authoritative Follow-up, Claim revision, contact authority and deadline.
        """
        raise NotImplementedError

    def list_expiring_follow_ups(
        self,
        deadline_before: datetime,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[FollowUpRecord], str | None]:
        """Return one bounded page of open P17 obligations by deadline.

        Deadline discovery is deliberately separate from due discovery so a
        blocked obligation with no ``due_at`` remains globally discoverable.
        """
        raise NotImplementedError

    def save_incomplete_checkpoint(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        follow_up: FollowUpRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        """Atomically pause a session, clear its active pointer, and create follow-up work."""
        raise NotImplementedError

    def get_active_session(self, claim_id: str, customer_id: str) -> SessionRecord | None:
        raise NotImplementedError

    def list_sessions_for_claim(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[SessionRecord]:
        raise NotImplementedError

    def search_sessions_internal(
        self,
        claim_id: str,
        customer_id: str,
        filters: dict[str, object],
        limit: int,
    ) -> list[StaffSessionSearchCandidate]:
        """Return bounded Session candidates after applying registered filters."""
        raise NotImplementedError

    def find_idempotency(
        self,
        actor_id: str,
        route: str,
        key: str,
    ) -> IdempotencyRecord | None:
        raise NotImplementedError

    def find_message_turn_idempotency(
        self,
        actor_id: str,
        route: str,
        claim_id: str,
        message_id: str,
    ) -> IdempotencyRecord | None:
        """Return the durable retry identity that committed one claimant message."""
        raise NotImplementedError

    def reserve_message_turn_idempotency_alias(
        self,
        actor_id: str,
        route: str,
        claim_id: str,
        message_id: str,
        key: str,
        request_fingerprint: str,
    ) -> IdempotencyRecord | None:
        """Atomically bind a new retry key to an existing claimant message turn."""
        raise NotImplementedError

    def save_idempotency(self, record: IdempotencyRecord) -> None:
        raise NotImplementedError


class PersistenceRepository(ClaimRepository, Protocol):
    """Provider-neutral persistence boundary for the full Sprint 1 record set."""

    def get_retention_operation(
        self,
        operation_id: str,
    ) -> RetentionOperation | None:
        raise NotImplementedError

    def get_retention_operation_for_claim(
        self,
        claim_id: str,
    ) -> RetentionOperation | None:
        """Read the monotonic resource-access closure for one Claim."""
        raise NotImplementedError

    def list_pending_retention_operations(
        self,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[RetentionOperation], str | None]:
        """Return one keyset page of unfinished retention work.

        Args:
            limit: Maximum operations read for the page (1-100).
            cursor: Position returned by the previous page, or ``None`` to start.

        Returns:
            Operations ordered by ``updated_at`` then operation ID, and the cursor of
            the next page, or ``None`` at the end of the sweep.

        Raises:
            ValueError: If ``limit`` is outside 1-100.
            InvalidRepositoryCursorError: If ``cursor`` is malformed or foreign.
        """
        raise NotImplementedError

    def list_retention_handoff_candidates(
        self,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[str], str | None]:
        """Return one keyset page of retention-eligible terminal Claims without retention.

        Eligibility is ``RETENTION_ELIGIBLE_TERMINAL_REASONS`` and ``_VALUES``: recovery
        expiry, staff abandonment and authorised closure. The terminal disposition is
        the durable handoff source, so a reservation that failed stays discoverable. A
        page reads at most ``limit`` eligible Claims; already reserved Claims in that
        window are skipped, so a page may hold fewer IDs than ``limit``.

        Args:
            limit: Maximum eligible Claims read for the page (1-100).
            cursor: Position returned by the previous page, or ``None`` to start.

        Returns:
            Claim IDs ordered by terminal ``recorded_at`` then Claim ID, and the cursor
            of the next page, or ``None`` at the end of the sweep.

        Raises:
            ValueError: If ``limit`` is outside 1-100.
            InvalidRepositoryCursorError: If ``cursor`` is malformed or foreign.
        """
        raise NotImplementedError

    def reserve_eligible_retention_operation(
        self,
        operation: RetentionOperation,
    ) -> RetentionOperation:
        """Atomically revalidate terminal authority and commit access closure."""
        raise NotImplementedError

    def reserve_retention_operation(
        self,
        operation: RetentionOperation,
    ) -> bool:
        """Reserve one logical destructive cleanup operation.

        Returns True only for the first successful reservation. Exact replay
        returns False. A different operation for the same Claim fails closed.
        """
        raise NotImplementedError

    def freeze_retention_targets(
        self,
        operation_id: str,
        expected_revision: int,
        *,
        frozen_at: datetime,
    ) -> RetentionOperation:
        """Atomically freeze the exact approved cleanup inventory."""
        raise NotImplementedError

    def get_retention_tombstone(
        self,
        target_id: str,
    ) -> RetentionRecordTombstone | None:
        """Return minimum retained evidence for one anonymised record."""
        raise NotImplementedError

    def record_retention_step_failure(
        self,
        operation_id: str,
        target_id: str,
        expected_revision: int,
        *,
        status: RetentionStepStatus,
        diagnostic_code: str,
        now: datetime,
    ) -> RetentionOperation:
        """Persist bounded failure/unknown evidence without repeating destruction."""
        raise NotImplementedError

    def authorize_retention_object_target(
        self,
        operation_id: str,
        target_id: str,
        expected_revision: int,
        *,
        now: datetime,
    ) -> tuple[RetentionOperation, RetentionDeleteAuthorization]:
        """Atomically order one object-delete authorization against retention holds."""
        raise NotImplementedError

    def record_retention_object_result(
        self,
        operation_id: str,
        authorization_id: str,
        *,
        outcome: ObjectDeletionOutcome,
        now: datetime,
    ) -> RetentionOperation:
        """Settle one previously authorized object-delete attempt durably."""
        raise NotImplementedError

    def apply_retention_record_target(
        self,
        operation_id: str,
        target_id: str,
        expected_revision: int,
        *,
        now: datetime,
    ) -> RetentionOperation:
        """Atomically mutate one frozen database target and append step evidence."""
        raise NotImplementedError

    def save_retention_operation(
        self,
        operation: RetentionOperation,
        expected_revision: int,
    ) -> None:
        """CAS-persist one valid retention execution transition."""
        raise NotImplementedError

    def save_retention_hold(
        self,
        hold: RetentionHoldRecord,
    ) -> None:
        """Persist or monotonically release one source-linked retention hold."""
        raise NotImplementedError

    def commit_retention_hold_action(
        self,
        hold: RetentionHoldRecord,
        *,
        expected_claim_revision: int,
        audit_event: AuditEventEnvelope,
        idempotency: IdempotencyRecord,
    ) -> None:
        """Atomically apply or release one hold under the expected Claim revision.

        The Claim revision is checked first; the hold transition (including the
        RetentionOperation hold/resume it implies), the Audit event and the actor's
        idempotency record then commit together or not at all.

        Args:
            hold: The new or released hold record.
            expected_claim_revision: Claim revision the Workbench action was offered on.
            audit_event: Internal Audit event for the action.
            idempotency: Replay record holding the first response.

        Raises:
            KeyError: The Claim no longer exists.
            RevisionConflict: The Claim revision changed after the action was offered.
            IdempotencyConflict: The audit event or replay key already holds other data.
            ValueError: The hold transition is not allowed.
        """
        raise NotImplementedError

    def list_retention_holds(
        self,
        claim_id: str,
    ) -> list[RetentionHoldRecord]:
        raise NotImplementedError

    def seed_validation_graph(self, graph: ValidationSeedGraph) -> IdempotencyRecord | None:
        """Persist the graph, returning an existing idempotent result on replay."""
        raise NotImplementedError

    def append_realtime_publication(
        self,
        publication: RealtimePublication | AgentTurnProgressPublication,
    ) -> RealtimeEvent:
        """Persist one provider-neutral publication outside a business mutation.

        Args:
            publication: Mutation intent without persistence-owned coordinates.

        Returns:
            The repository-created durable event.
        """
        raise NotImplementedError

    def replay_realtime_events(
        self,
        after: RealtimeCursor | None,
        *,
        limit: int,
    ) -> list[RealtimeEvent]:
        """Return durable events in stable cursor order."""
        raise NotImplementedError

    def realtime_high_watermark(self) -> RealtimeEvent | None:
        """Return the current durable tail without replaying retained history."""
        raise NotImplementedError

    def watch_realtime_events(self, stop: Event) -> Iterator[RealtimeEvent]:
        """Yield newly appended events without per-client repository polling."""
        raise NotImplementedError

    def append_audit_event(self, event: AuditEventEnvelope) -> None:
        """Append one immutable audit fact.

        Args:
            event: Audit event to persist.

        Returns:
            None.

        Raises:
            IdempotencyConflict: The event identity already exists with different content.
        """
        raise NotImplementedError

    def list_audit_events_internal(
        self,
        subject: AuditSubject,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[AuditEventEnvelope]:
        """List audit events after the caller authorises the subject read.

        Args:
            subject: Logical subject whose audit events are requested.
            start_at: Optional inclusive lower timestamp bound.
            end_at: Optional inclusive upper timestamp bound.

        Returns:
            Matching events in stable ``(created_at, event_id)`` order.

        Raises:
            ValueError: The requested time range is invalid.
        """
        raise NotImplementedError

    def list_audit_events_admin(
        self,
        *,
        event_type: str | None = None,
        subject_type: str | None = None,
        actor_id: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[AuditEventEnvelope]:
        """List bounded audit events for an authorised administration projection.

        Args:
            event_type: Optional controlled event type filter.
            subject_type: Optional logical subject type filter.
            actor_id: Optional actor identity filter.
            start_at: Optional inclusive lower timestamp bound.
            end_at: Optional inclusive upper timestamp bound.

        Returns:
            Matching immutable events in stable time and identity order.

        Raises:
            ValueError: The requested time range is invalid.
        """
        raise NotImplementedError

    def save_claim_mutation_with_audit(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        audit_events: tuple[AuditEventEnvelope, ...],
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        """Atomically persist a claim mutation, retry metadata, and audit facts.

        Args:
            claim: Resulting authoritative Claim State.
            expected_revision: Revision that must still be current.
            idempotency: Retry metadata scoped to the authenticated claimant or staff actor.
            audit_events: Immutable audit facts produced by the same mutation.
            branch_evaluation: Optional applied Dynamic Form evaluation for the resulting revision.

        Returns:
            None.

        Raises:
            RevisionConflict: The authoritative Claim revision changed first.
            IdempotencyConflict: Retry or audit identity conflicts with stored data.
            KeyError: Claim ownership or mutation links are invalid.
        """
        raise NotImplementedError

    def save_message(self, message: MessageRecord, customer_id: str) -> None:
        raise NotImplementedError

    def save_staff_agent_session(self, session: StaffAgentSession) -> None:
        raise NotImplementedError

    def get_staff_agent_session(self, session_id: str, staff_id: str) -> StaffAgentSession | None:
        raise NotImplementedError

    def list_staff_agent_sessions(self, staff_id: str) -> list[StaffAgentSession]:
        raise NotImplementedError

    def list_staff_agent_messages(self, session_id: str, staff_id: str) -> list[StaffAgentMessage]:
        raise NotImplementedError

    def get_staff_agent_execution(
        self, execution_id: str, staff_id: str
    ) -> StaffAgentExecutionRecord | None:
        raise NotImplementedError

    def find_staff_agent_message_by_client_id(
        self, session_id: str, staff_id: str, client_message_id: str
    ) -> StaffAgentMessage | None:
        raise NotImplementedError

    def save_staff_agent_turn(
        self,
        session: StaffAgentSession,
        staff_message: StaffAgentMessage,
        assistant_message: StaffAgentMessage,
    ) -> None:
        """Atomically append one Staff Agent exchange and advance its session timestamp."""
        raise NotImplementedError

    def save_message_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        message: MessageRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        """Atomically persist a claimant or staff message and claim revision."""
        raise NotImplementedError

    def find_message_checkpoint(
        self, claim_id: str, message_id: str, customer_id: str
    ) -> IdempotencyRecord | None:
        """Read the original accepted inbound checkpoint, not a later retry revision."""
        raise NotImplementedError

    def save_message_recovery(
        self,
        message: MessageRecord,
        idempotency: IdempotencyRecord,
        *,
        agent_message: MessageRecord | None = None,
        runtime_trace: RuntimeTraceRecord | None = None,
    ) -> None:
        """Complete an accepted attempt without changing Claim or message content.

        A rejected model attempt may include a bounded Runtime trace so its failure
        diagnostic is durable without turning the attempt into a completed turn.
        """
        raise NotImplementedError

    def get_message(
        self,
        claim_id: str,
        session_id: str,
        message_id: str,
        customer_id: str,
    ) -> MessageRecord | None:
        raise NotImplementedError

    def freeze_message_response(
        self,
        idempotency: IdempotencyRecord,
        response_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically retain the first claimant-safe response of a committed turn."""
        raise NotImplementedError

    def find_message_by_client_id(
        self,
        claim_id: str,
        client_message_id: str,
        customer_id: str,
    ) -> MessageRecord | None:
        raise NotImplementedError

    def list_messages(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> list[MessageRecord]:
        raise NotImplementedError

    def list_recent_messages(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
        limit: int,
    ) -> list[MessageRecord]:
        """Return at most the newest requested messages in stable ascending order."""
        raise NotImplementedError

    def save_conversation_summary(
        self,
        summary: VerifiedConversationSummary,
        customer_id: str,
    ) -> None:
        """Persist one immutable verified summary without replacing message history."""

        raise NotImplementedError

    def get_latest_conversation_summary(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> VerifiedConversationSummary | None:
        """Return the newest authorised summary for one claimant session."""

        raise NotImplementedError

    def save_agent_decision(self, decision: AgentDecisionRecord, customer_id: str) -> None:
        raise NotImplementedError

    def save_branch_evaluation(
        self,
        evaluation: BranchEvaluationRecord,
        customer_id: str,
    ) -> None:
        """Persist non-applied evaluation evidence without changing Claim State."""
        raise NotImplementedError

    def list_branch_evaluations(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[BranchEvaluationRecord]:
        raise NotImplementedError

    def get_claim_creation_operation(
        self,
        operation_id: str,
    ) -> ClaimCreationOperationRecord | None:
        """Return one provider-neutral Claim creation operation."""

        raise NotImplementedError

    def reserve_claim_creation_operation(
        self,
        operation: ClaimCreationOperationRecord,
    ) -> bool:
        """Atomically reserve the right to invoke Claim creation.

        Returns ``True`` only to the caller that may contact the provider. An
        identical persisted reservation returns ``False`` so the caller reconciles
        instead of issuing a second side effect.
        """

        raise NotImplementedError

    def save_claim_creation_operation(
        self,
        operation: ClaimCreationOperationRecord,
    ) -> None:
        """Persist a valid failure or unresolved operation transition."""

        raise NotImplementedError

    def save_claim_creation_outcome(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        operation: ClaimCreationOperationRecord,
        branch_evaluation: BranchEvaluationRecord,
    ) -> None:
        """Atomically accept one provider result with the resulting Claim revision."""

        raise NotImplementedError

    def get_assessor_routing_operation(
        self,
        operation_id: str,
    ) -> AssessorRoutingOperation | None:
        raise NotImplementedError

    def save_assessor_routing_operation(
        self,
        operation: AssessorRoutingOperation,
    ) -> None:
        """Persist an immutable operation identity and valid outcome transition."""
        raise NotImplementedError

    def save_assessor_routing_settlement(
        self,
        operation: AssessorRoutingOperation,
        task: ExternalTaskRecord,
        attempt: ExternalTaskAttempt,
        customer_id: str,
    ) -> None:
        """Atomically persist an assessor outcome and its task attempt."""
        raise NotImplementedError

    def save_assessor_reconciliation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        task: ExternalTaskRecord,
        operation: AssessorRoutingOperation,
        request: ExternalTaskRequest,
        evidence: EvidenceRecord,
        link: ExternalTaskEvidenceLink,
        branch_evaluation: BranchEvaluationRecord,
        customer_id: str,
        *,
        staff_action: StaffActionRecord | None = None,
        idempotency: IdempotencyRecord | None = None,
        required_staff_id: str | None = None,
        required_staff_revision: int | None = None,
    ) -> None:
        """Atomically settle one unknown assessor request as accepted.

        Args:
            claim: Resulting Claim carrying the reconciled routing result.
            expected_revision: Claim revision that must still be current.
            task: Existing external task advanced to accepted.
            operation: Existing assessor operation advanced to accepted.
            request: Existing request whose dispatch is confirmed by reconciliation.
            evidence: Pending material now owed by the accepted task.
            link: Immutable task-to-evidence relationship for that material.
            branch_evaluation: Applied branch projection for the new Claim revision.
            customer_id: Customer who owns every persisted record.
            staff_action: Optional completed Workbench action recorded with the settlement.
            idempotency: Optional staff mutation replay record.
            required_staff_id: Staff presence identity that must remain claimable.
            required_staff_revision: Presence revision required by the staff mutation.

        Returns:
            None.

        Raises:
            RevisionConflict: The stored Claim revision changed first.
            IdempotencyConflict: Stored state does not match this settlement.
            KeyError: A record is missing, belongs to another Claim, or is invalid.
        """
        raise NotImplementedError

    def save_assessor_routing_preparation(
        self,
        operation: AssessorRoutingOperation,
        decision: AgentDecisionRecord,
        customer_id: str,
        audit_events: tuple[AuditEventEnvelope, ...] = (),
    ) -> None:
        """Atomically persist routing authority, operation identity, and audit facts.

        Args:
            operation: Prepared assessor-routing operation.
            decision: Current deterministic Northwind authority decision.
            customer_id: Customer who owns the parent claim.
            audit_events: Immutable audit facts produced by the preparation.

        Returns:
            None.

        Raises:
            KeyError: Claim, session, authority, or audit scope is invalid.
            IdempotencyConflict: Existing operation, decision, or audit identity conflicts.
        """
        raise NotImplementedError

    def get_agent_decision(
        self,
        claim_id: str,
        decision_id: str,
        customer_id: str,
    ) -> AgentDecisionRecord | None:
        raise NotImplementedError

    def get_agent_decision_internal(
        self,
        claim_id: str,
        decision_id: str,
    ) -> AgentDecisionRecord | None:
        """Return a decision for server-side authorisation validation."""
        raise NotImplementedError

    def find_agent_decision_for_trigger(
        self,
        claim_id: str,
        trigger_message_id: str,
        customer_id: str,
    ) -> AgentDecisionRecord | None:
        raise NotImplementedError

    def list_agent_decisions(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[AgentDecisionRecord]:
        raise NotImplementedError

    def save_agent_turn(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        claimant_message: MessageRecord,
        agent_message: MessageRecord,
        decision: AgentDecisionRecord,
        idempotency: IdempotencyRecord,
        handoff: HandoffRecord | None = None,
        evidence: EvidenceRecord | None = None,
        branch_evaluation: BranchEvaluationRecord | None = None,
        runtime_trace: RuntimeTraceRecord | None = None,
        runtime_records: RuntimeTurnRecords | None = None,
        *,
        checkpointed: bool = False,
        review_signals: Sequence[ReviewSignalRecord] | None = None,
    ) -> None:
        """Atomically persist one validated Agent turn and optional Runtime trace."""
        raise NotImplementedError

    def get_runtime_turn_for_trigger(
        self,
        claim_id: str,
        trigger_message_id: str,
        customer_id: str,
    ) -> RuntimeTurnRecords | None:
        raise NotImplementedError

    def list_runtime_work_items(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[RuntimeWorkItemRecord]:
        """Return immutable Runtime WorkItem records for one authorised Claim."""
        raise NotImplementedError

    def save_runtime_work_item(
        self,
        item: RuntimeWorkItemRecord,
        customer_id: str,
    ) -> None:
        """Persist or settle one standalone Runtime responsibility record.

        Creation is insert-only and exact replay is idempotent. An existing
        standalone item may transition only from open/in_progress to
        completed/cancelled while keeping its logical identity, ownership,
        subject, kind, turn and creation time unchanged. This is the durable
        settlement boundary used by recovery reconciliation.
        """
        raise NotImplementedError

    def save_runtime_turn(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        claimant_message: MessageRecord,
        agent_message: MessageRecord,
        runtime_trace: RuntimeTraceRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        """Atomically persist a read-only namespaced Runtime turn.

        Unlike a legacy Agent turn, this operation does not advance Claim revision or
        create an ``AgentDecisionRecord``. It records the conversation, Runtime trace,
        Session activity, and retry identity as one transaction.
        """
        raise NotImplementedError

    def get_runtime_trace(
        self,
        claim_id: str,
        trace_id: str,
        customer_id: str,
    ) -> RuntimeTraceRecord | None:
        raise NotImplementedError

    def find_runtime_trace_for_trigger(
        self,
        claim_id: str,
        trigger_message_id: str,
        customer_id: str,
    ) -> RuntimeTraceRecord | None:
        raise NotImplementedError

    def save_evidence(self, evidence: EvidenceRecord, customer_id: str) -> None:
        raise NotImplementedError

    def get_evidence(
        self,
        claim_id: str,
        evidence_id: str,
        customer_id: str,
    ) -> EvidenceRecord | None:
        raise NotImplementedError

    def list_evidence(self, claim_id: str, customer_id: str) -> list[EvidenceRecord]:
        raise NotImplementedError

    def list_evidence_for_customer(self, customer_id: str) -> list[EvidenceRecord]:
        """Return Evidence owned by a customer across all of their Claims."""
        raise NotImplementedError

    def list_evidence_recovery_page(
        self, after_evidence_id: str | None = None, limit: int = 10
    ) -> list[EvidenceRecord]:
        """Discover a bounded internal page; the service decides repair eligibility.

        Args:
            after_evidence_id: Exclusive cursor from the previous page's last record.
            limit: Page size, clamped to 1 through 50.
        Returns:
            All Evidence states in ascending evidence_id order, without ownership filtering.
        Raises:
            ValueError: If persisted Evidence cannot satisfy the domain contract.
        """
        raise NotImplementedError

    def get_motor_other_driver(
        self, claim_id: str, customer_id: str
    ) -> MotorOtherDriverRecord | None:
        raise NotImplementedError

    def save_motor_other_driver_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        participant: MotorOtherDriverRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        """Atomically create the sole bounded other-driver record for a Motor Claim."""
        raise NotImplementedError

    def list_contents_item_evidence_associations(
        self, claim_id: str, customer_id: str
    ) -> list[ContentsItemEvidenceAssociation]:
        raise NotImplementedError

    def list_contents_item_evidence_association_page(
        self,
        claim_id: str,
        customer_id: str,
        item_id: str,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[ContentsItemEvidenceAssociation], str | None]:
        """Return one stable page without loading the Claim-level collection.

        Args:
            claim_id: The owning Claim identifier.
            customer_id: The authenticated Claim owner.
            item_id: The ContentsItem whose associations are requested.
            limit: The maximum records returned in this page.
            cursor: The opaque continuation cursor from the prior page, if any.

        Returns:
            The item-scoped records and the next opaque cursor, or ``None`` at the end.

        Raises:
            InvalidRepositoryCursorError: The cursor is malformed or has another scope.
        """
        raise NotImplementedError

    def save_contents_item_evidence_association_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        association: ContentsItemEvidenceAssociation,
        idempotency: IdempotencyRecord,
    ) -> None:
        """Atomically persist one immutable same-Claim item-to-Evidence link."""
        raise NotImplementedError

    def get_evidence_claim_link(
        self, target_claim_id: str, evidence_id: str, customer_id: str
    ) -> EvidenceClaimLink | None:
        raise NotImplementedError

    def list_evidence_claim_links(
        self, customer_id: str, target_claim_id: str | None = None
    ) -> list[EvidenceClaimLink]:
        raise NotImplementedError

    def save_evidence_action_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        evidence: EvidenceRecord | None,
        link: EvidenceClaimLink | None,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
        branch_evaluation: BranchEvaluationRecord,
    ) -> None:
        """Atomically persist one governed reuse or removal result."""
        raise NotImplementedError

    def save_evidence_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        evidence: EvidenceRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        """Atomically persist evidence, shared claim state, and retry metadata."""
        raise NotImplementedError

    def save_external_task(self, task: ExternalTaskRecord, customer_id: str) -> None:
        """Persist current operational state outside shared Claim State.

        Args:
            task: External task state to create or advance.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The parent claim is missing or not owned by the customer.
            IdempotencyConflict: The write changes immutable identity or is stale.
        """
        raise NotImplementedError

    def save_external_task_attempt(
        self,
        attempt: ExternalTaskAttempt,
        customer_id: str,
    ) -> None:
        """Append one immutable execution attempt for a claim-owned external task.

        Attempts are append-only execution history. The current ``ExternalTaskRecord``
        remains the lifecycle summary; this record explains each dispatch or retry and
        must survive provider restart.

        Args:
            attempt: Validated attempt outcome to append.
            customer_id: Customer who owns the parent claim.

        Raises:
            KeyError: The claim, task, or request authority is unavailable.
            IdempotencyConflict: The identity, sequence, or immutable payload conflicts.
        """
        raise NotImplementedError

    def save_external_task_settlement(
        self,
        task: ExternalTaskRecord,
        attempt: ExternalTaskAttempt,
        customer_id: str,
    ) -> None:
        """Atomically persist a generic task outcome and its task attempt."""
        raise NotImplementedError

    def reserve_external_dispatch(
        self,
        claim_id: str,
        request_id: str,
        customer_id: str,
        reserved_at: datetime,
        operation_id: str,
    ) -> ExternalTaskRequest | None:
        """Atomically claim the sole right to send one prepared external request.

        This is a compare-and-set, not a read followed by a write: two callers racing
        on the same request must not both be told they may dispatch. Whoever loses gets
        `None` and must fail before reaching the provider.

        Args:
            claim_id: Claim that owns the request.
            request_id: Request whose dispatch is being reserved.
            customer_id: Customer who owns the parent claim.
            reserved_at: Moment the reservation is taken.
            operation_id: Operation this attempt dispatches under, recorded with the
                reservation so an interrupted attempt still names its own identity.

        Returns:
            The reserved request when this caller won, or `None` when another attempt
            already holds the reservation.

        Raises:
            KeyError: The claim or request is missing or belongs to another customer.
        """

        raise NotImplementedError

    def release_external_dispatch(
        self,
        claim_id: str,
        request_id: str,
        customer_id: str,
    ) -> None:
        """Give up a reservation whose attempt established that nothing was sent.

        Only a definitely unsubmitted attempt may release. A reservation left in place
        says an attempt may have reached the provider, which is what keeps a crashed
        dispatch from being repeated as though it had never happened.

        Args:
            claim_id: Claim that owns the request.
            request_id: Request whose reservation is being released.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The claim or request is missing or belongs to another customer.
        """

        raise NotImplementedError

    def save_external_task_request(
        self,
        request: ExternalTaskRequest,
        customer_id: str,
    ) -> None:
        """Persist preparation or the first send record for one external task.

        Args:
            request: Claim-bound request preparation or send record.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The claim, task, consent, or authority is unavailable.
            IdempotencyConflict: Identity changes, a send is rewritten, or the
                task already has another request.
        """
        raise NotImplementedError

    def list_external_task_requests_internal(
        self,
        claim_id: str,
    ) -> list[ExternalTaskRequest]:
        """List request records for an authorised internal claim projection.

        Args:
            claim_id: Working Claim whose request records are requested.

        Returns:
            Claim-scoped requests in stable preparation order.

        Raises:
            RuntimeError: A configured persistence provider cannot complete the read.
        """
        raise NotImplementedError

    def save_external_task_evidence_link(
        self,
        link: ExternalTaskEvidenceLink,
        customer_id: str,
    ) -> None:
        """Persist one immutable evidence origin for an external task.

        Args:
            link: Task-to-evidence relationship to persist.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The parent claim, task, or evidence record is unavailable.
            IdempotencyConflict: The evidence already has a different origin.
        """
        raise NotImplementedError

    def save_external_task_result(self, result: ExternalTaskResult, customer_id: str) -> None:
        """Record what a third party returned for one task, or check an existing record.

        A task carries at most one canonical result. Everything that describes what
        arrived is fixed at ingestion: the result identity, its task and claim
        association, its source, its summary, its evidence identifiers, and the time it
        was received. `received_at` is an ingestion fact and never an advancing update
        stamp, so a later write cannot move it.

        The single permitted change is the one transition from `UNVERIFIED` to a checked
        verification state, which the verification operation makes. Writing the identical
        record again succeeds and changes nothing; writing a different one fails closed
        rather than overwriting what is stored.

        Which task states can carry an answer is decided by `assert_result_matches_task`,
        not restated here: `ACCEPTED`, where the provider took the request, and
        `UNKNOWN_OUTCOME`, which is the state a late answer resolves. Delivery is not the
        test, because a `PARTIAL` failure is an unknown outcome whether or not the request
        was recorded as submitted. A routing or request acknowledgement is not an answer
        in any of those states.

        Args:
            result: Returned-result state to ingest or advance to a checked verification.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The claim is unavailable, the named task is not on that claim or
                never reached the provider, or a named evidence record does not exist or
                is not linked to that same task.
            IdempotencyConflict: The write changes an ingestion fact, contradicts a
                verification already recorded, or adds a second result to a task.
        """
        raise NotImplementedError

    def list_external_tasks_internal(self, claim_id: str) -> list[ExternalTaskRecord]:
        """List task records after an internal caller authorises the claim read.

        Args:
            claim_id: Working Claim whose tasks are requested.

        Returns:
            Task records in stable creation order.

        Raises:
            RuntimeError: A configured persistence provider cannot complete the read.
        """
        raise NotImplementedError

    def list_external_task_attempts_internal(
        self,
        claim_id: str,
    ) -> list[ExternalTaskAttempt]:
        """List append-only external-task attempts for an authorised Claim read."""
        raise NotImplementedError

    def list_external_task_results_internal(self, claim_id: str) -> list[ExternalTaskResult]:
        """List returned results for an authorised internal projection.

        Args:
            claim_id: Working Claim whose external task results are requested.

        Returns:
            Result records in a stable order, oldest ingestion first.

        Raises:
            RuntimeError: A configured persistence provider cannot complete the read.
        """
        raise NotImplementedError

    def list_external_task_evidence_links_internal(
        self,
        claim_id: str,
    ) -> list[ExternalTaskEvidenceLink]:
        """List task-to-evidence links for an authorised internal projection.

        Args:
            claim_id: Working Claim whose evidence links are requested.

        Returns:
            Claim-scoped links in stable linkage order.

        Raises:
            RuntimeError: A configured persistence provider cannot complete the read.
        """
        raise NotImplementedError

    def save_retrieval_bundle(
        self,
        record: RetrievalRecord,
        review_signals: list[ReviewSignalRecord],
        customer_id: str,
    ) -> None:
        """Atomically persist one retrieval record and its review-only signals."""
        raise NotImplementedError

    def list_retrieval_records(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[RetrievalRecord]:
        raise NotImplementedError

    def list_review_signals(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[ReviewSignalRecord]:
        raise NotImplementedError

    def list_staff_actions(self, claim_id: str) -> list[StaffActionRecord]:
        raise NotImplementedError

    def get_staff_presence(self, staff_id: str) -> StaffPresenceRecord | None:
        raise NotImplementedError

    def list_staff_presence(self) -> list[StaffPresenceRecord]:
        raise NotImplementedError

    def save_staff_presence(
        self, presence: StaffPresenceRecord, expected_revision: int | None = None
    ) -> None:
        raise NotImplementedError

    def get_staff_action(self, claim_id: str, action_id: str) -> StaffActionRecord | None:
        raise NotImplementedError

    def list_customer_updates(self, claim_id: str) -> list[CustomerUpdateRecord]:
        raise NotImplementedError

    def list_signal_decisions(self, claim_id: str) -> list[SignalDecisionRecord]:
        raise NotImplementedError

    def get_claim_decision(self, claim_id: str, decision_id: str) -> ClaimDecisionRecord | None:
        raise NotImplementedError

    def list_collaboration_requests(self, claim_id: str) -> list[ClaimCollaborationRequest]:
        raise NotImplementedError

    def list_claim_coworkers(self, claim_id: str) -> list[ClaimCoworkerRecord]:
        raise NotImplementedError

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
        """Atomically persist ownership records and any linked handoff audit fact."""
        raise NotImplementedError

    def save_staff_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        *,
        staff_action: StaffActionRecord | None = None,
        customer_update: CustomerUpdateRecord | None = None,
        signal_decision: SignalDecisionRecord | None = None,
        claim_decision: ClaimDecisionRecord | None = None,
        handoff: HandoffRecord | None = None,
        message: MessageRecord | None = None,
        required_staff_id: str | None = None,
        required_staff_revision: int | None = None,
        audit_event: AuditEventEnvelope | None = None,
        staff_agent_execution: StaffAgentExecutionRecord | None = None,
    ) -> None:
        """Atomically persist staff write-back, guarded presence, audit, and replay.

        The registered ownership.accept_claim action alone may omit child business
        records; it requires a matching audit and presence guard and may change only
        the unassigned, created Claim's owner, revision, and update timestamp.
        Staff messages require a matching claimant-message action audit whether or not
        the same mutation also progresses an accepted handoff.
        """
        raise NotImplementedError

    def save_handoff(self, handoff: HandoffRecord, customer_id: str) -> None:
        raise NotImplementedError

    def get_handoff(
        self,
        claim_id: str,
        handoff_id: str,
        customer_id: str,
    ) -> HandoffRecord | None:
        raise NotImplementedError

    def list_handoffs(self, claim_id: str, customer_id: str) -> list[HandoffRecord]:
        raise NotImplementedError

    def save_handoff_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        handoff: HandoffRecord,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
        branch_evaluation: BranchEvaluationRecord | None = None,
        *,
        safety_message: MessageRecord | None = None,
    ) -> None:
        """Atomically persist a handoff, Claim revision, retry metadata, and audit fact."""
        raise NotImplementedError
