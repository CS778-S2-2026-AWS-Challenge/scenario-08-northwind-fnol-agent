import os
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import scrypt
from hmac import compare_digest
from secrets import token_hex

from backend.domain.staff_identity import StaffAccountRecord, StaffAuthSessionRecord
from backend.repositories.staff_identity import StaffIdentityRepository


def _password_hash(password: str, salt: bytes) -> str:
    digest = scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f'scrypt${salt.hex()}${digest.hex()}'


def _verify_password(encoded: str, password: str) -> bool:
    try:
        scheme, salt_hex, _ = encoded.split('$', 2)
        if scheme != 'scrypt':
            return False
        return compare_digest(_password_hash(password, bytes.fromhex(salt_hex)), encoded)
    except (TypeError, ValueError):
        return False


def _new_account(
    email: str,
    password: str,
    display_name: str,
    roles: tuple[str, ...],
) -> StaffAccountRecord:
    return StaffAccountRecord(
        staff_id=f'stf_{token_hex(8)}',
        email=email.strip().lower(),
        password_hash=_password_hash(password, os.urandom(16)),
        display_name=display_name.strip(),
        roles=roles,
    )


class FixtureStaffIdentityRepository(StaffIdentityRepository):
    """Isolated staff identities for development and automated tests."""

    def __init__(self) -> None:
        account = _new_account(
            'staff.one@example.invalid',
            'northwind-demo-staff',
            'Demo Claims Professional',
            ('claims_professional',),
        )
        account.staff_id = 'stf_demo'
        self._accounts = {account.staff_id: account}
        self._sessions: dict[str, StaffAuthSessionRecord] = {}

    def authenticate(self, email: str, password: str) -> StaffAccountRecord | None:
        normalized = email.strip().lower()
        account = next(
            (item for item in self._accounts.values() if item.email == normalized),
            None,
        )
        if (
            account is None
            or not account.active
            or not _verify_password(account.password_hash, password)
        ):
            return None
        return deepcopy(account)

    def get_account(self, staff_id: str) -> StaffAccountRecord | None:
        account = self._accounts.get(staff_id)
        return deepcopy(account) if account else None

    def provision_account(
        self,
        email: str,
        password: str,
        display_name: str,
        roles: tuple[str, ...],
    ) -> StaffAccountRecord:
        normalized = email.strip().lower()
        existing = next(
            (item for item in self._accounts.values() if item.email == normalized),
            None,
        )
        if existing is not None:
            return deepcopy(existing)
        account = _new_account(normalized, password, display_name, roles)
        self._accounts[account.staff_id] = deepcopy(account)
        return account

    def save_session(self, session: StaffAuthSessionRecord) -> None:
        self._sessions[session.token_hash] = deepcopy(session)

    def get_session(self, token_hash: str) -> StaffAuthSessionRecord | None:
        session = self._sessions.get(token_hash)
        if (
            session is None
            or session.revoked_at is not None
            or session.expires_at <= datetime.now(UTC)
        ):
            return None
        return deepcopy(session)

    def revoke_session(self, token_hash: str) -> bool:
        session = self._sessions.get(token_hash)
        if session is None or session.revoked_at is not None:
            return False
        session.revoked_at = datetime.now(UTC)
        return True


class SQLiteStaffIdentityRepository(StaffIdentityRepository):
    """Persistent staff accounts and revocable bearer sessions."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._initialise()

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS staff_accounts (
                    staff_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    roles TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS staff_sessions (
                    token_hash TEXT PRIMARY KEY,
                    staff_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS staff_sessions_staff_idx
                    ON staff_sessions(staff_id);
                """
            )

    @staticmethod
    def _account(row: sqlite3.Row) -> StaffAccountRecord:
        return StaffAccountRecord(
            staff_id=row['staff_id'],
            email=row['email'],
            password_hash=row['password_hash'],
            display_name=row['display_name'],
            roles=tuple(value for value in row['roles'].split(',') if value),
            active=bool(row['active']),
        )

    def authenticate(self, email: str, password: str) -> StaffAccountRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT * FROM staff_accounts WHERE email = ?',
                (email.strip().lower(),),
            ).fetchone()
        if row is None:
            return None
        account = self._account(row)
        if not account.active or not _verify_password(account.password_hash, password):
            return None
        return account

    def get_account(self, staff_id: str) -> StaffAccountRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT * FROM staff_accounts WHERE staff_id = ?', (staff_id,)
            ).fetchone()
        return self._account(row) if row is not None else None

    def provision_account(
        self,
        email: str,
        password: str,
        display_name: str,
        roles: tuple[str, ...],
    ) -> StaffAccountRecord:
        normalized = email.strip().lower()
        with self._connection() as connection:
            row = connection.execute(
                'SELECT * FROM staff_accounts WHERE email = ?', (normalized,)
            ).fetchone()
            if row is not None:
                return self._account(row)
            account = _new_account(normalized, password, display_name, roles)
            connection.execute(
                """
                INSERT INTO staff_accounts
                    (staff_id, email, password_hash, display_name, roles, active)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    account.staff_id,
                    account.email,
                    account.password_hash,
                    account.display_name,
                    ','.join(account.roles),
                    int(account.active),
                ),
            )
        return account

    def save_session(self, session: StaffAuthSessionRecord) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO staff_sessions
                    (token_hash, staff_id, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session.token_hash,
                    session.staff_id,
                    session.created_at.isoformat(),
                    session.expires_at.isoformat(),
                    session.revoked_at.isoformat() if session.revoked_at else None,
                ),
            )

    def get_session(self, token_hash: str) -> StaffAuthSessionRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT * FROM staff_sessions WHERE token_hash = ?', (token_hash,)
            ).fetchone()
        if row is None:
            return None
        expires_at = datetime.fromisoformat(row['expires_at'])
        revoked_at = datetime.fromisoformat(row['revoked_at']) if row['revoked_at'] else None
        if revoked_at is not None or expires_at <= datetime.now(UTC):
            return None
        return StaffAuthSessionRecord(
            token_hash=row['token_hash'],
            staff_id=row['staff_id'],
            created_at=datetime.fromisoformat(row['created_at']),
            expires_at=expires_at,
            revoked_at=revoked_at,
        )

    def revoke_session(self, token_hash: str) -> bool:
        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE staff_sessions SET revoked_at = ?
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (datetime.now(UTC).isoformat(), token_hash),
            ).rowcount
        return updated == 1
