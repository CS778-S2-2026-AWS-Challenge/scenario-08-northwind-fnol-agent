from copy import deepcopy

from backend.domain.external_services import (
    ExternalTaskEvidenceLink,
    ExternalTaskRecord,
    ExternalTaskRequest,
    assert_disclosure_within_consent,
    assert_request_matches_task,
)
from backend.domain.models import (
    ActorType,
    AgentDecisionRecord,
    AssessorRoutingOperation,
    AssessorRoutingOperationStatus,
    AuthorityOutcome,
    CustomerUpdateRecord,
    EvidenceRecord,
    HandoffRecord,
    MessageRecord,
    SessionRecord,
    SessionStatus,
    SignalDecisionRecord,
    StaffActionRecord,
    StaffActionStatus,
    WorkingClaim,
)
from backend.domain.retrieval import RetrievalRecord, ReviewSignalRecord
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)


class FixtureRepository(PersistenceRepository):
    """In-memory repository used by the prototype and replaceable contract tests."""

    def __init__(self) -> None:
        self._claims: dict[str, WorkingClaim] = {}
        self._sessions: dict[str, SessionRecord] = {}
        self._messages: dict[str, MessageRecord] = {}
        self._decisions: dict[str, AgentDecisionRecord] = {}
        self._assessor_routing_operations: dict[str, AssessorRoutingOperation] = {}
        self._evidence: dict[str, EvidenceRecord] = {}
        self._external_tasks: dict[str, ExternalTaskRecord] = {}
        self._external_task_requests: dict[str, ExternalTaskRequest] = {}
        self._external_task_evidence_links: dict[tuple[str, str], ExternalTaskEvidenceLink] = {}
        self._retrievals: dict[str, RetrievalRecord] = {}
        self._review_signals: dict[str, ReviewSignalRecord] = {}
        self._staff_actions: dict[str, StaffActionRecord] = {}
        self._customer_updates: dict[str, CustomerUpdateRecord] = {}
        self._signal_decisions: dict[str, SignalDecisionRecord] = {}
        self._handoffs: dict[str, HandoffRecord] = {}
        self._idempotency: dict[tuple[str, str, str], IdempotencyRecord] = {}

    @property
    def claim_count(self) -> int:
        return len(self._claims)

    def reset_demo_state(self) -> dict[str, int]:
        """Clear only records owned by this in-memory prototype repository."""
        cleared = {
            'claims': len(self._claims),
            'sessions': len(self._sessions),
            'messages': len(self._messages),
            'agent_decisions': len(self._decisions),
            'assessor_routing_operations': len(self._assessor_routing_operations),
            'evidence': len(self._evidence),
            'external_tasks': len(self._external_tasks),
            'external_task_requests': len(self._external_task_requests),
            'external_task_evidence_links': len(self._external_task_evidence_links),
            'retrievals': len(self._retrievals),
            'review_signals': len(self._review_signals),
            'staff_actions': len(self._staff_actions),
            'customer_updates': len(self._customer_updates),
            'signal_decisions': len(self._signal_decisions),
            'handoffs': len(self._handoffs),
            'idempotency_records': len(self._idempotency),
        }
        self._claims.clear()
        self._sessions.clear()
        self._messages.clear()
        self._decisions.clear()
        self._assessor_routing_operations.clear()
        self._evidence.clear()
        self._external_tasks.clear()
        self._external_task_requests.clear()
        self._external_task_evidence_links.clear()
        self._retrievals.clear()
        self._review_signals.clear()
        self._staff_actions.clear()
        self._customer_updates.clear()
        self._signal_decisions.clear()
        self._handoffs.clear()
        self._idempotency.clear()
        return cleared

    def create_claim(self, claim: WorkingClaim, session: SessionRecord) -> None:
        self._claims[claim.claim_id] = deepcopy(claim)
        self._sessions[session.session_id] = deepcopy(session)

    def get_claim(self, claim_id: str, customer_id: str) -> WorkingClaim | None:
        claim = self._claims.get(claim_id)
        if claim is None or claim.customer_id != customer_id:
            return None
        return deepcopy(claim)

    def get_claim_internal(self, claim_id: str) -> WorkingClaim | None:
        claim = self._claims.get(claim_id)
        return deepcopy(claim) if claim is not None else None

    def save_claim(self, claim: WorkingClaim, expected_revision: int) -> None:
        self._validate_claim_mutation(claim, expected_revision)
        self._claims[claim.claim_id] = deepcopy(claim)

    def _validate_claim_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        *,
        allow_active_session_change: bool = False,
    ) -> WorkingClaim:
        """Validate the shared Claim State precondition before any child write."""
        stored_claim = self._claims.get(claim.claim_id)
        if stored_claim is None:
            raise KeyError(claim.claim_id)
        if stored_claim.revision != expected_revision:
            raise RevisionConflict(stored_claim.revision)
        if stored_claim.customer_id != claim.customer_id or claim.revision != expected_revision + 1:
            raise KeyError(claim.claim_id)
        if (
            not allow_active_session_change
            and stored_claim.active_session_id != claim.active_session_id
        ):
            raise KeyError(claim.claim_id)
        return stored_claim

    def save_claim_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
    ) -> None:
        self._validate_claim_mutation(claim, expected_revision)
        if (
            idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != (claim.active_session_id or '')
        ):
            raise KeyError(claim.claim_id)
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        if lookup in self._idempotency:
            raise IdempotencyConflict(idempotency.key)

        self._claims[claim.claim_id] = deepcopy(claim)
        self._idempotency[lookup] = deepcopy(idempotency)

    def get_session(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> SessionRecord | None:
        session = self._sessions.get(session_id)
        if session is None or session.claim_id != claim_id or session.customer_id != customer_id:
            return None
        return deepcopy(session)

    def save_session(self, session: SessionRecord) -> None:
        claim = self._claims.get(session.claim_id)
        if claim is None or claim.customer_id != session.customer_id:
            raise KeyError(session.claim_id)
        self._sessions[session.session_id] = deepcopy(session)

    def save_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        stored_claim = self._validate_claim_mutation(
            claim,
            expected_revision,
            allow_active_session_change=True,
        )
        records_match = (
            stored_claim.customer_id == claim.customer_id
            and claim.active_session_id == session.session_id
            and session.claim_id == claim.claim_id
            and session.customer_id == claim.customer_id
            and session.status is SessionStatus.ACTIVE
            and session.context_revision == expected_revision
            and idempotency.actor_id == claim.customer_id
            and idempotency.claim_id == claim.claim_id
            and idempotency.session_id == session.session_id
        )
        if not records_match:
            raise KeyError(claim.claim_id)
        if session.session_id in self._sessions:
            raise IdempotencyConflict(session.session_id)
        if any(
            existing.claim_id == claim.claim_id and existing.status is SessionStatus.ACTIVE
            for existing in self._sessions.values()
        ):
            raise KeyError(claim.claim_id)
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        if self._idempotency.get(lookup) is not None:
            raise IdempotencyConflict(idempotency.key)

        self._claims[claim.claim_id] = deepcopy(claim)
        self._sessions[session.session_id] = deepcopy(session)
        self._idempotency[lookup] = deepcopy(idempotency)

    def get_active_session(self, claim_id: str, customer_id: str) -> SessionRecord | None:
        claim = self.get_claim(claim_id, customer_id)
        if claim is None or claim.active_session_id is None:
            return None
        return self.get_session(claim_id, claim.active_session_id, customer_id)

    def list_sessions_for_claim(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[SessionRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        sessions = [
            deepcopy(session)
            for session in self._sessions.values()
            if session.claim_id == claim_id and session.customer_id == customer_id
        ]
        return sorted(sessions, key=lambda session: session.started_at)

    def find_idempotency(
        self,
        actor_id: str,
        route: str,
        key: str,
    ) -> IdempotencyRecord | None:
        return self._idempotency.get((actor_id, route, key))

    def save_idempotency(self, record: IdempotencyRecord) -> None:
        lookup = (record.actor_id, record.route, record.key)
        existing = self._idempotency.get(lookup)
        if existing is not None and existing.request_fingerprint != record.request_fingerprint:
            raise IdempotencyConflict(record.key)
        self._idempotency[lookup] = record

    def list_claims_for_customer(self, customer_id: str) -> list[WorkingClaim]:
        claims = [
            deepcopy(claim) for claim in self._claims.values() if claim.customer_id == customer_id
        ]
        return sorted(claims, key=lambda claim: claim.created_at)

    def list_claims_internal(self) -> list[WorkingClaim]:
        return sorted(
            (deepcopy(claim) for claim in self._claims.values()),
            key=lambda claim: claim.updated_at,
            reverse=True,
        )

    def save_message(self, message: MessageRecord, customer_id: str) -> None:
        if (
            self.get_claim(message.claim_id, customer_id) is None
            or self.get_session(
                message.claim_id,
                message.session_id,
                customer_id,
            )
            is None
        ):
            raise KeyError(message.claim_id)
        self._messages[message.message_id] = deepcopy(message)

    def save_message_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        message: MessageRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        stored_claim = self._validate_claim_mutation(claim, expected_revision)
        stored_session = self._sessions.get(session.session_id)
        records_match = (
            stored_session is not None
            and stored_claim.active_session_id == session.session_id
            and stored_session.claim_id == claim.claim_id
            and stored_session.customer_id == claim.customer_id
            and stored_session.status is SessionStatus.ACTIVE
            and claim.active_session_id == session.session_id
            and session.claim_id == claim.claim_id
            and session.customer_id == claim.customer_id
            and session.status is SessionStatus.ACTIVE
            and session.context_revision == claim.revision
            and message.claim_id == claim.claim_id
            and message.session_id == session.session_id
            and message.actor is ActorType.CLAIMANT
            and idempotency.actor_id == claim.customer_id
            and idempotency.claim_id == claim.claim_id
            and idempotency.session_id == session.session_id
            and idempotency.message_id == message.message_id
        )
        if not records_match:
            raise KeyError(claim.claim_id)
        if message.message_id in self._messages:
            raise IdempotencyConflict(message.message_id)
        if message.client_message_id is not None and any(
            existing.claim_id == claim.claim_id
            and existing.client_message_id == message.client_message_id
            for existing in self._messages.values()
        ):
            raise IdempotencyConflict(message.client_message_id)
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing = self._idempotency.get(lookup)
        if existing is not None and existing.request_fingerprint != idempotency.request_fingerprint:
            raise IdempotencyConflict(idempotency.key)
        self._claims[claim.claim_id] = deepcopy(claim)
        self._sessions[session.session_id] = deepcopy(session)
        self._messages[message.message_id] = deepcopy(message)
        self._idempotency[lookup] = deepcopy(idempotency)

    def get_message(
        self,
        claim_id: str,
        session_id: str,
        message_id: str,
        customer_id: str,
    ) -> MessageRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        message = self._messages.get(message_id)
        if message is None or message.claim_id != claim_id or message.session_id != session_id:
            return None
        return deepcopy(message)

    def find_message_by_client_id(
        self,
        claim_id: str,
        client_message_id: str,
        customer_id: str,
    ) -> MessageRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        for message in self._messages.values():
            if message.claim_id == claim_id and message.client_message_id == client_message_id:
                return deepcopy(message)
        return None

    def list_messages(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> list[MessageRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        messages = [
            deepcopy(message)
            for message in self._messages.values()
            if message.claim_id == claim_id and message.session_id == session_id
        ]
        return sorted(messages, key=lambda message: (message.created_at, message.message_id))

    def save_agent_decision(self, decision: AgentDecisionRecord, customer_id: str) -> None:
        if (
            self.get_claim(decision.claim_id, customer_id) is None
            or self.get_session(
                decision.claim_id,
                decision.session_id,
                customer_id,
            )
            is None
        ):
            raise KeyError(decision.claim_id)
        self._decisions[decision.decision_id] = deepcopy(decision)

    def get_assessor_routing_operation(
        self,
        operation_id: str,
    ) -> AssessorRoutingOperation | None:
        operation = self._assessor_routing_operations.get(operation_id)
        return deepcopy(operation) if operation is not None else None

    def save_assessor_routing_operation(
        self,
        operation: AssessorRoutingOperation,
    ) -> None:
        claim = self._claims.get(operation.claim_id)
        if (
            claim is None
            or claim.external_claim is None
            or claim.external_claim.external_claim_id != operation.external_claim_id
            or operation.authorised_revision > claim.revision
        ):
            raise KeyError(operation.claim_id)

        existing = self._assessor_routing_operations.get(operation.operation_id)
        if existing is None:
            if operation.status is not AssessorRoutingOperationStatus.PREPARED:
                raise IdempotencyConflict(operation.operation_id)
            self._assessor_routing_operations[operation.operation_id] = deepcopy(operation)
            return

        immutable_identity = (
            'claim_id',
            'external_claim_id',
            'authorisation_ref',
            'claimant_consent_ref',
            'requested_action',
            'authorised_revision',
            'request_fingerprint',
            'created_at',
        )
        if any(
            getattr(existing, field_name) != getattr(operation, field_name)
            for field_name in immutable_identity
        ):
            raise IdempotencyConflict(operation.operation_id)
        if operation.updated_at < existing.updated_at:
            raise IdempotencyConflict(operation.operation_id)
        if existing.status in {
            AssessorRoutingOperationStatus.ACCEPTED,
            AssessorRoutingOperationStatus.TERMINAL_FAILURE,
        }:
            if existing != operation:
                raise IdempotencyConflict(operation.operation_id)
            return
        allowed_statuses = {
            AssessorRoutingOperationStatus.RETRYABLE_FAILURE,
            AssessorRoutingOperationStatus.TERMINAL_FAILURE,
            AssessorRoutingOperationStatus.ACCEPTED,
        }
        if operation.status not in allowed_statuses:
            if existing != operation:
                raise IdempotencyConflict(operation.operation_id)
            return
        self._assessor_routing_operations[operation.operation_id] = deepcopy(operation)

    def save_assessor_routing_preparation(
        self,
        operation: AssessorRoutingOperation,
        decision: AgentDecisionRecord,
        customer_id: str,
    ) -> None:
        claim = self._claims.get(operation.claim_id)
        session = self._sessions.get(decision.session_id)
        if (
            claim is None
            or claim.customer_id != customer_id
            or claim.active_session_id != decision.session_id
            or session is None
            or session.claim_id != claim.claim_id
            or session.customer_id != customer_id
            or claim.external_claim is None
            or claim.external_claim.external_claim_id != operation.external_claim_id
            or operation.status is not AssessorRoutingOperationStatus.PREPARED
            or operation.authorised_revision != claim.revision
            or decision.claim_id != claim.claim_id
            or decision.decision_id != operation.authorisation_ref
            or decision.resulting_revision != operation.authorised_revision
            or decision.authority.outcome is not AuthorityOutcome.AUTHORISED
            or 'ASSESSOR_RULE_AUTHORISED' not in decision.reason_codes
        ):
            raise KeyError(operation.claim_id)

        existing_operation = self._assessor_routing_operations.get(operation.operation_id)
        existing_decision = self._decisions.get(decision.decision_id)
        if existing_operation is not None or existing_decision is not None:
            if existing_operation == operation and existing_decision == decision:
                return
            raise IdempotencyConflict(operation.operation_id)

        self._decisions[decision.decision_id] = deepcopy(decision)
        self._assessor_routing_operations[operation.operation_id] = deepcopy(operation)

    def get_agent_decision(
        self,
        claim_id: str,
        decision_id: str,
        customer_id: str,
    ) -> AgentDecisionRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        decision = self._decisions.get(decision_id)
        if decision is None or decision.claim_id != claim_id:
            return None
        return deepcopy(decision)

    def get_agent_decision_internal(
        self,
        claim_id: str,
        decision_id: str,
    ) -> AgentDecisionRecord | None:
        decision = self._decisions.get(decision_id)
        if decision is None or decision.claim_id != claim_id:
            return None
        return deepcopy(decision)

    def find_agent_decision_for_trigger(
        self,
        claim_id: str,
        trigger_message_id: str,
        customer_id: str,
    ) -> AgentDecisionRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        for decision in self._decisions.values():
            if decision.claim_id == claim_id and decision.trigger_message_id == trigger_message_id:
                return deepcopy(decision)
        return None

    def list_agent_decisions(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[AgentDecisionRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        decisions = [
            deepcopy(decision)
            for decision in self._decisions.values()
            if decision.claim_id == claim_id
        ]
        return sorted(
            decisions,
            key=lambda decision: (
                decision.resulting_revision,
                decision.created_at,
                decision.decision_id,
            ),
        )

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
        stored_claim = self._validate_claim_mutation(claim, expected_revision)
        stored_session = self._sessions.get(session.session_id)
        existing_claimant_message = self._messages.get(claimant_message.message_id)
        existing_agent_message = self._messages.get(agent_message.message_id)
        existing_decision = self._decisions.get(decision.decision_id)
        existing_handoff = self._handoffs.get(handoff.handoff_id) if handoff is not None else None
        existing_evidence = (
            self._evidence.get(evidence.evidence_id) if evidence is not None else None
        )
        existing_children = (
            existing_claimant_message,
            existing_agent_message,
            existing_decision,
            existing_handoff,
            existing_evidence,
        )
        child_ownership_matches = all(
            existing is None or existing.claim_id == claim.claim_id
            for existing in existing_children
        )
        records_match = (
            child_ownership_matches
            and claimant_message.message_id != agent_message.message_id
            and stored_claim.customer_id == claim.customer_id
            and stored_session is not None
            and stored_session.claim_id == claim.claim_id
            and stored_session.customer_id == claim.customer_id
            and stored_session.status is SessionStatus.ACTIVE
            and stored_claim.active_session_id == session.session_id
            and claim.active_session_id == session.session_id
            and session.status is SessionStatus.ACTIVE
            and claim.customer_id == session.customer_id
            and idempotency.actor_id == claim.customer_id
            and claim.claim_id == session.claim_id
            and claim.claim_id == claimant_message.claim_id
            and claim.claim_id == agent_message.claim_id
            and claim.claim_id == decision.claim_id
            and session.session_id == claimant_message.session_id
            and session.session_id == agent_message.session_id
            and session.session_id == decision.session_id
            and session.context_revision == claim.revision
            and decision.resulting_revision == claim.revision
            and claimant_message.actor is ActorType.CLAIMANT
            and agent_message.actor is ActorType.AGENT
            and claimant_message.message_id == decision.trigger_message_id
            and claimant_message.message_id == agent_message.in_reply_to
            and idempotency.claim_id == claim.claim_id
            and idempotency.session_id == session.session_id
            and idempotency.message_id == claimant_message.message_id
            and idempotency.agent_message_id == agent_message.message_id
            and idempotency.decision_id == decision.decision_id
            and (handoff is None or handoff.claim_id == claim.claim_id)
            and (handoff is None or idempotency.handoff_id == handoff.handoff_id)
            and decision.handoff_id == (handoff.handoff_id if handoff is not None else None)
            and (evidence is None or evidence.claim_id == claim.claim_id)
        )
        if not records_match:
            raise KeyError(claim.claim_id)
        immutable_collision = next(
            (
                identity
                for identity, existing in (
                    (claimant_message.message_id, existing_claimant_message),
                    (agent_message.message_id, existing_agent_message),
                    (decision.decision_id, existing_decision),
                )
                if existing is not None
            ),
            None,
        )
        if immutable_collision is not None:
            raise IdempotencyConflict(immutable_collision)
        duplicate_client_message = next(
            (
                message
                for message in self._messages.values()
                if message.claim_id == claim.claim_id
                and message.client_message_id == claimant_message.client_message_id
            ),
            None,
        )
        if duplicate_client_message is not None:
            raise IdempotencyConflict(claimant_message.client_message_id or '')
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing_idempotency = self._idempotency.get(lookup)
        if (
            existing_idempotency is not None
            and existing_idempotency.request_fingerprint != idempotency.request_fingerprint
        ):
            raise IdempotencyConflict(idempotency.key)

        self._claims[claim.claim_id] = deepcopy(claim)
        self._sessions[session.session_id] = deepcopy(session)
        self._messages[claimant_message.message_id] = deepcopy(claimant_message)
        self._messages[agent_message.message_id] = deepcopy(agent_message)
        self._decisions[decision.decision_id] = deepcopy(decision)
        if handoff is not None:
            self._handoffs[handoff.handoff_id] = deepcopy(handoff)
        if evidence is not None:
            self._evidence[evidence.evidence_id] = deepcopy(evidence)
        self._idempotency[lookup] = idempotency

    def save_evidence(self, evidence: EvidenceRecord, customer_id: str) -> None:
        if self.get_claim(evidence.claim_id, customer_id) is None:
            raise KeyError(evidence.claim_id)
        self._evidence[evidence.evidence_id] = deepcopy(evidence)

    def get_evidence(
        self,
        claim_id: str,
        evidence_id: str,
        customer_id: str,
    ) -> EvidenceRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        evidence = self._evidence.get(evidence_id)
        if evidence is None or evidence.claim_id != claim_id:
            return None
        return deepcopy(evidence)

    def list_evidence(self, claim_id: str, customer_id: str) -> list[EvidenceRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        evidence_records = [
            deepcopy(evidence)
            for evidence in self._evidence.values()
            if evidence.claim_id == claim_id
        ]
        return sorted(evidence_records, key=lambda evidence: evidence.created_at)

    def save_evidence_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        evidence: EvidenceRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        self._validate_claim_mutation(claim, expected_revision)
        existing_evidence = self._evidence.get(evidence.evidence_id)
        if (
            evidence.claim_id != claim.claim_id
            or (existing_evidence is not None and existing_evidence.claim_id != claim.claim_id)
            or idempotency.claim_id != claim.claim_id
            or idempotency.actor_id != claim.customer_id
            or idempotency.session_id != (claim.active_session_id or '')
        ):
            raise KeyError(claim.claim_id)
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing_idempotency = self._idempotency.get(lookup)
        if (
            existing_idempotency is not None
            and existing_idempotency.request_fingerprint != idempotency.request_fingerprint
        ):
            raise IdempotencyConflict(idempotency.key)

        self._claims[claim.claim_id] = deepcopy(claim)
        self._evidence[evidence.evidence_id] = deepcopy(evidence)
        self._idempotency[lookup] = idempotency

    def save_external_task(self, task: ExternalTaskRecord, customer_id: str) -> None:
        """Create or advance one claim-owned external task.

        Args:
            task: External task state to create or advance.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The claim is missing or not owned by the customer.
            IdempotencyConflict: The write changes immutable identity or is stale.
        """
        if self.get_claim(task.claim_id, customer_id) is None:
            raise KeyError(task.claim_id)
        existing = self._external_tasks.get(task.task_id)
        if existing is not None and existing.claim_id != task.claim_id:
            raise IdempotencyConflict(task.task_id)
        immutable_identity = (
            'claim_id',
            'service_identity',
            'requested_action',
            'integration_source',
            'created_at',
        )
        if existing is not None and existing != task:
            changed_identity = any(
                getattr(existing, name) != getattr(task, name) for name in immutable_identity
            )
            if changed_identity or task.updated_at <= existing.updated_at:
                raise IdempotencyConflict(task.task_id)
        self._external_tasks[task.task_id] = deepcopy(task)

    def save_external_task_request(
        self,
        request: ExternalTaskRequest,
        customer_id: str,
    ) -> None:
        """Persist a claim-owned request preparation or its first send record.

        Args:
            request: Request state to create or advance from prepared to sent.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The claim, task, consent, or authority is unavailable.
            IdempotencyConflict: Identity changes, a send is rewritten, or the
                task already has another request.
        """
        claim = self.get_claim(request.claim_id, customer_id)
        task = self._external_tasks.get(request.task_id)
        if claim is None or task is None or task.claim_id != request.claim_id:
            raise KeyError(request.claim_id)
        try:
            assert_request_matches_task(request, task)
        except ValueError as conflict:
            raise IdempotencyConflict(request.request_id) from conflict
        consent = next(
            (
                record
                for record in claim.external_service_consents
                if record.consent_ref == request.authorisation.claimant_consent_ref
            ),
            None,
        )
        decision = self._decisions.get(request.authorisation.northwind_authority_ref)
        if (
            consent is None
            or decision is None
            or decision.claim_id != request.claim_id
            or decision.resulting_revision != request.authorisation.authorised_revision
            or decision.authority.outcome is not AuthorityOutcome.AUTHORISED
        ):
            raise KeyError(request.request_id)
        try:
            assert_disclosure_within_consent(
                request,
                consent,
                claim_customer_id=customer_id,
            )
        except ValueError as conflict:
            raise IdempotencyConflict(request.request_id) from conflict
        for held in self._external_task_requests.values():
            if held.task_id == request.task_id and held.request_id != request.request_id:
                raise IdempotencyConflict(request.task_id)
        existing = self._external_task_requests.get(request.request_id)
        if existing is not None and existing != request:
            immutable_identity = (
                'request_id',
                'task_id',
                'claim_id',
                'service_identity',
                'requested_action',
                'purpose',
                'disclosed_fields',
                'authorisation',
                'prepared_at',
            )
            changed_identity = any(
                getattr(existing, name) != getattr(request, name) for name in immutable_identity
            )
            first_send = (
                existing.sent_at is None
                and existing.operation_id is None
                and request.sent_at is not None
                and request.operation_id is not None
            )
            if changed_identity or not first_send:
                raise IdempotencyConflict(request.request_id)
        self._external_task_requests[request.request_id] = deepcopy(request)

    def list_external_task_requests_internal(
        self,
        claim_id: str,
    ) -> list[ExternalTaskRequest]:
        """List request records for an already-authorised internal claim read.

        Args:
            claim_id: Working Claim whose requests are requested.

        Returns:
            Deep-copied requests in stable preparation order.

        Raises:
            RuntimeError: The in-memory fixture cannot complete the read.
        """
        requests = [
            deepcopy(request)
            for request in self._external_task_requests.values()
            if request.claim_id == claim_id
        ]
        return sorted(requests, key=lambda request: (request.prepared_at, request.request_id))

    def save_external_task_evidence_link(
        self,
        link: ExternalTaskEvidenceLink,
        customer_id: str,
    ) -> None:
        """Save one claim-owned evidence origin after validating its task and record.

        Args:
            link: Task-to-evidence relationship to persist.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The claim, task, or evidence record is missing or not owned.
            IdempotencyConflict: The evidence already has a different origin.
        """
        if self.get_claim(link.claim_id, customer_id) is None:
            raise KeyError(link.claim_id)
        task = self._external_tasks.get(link.task_id)
        if task is None or task.claim_id != link.claim_id:
            raise KeyError(link.task_id)
        if self.get_evidence(link.claim_id, link.evidence_id, customer_id) is None:
            raise KeyError(link.evidence_id)
        key = (link.claim_id, link.evidence_id)
        existing = self._external_task_evidence_links.get(key)
        if existing is not None and existing != link:
            raise IdempotencyConflict(link.evidence_id)
        self._external_task_evidence_links[key] = deepcopy(link)

    def list_external_tasks_internal(self, claim_id: str) -> list[ExternalTaskRecord]:
        """List task records for an already-authorised internal claim read.

        Args:
            claim_id: Working Claim whose tasks are requested.

        Returns:
            Deep-copied task records in stable creation order.

        Raises:
            RuntimeError: The in-memory fixture cannot complete the read.
        """
        tasks = [
            deepcopy(task) for task in self._external_tasks.values() if task.claim_id == claim_id
        ]
        return sorted(tasks, key=lambda task: (task.created_at, task.task_id))

    def list_external_task_evidence_links_internal(
        self,
        claim_id: str,
    ) -> list[ExternalTaskEvidenceLink]:
        """List evidence-origin links for an authorised internal claim read.

        Args:
            claim_id: Working Claim whose evidence links are requested.

        Returns:
            Deep-copied links in stable linkage order.

        Raises:
            RuntimeError: The in-memory fixture cannot complete the read.
        """
        links = [
            deepcopy(link)
            for link in self._external_task_evidence_links.values()
            if link.claim_id == claim_id
        ]
        return sorted(links, key=lambda link: (link.linked_at, link.evidence_id, link.task_id))

    def save_retrieval_bundle(
        self,
        record: RetrievalRecord,
        review_signals: list[ReviewSignalRecord],
        customer_id: str,
    ) -> None:
        if self.get_claim(record.claim_id, customer_id) is None:
            raise KeyError(record.claim_id)
        if any(
            signal.claim_id != record.claim_id or record.retrieval_id not in signal.source_refs
            for signal in review_signals
        ):
            raise KeyError(record.claim_id)

        existing_record = self._retrievals.get(record.retrieval_id)
        if existing_record is not None and existing_record != record:
            raise IdempotencyConflict(record.retrieval_id)

        incoming_signals: dict[str, ReviewSignalRecord] = {}
        for signal in review_signals:
            incoming_signal = incoming_signals.get(signal.signal_id)
            if incoming_signal is not None and incoming_signal != signal:
                raise IdempotencyConflict(signal.signal_id)
            incoming_signals[signal.signal_id] = signal

        for signal in incoming_signals.values():
            existing_signal = self._review_signals.get(signal.signal_id)
            if existing_signal is not None and existing_signal != signal:
                raise IdempotencyConflict(signal.signal_id)

        self._retrievals[record.retrieval_id] = deepcopy(record)
        for signal in incoming_signals.values():
            self._review_signals[signal.signal_id] = deepcopy(signal)

    def list_retrieval_records(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[RetrievalRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        records = [
            deepcopy(record) for record in self._retrievals.values() if record.claim_id == claim_id
        ]
        return sorted(records, key=lambda record: (record.source.retrieved_at, record.retrieval_id))

    def list_review_signals(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[ReviewSignalRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        signals = [
            deepcopy(signal)
            for signal in self._review_signals.values()
            if signal.claim_id == claim_id
        ]
        return sorted(signals, key=lambda signal: (signal.created_at, signal.signal_id))

    def list_staff_actions(self, claim_id: str) -> list[StaffActionRecord]:
        return sorted(
            [deepcopy(item) for item in self._staff_actions.values() if item.claim_id == claim_id],
            key=lambda item: (item.created_at, item.action_id),
        )

    def get_staff_action(self, claim_id: str, action_id: str) -> StaffActionRecord | None:
        action = self._staff_actions.get(action_id)
        if action is None or action.claim_id != claim_id:
            return None
        return deepcopy(action)

    def list_customer_updates(self, claim_id: str) -> list[CustomerUpdateRecord]:
        return sorted(
            [
                deepcopy(item)
                for item in self._customer_updates.values()
                if item.claim_id == claim_id
            ],
            key=lambda item: (item.created_at, item.update_id),
        )

    def list_signal_decisions(self, claim_id: str) -> list[SignalDecisionRecord]:
        return sorted(
            [
                deepcopy(item)
                for item in self._signal_decisions.values()
                if item.claim_id == claim_id
            ],
            key=lambda item: (item.created_at, item.signal_decision_id),
        )

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
        stored_claim = self._validate_claim_mutation(claim, expected_revision)
        if not any((staff_action, customer_update, signal_decision, handoff, message)):
            raise KeyError(claim.claim_id)
        records = (staff_action, customer_update, signal_decision, handoff, message)
        active_session_id = claim.active_session_id or ''
        stored_session = self._sessions.get(active_session_id) if message is not None else None
        existing_staff_action = (
            self._staff_actions.get(staff_action.action_id) if staff_action is not None else None
        )
        existing_customer_update = (
            self._customer_updates.get(customer_update.update_id)
            if customer_update is not None
            else None
        )
        existing_signal_decision = (
            self._signal_decisions.get(signal_decision.signal_decision_id)
            if signal_decision is not None
            else None
        )
        existing_handoff = self._handoffs.get(handoff.handoff_id) if handoff is not None else None
        existing_message = self._messages.get(message.message_id) if message is not None else None
        child_ownership_matches = all(
            existing is None or existing.claim_id == claim.claim_id
            for existing in (
                existing_staff_action,
                existing_customer_update,
                existing_signal_decision,
                existing_handoff,
                existing_message,
            )
        )
        records_match = (
            child_ownership_matches
            and all(item is None or item.claim_id == claim.claim_id for item in records)
            and idempotency.claim_id == claim.claim_id
            and idempotency.session_id in {'', active_session_id}
            and (
                staff_action is None
                or (
                    staff_action.status is not StaffActionStatus.COMPLETED
                    and staff_action.completed_by is None
                )
                or (
                    staff_action.status is StaffActionStatus.COMPLETED
                    and staff_action.completed_by == idempotency.actor_id
                )
            )
            and (customer_update is None or customer_update.created_by == idempotency.actor_id)
            and (signal_decision is None or signal_decision.actor_id == idempotency.actor_id)
            and (handoff is None or idempotency.handoff_id == handoff.handoff_id)
            and (
                message is None
                or (
                    stored_claim.active_session_id == active_session_id
                    and stored_session is not None
                    and stored_session.claim_id == claim.claim_id
                    and stored_session.customer_id == claim.customer_id
                    and stored_session.status is SessionStatus.ACTIVE
                    and message.actor is ActorType.STAFF
                    and message.session_id == active_session_id
                    and message.session_id == idempotency.session_id
                    and idempotency.message_id == message.message_id
                )
            )
        )
        if not records_match:
            raise KeyError(claim.claim_id)
        if existing_message is not None:
            raise IdempotencyConflict(message.message_id if message is not None else '')
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing = self._idempotency.get(lookup)
        if existing is not None and existing.request_fingerprint != idempotency.request_fingerprint:
            raise IdempotencyConflict(idempotency.key)
        self._claims[claim.claim_id] = deepcopy(claim)
        if staff_action is not None:
            self._staff_actions[staff_action.action_id] = deepcopy(staff_action)
        if customer_update is not None:
            self._customer_updates[customer_update.update_id] = deepcopy(customer_update)
        if signal_decision is not None:
            self._signal_decisions[signal_decision.signal_decision_id] = deepcopy(signal_decision)
        if handoff is not None:
            self._handoffs[handoff.handoff_id] = deepcopy(handoff)
        if message is not None:
            self._messages[message.message_id] = deepcopy(message)
        self._idempotency[lookup] = deepcopy(idempotency)

    def save_handoff(self, handoff: HandoffRecord, customer_id: str) -> None:
        if self.get_claim(handoff.claim_id, customer_id) is None:
            raise KeyError(handoff.claim_id)
        self._handoffs[handoff.handoff_id] = deepcopy(handoff)

    def get_handoff(
        self,
        claim_id: str,
        handoff_id: str,
        customer_id: str,
    ) -> HandoffRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        handoff = self._handoffs.get(handoff_id)
        if handoff is None or handoff.claim_id != claim_id:
            return None
        return deepcopy(handoff)

    def list_handoffs(self, claim_id: str, customer_id: str) -> list[HandoffRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        handoffs = [
            deepcopy(handoff) for handoff in self._handoffs.values() if handoff.claim_id == claim_id
        ]
        return sorted(handoffs, key=lambda handoff: handoff.created_at)

    def save_handoff_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        handoff: HandoffRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        self._validate_claim_mutation(claim, expected_revision)
        existing_handoff = self._handoffs.get(handoff.handoff_id)
        if (
            handoff.claim_id != claim.claim_id
            or (existing_handoff is not None and existing_handoff.claim_id != claim.claim_id)
            or idempotency.claim_id != claim.claim_id
            or idempotency.actor_id != claim.customer_id
            or idempotency.session_id != (claim.active_session_id or '')
            or idempotency.handoff_id != handoff.handoff_id
        ):
            raise KeyError(claim.claim_id)
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing_idempotency = self._idempotency.get(lookup)
        if (
            existing_idempotency is not None
            and existing_idempotency.request_fingerprint != idempotency.request_fingerprint
        ):
            raise IdempotencyConflict(idempotency.key)

        self._claims[claim.claim_id] = deepcopy(claim)
        self._handoffs[handoff.handoff_id] = deepcopy(handoff)
        self._idempotency[lookup] = idempotency
