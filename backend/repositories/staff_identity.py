from typing import Protocol

from backend.domain.staff_identity import StaffAccountRecord, StaffAuthSessionRecord


class StaffIdentityRepository(Protocol):
    def list_accounts(self) -> list[StaffAccountRecord]: ...

    def authenticate(self, email: str, password: str) -> StaffAccountRecord | None: ...

    def get_account(self, staff_id: str) -> StaffAccountRecord | None: ...

    def save_account(self, account: StaffAccountRecord, expected_revision: int) -> None: ...

    def create_account(
        self,
        email: str,
        password: str,
        display_name: str,
        roles: tuple[str, ...],
    ) -> StaffAccountRecord | None: ...

    def provision_account(
        self,
        email: str,
        password: str,
        display_name: str,
        roles: tuple[str, ...],
    ) -> StaffAccountRecord: ...

    def save_session(self, session: StaffAuthSessionRecord) -> None: ...

    def get_session(self, token_hash: str) -> StaffAuthSessionRecord | None: ...

    def revoke_session(self, token_hash: str) -> bool: ...

    def list_sessions(self, staff_id: str) -> list[StaffAuthSessionRecord]: ...

    def get_session_by_id(self, session_id: str) -> StaffAuthSessionRecord | None: ...

    def revoke_session_by_id(
        self, session_id: str, expected_revision: int
    ) -> StaffAuthSessionRecord: ...
