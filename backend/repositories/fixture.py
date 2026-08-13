from copy import deepcopy

from backend.domain.models import (
    ActorType,
    AgentDecisionRecord,
    CustomerUpdateRecord,
    EvidenceRecord,
    MessageRecord,
    SessionRecord,
    SignalDecisionRecord,
    StaffActionRecord,
    WorkingClaim,
)
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
        self._evidence: dict[str, EvidenceRecord] = {}
        self._staff_actions: dict[str, StaffActionRecord] = {}
        self._customer_updates: dict[str, CustomerUpdateRecord] = {}
        self._signal_decisions: dict[str, SignalDecisionRecord] = {}
        self._idempotency: dict[tuple[str, str, str], IdempotencyRecord] = {}

    @property
    def claim_count(self) -> int:
        return len(self._claims)

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
        stored_claim = self._claims.get(claim.claim_id)
        if stored_claim is None:
            raise KeyError(claim.claim_id)
        if stored_claim.revision != expected_revision:
            raise RevisionConflict(stored_claim.revision)
        self._claims[claim.claim_id] = deepcopy(claim)

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
        return sorted(messages, key=lambda message: message.created_at)

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

    def save_agent_turn(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        claimant_message: MessageRecord,
        agent_message: MessageRecord,
        decision: AgentDecisionRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        stored_claim = self._claims.get(claim.claim_id)
        stored_session = self._sessions.get(session.session_id)
        if stored_claim is None:
            raise KeyError(claim.claim_id)
        if stored_claim.revision != expected_revision:
            raise RevisionConflict(stored_claim.revision)
        records_match = (
            stored_claim.customer_id == claim.customer_id
            and stored_session is not None
            and stored_session.claim_id == claim.claim_id
            and stored_session.customer_id == claim.customer_id
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
        )
        if not records_match:
            raise KeyError(claim.claim_id)
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
        stored_claim = self._claims.get(claim.claim_id)
        if stored_claim is None:
            raise KeyError(claim.claim_id)
        if stored_claim.revision != expected_revision:
            raise RevisionConflict(stored_claim.revision)
        if (
            evidence.claim_id != claim.claim_id
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
    ) -> None:
        stored = self._claims.get(claim.claim_id)
        if stored is None:
            raise KeyError(claim.claim_id)
        if stored.revision != expected_revision:
            raise RevisionConflict(stored.revision)
        if not any((staff_action, customer_update, signal_decision)):
            raise KeyError(claim.claim_id)
        records = (staff_action, customer_update, signal_decision)
        if any(item is not None and item.claim_id != claim.claim_id for item in records):
            raise KeyError(claim.claim_id)
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
        self._idempotency[lookup] = deepcopy(idempotency)
