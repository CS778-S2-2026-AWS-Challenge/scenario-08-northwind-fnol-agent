from copy import deepcopy

from backend.domain.models import SessionRecord, WorkingClaim
from backend.repositories.protocols import (
    ClaimRepository,
    IdempotencyConflict,
    IdempotencyRecord,
    RevisionConflict,
)


class FixtureRepository(ClaimRepository):
    """In-memory repository used by the prototype and replaceable contract tests."""

    def __init__(self) -> None:
        self._claims: dict[str, WorkingClaim] = {}
        self._sessions: dict[str, SessionRecord] = {}
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
        self._sessions[session.session_id] = deepcopy(session)

    def get_active_session(self, claim_id: str, customer_id: str) -> SessionRecord | None:
        claim = self.get_claim(claim_id, customer_id)
        if claim is None or claim.active_session_id is None:
            return None
        return self.get_session(claim_id, claim.active_session_id, customer_id)

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
