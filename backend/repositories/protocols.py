from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol

from backend.domain.audit import AuditEventEnvelope, AuditSubject
from backend.domain.external_services import (
    ExternalTaskEvidenceLink,
    ExternalTaskRecord,
    ExternalTaskRequest,
    ExternalTaskResult,
)
from backend.domain.models import (
    AgentDecisionRecord,
    AssessorRoutingOperation,
    BranchEvaluationRecord,
    ClaimCollaborationRequest,
    ClaimCoworkerRecord,
    CustomerUpdateRecord,
    EvidenceRecord,
    FollowUpRecord,
    HandoffRecord,
    MessageRecord,
    RuntimeTraceRecord,
    SessionRecord,
    SessionStatus,
    SignalDecisionRecord,
    StaffActionRecord,
    WorkingClaim,
)
from backend.domain.retrieval import RetrievalRecord, ReviewSignalRecord
from backend.domain.runtime import RuntimeTurnRecords, RuntimeWorkItemRecord
from backend.domain.staff_agent import (
    StaffAgentExecutionRecord,
    StaffAgentMessage,
    StaffAgentMessageRole,
    StaffAgentSession,
)
from backend.domain.staff_identity import StaffPresenceRecord


class RepositoryConflict(Exception):
    """Base class for persistence conflicts exposed by the application layer."""


class RevisionConflict(RepositoryConflict):
    def __init__(self, current_revision: int) -> None:
        super().__init__(f'Current revision is {current_revision}.')
        self.current_revision = current_revision


class IdempotencyConflict(RepositoryConflict):
    pass


class DemoSeedConflict(RepositoryConflict):
    """The controlled validation seed cannot run against a populated queue."""

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
    runtime_trace_id: str | None = None
    handoff_id: str | None = None
    follow_up_id: str | None = None
    action_registry_version: str | None = None
    action_code: str | None = None
    target_ref: str | None = None
    staff_agent_session_id: str | None = None
    staff_agent_message_id: str | None = None
    staff_agent_draft_id: str | None = None
    staff_agent_execution_id: str | None = None
    response_payload: dict[str, Any] | None = None


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
    def create_claim(self, claim: WorkingClaim, session: SessionRecord) -> None:
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
        replaced_active_session: SessionRecord | None = None,
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

    def find_idempotency(
        self,
        actor_id: str,
        route: str,
        key: str,
    ) -> IdempotencyRecord | None:
        raise NotImplementedError

    def save_idempotency(self, record: IdempotencyRecord) -> None:
        raise NotImplementedError


class PersistenceRepository(ClaimRepository, Protocol):
    """Provider-neutral persistence boundary for the full Sprint 1 record set."""

    def seed_validation_graph(self, graph: ValidationSeedGraph) -> IdempotencyRecord | None:
        """Persist the graph, returning an existing idempotent result on replay."""
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

    def get_message(
        self,
        claim_id: str,
        session_id: str,
        message_id: str,
        customer_id: str,
    ) -> MessageRecord | None:
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

    def save_assessor_reconciliation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        task: ExternalTaskRecord,
        operation: AssessorRoutingOperation,
        evidence: EvidenceRecord,
        link: ExternalTaskEvidenceLink,
        branch_evaluation: BranchEvaluationRecord,
        customer_id: str,
    ) -> None:
        """Atomically settle one unknown assessor request as accepted.

        Args:
            claim: Resulting Claim carrying the reconciled routing result.
            expected_revision: Claim revision that must still be current.
            task: Existing external task advanced to accepted.
            operation: Existing assessor operation advanced to accepted.
            evidence: Pending material now owed by the accepted task.
            link: Immutable task-to-evidence relationship for that material.
            branch_evaluation: Applied branch projection for the new Claim revision.
            customer_id: Customer who owns every persisted record.

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
        staff_agent_execution: StaffAgentExecutionRecord | None = None,
    ) -> None:
        """Atomically persist an ownership transition and its collaboration record."""
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
        handoff: HandoffRecord | None = None,
        message: MessageRecord | None = None,
        required_staff_id: str | None = None,
        required_staff_revision: int | None = None,
        staff_agent_execution: StaffAgentExecutionRecord | None = None,
    ) -> None:
        """Atomically persist an authorised staff write-back and shared claim revision."""
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
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        """Atomically persist a handoff, shared claim state, and retry metadata."""
        raise NotImplementedError
