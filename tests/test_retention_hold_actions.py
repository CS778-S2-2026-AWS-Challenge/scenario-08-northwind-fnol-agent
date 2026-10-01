"""Authorised staff apply and release retention holds through the Workbench contract."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import MockEvidenceStorage
from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.models import WorkingClaim
from backend.domain.recovery_policy_registry import INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
from backend.domain.retention import (
    ApplyRetentionHoldRequest,
    ReleaseRetentionHoldRequest,
    RetentionHoldReason,
    RetentionOperationStatus,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services.follow_up_recovery import process_expiring_follow_up
from backend.services.recovery_worker import run_recovery_cycle
from backend.services.retention import reserve_retention_from_terminal
from backend.services.retention_holds import apply_retention_hold, release_retention_hold
from tests.test_p17_staff_abandonment import _checkpoint, _repository

OWNER = Principal(
    subject='stf_demo',
    actor_type='staff',
    auth_source='test:staff_session',
    scopes=frozenset({'workbench:read', 'workbench:write'}),
)
APPLY = ApplyRetentionHoldRequest(
    reason=RetentionHoldReason.INVESTIGATION,
    note='Fraud team case FT-12 requires the records to be kept.',
)
RELEASE = ReleaseRetentionHoldRequest(note='Fraud team case FT-12 is closed.')


def _expired_with_retention(
    repository: PersistenceRepository, claim_id: str
) -> tuple[WorkingClaim, datetime]:
    """Expire the recovery and reserve retention, as the worker does at the deadline."""

    claim, follow_up, interrupted_at = _checkpoint(repository, claim_id=claim_id)
    deadline = interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
    assert process_expiring_follow_up(repository, follow_up, deadline) is not None
    reserve_retention_from_terminal(repository, claim.claim_id, now=deadline)
    expired = repository.get_claim_internal(claim.claim_id)
    assert expired is not None
    return expired, deadline


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_hold_blocks_cleanup_until_release_resumes_the_same_operation(kind: str) -> None:
    repository = _repository(kind)
    claim, deadline = _expired_with_retention(repository, f'clm_hold_cycle_{kind}')
    storage = MockEvidenceStorage()
    reserved = repository.get_retention_operation_for_claim(claim.claim_id)
    assert reserved is not None

    hold = apply_retention_hold(
        repository, OWNER, claim.claim_id, APPLY, f'hold-{kind}', str(claim.revision)
    )
    assert hold.active is True
    assert hold.reason is RetentionHoldReason.INVESTIGATION

    blocked = run_recovery_cycle(repository, storage, now=deadline + timedelta(minutes=1), limit=10)
    held = repository.get_retention_operation_for_claim(claim.claim_id)
    assert blocked.retention_progressed == 0
    assert held is not None and held.status is RetentionOperationStatus.HELD
    assert held.targets_frozen_at is None
    assert repository.get_claim_internal(claim.claim_id) is not None

    released = release_retention_hold(
        repository,
        OWNER,
        claim.claim_id,
        hold.hold_id,
        RELEASE,
        f'release-{kind}',
        str(claim.revision),
    )
    assert released.active is False and released.released_at is not None

    resumed = run_recovery_cycle(repository, storage, now=deadline + timedelta(minutes=2), limit=10)
    completed = repository.get_retention_operation_for_claim(claim.claim_id)
    assert resumed.retention_progressed == 1
    assert completed is not None
    assert completed.operation_id == reserved.operation_id
    assert completed.status is RetentionOperationStatus.COMPLETED
    assert hold.hold_id in completed.hold_refs


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_hold_actions_replay_exactly_and_refuse_a_reused_key(kind: str) -> None:
    repository = _repository(kind)
    claim, _ = _expired_with_retention(repository, f'clm_hold_replay_{kind}')

    first = apply_retention_hold(
        repository, OWNER, claim.claim_id, APPLY, 'hold-replay', str(claim.revision)
    )
    replay = apply_retention_hold(
        repository, OWNER, claim.claim_id, APPLY, 'hold-replay', str(claim.revision)
    )
    assert replay == first
    assert [item.hold_id for item in repository.list_retention_holds(claim.claim_id)] == [
        first.hold_id
    ]

    with pytest.raises(ApiError) as reused:
        apply_retention_hold(
            repository,
            OWNER,
            claim.claim_id,
            APPLY.model_copy(update={'reason': RetentionHoldReason.LEGAL_HOLD}),
            'hold-replay',
            str(claim.revision),
        )
    assert (reused.value.status_code, reused.value.code) == (409, 'IDEMPOTENCY_CONFLICT')

    # An active hold offers only release, so a second apply is not executable.
    with pytest.raises(ApiError) as second:
        apply_retention_hold(
            repository, OWNER, claim.claim_id, APPLY, 'hold-second', str(claim.revision)
        )
    assert second.value.status_code == 403


@pytest.mark.parametrize(
    ('principal', 'status_code'),
    [
        (
            Principal(
                subject='stf_demo',
                actor_type='staff',
                auth_source='test:staff_session',
                scopes=frozenset({'workbench:read'}),
            ),
            403,
        ),
        (
            Principal(
                subject='stf_other',
                actor_type='staff',
                auth_source='test:staff_session',
                scopes=frozenset({'workbench:read', 'workbench:write'}),
            ),
            403,
        ),
    ],
    ids=['read-only-staff', 'not-primary-owner'],
)
def test_only_the_primary_owner_with_write_scope_can_apply_a_hold(
    principal: Principal, status_code: int
) -> None:
    repository = _repository('fixture')
    claim, _ = _expired_with_retention(repository, 'clm_hold_denied')

    with pytest.raises(ApiError) as denied:
        apply_retention_hold(
            repository, principal, claim.claim_id, APPLY, 'hold-denied', str(claim.revision)
        )

    assert denied.value.status_code == status_code
    assert repository.list_retention_holds(claim.claim_id) == []


def test_workbench_hold_routes_create_release_and_project_hold_state(
    client: TestClient,
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim, _ = _expired_with_retention(repository, 'clm_hold_api')
    headers = {**staff_auth_headers, 'If-Match': str(claim.revision)}

    detail = client.get(f'/api/v1/workbench/claims/{claim.claim_id}', headers=staff_auth_headers)
    offered = {item['action_code'] for item in detail.json()['allowed_actions']}
    assert 'retention.hold.apply' in offered

    created = client.post(
        f'/api/v1/workbench/claims/{claim.claim_id}/retention-holds',
        headers={**headers, 'Idempotency-Key': 'api-hold'},
        json=APPLY.model_dump(mode='json'),
    )
    assert created.status_code == 201, created.text
    hold_id = created.json()['hold_id']
    retention = client.get(
        f'/api/v1/workbench/claims/{claim.claim_id}/retention', headers=staff_auth_headers
    )
    assert retention.json()['hold_active'] is True

    released = client.post(
        f'/api/v1/workbench/claims/{claim.claim_id}/retention-holds/{hold_id}/release',
        headers={**headers, 'Idempotency-Key': 'api-release'},
        json=RELEASE.model_dump(mode='json'),
    )
    assert released.status_code == 200, released.text
    assert released.json()['active'] is False
    retention = client.get(
        f'/api/v1/workbench/claims/{claim.claim_id}/retention', headers=staff_auth_headers
    )
    assert retention.json()['hold_active'] is False
