import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event

import pytest

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
from backend.domain.identity import ClaimantAuthSessionRecord, CustomerAccountRecord
from backend.domain.staff_identity import StaffAuthSessionRecord
from backend.repositories.identity import DuplicateEmailConflict
from backend.repositories.protocols import RevisionConflict
from backend.services.business_seed import BUSINESS_SEED_PATH, load_business_seed


@pytest.mark.parametrize('adapter', ['fixture', 'sqlite'])
def test_business_seed_identity_preserves_existing_profile(adapter: str, tmp_path: Path) -> None:
    repository = (
        FixtureIdentityRepository()
        if adapter == 'fixture'
        else SQLiteIdentityRepository(str(tmp_path / 'claimant.sqlite'))
    )
    seed = load_business_seed(BUSINESS_SEED_PATH)
    customer = seed.customers[0]
    first = repository.ensure_seed_account(
        customer.customer_id, customer.email, customer.synthetic_password, customer.display_name
    )
    changed = replace(
        first,
        phone='021 555 0150',
        email='edited-seed@example.invalid',
        revision=first.revision + 1,
        updated_at=datetime.now(UTC),
    )
    repository.save_account(changed, first.revision)
    again = repository.ensure_seed_account(
        customer.customer_id, customer.email, 'different-seed-value', customer.display_name
    )
    assert again.revision == changed.revision
    assert again.phone == '021 555 0150'
    assert again.email == changed.email
    assert repository.authenticate(changed.email, customer.synthetic_password) is not None
    assert repository.authenticate(changed.email, 'different-seed-value') is None


@pytest.mark.parametrize('adapter', ['fixture', 'sqlite'])
@pytest.mark.parametrize('existing_seed_id', [False, True])
def test_business_seed_identity_rejects_email_owned_by_another_customer(
    adapter: str, existing_seed_id: bool, tmp_path: Path
) -> None:
    repository = (
        FixtureIdentityRepository()
        if adapter == 'fixture'
        else SQLiteIdentityRepository(str(tmp_path / 'claimant.sqlite'))
    )
    existing = repository.create_account('already@example.invalid', 'secret', 'Existing')
    assert existing is not None
    if existing_seed_id:
        repository.ensure_seed_account(
            'cus_seed_conflict', 'original@example.invalid', 'seed-only', 'Seeded'
        )
    with pytest.raises(ValueError, match='email belongs to another customer'):
        repository.ensure_seed_account(
            'cus_seed_conflict', 'already@example.invalid', 'seed-only', 'Seeded'
        )


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


