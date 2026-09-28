from copy import deepcopy
from datetime import UTC, datetime, timedelta

import mongomock
import pytest

from backend.domain.follow_up_migration import (
    follow_up_backfill_subject,
)
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

NOW = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
MIGRATION_TIME = NOW + timedelta(days=10)


def _repository(kind: str):
    if kind == 'fixture':
        return FixtureRepository()

    repository = MongoDBRepository(
        mongomock.MongoClient(),
        'follow_up_backfill_test',
    )
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


def _seed_legacy(
    repository,
    suffix: str,
    *,
    contradictory_created_at: bool = False,
):
    interrupted_at = NOW

    created_at = (
        NOW + timedelta(minutes=5)
        if contradictory_created_at
        else NOW
    )

    claim_id = f'clm_{suffix}'
    customer_id = f'cus_{suffix}'
    session_id = f'ses_{suffix}'
    follow_up_id = f'fup_{suffix}'

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
        created_at=NOW,
        updated_at=NOW,
    )

    session = SessionRecord(
        session_id=session_id,
        claim_id=claim_id,
        customer_id=customer_id,
        status=SessionStatus.ACTIVE,
        context_revision=1,
        started_at=NOW,
        last_active_at=NOW,
    )

    repository.create_claim(claim, session)

    recovery = SessionRecoveryContext(
        interrupted_at=interrupted_at,
        last_meaningful_activity_at=NOW,
        last_meaningful_activity_source_ref=(
            f'claim:{claim_id}:revision:1'
        ),
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
            'updated_at': NOW,
        }
    )

    due_at = NOW + timedelta(hours=2)

    # Deliberately P17.1 legacy: no policy_id, policy_version,
    # deadline_at or typed reason.
    follow_up = FollowUpRecord(
        follow_up_id=follow_up_id,
        claim_id=claim_id,
        source_session_id=session_id,
        responsible_party=ResponsibleParty.SYSTEM,
        source_refs=[
            f'session:{session_id}',
            f'claim:{claim_id}:revision:2',
        ],
        contact_permission=FollowUpContactPermission.AUTHORISED,
        attempt_count=2,
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=due_at,
        created_at=created_at,
        updated_at=created_at,
    )

    # This deliberately seeds pre-contract P17.1 persistence state.
    #
    # Do NOT use save_incomplete_checkpoint here: that API represents the
    # current creation contract and correctly refuses a newly-created Follow-up
    # whose attempt_count is already non-zero. Migration tests instead need to
    # reproduce a record that was persisted before the current contract existed.
    if isinstance(repository, FixtureRepository):
        repository._claims[claim_id] = deepcopy(paused_claim)
        repository._sessions[session_id] = deepcopy(paused_session)
        repository._follow_ups[follow_up_id] = deepcopy(follow_up)

    elif isinstance(repository, MongoDBRepository):
        repository._put(
            'claim',
            claim_id,
            paused_claim,
            customer_id=customer_id,
            claim_id=claim_id,
        )
        repository._put(
            'session',
            session_id,
            paused_session,
            customer_id=customer_id,
            claim_id=claim_id,
        )

        # exclude_none=True is intentional.  A genuine P17.1 Mongo document
        # predates policy_id / policy_version / deadline_at / reason_code;
        # those fields are absent rather than newly persisted as null.
        legacy_document = {
            **follow_up.model_dump(
                mode='json',
                exclude_none=True,
            ),
            '_id': repository._record_id(
                'follow_up',
                follow_up_id,
            ),
            'record_type': 'follow_up',
            'customer_id': customer_id,
            'claim_id': claim_id,
        }

        repository._collection.insert_one(
            legacy_document
        )

    else:
        raise TypeError(
            f'Unsupported migration-test repository: {type(repository)!r}'
        )

    return follow_up


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_valid_p17_1_backfill_binds_from_original_interruption(
    kind: str,
) -> None:
    repository = _repository(kind)
    legacy = _seed_legacy(repository, f'valid-{kind}')

    result = repository.backfill_incomplete_claim_recovery(
        recorded_at=MIGRATION_TIME,
    )

    assert result == (1, 0)

    migrated = repository.get_follow_up(
        legacy.claim_id,
        legacy.follow_up_id,
        f'cus_valid-{kind}',
    )

    assert migrated is not None
    assert migrated.policy_id == 'incomplete_claim_follow_up'
    assert migrated.policy_version == 'v1'
    assert migrated.deadline_at == NOW + timedelta(days=7)

    # Historical P17.1 evidence remains unchanged.
    assert migrated.created_at == legacy.created_at
    assert migrated.due_at == legacy.due_at
    assert migrated.source_refs == legacy.source_refs
    assert migrated.attempt_count == 2

    # Migration must not fabricate historical execution records.
    assert repository.list_follow_up_operations(
        legacy.claim_id,
        legacy.follow_up_id,
        f'cus_valid-{kind}',
    ) == []

    events = repository.list_audit_events_internal(
        follow_up_backfill_subject(migrated)
    )

    assert len(events) == 1
    assert events[0].outcome.value == 'succeeded'
    assert events[0].actor.actor_id == 'p17-recovery-migration'

    # Exact rerun is a no-op and does not duplicate Audit.
    assert repository.backfill_incomplete_claim_recovery(
        recorded_at=MIGRATION_TIME,
    ) == (0, 0)

    assert len(
        repository.list_audit_events_internal(
            follow_up_backfill_subject(migrated)
        )
    ) == 1


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_contradictory_p17_1_record_fails_closed_without_guessing(
    kind: str,
) -> None:
    repository = _repository(kind)

    legacy = _seed_legacy(
        repository,
        f'invalid-{kind}',
        contradictory_created_at=True,
    )

    original_due = legacy.due_at
    original_refs = list(legacy.source_refs)

    result = repository.backfill_incomplete_claim_recovery(
        recorded_at=MIGRATION_TIME,
    )

    assert result == (0, 1)

    migrated = repository.get_follow_up(
        legacy.claim_id,
        legacy.follow_up_id,
        f'cus_invalid-{kind}',
    )

    assert migrated is not None
    assert migrated.status is FollowUpStatus.BLOCKED
    assert (
        migrated.reason_code
        is FollowUpReasonCode.SOURCE_STATE_INCONSISTENT
    )

    # No invented recovery clock/policy binding.
    assert migrated.policy_id is None
    assert migrated.policy_version is None
    assert migrated.deadline_at is None

    # Historical evidence is preserved even though it is no longer executable.
    assert migrated.created_at == legacy.created_at
    assert migrated.due_at == original_due
    assert migrated.source_refs == original_refs
    assert migrated.attempt_count == legacy.attempt_count

    due, _ = repository.list_due_follow_ups(
        MIGRATION_TIME,
        limit=10,
        cursor=None,
    )
    assert migrated.follow_up_id not in {
        item.follow_up_id for item in due
    }

    assert repository.list_follow_up_operations(
        legacy.claim_id,
        legacy.follow_up_id,
        f'cus_invalid-{kind}',
    ) == []

    events = repository.list_audit_events_internal(
        follow_up_backfill_subject(migrated)
    )

    assert len(events) == 1
    assert events[0].outcome.value == 'failed'
    assert 'failed closed' in events[0].reason.lower()
