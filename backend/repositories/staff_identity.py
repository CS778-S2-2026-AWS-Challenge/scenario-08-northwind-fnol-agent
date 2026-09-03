from typing import Protocol

from backend.domain.staff_identity import StaffAccountRecord, StaffAuthSessionRecord


class StaffIdentityRepository(Protocol):
    def authenticate(self, email: str, password: str) -> StaffAccountRecord | None: ...

    def get_account(self, staff_id: str) -> StaffAccountRecord | None: ...

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