def test_sqlite_claim_auto_fill_preferences_persist_across_repository_instances(
    tmp_path: Path,
) -> None:
    path = tmp_path / 'claim-auto-fill.sqlite'
    repository = SQLiteIdentityRepository(str(path))
    account = repository.create_account('saved@example.invalid', 'secret', 'Saved User')
    assert account is not None
    enabled = {key: True for key in account.claim_auto_fill_preferences}
    repository.save_account(
        replace(
            account,
            claim_auto_fill_preferences=enabled,
            revision=account.revision + 1,
            updated_at=datetime.now(UTC),
        ),
        account.revision,
    )

    reopened = SQLiteIdentityRepository(str(path)).get_account(account.customer_id)

    assert reopened is not None
    assert reopened.claim_auto_fill_preferences == enabled


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
    # Provisioning a seeded account again resets it to the seed values, keeping its identity.
    reseeded = repository.provision_account('STAFF@example.com', 'other', 'Reseeded', ('other',))
    assert reseeded.staff_id == account.staff_id
    assert (reseeded.display_name, reseeded.roles) == ('Reseeded', ('other',))
    assert reseeded.revision == account.revision + 1
    assert repository.authenticate('staff@example.com', 'secret') is None
    account = repository.provision_account(
        'staff@example.com', 'secret', 'Staff', ('claims_professional', 'supervisor')
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
    assert claimant.legal_name == 'Legacy'
    assert claimant.display_name == claimant.legal_name
    assert claimant.preferred_name is None
    assert claimant.date_of_birth is None
    assert claimant.residential_address is None
    assert claimant.claim_auto_fill_preferences == {
        'personal_details': False,
        'policy_number': False,
        'saved_assets': False,
        'payment_details': False,
        'identity_information': False,
    }
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


@pytest.mark.parametrize('repository_kind', ['fixture', 'sqlite'])
def test_claimant_identity_save_separates_profile_invariants_from_revision_conflicts(
    repository_kind: str, tmp_path: Path
) -> None:
    repository = (
        FixtureIdentityRepository()
        if repository_kind == 'fixture'
        else SQLiteIdentityRepository(str(tmp_path / 'profile-boundary.sqlite'))
    )
    if repository_kind == 'sqlite':
        repository.create_account('profile@example.invalid', 'secret', 'Profile Owner')
    account = repository.list_accounts()[0]
    invalid = replace(
        account,
        legal_name='   ',
        display_name='   ',
        revision=account.revision + 1,
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(ValueError, match='invalid_legal_name'):
        repository.save_account(invalid, account.revision)

    valid = replace(
        account,
        phone='021 555 0199',
        revision=account.revision + 1,
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(RevisionConflict) as conflict:
        repository.save_account(valid, 0)

    assert conflict.value.current_revision == account.revision
    assert repository.get_account(account.customer_id) == account


@pytest.mark.parametrize('repository_kind', ['fixture', 'sqlite'])
def test_claimant_identity_save_rejects_duplicate_email_without_partial_write(
    repository_kind: str, tmp_path: Path
) -> None:
    repository = (
        FixtureIdentityRepository()
        if repository_kind == 'fixture'
        else SQLiteIdentityRepository(str(tmp_path / 'duplicate-email.sqlite'))
    )
    if repository_kind == 'sqlite':
        first = repository.create_account('first@example.invalid', 'secret-one', 'First')
        second = repository.create_account('second@example.invalid', 'secret-two', 'Second')
        assert first is not None
        assert second is not None
    else:
        first, second = repository.list_accounts()

    duplicate = replace(
        second,
        email=first.email,
        revision=second.revision + 1,
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(DuplicateEmailConflict):
        repository.save_account(duplicate, second.revision)

    assert repository.get_account(second.customer_id) == second


@pytest.mark.parametrize('repository_kind', ['fixture', 'sqlite'])
def test_claimant_identity_save_prioritises_revision_conflict_over_duplicate_email(
    repository_kind: str, tmp_path: Path
) -> None:
    repository = (
        FixtureIdentityRepository()
        if repository_kind == 'fixture'
        else SQLiteIdentityRepository(str(tmp_path / 'stale-email.sqlite'))
    )
    if repository_kind == 'sqlite':
        first = repository.create_account('first@example.invalid', 'secret-one', 'First')
        second = repository.create_account('second@example.invalid', 'secret-two', 'Second')
        assert first is not None
        assert second is not None
    else:
        first, second = repository.list_accounts()

    stale_duplicate = replace(
        second,
        email=first.email,
        revision=second.revision + 1,
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(RevisionConflict) as conflict:
        repository.save_account(stale_duplicate, second.revision - 1)

    assert conflict.value.current_revision == second.revision
    assert repository.get_account(second.customer_id) == second


@pytest.mark.parametrize('repository_kind', ['fixture', 'sqlite'])
def test_claimant_identity_save_serialises_competing_email_updates(
    repository_kind: str, tmp_path: Path
) -> None:
    repository = (
        FixtureIdentityRepository()
        if repository_kind == 'fixture'
        else SQLiteIdentityRepository(str(tmp_path / 'racing-email.sqlite'))
    )
    if repository_kind == 'sqlite':
        first = repository.create_account('first@example.invalid', 'secret-one', 'First')
        second = repository.create_account('second@example.invalid', 'secret-two', 'Second')
        assert first is not None
        assert second is not None
    else:
        first, second = repository.list_accounts()

    barrier = Barrier(2)

    def compete(account: CustomerAccountRecord) -> Exception | None:
        updated = replace(
            account,
            email='shared@example.invalid',
            revision=account.revision + 1,
            updated_at=datetime.now(UTC),
        )
        barrier.wait()
        try:
            repository.save_account(updated, account.revision)
        except Exception as error:
            return error
        return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(compete, (first, second)))

    assert sum(outcome is None for outcome in outcomes) == 1
    assert sum(isinstance(outcome, DuplicateEmailConflict) for outcome in outcomes) == 1
    saved = repository.list_accounts()
    assert sum(account.email == 'shared@example.invalid' for account in saved) == 1


@pytest.mark.parametrize('repository_kind', ['fixture', 'sqlite'])
def test_claimant_identity_revision_guard_blocks_concurrent_account_write(
    repository_kind: str, tmp_path: Path
) -> None:
    repository = (
        FixtureIdentityRepository()
        if repository_kind == 'fixture'
        else SQLiteIdentityRepository(str(tmp_path / 'revision-guard.sqlite'))
    )
    account = (
        repository.get_account('cus_demo')
        if repository_kind == 'fixture'
        else repository.create_account('guard@example.invalid', 'secret', 'Guarded')
    )
    assert account is not None

    guard_entered = Event()
    release_guard = Event()
    writer_started = Event()
    writer_finished = Event()

    def hold_guard() -> None:
        with repository.hold_account_revision(account.customer_id, account.revision):
            guard_entered.set()
            assert release_guard.wait(timeout=2)

    def update_account() -> None:
        assert guard_entered.wait(timeout=2)
        current = repository.get_account(account.customer_id)
        assert current is not None
        updated = replace(
            current,
            phone='021 555 0188',
            revision=current.revision + 1,
            updated_at=datetime.now(UTC),
        )
        writer_started.set()
        repository.save_account(updated, current.revision)
        writer_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        guard_future = executor.submit(hold_guard)
        assert guard_entered.wait(timeout=2)
        writer_future = executor.submit(update_account)
        assert writer_started.wait(timeout=2)
        assert not writer_finished.wait(timeout=0.1)
        release_guard.set()
        guard_future.result(timeout=2)
        writer_future.result(timeout=2)

    saved = repository.get_account(account.customer_id)
    assert saved is not None
    assert saved.phone == '021 555 0188'
    assert saved.revision == account.revision + 1


@pytest.mark.parametrize('repository_kind', ['fixture', 'sqlite'])
def test_claimant_identity_revision_guard_rejects_prior_profile_write(
    repository_kind: str, tmp_path: Path
) -> None:
    repository = (
        FixtureIdentityRepository()
        if repository_kind == 'fixture'
        else SQLiteIdentityRepository(str(tmp_path / 'revision-guard-stale.sqlite'))
    )
    account = (
        repository.get_account('cus_demo')
        if repository_kind == 'fixture'
        else repository.create_account('stale-guard@example.invalid', 'secret', 'Guarded')
    )
    assert account is not None
    updated = replace(
        account,
        phone='021 555 0199',
        revision=account.revision + 1,
        updated_at=datetime.now(UTC),
    )
    repository.save_account(updated, account.revision)

    with (
        pytest.raises(RevisionConflict) as conflict,
        repository.hold_account_revision(account.customer_id, account.revision),
    ):
        raise AssertionError('stale guard must not yield')

    assert conflict.value.current_revision == updated.revision


@pytest.mark.parametrize('repository_kind', ['fixture', 'sqlite'])
def test_claimant_identity_revision_guard_releases_after_exception(
    repository_kind: str, tmp_path: Path
) -> None:
    repository = (
        FixtureIdentityRepository()
        if repository_kind == 'fixture'
        else SQLiteIdentityRepository(str(tmp_path / 'revision-guard-release.sqlite'))
    )
    account = (
        repository.get_account('cus_demo')
        if repository_kind == 'fixture'
        else repository.create_account('release-guard@example.invalid', 'secret', 'Guarded')
    )
    assert account is not None

    with (
        pytest.raises(RuntimeError, match='claim write failed'),
        repository.hold_account_revision(account.customer_id, account.revision),
    ):
        raise RuntimeError('claim write failed')

    current = repository.get_account(account.customer_id)
    assert current is not None
    updated = replace(
        current,
        phone='021 555 0177',
        revision=current.revision + 1,
        updated_at=datetime.now(UTC),
    )
    repository.save_account(updated, current.revision)
    saved = repository.get_account(account.customer_id)
    assert saved is not None
    assert saved.phone == '021 555 0177'
