import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import scrypt
from hmac import compare_digest
from secrets import token_hex
from threading import RLock

from backend.domain.identity import (
    ClaimantAuthSessionRecord,
    CustomerAccountRecord,
    validate_customer_account_profile,
)
from backend.repositories.identity import DuplicateEmailConflict, IdentityRepository
from backend.repositories.protocols import RevisionConflict
from backend.services.business_seed import BUSINESS_SEED_PATH, BusinessSeed, load_business_seed


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

    def __init__(self, seed: BusinessSeed | None = None) -> None:
        self._accounts: dict[str, CustomerAccountRecord] = {}
        self._sessions: dict[str, ClaimantAuthSessionRecord] = {}
        self._account_lock = RLock()
        selected_seed = load_business_seed(BUSINESS_SEED_PATH) if seed is None else seed
        for account in selected_seed.customers:
            self.ensure_seed_account(
                account.customer_id, account.email, account.synthetic_password, account.display_name
            )

    def ensure_seed_account(
        self, customer_id: str, email: str, password: str, display_name: str
    ) -> CustomerAccountRecord:
        """Insert a fixed synthetic identity without resetting an existing account.

        Args:
            customer_id: Stable manifest identity.
            email: Synthetic account email.
            password: Synthetic password used only when inserting.
            display_name: Initial account name.
        Returns:
            The persisted account, including any existing profile edits.
        Raises:
            ValueError: Another identity already owns the supplied email.
        """
        normalized = email.strip().lower()
        with self._account_lock:
            if any(
                account.email == normalized and account.customer_id != customer_id
                for account in self._accounts.values()
            ):
                raise ValueError('Business seed email belongs to another customer.')
            existing = self._accounts.get(customer_id)
            if existing is not None:
                return deepcopy(existing)
            account = CustomerAccountRecord(
                customer_id=customer_id,
                email=normalized,
                password_hash=_password_hash(customer_id, password),
                display_name=display_name.strip(),
                legal_name=display_name.strip(),
            )
            validate_customer_account_profile(account)
            self._accounts[customer_id] = account
            return deepcopy(account)

    def authenticate(self, email: str, password: str) -> CustomerAccountRecord | None:
        normalized = email.strip().lower()
        for account in self._accounts.values():
            if (
                account.active
                and account.email == normalized
                and compare_digest(
                    account.password_hash, _password_hash(account.customer_id, password)
                )
            ):
                return deepcopy(account)
        return None

    def list_accounts(self) -> list[CustomerAccountRecord]:
        return deepcopy(list(self._accounts.values()))

    def create_account(
        self, email: str, password: str, display_name: str, phone: str = ''
    ) -> CustomerAccountRecord | None:
        normalized = email.strip().lower()
        with self._account_lock:
            if any(account.email == normalized for account in self._accounts.values()):
                return None
            customer_id = f'cus_{token_hex(8)}'
            account = CustomerAccountRecord(
                customer_id=customer_id,
                email=normalized,
                password_hash=_password_hash(customer_id, password),
                display_name=display_name.strip(),
                legal_name=display_name.strip(),
                phone=phone.strip(),
            )
            validate_customer_account_profile(account)
            self._accounts[customer_id] = deepcopy(account)
            return deepcopy(account)

    def get_account(self, customer_id: str) -> CustomerAccountRecord | None:
        account = self._accounts.get(customer_id)
        return deepcopy(account) if account else None

    @contextmanager
    def hold_account_revision(
        self, customer_id: str, expected_revision: int
    ) -> Iterator[CustomerAccountRecord]:
        with self._account_lock:
            account = self._accounts.get(customer_id)
            if account is None:
                raise KeyError(customer_id)
            if account.revision != expected_revision:
                raise RevisionConflict(account.revision)
            yield deepcopy(account)

    def save_account(self, account: CustomerAccountRecord, expected_revision: int) -> None:
        validate_customer_account_profile(account)
        with self._account_lock:
            current = self._accounts.get(account.customer_id)
            if current is None:
                raise KeyError(account.customer_id)
            if current.revision != expected_revision or account.revision != expected_revision + 1:
                raise RevisionConflict(current.revision)
            if any(
                candidate.customer_id != account.customer_id and candidate.email == account.email
                for candidate in self._accounts.values()
            ):
                raise DuplicateEmailConflict(account.email)
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
        now = datetime.now(UTC)
        session.revoked_at = now
        session.revision += 1
        session.updated_at = now
        return True

    def list_sessions(self, customer_id: str) -> list[ClaimantAuthSessionRecord]:
        sessions = [item for item in self._sessions.values() if item.customer_id == customer_id]
        sessions.sort(key=lambda item: (item.created_at, item.session_id), reverse=True)
        return deepcopy(sessions)

    def get_session_by_id(self, session_id: str) -> ClaimantAuthSessionRecord | None:
        session = next(
            (item for item in self._sessions.values() if item.session_id == session_id), None
        )
        return deepcopy(session) if session is not None else None

    def revoke_session_by_id(
        self, session_id: str, expected_revision: int
    ) -> ClaimantAuthSessionRecord:
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
                    legal_name TEXT,
                    preferred_name TEXT,
                    date_of_birth TEXT,
                    phone TEXT NOT NULL DEFAULT '',
                    residential_address TEXT,
                    email_updates INTEGER NOT NULL DEFAULT 1,
                    sms_updates INTEGER NOT NULL DEFAULT 0,
                    auto_fill_personal_details INTEGER NOT NULL DEFAULT 0,
                    auto_fill_policy_number INTEGER NOT NULL DEFAULT 0,
                    auto_fill_saved_assets INTEGER NOT NULL DEFAULT 0,
                    auto_fill_payment_details INTEGER NOT NULL DEFAULT 0,
                    auto_fill_identity_information INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    revision INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    session_id TEXT,
                    customer_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT
                );
                CREATE INDEX IF NOT EXISTS sessions_customer_idx ON sessions(customer_id);
                """
            )
            columns = {
                row['name'] for row in connection.execute('PRAGMA table_info(accounts)').fetchall()
            }
            if 'active' not in columns:
                connection.execute(
                    'ALTER TABLE accounts ADD COLUMN active INTEGER NOT NULL DEFAULT 1'
                )
            for name in (
                'auto_fill_personal_details',
                'auto_fill_policy_number',
                'auto_fill_saved_assets',
                'auto_fill_payment_details',
                'auto_fill_identity_information',
            ):
                if name not in columns:
                    connection.execute(
                        f'ALTER TABLE accounts ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0'
                    )
            for name, declaration in (
                ('legal_name', 'TEXT'),
                ('preferred_name', 'TEXT'),
                ('date_of_birth', 'TEXT'),
                ('residential_address', 'TEXT'),
            ):
                if name not in columns:
                    connection.execute(f'ALTER TABLE accounts ADD COLUMN {name} {declaration}')
            connection.execute(
                'UPDATE accounts SET legal_name = display_name '
                "WHERE legal_name IS NULL OR trim(legal_name) = ''"
            )
            if 'revision' not in columns:
                connection.execute(
                    'ALTER TABLE accounts ADD COLUMN revision INTEGER NOT NULL DEFAULT 1'
                )
            if 'updated_at' not in columns:
                connection.execute('ALTER TABLE accounts ADD COLUMN updated_at TEXT')
                connection.execute(
                    'UPDATE accounts SET updated_at = ? WHERE updated_at IS NULL',
                    (datetime.now(UTC).isoformat(),),
                )
            session_columns = {
                row['name'] for row in connection.execute('PRAGMA table_info(sessions)').fetchall()
            }
            if 'session_id' not in session_columns:
                connection.execute('ALTER TABLE sessions ADD COLUMN session_id TEXT')
            if 'revision' not in session_columns:
                connection.execute(
                    'ALTER TABLE sessions ADD COLUMN revision INTEGER NOT NULL DEFAULT 1'
                )
            if 'updated_at' not in session_columns:
                connection.execute('ALTER TABLE sessions ADD COLUMN updated_at TEXT')
            rows = connection.execute(
                'SELECT token_hash, session_id, created_at, updated_at FROM sessions'
            ).fetchall()
            for row in rows:
                connection.execute(
                    'UPDATE sessions SET session_id = ?, updated_at = ? WHERE token_hash = ?',
                    (
                        row['session_id'] or f'ias_{token_hex(10)}',
                        row['updated_at'] or row['created_at'],
                        row['token_hash'],
                    ),
                )
            connection.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS sessions_session_id_idx ON sessions(session_id)'
            )

    @staticmethod
    def _account(row: sqlite3.Row) -> CustomerAccountRecord:
        return CustomerAccountRecord(
            customer_id=row['customer_id'],
            email=row['email'],
            password_hash=row['password_hash'],
            display_name=row['display_name'],
            legal_name=row['legal_name'] or row['display_name'],
            preferred_name=row['preferred_name'],
            date_of_birth=(
                datetime.fromisoformat(row['date_of_birth']).date()
                if row['date_of_birth']
                else None
            ),
            phone=row['phone'],
            residential_address=row['residential_address'],
            communication_preferences={
                'email': bool(row['email_updates']),
                'sms': bool(row['sms_updates']),
            },
            claim_auto_fill_preferences={
                'personal_details': bool(row['auto_fill_personal_details']),
                'policy_number': bool(row['auto_fill_policy_number']),
                'saved_assets': bool(row['auto_fill_saved_assets']),
                'payment_details': bool(row['auto_fill_payment_details']),
                'identity_information': bool(row['auto_fill_identity_information']),
            },
            active=bool(row['active']),
            revision=int(row['revision']),
            updated_at=datetime.fromisoformat(row['updated_at']),
        )

    def authenticate(self, email: str, password: str) -> CustomerAccountRecord | None:
        normalized = email.strip().lower()
        with self._connection() as connection:
            row = connection.execute(
                'SELECT * FROM accounts WHERE email = ?', (normalized,)
            ).fetchone()
        if (
            row is None
            or not bool(row['active'])
            or not _verify_sqlite_password(row['password_hash'], password)
        ):
            return None
        return self._account(row)

    def ensure_seed_account(
        self, customer_id: str, email: str, password: str, display_name: str
    ) -> CustomerAccountRecord:
        """Serialize fixed-ID insertion and preserve all existing account state.

        Args:
            customer_id: Stable manifest identity.
            email: Synthetic account email.
            password: Synthetic password used only when inserting.
            display_name: Initial account name.
        Returns:
            The inserted or already persisted account.
        Raises:
            ValueError: Another identity already owns the supplied email.
        """
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            collision = connection.execute(
                'SELECT customer_id FROM accounts WHERE email = ? AND customer_id != ?',
                (email.strip().lower(), customer_id),
            ).fetchone()
            if collision is not None:
                raise ValueError('Business seed email belongs to another customer.')
            existing = connection.execute(
                'SELECT * FROM accounts WHERE customer_id = ?', (customer_id,)
            ).fetchone()
            if existing is not None:
                return self._account(existing)
            account = CustomerAccountRecord(
                customer_id=customer_id,
                email=email.strip().lower(),
                password_hash=_sqlite_password_hash(password, os.urandom(16)),
                display_name=display_name.strip(),
                legal_name=display_name.strip(),
            )
            validate_customer_account_profile(account)
            try:
                connection.execute(
                    'INSERT INTO accounts '
                    '(customer_id, email, password_hash, display_name, legal_name, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    (
                        account.customer_id,
                        account.email,
                        account.password_hash,
                        account.display_name,
                        account.legal_name,
                        account.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError('Business seed email belongs to another customer.') from error
        return account

    def create_account(
        self, email: str, password: str, display_name: str, phone: str = ''
    ) -> CustomerAccountRecord | None:
        normalized = email.strip().lower()
        customer_id = f'cus_{token_hex(8)}'
        account = CustomerAccountRecord(
            customer_id=customer_id,
            email=normalized,
            password_hash=_sqlite_password_hash(password, os.urandom(16)),
            display_name=display_name.strip(),
            legal_name=display_name.strip(),
            phone=phone.strip(),
        )
        validate_customer_account_profile(account)
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO accounts
                    (customer_id, email, password_hash, display_name, legal_name,
                     preferred_name, date_of_birth, phone, residential_address,
                     email_updates, sms_updates, auto_fill_personal_details,
                     auto_fill_policy_number, auto_fill_saved_assets,
                     auto_fill_payment_details, auto_fill_identity_information,
                     active, revision, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account.customer_id,
                        account.email,
                        account.password_hash,
                        account.display_name,
                        account.legal_name,
                        account.preferred_name,
                        account.date_of_birth.isoformat() if account.date_of_birth else None,
                        account.phone,
                        account.residential_address,
                        int(account.communication_preferences['email']),
                        int(account.communication_preferences['sms']),
                        int(account.claim_auto_fill_preferences['personal_details']),
                        int(account.claim_auto_fill_preferences['policy_number']),
                        int(account.claim_auto_fill_preferences['saved_assets']),
                        int(account.claim_auto_fill_preferences['payment_details']),
                        int(account.claim_auto_fill_preferences['identity_information']),
                        int(account.active),
                        account.revision,
                        account.updated_at.isoformat(),
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

    @contextmanager
    def hold_account_revision(
        self, customer_id: str, expected_revision: int
    ) -> Iterator[CustomerAccountRecord]:
        connection = self._connection()
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                'SELECT * FROM accounts WHERE customer_id = ?', (customer_id,)
            ).fetchone()
            if row is None:
                raise KeyError(customer_id)
            account = self._account(row)
            if account.revision != expected_revision:
                raise RevisionConflict(account.revision)
            yield account
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_accounts(self) -> list[CustomerAccountRecord]:
        with self._connection() as connection:
            rows = connection.execute('SELECT * FROM accounts ORDER BY customer_id').fetchall()
        return [self._account(row) for row in rows]

    def save_account(self, account: CustomerAccountRecord, expected_revision: int) -> None:
        validate_customer_account_profile(account)
        try:
            with self._connection() as connection:
                updated = connection.execute(
                    """
                    UPDATE accounts SET email = ?, password_hash = ?, display_name = ?,
                        legal_name = ?, preferred_name = ?, date_of_birth = ?, phone = ?,
                        residential_address = ?, email_updates = ?, sms_updates = ?,
                        auto_fill_personal_details = ?, auto_fill_policy_number = ?,
                        auto_fill_saved_assets = ?, auto_fill_payment_details = ?,
                        auto_fill_identity_information = ?, active = ?, revision = ?, updated_at = ?
                    WHERE customer_id = ? AND revision = ?
                    """,
                    (
                        account.email,
                        account.password_hash,
                        account.display_name,
                        account.legal_name,
                        account.preferred_name,
                        account.date_of_birth.isoformat() if account.date_of_birth else None,
                        account.phone,
                        account.residential_address,
                        int(account.communication_preferences['email']),
                        int(account.communication_preferences['sms']),
                        int(account.claim_auto_fill_preferences['personal_details']),
                        int(account.claim_auto_fill_preferences['policy_number']),
                        int(account.claim_auto_fill_preferences['saved_assets']),
                        int(account.claim_auto_fill_preferences['payment_details']),
                        int(account.claim_auto_fill_preferences['identity_information']),
                        int(account.active),
                        account.revision,
                        account.updated_at.isoformat(),
                        account.customer_id,
                        expected_revision,
                    ),
                ).rowcount
        except sqlite3.IntegrityError as error:
            with self._connection() as connection:
                owner = connection.execute(
                    'SELECT customer_id FROM accounts WHERE email = ?', (account.email,)
                ).fetchone()
            if owner is not None and owner['customer_id'] != account.customer_id:
                raise DuplicateEmailConflict(account.email) from error
            raise
        if updated != 1:
            current = self.get_account(account.customer_id)
            if current is None:
                raise KeyError(account.customer_id)
            raise RevisionConflict(current.revision)

    def save_session(self, session: ClaimantAuthSessionRecord) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO sessions
                (token_hash, session_id, customer_id, created_at, expires_at, revoked_at,
                 revision, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.token_hash,
                    session.session_id,
                    session.customer_id,
                    session.created_at.isoformat(),
                    session.expires_at.isoformat(),
                    session.revoked_at.isoformat() if session.revoked_at else None,
                    session.revision,
                    session.updated_at.isoformat(),
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
            session_id=row['session_id'],
            customer_id=row['customer_id'],
            created_at=datetime.fromisoformat(row['created_at']),
            expires_at=expires_at,
            revoked_at=revoked_at,
            revision=int(row['revision']),
            updated_at=datetime.fromisoformat(row['updated_at']),
        )

    def revoke_session(self, token_hash: str) -> bool:
        with self._connection() as connection:
            updated = connection.execute(
                'UPDATE sessions SET revoked_at = ?, revision = revision + 1, updated_at = ? '
                'WHERE token_hash = ? AND revoked_at IS NULL',
                (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), token_hash),
            ).rowcount
        return updated == 1

    def list_sessions(self, customer_id: str) -> list[ClaimantAuthSessionRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT * FROM sessions WHERE customer_id = ? '
                'ORDER BY created_at DESC, session_id DESC',
                (customer_id,),
            ).fetchall()
        return [self._session(row) for row in rows]

    @staticmethod
    def _session(row: sqlite3.Row) -> ClaimantAuthSessionRecord:
        return ClaimantAuthSessionRecord(
            token_hash=row['token_hash'],
            session_id=row['session_id'],
            customer_id=row['customer_id'],
            created_at=datetime.fromisoformat(row['created_at']),
            expires_at=datetime.fromisoformat(row['expires_at']),
            revoked_at=datetime.fromisoformat(row['revoked_at']) if row['revoked_at'] else None,
            revision=int(row['revision']),
            updated_at=datetime.fromisoformat(row['updated_at']),
        )

    def get_session_by_id(self, session_id: str) -> ClaimantAuthSessionRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT * FROM sessions WHERE session_id = ?', (session_id,)
            ).fetchone()
        return self._session(row) if row is not None else None

    def revoke_session_by_id(
        self, session_id: str, expected_revision: int
    ) -> ClaimantAuthSessionRecord:
        now = datetime.now(UTC)
        with self._connection() as connection:
            updated = connection.execute(
                'UPDATE sessions SET revoked_at = ?, revision = revision + 1, updated_at = ? '
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
