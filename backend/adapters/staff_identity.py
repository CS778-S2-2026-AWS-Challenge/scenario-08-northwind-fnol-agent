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

    def list_accounts(self) -> list[StaffAccountRecord]:
        return deepcopy(list(self._accounts.values()))

    def get_account(self, staff_id: str) -> StaffAccountRecord | None:
        account = self._accounts.get(staff_id)
        return deepcopy(account) if account else None

    def save_account(self, account: StaffAccountRecord, expected_revision: int) -> None:
        current = self._accounts.get(account.staff_id)
        if current is None:
            raise KeyError(account.staff_id)
        if current.revision != expected_revision or account.revision != expected_revision + 1:
            raise ValueError('stale_revision')
        self._accounts[account.staff_id] = deepcopy(account)

    def create_account(
        self,
        email: str,
        password: str,
        display_name: str,
        roles: tuple[str, ...],
    ) -> StaffAccountRecord | None:
        normalized = email.strip().lower()
        if any(item.email == normalized for item in self._accounts.values()):
            return None
        account = _new_account(normalized, password, display_name, roles)
        self._accounts[account.staff_id] = deepcopy(account)
        return deepcopy(account)

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
        now = datetime.now(UTC)
        session.revoked_at = now
        session.revision += 1
        session.updated_at = now
        return True

    def list_sessions(self, staff_id: str) -> list[StaffAuthSessionRecord]:
        sessions = [item for item in self._sessions.values() if item.staff_id == staff_id]
        sessions.sort(key=lambda item: (item.created_at, item.session_id), reverse=True)
        return deepcopy(sessions)

    def get_session_by_id(self, session_id: str) -> StaffAuthSessionRecord | None:
        session = next(
            (item for item in self._sessions.values() if item.session_id == session_id), None
        )
        return deepcopy(session) if session is not None else None

    def revoke_session_by_id(
        self, session_id: str, expected_revision: int
    ) -> StaffAuthSessionRecord:
        session = next(
            (item for item in self._sessions.values() if item.session_id == session_id), None
        )
        if session is None:
            raise KeyError(session_id)
        if session.revision != expected_revision:
            raise ValueError('stale_revision')
        if session.revoked_at is not None:
            raise ValueError('session_not_active')
        now = datetime.now(UTC)
        session.revoked_at = now
        session.revision += 1
        session.updated_at = now
        return deepcopy(session)


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
                    active INTEGER NOT NULL DEFAULT 1,
                    revision INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS staff_sessions (
                    token_hash TEXT PRIMARY KEY,
                    session_id TEXT,
                    staff_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT
                );
                CREATE INDEX IF NOT EXISTS staff_sessions_staff_idx
                    ON staff_sessions(staff_id);
                """
            )
            account_columns = {
                row['name']
                for row in connection.execute('PRAGMA table_info(staff_accounts)').fetchall()
            }
            if 'revision' not in account_columns:
                connection.execute(
                    'ALTER TABLE staff_accounts ADD COLUMN revision INTEGER NOT NULL DEFAULT 1'
                )
            if 'updated_at' not in account_columns:
                connection.execute('ALTER TABLE staff_accounts ADD COLUMN updated_at TEXT')
                connection.execute(
                    'UPDATE staff_accounts SET updated_at = ? WHERE updated_at IS NULL',
                    (datetime.now(UTC).isoformat(),),
                )
            session_columns = {
                row['name']
                for row in connection.execute('PRAGMA table_info(staff_sessions)').fetchall()
            }
            if 'session_id' not in session_columns:
                connection.execute('ALTER TABLE staff_sessions ADD COLUMN session_id TEXT')
            if 'revision' not in session_columns:
                connection.execute(
                    'ALTER TABLE staff_sessions ADD COLUMN revision INTEGER NOT NULL DEFAULT 1'
                )
            if 'updated_at' not in session_columns:
                connection.execute('ALTER TABLE staff_sessions ADD COLUMN updated_at TEXT')
            rows = connection.execute(
                'SELECT token_hash, session_id, created_at, updated_at FROM staff_sessions'
            ).fetchall()
            for row in rows:
                connection.execute(
                    'UPDATE staff_sessions SET session_id = ?, updated_at = ? WHERE token_hash = ?',
                    (
                        row['session_id'] or f'ias_{token_hex(10)}',
                        row['updated_at'] or row['created_at'],
                        row['token_hash'],
                    ),
                )
            connection.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS staff_sessions_session_id_idx '
                'ON staff_sessions(session_id)'
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
            revision=int(row['revision']),
            updated_at=datetime.fromisoformat(row['updated_at']),
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

    def list_accounts(self) -> list[StaffAccountRecord]:
        with self._connection() as connection:
            rows = connection.execute('SELECT * FROM staff_accounts ORDER BY staff_id').fetchall()
        return [self._account(row) for row in rows]

    def save_account(self, account: StaffAccountRecord, expected_revision: int) -> None:
        with self._connection() as connection:
            updated = connection.execute(
                'UPDATE staff_accounts SET display_name = ?, roles = ?, active = ?, '
                'revision = ?, updated_at = ? WHERE staff_id = ? AND revision = ?',
                (
                    account.display_name,
                    ','.join(account.roles),
                    int(account.active),
                    account.revision,
                    account.updated_at.isoformat(),
                    account.staff_id,
                    expected_revision,
                ),
            ).rowcount
        if updated != 1:
            if self.get_account(account.staff_id) is None:
                raise KeyError(account.staff_id)
            raise ValueError('stale_revision')

    def create_account(
        self,
        email: str,
        password: str,
        display_name: str,
        roles: tuple[str, ...],
    ) -> StaffAccountRecord | None:
        normalized = email.strip().lower()
        account = _new_account(normalized, password, display_name, roles)
        try:
            with self._connection() as connection:
                connection.execute(
                    'INSERT INTO staff_accounts '
                    '(staff_id, email, password_hash, display_name, roles, active, '
                    'revision, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (
                        account.staff_id,
                        account.email,
                        account.password_hash,
                        account.display_name,
                        ','.join(account.roles),
                        int(account.active),
                        account.revision,
                        account.updated_at.isoformat(),
                    ),
                )
        except sqlite3.IntegrityError:
            return None
        return account

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
                    (staff_id, email, password_hash, display_name, roles, active,
                     revision, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account.staff_id,
                    account.email,
                    account.password_hash,
                    account.display_name,
                    ','.join(account.roles),
                    int(account.active),
                    account.revision,
                    account.updated_at.isoformat(),
                ),
            )
        return account

    def save_session(self, session: StaffAuthSessionRecord) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO staff_sessions
                    (token_hash, session_id, staff_id, created_at, expires_at, revoked_at,
                     revision, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.token_hash,
                    session.session_id,
                    session.staff_id,
                    session.created_at.isoformat(),
                    session.expires_at.isoformat(),
                    session.revoked_at.isoformat() if session.revoked_at else None,
                    session.revision,
                    session.updated_at.isoformat(),
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
            session_id=row['session_id'],
            staff_id=row['staff_id'],
            created_at=datetime.fromisoformat(row['created_at']),
            expires_at=expires_at,
            revoked_at=revoked_at,
            revision=int(row['revision']),
            updated_at=datetime.fromisoformat(row['updated_at']),
        )

    def revoke_session(self, token_hash: str) -> bool:
        with self._connection() as connection:
            now = datetime.now(UTC)
            updated = connection.execute(
                """
                UPDATE staff_sessions SET revoked_at = ?, revision = revision + 1, updated_at = ?
                WHERE token_hash = ? AND revoked_at IS NULL
                """,
                (now.isoformat(), now.isoformat(), token_hash),
            ).rowcount
        return updated == 1

    @staticmethod
    def _session(row: sqlite3.Row) -> StaffAuthSessionRecord:
        return StaffAuthSessionRecord(
            token_hash=row['token_hash'],
            session_id=row['session_id'],
            staff_id=row['staff_id'],
            created_at=datetime.fromisoformat(row['created_at']),
            expires_at=datetime.fromisoformat(row['expires_at']),
            revoked_at=datetime.fromisoformat(row['revoked_at']) if row['revoked_at'] else None,
            revision=int(row['revision']),
            updated_at=datetime.fromisoformat(row['updated_at']),
        )

    def list_sessions(self, staff_id: str) -> list[StaffAuthSessionRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT * FROM staff_sessions WHERE staff_id = ? '
                'ORDER BY created_at DESC, session_id DESC',
                (staff_id,),
            ).fetchall()
        return [self._session(row) for row in rows]

    def get_session_by_id(self, session_id: str) -> StaffAuthSessionRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT * FROM staff_sessions WHERE session_id = ?', (session_id,)
            ).fetchone()
        return self._session(row) if row is not None else None

    def revoke_session_by_id(
        self, session_id: str, expected_revision: int
    ) -> StaffAuthSessionRecord:
        now = datetime.now(UTC)
        with self._connection() as connection:
            updated = connection.execute(
                'UPDATE staff_sessions SET revoked_at = ?, revision = revision + 1, updated_at = ? '
                'WHERE session_id = ? AND revision = ? AND revoked_at IS NULL',
                (now.isoformat(), now.isoformat(), session_id, expected_revision),
            ).rowcount
        if updated != 1:
            current = self.get_session_by_id(session_id)
            if current is None:
                raise KeyError(session_id)
            if current.revision != expected_revision:
                raise ValueError('stale_revision')
            raise ValueError('session_not_active')
        result = self.get_session_by_id(session_id)
        if result is None:
            raise KeyError(session_id)
        return result
