import os
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import scrypt
from hmac import compare_digest
from secrets import token_hex

from backend.domain.identity import ClaimantAuthSessionRecord, CustomerAccountRecord
from backend.repositories.identity import IdentityRepository


def _password_hash(customer_id: str, password: str) -> str:
    return scrypt(
        password.encode(),
        salt=f'northwind-development-{customer_id}'.encode(),
        n=2**14,
        r=8,
        p=1,
    ).hex()


def _sqlite_password_hash(password: str, salt: bytes) -> str:
    digest = scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f'scrypt${salt.hex()}${digest.hex()}'


def _verify_sqlite_password(encoded: str, password: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = encoded.split('$', 2)
        if scheme != 'scrypt':
            return False
        salt = bytes.fromhex(salt_hex)
        expected = _sqlite_password_hash(password, salt)
        return compare_digest(expected, encoded)
    except (ValueError, TypeError):
        return False


class FixtureIdentityRepository(IdentityRepository):
    """Development/test identities only; never a production identity provider."""

    def __init__(self) -> None:
        seeds = (
            ('cus_demo', 'claimant.one@example.invalid', 'northwind-demo-one', 'Demo Claimant One'),
            (
                'cus_other',
                'claimant.two@example.invalid',
                'northwind-demo-two',
                'Demo Claimant Two',
            ),
        )
        self._accounts = {
            customer_id: CustomerAccountRecord(
                customer_id=customer_id,
                email=email,
                password_hash=_password_hash(customer_id, password),
                display_name=display_name,
            )
            for customer_id, email, password, display_name in seeds
        }
        self._sessions: dict[str, ClaimantAuthSessionRecord] = {}

    def authenticate(self, email: str, password: str) -> CustomerAccountRecord | None:
        normalized = email.strip().lower()
        for account in self._accounts.values():
            if account.email == normalized and compare_digest(
                account.password_hash, _password_hash(account.customer_id, password)
            ):
                return deepcopy(account)
        return None

    def create_account(
        self, email: str, password: str, display_name: str
    ) -> CustomerAccountRecord | None:
        normalized = email.strip().lower()
        if any(account.email == normalized for account in self._accounts.values()):
            return None
        customer_id = f'cus_{token_hex(8)}'
        account = CustomerAccountRecord(
            customer_id=customer_id,
            email=normalized,
            password_hash=_password_hash(customer_id, password),
            display_name=display_name.strip(),
        )
        self._accounts[customer_id] = deepcopy(account)
        return deepcopy(account)

    def get_account(self, customer_id: str) -> CustomerAccountRecord | None:
        account = self._accounts.get(customer_id)
        return deepcopy(account) if account else None

    def save_account(self, account: CustomerAccountRecord) -> None:
        if account.customer_id not in self._accounts:
            raise KeyError(account.customer_id)
        self._accounts[account.customer_id] = deepcopy(account)

    def save_session(self, session: ClaimantAuthSessionRecord) -> None:
        self._sessions[session.token_hash] = deepcopy(session)

    def get_session(self, token_hash: str) -> ClaimantAuthSessionRecord | None:
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


class SQLiteIdentityRepository(IdentityRepository):
    """Persistent claimant identity store for the real local/runtime path.

    SQLite is the local implementation of the identity adapter: credentials are
    never kept in browser storage or source files, passwords are salted scrypt
    hashes, and only a hash of each bearer session token is persisted.
    """

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
                CREATE TABLE IF NOT EXISTS accounts (
                    customer_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    email_updates INTEGER NOT NULL DEFAULT 1,
                    sms_updates INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS sessions_customer_idx ON sessions(customer_id);
                """
            )

    @staticmethod
    def _account(row: sqlite3.Row) -> CustomerAccountRecord:
        return CustomerAccountRecord(
            customer_id=row['customer_id'],
            email=row['email'],
            password_hash=row['password_hash'],
            display_name=row['display_name'],
            phone=row['phone'],
            communication_preferences={
                'email': bool(row['email_updates']),
                'sms': bool(row['sms_updates']),
            },
        )

    def authenticate(self, email: str, password: str) -> CustomerAccountRecord | None:
        normalized = email.strip().lower()
        with self._connection() as connection:
            row = connection.execute(
                'SELECT * FROM accounts WHERE email = ?', (normalized,)
            ).fetchone()
        if row is None or not _verify_sqlite_password(row['password_hash'], password):
            return None
        return self._account(row)

    def create_account(
        self, email: str, password: str, display_name: str
    ) -> CustomerAccountRecord | None:
        normalized = email.strip().lower()
        customer_id = f'cus_{token_hex(8)}'
        account = CustomerAccountRecord(
            customer_id=customer_id,
            email=normalized,
            password_hash=_sqlite_password_hash(password, os.urandom(16)),
            display_name=display_name.strip(),
        )
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO accounts
                    (customer_id, email, password_hash, display_name, phone,
                     email_updates, sms_updates)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account.customer_id,
                        account.email,
                        account.password_hash,
                        account.display_name,
                        account.phone,
                        int(account.communication_preferences['email']),
                        int(account.communication_preferences['sms']),
                    ),
                )
        except sqlite3.IntegrityError:
            return None
        return account

    def get_account(self, customer_id: str) -> CustomerAccountRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT * FROM accounts WHERE customer_id = ?', (customer_id,)
            ).fetchone()
        return self._account(row) if row is not None else None

    def save_account(self, account: CustomerAccountRecord) -> None:
        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE accounts SET email = ?, password_hash = ?, display_name = ?, phone = ?,
                    email_updates = ?, sms_updates = ? WHERE customer_id = ?
                """,
                (
                    account.email,
                    account.password_hash,
                    account.display_name,
                    account.phone,
                    int(account.communication_preferences['email']),
                    int(account.communication_preferences['sms']),
                    account.customer_id,
                ),
            ).rowcount
        if updated != 1:
            raise KeyError(account.customer_id)

    def save_session(self, session: ClaimantAuthSessionRecord) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO sessions
                (token_hash, customer_id, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session.token_hash,
                    session.customer_id,
                    session.created_at.isoformat(),
                    session.expires_at.isoformat(),
                    session.revoked_at.isoformat() if session.revoked_at else None,
                ),
            )

    def get_session(self, token_hash: str) -> ClaimantAuthSessionRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT * FROM sessions WHERE token_hash = ?', (token_hash,)
            ).fetchone()
        if row is None:
            return None
        expires_at = datetime.fromisoformat(row['expires_at'])
        revoked_at = datetime.fromisoformat(row['revoked_at']) if row['revoked_at'] else None
        if revoked_at is not None or expires_at <= datetime.now(UTC):
            return None
        return ClaimantAuthSessionRecord(
            token_hash=row['token_hash'],
            customer_id=row['customer_id'],
            created_at=datetime.fromisoformat(row['created_at']),
            expires_at=expires_at,
            revoked_at=revoked_at,
        )

    def revoke_session(self, token_hash: str) -> bool:
        with self._connection() as connection:
            updated = connection.execute(
                'UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL',
                (datetime.now(UTC).isoformat(), token_hash),
            ).rowcount
        return updated == 1
