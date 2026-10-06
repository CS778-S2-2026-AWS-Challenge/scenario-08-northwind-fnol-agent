from contextlib import AbstractContextManager
from typing import Protocol

from backend.domain.identity import ClaimantAuthSessionRecord, CustomerAccountRecord
from backend.repositories.protocols import RepositoryConflict


class DuplicateEmailConflict(RepositoryConflict):
    """Another claimant account owns the normalized email address."""


class IdentityRepository(Protocol):
    def ensure_seed_account(
        self, customer_id: str, email: str, password: str, display_name: str
    ) -> CustomerAccountRecord: ...

    def list_accounts(self) -> list[CustomerAccountRecord]: ...

    def authenticate(self, email: str, password: str) -> CustomerAccountRecord | None: ...

    def create_account(
        self, email: str, password: str, display_name: str, phone: str = ''
    ) -> CustomerAccountRecord | None: ...

    def get_account(self, customer_id: str) -> CustomerAccountRecord | None: ...

    def hold_account_revision(
        self, customer_id: str, expected_revision: int
    ) -> AbstractContextManager[CustomerAccountRecord]: ...

    def save_account(self, account: CustomerAccountRecord, expected_revision: int) -> None: ...

    def save_session(self, session: ClaimantAuthSessionRecord) -> None: ...

    def get_session(self, token_hash: str) -> ClaimantAuthSessionRecord | None: ...

    def revoke_session(self, token_hash: str) -> bool: ...

    def list_sessions(self, customer_id: str) -> list[ClaimantAuthSessionRecord]: ...

    def get_session_by_id(self, session_id: str) -> ClaimantAuthSessionRecord | None: ...

    def revoke_session_by_id(
        self, session_id: str, expected_revision: int
    ) -> ClaimantAuthSessionRecord: ...
