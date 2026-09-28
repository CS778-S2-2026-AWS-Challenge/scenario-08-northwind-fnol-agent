from datetime import UTC, datetime, timedelta

import mongomock
import pytest

from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    FollowUpContactPermission,
    FollowUpReasonCode,
    FollowUpRecord,
    FollowUpStatus,
    PreferredChannel,
    ResponsibleParty,
    SessionRecord,
    SessionRecoveryContext,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.pagination import InvalidRepositoryCursorError
from backend.repositories.protocols import IdempotencyRecord

NOW = datetime(2026, 9, 28, 5, 0, tzinfo=UTC)


def _repository(kind: str) -> FixtureRepository | MongoDBRepository:
    if kind == 'fixture':
        return FixtureRepository()

    repository = MongoDBRepository(
        mongomock.MongoClient(),
        'follow_up_discovery_test',
    )
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


def _seed_follow_up(
    repository: FixtureRepository | MongoDBRepository,
    suffix: str,
    *,
    status: FollowUpStatus,
    due_at: datetime | None,
    deadline_at: datetime,
) -> FollowUpRecord:
    created_at = NOW - timedelta(days=3)

    claim_id = f'clm_{suffix}'
    session_id = f'ses_{suffix}'
    follow_up_id = f'fup_{suffix}'
    customer_id = f'cus_{suffix}'

    claim = WorkingClaim(
        claim_id=claim_id,
        customer_id=customer_id,
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='motor',
        claim_state=ClaimState(),
        active_session_id=session_id,
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Continue describing the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=created_at,
        updated_at=created_at,
    )

    session = SessionRecord(
        session_id=session_id,
        claim_id=claim_id,
        customer_id=customer_id,
        status=SessionStatus.ACTIVE,
        context_revision=1,
        started_at=created_at,
        last_active_at=created_at,
    )

    repository.create_claim(claim, session)

    recovery = SessionRecoveryContext(
        interrupted_at=created_at,
        last_meaningful_activity_at=created_at,
        last_meaningful_activity_source_ref=(f'claim:{claim_id}:revision:1'),
        resume_point='Continue describing the incident.',
    )

    paused_session = session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            'recovery_context': recovery,
        }
    )

    paused_claim = claim.model_copy(
        update={
            'revision': 2,
            'active_session_id': None,
            'updated_at': created_at,
        }
    )

    blocked = status is FollowUpStatus.BLOCKED

    follow_up = FollowUpRecord(
        follow_up_id=follow_up_id,
        claim_id=claim_id,
        source_session_id=session_id,
        policy_id='incomplete_claim_follow_up',
        policy_version='v1',
        deadline_at=deadline_at,
        responsible_party=ResponsibleParty.SYSTEM,
        source_refs=[f'session:{session_id}'],
        contact_permission=(
            FollowUpContactPermission.NOT_AUTHORISED
            if blocked
            else FollowUpContactPermission.AUTHORISED
        ),
        channel=None if blocked else PreferredChannel.IN_APP,
        blocked_reason=(FollowUpReasonCode.CONTACT_NOT_AUTHORISED if blocked else None),
        status=status,
        due_at=due_at,
        created_at=created_at,
        updated_at=created_at,
    )

    idempotency = IdempotencyRecord(
        actor_id=customer_id,
        route=f'/test/{suffix}/pause',
        key=f'{suffix}-pause',
        request_fingerprint=f'{suffix}-pause',
        claim_id=claim_id,
        session_id=session_id,
        follow_up_id=follow_up_id,
    )

    repository.save_incomplete_checkpoint(
        paused_claim,
        expected_revision=1,
        session=paused_session,
        follow_up=follow_up,
        idempotency=idempotency,
    )

    return follow_up


def _seed_discovery_set(
    repository: FixtureRepository | MongoDBRepository,
) -> tuple[FollowUpRecord, FollowUpRecord, FollowUpRecord, FollowUpRecord]:
    due_a = _seed_follow_up(
        repository,
        'due-a',
        status=FollowUpStatus.PENDING,
        due_at=NOW - timedelta(hours=2),
        deadline_at=NOW + timedelta(days=2),
    )

    due_b = _seed_follow_up(
        repository,
        'due-b',
        status=FollowUpStatus.PENDING,
        due_at=NOW - timedelta(hours=2),
        deadline_at=NOW + timedelta(days=2),
    )

    _seed_follow_up(
        repository,
        'future',
        status=FollowUpStatus.PENDING,
        due_at=NOW + timedelta(hours=1),
        deadline_at=NOW + timedelta(days=2),
    )

    expired_blocked = _seed_follow_up(
        repository,
        'expired-blocked',
        status=FollowUpStatus.BLOCKED,
        due_at=None,
        deadline_at=NOW - timedelta(hours=2),
    )

    expired_pending = _seed_follow_up(
        repository,
        'expired-pending',
        status=FollowUpStatus.PENDING,
        due_at=NOW - timedelta(hours=3),
        deadline_at=NOW - timedelta(hours=1),
    )

    return (
        due_a,
        due_b,
        expired_blocked,
        expired_pending,
    )


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_due_discovery_is_bounded_stable_and_excludes_expired(
    kind: str,
) -> None:
    repository = _repository(kind)
    due_a, due_b, _, _ = _seed_discovery_set(repository)

    first, cursor = repository.list_due_follow_ups(
        NOW,
        limit=1,
        cursor=None,
    )

    assert [item.follow_up_id for item in first] == [due_a.follow_up_id]
    assert cursor is not None

    with pytest.raises(InvalidRepositoryCursorError):
        repository.list_due_follow_ups(
            NOW + timedelta(seconds=1),
            limit=1,
            cursor=cursor,
        )

    second, next_cursor = repository.list_due_follow_ups(
        NOW,
        limit=1,
        cursor=cursor,
    )

    assert [item.follow_up_id for item in second] == [due_b.follow_up_id]
    assert next_cursor is None


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_deadline_discovery_includes_blocked_without_due_time(
    kind: str,
) -> None:
    repository = _repository(kind)
    _, _, blocked, pending = _seed_discovery_set(repository)

    first, cursor = repository.list_expiring_follow_ups(
        NOW,
        limit=1,
        cursor=None,
    )

    assert [item.follow_up_id for item in first] == [blocked.follow_up_id]
    assert first[0].due_at is None
    assert cursor is not None

    with pytest.raises(InvalidRepositoryCursorError):
        repository.list_due_follow_ups(
            NOW,
            limit=1,
            cursor=cursor,
        )

    second, next_cursor = repository.list_expiring_follow_ups(
        NOW,
        limit=1,
        cursor=cursor,
    )

    assert [item.follow_up_id for item in second] == [pending.follow_up_id]
    assert next_cursor is None


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_follow_up_discovery_limit_is_bounded(
    kind: str,
) -> None:
    repository = _repository(kind)

    with pytest.raises(ValueError):
        repository.list_due_follow_ups(
            NOW,
            limit=0,
            cursor=None,
        )

    with pytest.raises(ValueError):
        repository.list_expiring_follow_ups(
            NOW,
            limit=1001,
            cursor=None,
        )
