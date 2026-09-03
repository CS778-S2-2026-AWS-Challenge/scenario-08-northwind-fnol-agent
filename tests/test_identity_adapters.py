from datetime import UTC, datetime, timedelta

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
    created.phone = '021 123 456'
    repository.save_account(created)
    assert repository.get_account(created.customer_id).phone == '021 123 456'

    now = datetime.now(UTC)
    session = ClaimantAuthSessionRecord(
        token_hash='fixture-token',
        customer_id=created.customer_id,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    repository.save_session(session)
    assert repository.get_session('fixture-token') is not None
    assert repository.revoke_session('fixture-token') is True
    assert repository.get_session('fixture-token') is None
    assert repository.revoke_session('fixture-token') is False


def test_sqlite_claimant_identity_persists_accounts_and_sessions(tmp_path) -> None:
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

    account.phone = '021 555 0100'
    account.communication_preferences = {'email': False, 'sms': True}
    repository.save_account(account)
    saved = repository.get_account(account.customer_id)
    assert saved is not None
    assert saved.phone == '021 555 0100'
    assert saved.communication_preferences == {'email': False, 'sms': True}

    now = datetime.now(UTC)
    session = ClaimantAuthSessionRecord(
        token_hash='sqlite-token',
        customer_id=account.customer_id,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    repository.save_session(session)
    assert repository.get_session('sqlite-token') is not None
    assert repository.revoke_session('sqlite-token') is True
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
    assert repository.revoke_session('staff-fixture-token') is True
    assert repository.get_session('staff-fixture-token') is None
    assert repository.revoke_session('staff-fixture-token') is False


def test_sqlite_staff_identity_persists_accounts_and_sessions(tmp_path) -> None:
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

    now = datetime.now(UTC)
    session = StaffAuthSessionRecord(
        token_hash='staff-sqlite-token',
        staff_id=account.staff_id,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    repository.save_session(session)
    assert repository.get_session('staff-sqlite-token') is not None
    assert repository.revoke_session('staff-sqlite-token') is True
    assert repository.get_session('staff-sqlite-token') is None
    assert repository.revoke_session('staff-sqlite-token') is False
    assert _verify_password('not-a-password-hash', 'secret') is False
