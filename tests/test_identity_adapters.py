import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.adapters.identity import (
    FixtureIdentityRepository,
    SQLiteIdentityRepository,
    _verify_sqlite_password,
)
from backend.adapters.staff_identity import (
    FixtureStaffIdentityRepository,
    SQLiteStaffIdentityRepository,
    _verify_password,
)
from backend.domain.identity import ClaimantAuthSessionRecord
from backend.domain.staff_identity import StaffAuthSessionRecord


def test_fixture_claimant_identity_covers_account_and_session_lifecycle() -> None:
    repository = FixtureIdentityRepository()
    account = repository.authenticate(' CLAIMANT.ONE@EXAMPLE.INVALID ', 'northwind-demo-one')
    assert account is not None
    assert repository.authenticate(account.email, 'wrong-password') is None
    assert repository.get_account(account.customer_id) is not None
    assert repository.get_account('missing') is None

    created = repository.create_account('new@example.invalid', 'secret', ' New User ')
    assert created is not None
    assert created.display_name == 'New User'
    assert repository.create_account('NEW@example.invalid', 'secret', 'Duplicate') is None
    updated = replace(
        created,
        phone='021 123 456',
        revision=created.revision + 1,
        updated_at=datetime.now(UTC),
    )
    repository.save_account(updated, created.revision)
    saved_created = repository.get_account(created.customer_id)
    assert saved_created is not None
    assert saved_created.phone == '021 123 456'

    now = datetime.now(UTC)
    session = ClaimantAuthSessionRecord(
        token_hash='fixture-token',
        customer_id=created.customer_id,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    repository.save_session(session)
    assert repository.get_session('fixture-token') is not None
    listed = repository.list_sessions(created.customer_id)
    assert listed[0].session_id == session.session_id
    revoked = repository.revoke_session_by_id(session.session_id, 1)
    assert revoked.revision == 2
    assert revoked.revoked_at is not None
    assert repository.get_session('fixture-token') is None
    assert repository.revoke_session('fixture-token') is False


def test_sqlite_claimant_identity_persists_accounts_and_sessions(tmp_path: Path) -> None:
    repository = SQLiteIdentityRepository(str(tmp_path / 'claimant.sqlite'))
    assert repository.authenticate('missing@example.invalid', 'secret') is None
    account = repository.create_account(' User@Example.com ', 'secret', ' User ')
    assert account is not None
    assert account.email == 'user@example.com'
    assert repository.create_account('USER@example.com', 'other', 'Duplicate') is None
    assert repository.authenticate('USER@example.com', 'secret') is not None
    assert repository.authenticate('user@example.com', 'wrong') is None
    assert repository.get_account(account.customer_id) is not None
    assert repository.get_account('missing') is None

    updated = replace(
        account,
        phone='021 555 0100',
        communication_preferences={'email': False, 'sms': True},
        active=False,
        revision=account.revision + 1,
        updated_at=datetime.now(UTC),
    )
    repository.save_account(updated, account.revision)
    saved = repository.get_account(account.customer_id)
    assert saved is not None
    assert saved.phone == '021 555 0100'
    assert saved.communication_preferences == {'email': False, 'sms': True}
    assert saved.active is False
    assert repository.authenticate(updated.email, 'secret') is None

    now = datetime.now(UTC)
    session = ClaimantAuthSessionRecord(
        token_hash='sqlite-token',
        customer_id=updated.customer_id,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    repository.save_session(session)
    assert repository.get_session('sqlite-token') is not None
    assert repository.list_sessions(updated.customer_id)[0].session_id == session.session_id
    revoked = repository.revoke_session_by_id(session.session_id, 1)
    assert revoked.revision == 2
    assert repository.get_session('sqlite-token') is None
    assert repository.revoke_session('sqlite-token') is False
    assert _verify_sqlite_password('not-a-password-hash', 'secret') is False


def test_fixture_staff_identity_covers_provision_and_session_lifecycle() -> None:
    repository = FixtureStaffIdentityRepository()
    account = repository.authenticate('STAFF.ONE@EXAMPLE.INVALID', 'northwind-demo-staff')
    assert account is not None
    assert repository.authenticate(account.email, 'wrong-password') is None
    assert repository.get_account(account.staff_id) is not None
    assert repository.get_account('missing') is None

    updated = replace(
        account,
        active=False,
        revision=account.revision + 1,
        updated_at=datetime.now(UTC),
    )
    repository.save_account(updated, account.revision)
    assert repository.authenticate(account.email, 'northwind-demo-staff') is None
    assert (
        repository.provision_account(
            account.email, 'ignored', 'Ignored', ('claims_professional',)
        ).staff_id
        == account.staff_id
    )
    created = repository.provision_account(
        'second@example.invalid', 'secret', ' Second ', ('supervisor',)
    )
    assert created.display_name == 'Second'

    now = datetime.now(UTC)
    session = StaffAuthSessionRecord(
        token_hash='staff-fixture-token',
        staff_id=created.staff_id,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    repository.save_session(session)
    assert repository.get_session('staff-fixture-token') is not None
    assert repository.list_sessions(created.staff_id)[0].session_id == session.session_id
    revoked = repository.revoke_session_by_id(session.session_id, 1)
    assert revoked.revision == 2
    assert repository.get_session('staff-fixture-token') is None
    assert repository.revoke_session('staff-fixture-token') is False


def test_sqlite_staff_identity_persists_accounts_and_sessions(tmp_path: Path) -> None:
    repository = SQLiteStaffIdentityRepository(str(tmp_path / 'staff.sqlite'))
    assert repository.authenticate('missing@example.invalid', 'secret') is None
    account = repository.provision_account(
        ' Staff@Example.com ', 'secret', ' Staff ', ('claims_professional', 'supervisor')
    )
    assert account.email == 'staff@example.com'
    assert account.display_name == 'Staff'
    assert (
        repository.provision_account('STAFF@example.com', 'other', 'Duplicate', ('other',)).staff_id
        == account.staff_id
    )
    assert repository.authenticate('STAFF@example.com', 'secret') is not None
    assert repository.authenticate('staff@example.com', 'wrong') is None
    assert repository.get_account(account.staff_id) is not None
    assert repository.get_account('missing') is None

    updated = replace(
        account,
        active=False,
        revision=account.revision + 1,
        updated_at=datetime.now(UTC),
    )
    repository.save_account(updated, account.revision)
    assert repository.authenticate(updated.email, 'secret') is None

    now = datetime.now(UTC)
    session = StaffAuthSessionRecord(
        token_hash='staff-sqlite-token',
        staff_id=updated.staff_id,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    repository.save_session(session)
    assert repository.get_session('staff-sqlite-token') is not None
    assert repository.list_sessions(updated.staff_id)[0].session_id == session.session_id
    revoked = repository.revoke_session_by_id(session.session_id, 1)
    assert revoked.revision == 2
    assert repository.get_session('staff-sqlite-token') is None
    assert repository.revoke_session('staff-sqlite-token') is False
    assert _verify_password('not-a-password-hash', 'secret') is False


def test_sqlite_identity_adapters_upgrade_legacy_account_and_session_tables(
    tmp_path: Path,
) -> None:
    created_at = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
    expires_at = created_at + timedelta(days=90)
    claimant_path = tmp_path / 'legacy-claimant.sqlite'
    with sqlite3.connect(claimant_path) as connection:
        connection.executescript(
            """
            CREATE TABLE accounts (
                customer_id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                email_updates INTEGER NOT NULL DEFAULT 1,
                sms_updates INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE sessions (
                token_hash TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            );
            """
        )
        connection.execute(
            'INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?, ?)',
            ('cus_legacy', 'legacy@example.invalid', 'legacy-hash', 'Legacy', '', 1, 0),
        )
        connection.execute(
            'INSERT INTO sessions VALUES (?, ?, ?, ?, ?)',
            (
                'legacy-token-hash',
                'cus_legacy',
                created_at.isoformat(),
                expires_at.isoformat(),
                None,
            ),
        )

    claimant_repository = SQLiteIdentityRepository(str(claimant_path))
    claimant = claimant_repository.get_account('cus_legacy')
    claimant_sessions = claimant_repository.list_sessions('cus_legacy')
    assert claimant is not None
    assert claimant.active is True
    assert claimant.revision == 1
    assert claimant.updated_at.tzinfo is not None
    assert len(claimant_sessions) == 1
    assert claimant_sessions[0].session_id.startswith('ias_')
    assert claimant_sessions[0].revision == 1
    assert claimant_sessions[0].updated_at == created_at
    assert (
        claimant_repository.revoke_session_by_id(
            claimant_sessions[0].session_id, claimant_sessions[0].revision
        ).revision
        == 2
    )

    staff_path = tmp_path / 'legacy-staff.sqlite'
    with sqlite3.connect(staff_path) as connection:
        connection.executescript(
            """
            CREATE TABLE staff_accounts (
                staff_id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                roles TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE staff_sessions (
                token_hash TEXT PRIMARY KEY,
                staff_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            );
            """
        )
        connection.execute(
            'INSERT INTO staff_accounts VALUES (?, ?, ?, ?, ?, ?)',
            (
                'stf_legacy',
                'legacy.staff@example.invalid',
                'legacy-hash',
                'Legacy Staff',
                'claims_professional',
                1,
            ),
        )
        connection.execute(
            'INSERT INTO staff_sessions VALUES (?, ?, ?, ?, ?)',
            (
                'legacy-staff-token-hash',
                'stf_legacy',
                created_at.isoformat(),
                expires_at.isoformat(),
                None,
            ),
        )

    staff_repository = SQLiteStaffIdentityRepository(str(staff_path))
    staff = staff_repository.get_account('stf_legacy')
    staff_sessions = staff_repository.list_sessions('stf_legacy')
    assert staff is not None
    assert staff.revision == 1
    assert staff.updated_at.tzinfo is not None
    assert len(staff_sessions) == 1
    assert staff_sessions[0].session_id.startswith('ias_')
    assert staff_sessions[0].revision == 1
    assert staff_sessions[0].updated_at == created_at
    assert (
        staff_repository.revoke_session_by_id(
            staff_sessions[0].session_id, staff_sessions[0].revision
        ).revision
        == 2
    )
