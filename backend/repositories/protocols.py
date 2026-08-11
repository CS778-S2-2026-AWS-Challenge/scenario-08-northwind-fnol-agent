from dataclasses import dataclass
from typing import Protocol

from backend.domain.models import EvidenceRecord, MessageRecord, SessionRecord, WorkingClaim


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


class ClaimRepository(Protocol):
    def create_claim(self, claim: WorkingClaim, session: SessionRecord) -> None:
        raise NotImplementedError

    def get_claim(self, claim_id: str, customer_id: str) -> WorkingClaim | None:
        raise NotImplementedError

    def save_claim(self, claim: WorkingClaim, expected_revision: int) -> None:
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

    def get_active_session(self, claim_id: str, customer_id: str) -> SessionRecord | None:
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

    def list_claims_for_customer(self, customer_id: str) -> list[WorkingClaim]:
        raise NotImplementedError

    def save_message(self, message: MessageRecord, customer_id: str) -> None:
        raise NotImplementedError

    def list_messages(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> list[MessageRecord]:
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
