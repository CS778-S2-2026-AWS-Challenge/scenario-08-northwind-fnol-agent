"""`save_claim()` must enforce the Claim revision and active-session boundary.

`docs/claim-state-transaction-boundary.md` makes `WorkingClaim.revision` the only
optimistic-concurrency token, requires a material mutation to advance it exactly
once, and reserves `active_session_id` changes for the dedicated resume/start
session mutation. These regressions cover the public repository entry point in
both implemented adapters.

The MongoDB evidence is logical: ``mongomock`` proves the precondition ordering
and the resulting snapshot, not live transaction rollback or concurrency.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import mongomock
import pytest

from backend.domain.models import (
    Channel,
    CustomerNextStep,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import PersistenceRepository, RevisionConflict

FIXED_TIME = datetime(2026, 8, 27, 5, 0, tzinfo=UTC)
CLAIM_ID = 'clm_save_boundary'
CUSTOMER_ID = 'cus_save_boundary'
SESSION_ID = 'ses_save_boundary'


def _mongo() -> MongoDBRepository:
    repository = MongoDBRepository(mongomock.MongoClient(), 'northwind_save_boundary')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


ADAPTERS: list[tuple[str, Callable[[], PersistenceRepository]]] = [
    ('fixture', FixtureRepository),
    ('mongodb', _mongo),
]


def _seeded(
    build: Callable[[], PersistenceRepository],
) -> tuple[PersistenceRepository, WorkingClaim]:
    repository = build()
    claim = WorkingClaim(
        claim_id=CLAIM_ID,
        customer_id=CUSTOMER_ID,
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id=SESSION_ID,
        customer_next_step=CustomerNextStep(
            status='continue_intake',
            summary='Continue the claim intake.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    session = SessionRecord(
        session_id=SESSION_ID,
        claim_id=CLAIM_ID,
        customer_id=CUSTOMER_ID,
        context_revision=1,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
        status=SessionStatus.ACTIVE,
    )
    repository.create_claim(claim, session)
    return repository, claim


@pytest.mark.parametrize(('name', 'build'), ADAPTERS)
def test_save_claim_rejects_a_revision_jump_and_leaves_the_snapshot_unchanged(
    name: str,
    build: Callable[[], PersistenceRepository],
) -> None:
    repository, claim = _seeded(build)

    with pytest.raises(KeyError):
        repository.save_claim(claim.model_copy(update={'revision': 3}), expected_revision=1)

    assert repository.get_claim(CLAIM_ID, CUSTOMER_ID) == claim


@pytest.mark.parametrize(('name', 'build'), ADAPTERS)
def test_save_claim_rejects_an_active_session_pointer_switch(
    name: str,
    build: Callable[[], PersistenceRepository],
) -> None:
    repository, claim = _seeded(build)

    with pytest.raises(KeyError):
        repository.save_claim(
            claim.model_copy(update={'revision': 2, 'active_session_id': 'ses_unvalidated'}),
            expected_revision=1,
        )

    assert repository.get_claim(CLAIM_ID, CUSTOMER_ID) == claim


@pytest.mark.parametrize(('name', 'build'), ADAPTERS)
def test_save_claim_rejects_clearing_the_active_session_pointer(
    name: str,
    build: Callable[[], PersistenceRepository],
) -> None:
    repository, claim = _seeded(build)

    with pytest.raises(KeyError):
        repository.save_claim(
            claim.model_copy(update={'revision': 2, 'active_session_id': None}),
            expected_revision=1,
        )

    assert repository.get_claim(CLAIM_ID, CUSTOMER_ID) == claim


@pytest.mark.parametrize(('name', 'build'), ADAPTERS)
def test_save_claim_reports_a_stale_expected_revision_as_a_conflict_first(
    name: str,
    build: Callable[[], PersistenceRepository],
) -> None:
    """A stale caller must still see RevisionConflict, not the next-revision rejection."""

    repository, claim = _seeded(build)
    repository.save_claim(claim.model_copy(update={'revision': 2}), expected_revision=1)
    current = repository.get_claim(CLAIM_ID, CUSTOMER_ID)
    assert current is not None

    with pytest.raises(RevisionConflict) as conflict:
        repository.save_claim(claim.model_copy(update={'revision': 2}), expected_revision=1)

    assert conflict.value.current_revision == 2
    assert repository.get_claim(CLAIM_ID, CUSTOMER_ID) == current


@pytest.mark.parametrize(('name', 'build'), ADAPTERS)
def test_save_claim_accepts_a_material_mutation_that_preserves_the_pointer(
    name: str,
    build: Callable[[], PersistenceRepository],
) -> None:
    repository, claim = _seeded(build)
    advanced = claim.model_copy(
        update={
            'revision': 2,
            'customer_next_step': CustomerNextStep(
                status='awaiting_evidence',
                summary='Upload the requested evidence.',
                responsible_party=ResponsibleParty.CLAIMANT,
            ),
        }
    )

    repository.save_claim(advanced, expected_revision=1)

    stored = repository.get_claim(CLAIM_ID, CUSTOMER_ID)
    assert stored == advanced
    assert stored is not None
    assert stored.active_session_id == SESSION_ID
