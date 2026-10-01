"""Blocked retention work cannot starve later work: discovery is a resumable keyset sweep."""

from datetime import timedelta

import pytest

from backend.adapters.evidence_storage import MockEvidenceStorage
from backend.domain.external_services import (
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
)
from backend.domain.models import IntegrationSource, WorkingClaim
from backend.domain.retention import RetentionOperationStatus
from backend.repositories.fixture import FixtureRepository
from backend.repositories.pagination import (
    InvalidRepositoryCursorError,
    RetentionDiscoveryCursor,
    encode_retention_discovery_cursor,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.recovery_worker import run_recovery_cycle
from tests.test_retention_repository_guards import (
    NOW,
    _create,
    _manual_operation,
    _repository,
    _terminalise,
)

LIMIT = 2


def _terminal_claim(
    repository: PersistenceRepository, claim_id: str, *, blocked: bool
) -> WorkingClaim:
    """Create a retention-eligible terminal Claim, optionally with an unknown external result."""

    base = _create(repository, claim_id)
    if blocked:
        repository.save_external_task(
            ExternalTaskRecord(
                task_id=f'ext_{claim_id}',
                claim_id=claim_id,
                service_identity='vehicle_damage_assessment_routing',
                requested_action='vehicle_damage_assessment',
                integration_source=IntegrationSource.FIXTURE,
                status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
                delivery=ExternalTaskDelivery.SUBMITTED,
                delivery_evidence='fixture:submitted',
                failure_code=ExternalTaskFailureCode.TIMEOUT,
                created_at=NOW + timedelta(seconds=10),
                updated_at=NOW + timedelta(seconds=10),
            ),
            base.customer_id,
        )
    return _terminalise(repository, base)


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_blocked_handoffs_cannot_starve_a_later_eligible_claim(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    # A full page of older eligible Claims that reservation must refuse.
    for suffix in ('a', 'b'):
        _terminal_claim(repository, f'clm_handoff_sweep_{suffix}_{kind}', blocked=True)
    ready = _terminal_claim(repository, f'clm_handoff_sweep_z_{kind}', blocked=False)
    storage = MockEvidenceStorage()

    first = run_recovery_cycle(repository, storage, now=NOW + timedelta(minutes=10), limit=LIMIT)
    assert first.retention_blocked == LIMIT
    assert repository.get_retention_operation_for_claim(ready.claim_id) is None
    assert first.handoff_cursor is not None

    second = run_recovery_cycle(
        repository,
        storage,
        now=NOW + timedelta(minutes=11),
        limit=LIMIT,
        handoff_cursor=first.handoff_cursor,
        pending_retention_cursor=first.pending_retention_cursor,
    )
    retention = repository.get_retention_operation_for_claim(ready.claim_id)
    assert retention is not None
    assert retention.status is RetentionOperationStatus.COMPLETED
    assert second.handoff_cursor is None
    for suffix in ('a', 'b'):
        blocked_id = f'clm_handoff_sweep_{suffix}_{kind}'
        assert repository.get_retention_operation_for_claim(blocked_id) is None


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_blocked_pending_retention_cannot_starve_a_later_operation(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    # Reserved operations whose cleanup freeze must refuse an unknown external result.
    for suffix in ('a', 'b'):
        blocked = _terminal_claim(repository, f'clm_pending_sweep_{suffix}_{kind}', blocked=True)
        assert repository.reserve_retention_operation(_manual_operation(blocked)) is True
    ready = _terminal_claim(repository, f'clm_pending_sweep_z_{kind}', blocked=False)
    assert repository.reserve_retention_operation(_manual_operation(ready)) is True
    storage = MockEvidenceStorage()

    first = run_recovery_cycle(repository, storage, now=NOW + timedelta(minutes=10), limit=LIMIT)
    untouched = repository.get_retention_operation_for_claim(ready.claim_id)
    assert first.retention_blocked == LIMIT
    assert untouched is not None and untouched.targets_frozen_at is None
    assert first.pending_retention_cursor is not None

    run_recovery_cycle(
        repository,
        storage,
        now=NOW + timedelta(minutes=11),
        limit=LIMIT,
        handoff_cursor=first.handoff_cursor,
        pending_retention_cursor=first.pending_retention_cursor,
    )
    completed = repository.get_retention_operation_for_claim(ready.claim_id)
    assert completed is not None
    assert completed.status is RetentionOperationStatus.COMPLETED


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_retention_discovery_pages_are_bounded_and_resume_after_the_cursor(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    ids = [f'clm_page_{suffix}_{kind}' for suffix in ('a', 'b', 'c')]
    for claim_id in ids:
        _terminal_claim(repository, claim_id, blocked=False)

    first, cursor = repository.list_retention_handoff_candidates(limit=LIMIT)
    second, end = repository.list_retention_handoff_candidates(limit=LIMIT, cursor=cursor)

    assert first == ids[:LIMIT]
    assert second == ids[LIMIT:]
    assert cursor is not None and end is None


@pytest.mark.parametrize(
    'value',
    [
        encode_retention_discovery_cursor(
            RetentionDiscoveryCursor('pending', NOW, 'ret_operation')
        ),
        'not-a-cursor',
    ],
    ids=['other-sweep', 'malformed'],
)
def test_handoff_discovery_refuses_a_foreign_or_malformed_cursor(value: str) -> None:
    with pytest.raises(InvalidRepositoryCursorError):
        FixtureRepository().list_retention_handoff_candidates(limit=LIMIT, cursor=value)
