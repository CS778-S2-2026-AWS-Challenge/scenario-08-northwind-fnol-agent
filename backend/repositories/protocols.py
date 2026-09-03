from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from backend.domain.audit import AuditEventEnvelope, AuditSubject
from backend.domain.external_services import (
    ExternalTaskEvidenceLink,
    ExternalTaskRecord,
    ExternalTaskRequest,
)
from backend.domain.models import (
    AgentDecisionRecord,
    AssessorRoutingOperation,
    CustomerUpdateRecord,
    EvidenceRecord,
    HandoffRecord,
    MessageRecord,
    SessionRecord,
    SignalDecisionRecord,
    StaffActionRecord,
    WorkingClaim,
)
from backend.domain.retrieval import RetrievalRecord, ReviewSignalRecord


class RepositoryConflict(Exception):
    """Base class for persistence conflicts exposed by the application layer."""


class RevisionConflict(RepositoryConflict):
    def __init__(self, current_revision: int) -> None:
        super().__init__(f'Current revision is {current_revision}.')
        self.current_revision = current_revision


class IdempotencyConflict(RepositoryConflict):
    pass


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
    handoff_id: str | None = None
    response_payload: dict[str, Any] | None = None


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

    def save_claim(self, claim: WorkingClaim, expected_revision: int) -> None:
        raise NotImplementedError

    def save_claim_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
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
    ) -> None:
        """Atomically persist a resumed session, claim revision, and retry metadata."""
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

    def save_claim_mutation_with_audit(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        audit_events: tuple[AuditEventEnvelope, ...],
    ) -> None:
        """Atomically persist a claim mutation, retry metadata, and audit facts.

        Args:
            claim: Resulting authoritative Claim State.
            expected_revision: Revision that must still be current.
            idempotency: Retry metadata for the accepted mutation.
            audit_events: Immutable audit facts produced by the same mutation.

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

    def save_assessor_routing_preparation(
        self,
        operation: AssessorRoutingOperation,
        decision: AgentDecisionRecord,
        customer_id: str,
    ) -> None:
        """Atomically persist routing authority and its immutable operation identity."""
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
    ) -> None:
        """Atomically persist one validated Agent turn."""
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

    def get_staff_action(self, claim_id: str, action_id: str) -> StaffActionRecord | None:
        raise NotImplementedError

    def list_customer_updates(self, claim_id: str) -> list[CustomerUpdateRecord]:
        raise NotImplementedError

    def list_signal_decisions(self, claim_id: str) -> list[SignalDecisionRecord]:
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
    ) -> None:
        """Atomically persist a handoff, shared claim state, and retry metadata."""
        raise NotImplementedError
