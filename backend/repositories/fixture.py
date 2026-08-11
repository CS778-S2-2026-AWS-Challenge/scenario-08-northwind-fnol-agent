from copy import deepcopy

from backend.domain.models import EvidenceRecord, MessageRecord, SessionRecord, WorkingClaim
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
        self._evidence: dict[str, EvidenceRecord] = {}
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
        if self.get_claim(message.claim_id, customer_id) is None:
            raise KeyError(message.claim_id)
        self._messages[message.message_id] = deepcopy(message)

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
