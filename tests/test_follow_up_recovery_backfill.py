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
from backend.repositories.protocols import IdempotencyConflict

NOW = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
MIGRATION_TIME = NOW + timedelta(days=10)


def _repository(
    kind: str,
) -> FixtureRepository | MongoDBRepository:
    if kind == 'fixture':
        return FixtureRepository()

    repository = MongoDBRepository(
        mongomock.MongoClient(),
        'follow_up_backfill_test',
    )
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


def _seed_legacy(
    repository: FixtureRepository | MongoDBRepository,
    suffix: str,
    *,
    contradictory_created_at: bool = False,
) -> FollowUpRecord:
    interrupted_at = NOW

    created_at = NOW + timedelta(minutes=5) if contradictory_created_at else NOW

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
        model_profile_id='openrouter-gpt-4o',
        status=SessionStatus.ACTIVE,
        context_revision=1,
        started_at=NOW,
        last_active_at=NOW,
    )

    repository.create_claim(claim, session)

    recovery = SessionRecoveryContext(
        interrupted_at=interrupted_at,
        last_meaningful_activity_at=NOW,
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

        repository._collection.insert_one(legacy_document)

    else:
        raise TypeError(f'Unsupported migration-test repository: {type(repository)!r}')

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
    assert migrated.policy_version == 1
    assert migrated.deadline_at == NOW + timedelta(days=7)

    # Historical P17.1 evidence remains unchanged.
    assert migrated.created_at == legacy.created_at
    assert migrated.due_at == legacy.due_at
    assert migrated.source_refs == legacy.source_refs
    assert migrated.attempt_count == 2

    # Migration must not fabricate historical execution records.
    assert (
        repository.list_follow_up_operations(
            legacy.claim_id,
            legacy.follow_up_id,
            f'cus_valid-{kind}',
        )
        == []
    )

    events = repository.list_audit_events_internal(follow_up_backfill_subject(migrated))

    assert len(events) == 1
    assert events[0].outcome.value == 'succeeded'
    assert events[0].actor.actor_id == 'p17-recovery-migration'

    # Exact rerun is a no-op and does not duplicate Audit.
    assert repository.backfill_incomplete_claim_recovery(
        recorded_at=MIGRATION_TIME,
    ) == (0, 0)

    assert len(repository.list_audit_events_internal(follow_up_backfill_subject(migrated))) == 1


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
    assert migrated.reason_code is FollowUpReasonCode.SOURCE_STATE_INCONSISTENT

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
    assert migrated.follow_up_id not in {item.follow_up_id for item in due}

    assert (
        repository.list_follow_up_operations(
            legacy.claim_id,
            legacy.follow_up_id,
            f'cus_invalid-{kind}',
        )
        == []
    )

    events = repository.list_audit_events_internal(follow_up_backfill_subject(migrated))

    assert len(events) == 1
    assert events[0].outcome.value == 'failed'
    assert 'failed closed' in events[0].reason.lower()


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_p17_1_backfill_replay_is_idempotent(
    kind: str,
) -> None:
    repository = _repository(kind)
    label = f'replay-{kind}'

    legacy = _seed_legacy(
        repository,
        label,
    )

    recorded_at = datetime(
        2026,
        9,
        28,
        8,
        0,
        tzinfo=UTC,
    )

    first_counts = repository.backfill_incomplete_claim_recovery(
        recorded_at=recorded_at,
    )

    assert first_counts == (1, 0)

    customer_id = f'cus_{label}'

    first = repository.get_follow_up(
        legacy.claim_id,
        legacy.follow_up_id,
        customer_id,
    )

    assert first is not None
    assert first.policy_id is not None
    assert first.policy_version is not None
    assert first.deadline_at is not None

    subject = follow_up_backfill_subject(legacy)

    first_events = repository.list_audit_events_internal(subject)

    assert len(first_events) == 1

    replay_counts = repository.backfill_incomplete_claim_recovery(
        recorded_at=(recorded_at + timedelta(minutes=5)),
    )

    assert replay_counts == (0, 0)

    replay = repository.get_follow_up(
        legacy.claim_id,
        legacy.follow_up_id,
        customer_id,
    )

    assert replay == first

    replay_events = repository.list_audit_events_internal(subject)

    assert replay_events == first_events


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_p17_1_missing_interruption_source_fails_closed(
    kind: str,
) -> None:
    repository = _repository(kind)
    label = f'missing-source-{kind}'

    legacy = _seed_legacy(
        repository,
        label,
    )

    original = deepcopy(legacy)

    # There is deliberately no separate migration clock fallback.
    # Removing the authoritative source Session also removes the only
    # permitted source for SessionRecoveryContext.interrupted_at.
    if isinstance(
        repository,
        FixtureRepository,
    ):
        repository._sessions.pop(
            legacy.source_session_id,
            None,
        )
    else:
        assert isinstance(
            repository,
            MongoDBRepository,
        )

        repository._collection.delete_many(
            {
                'record_type': 'session',
                'session_id': (legacy.source_session_id),
            }
        )

    counts = repository.backfill_incomplete_claim_recovery(
        recorded_at=datetime(
            2026,
            9,
            28,
            8,
            30,
            tzinfo=UTC,
        ),
    )

    assert counts == (0, 1)

    migrated = repository.get_follow_up(
        legacy.claim_id,
        legacy.follow_up_id,
        f'cus_{label}',
    )

    assert migrated is not None

    assert migrated.status is FollowUpStatus.BLOCKED

    assert migrated.reason_code in {
        FollowUpReasonCode.SOURCE_STATE_INCONSISTENT,
        FollowUpReasonCode.POLICY_BINDING_INVALID,
    }

    # No guessed recovery clock / automatic work.
    assert migrated.deadline_at is None
    assert migrated.due_at is not None
    assert migrated.due_at.isoformat() == '2026-09-28T08:00:00+00:00'

    # The legacy schedule is historical evidence only.  A fail-closed
    # BLOCKED obligation must never become executable due work.
    due_page, _ = repository.list_due_follow_ups(
        migrated.due_at + timedelta(seconds=1),
        limit=10,
        cursor=None,
    )

    assert migrated.follow_up_id not in {item.follow_up_id for item in due_page}

    # Historical provenance must survive fail-closed migration.
    assert migrated.created_at == original.created_at
    assert migrated.source_refs == original.source_refs

    events = repository.list_audit_events_internal(follow_up_backfill_subject(legacy))

    assert len(events) == 1


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_migrated_open_recovery_remains_deadline_discoverable(
    kind: str,
) -> None:
    repository = _repository(kind)
    label = f'deadline-discovery-{kind}'

    legacy = _seed_legacy(
        repository,
        label,
    )

    counts = repository.backfill_incomplete_claim_recovery(
        recorded_at=datetime(
            2026,
            9,
            28,
            9,
            0,
            tzinfo=UTC,
        ),
    )

    assert counts == (1, 0)

    migrated = repository.get_follow_up(
        legacy.claim_id,
        legacy.follow_up_id,
        f'cus_{label}',
    )

    assert migrated is not None
    assert migrated.deadline_at is not None

    page, cursor = repository.list_expiring_follow_ups(
        migrated.deadline_at,
        limit=10,
        cursor=None,
    )

    assert cursor is None

    assert migrated.follow_up_id in {item.follow_up_id for item in page}

    # Deadline discovery includes all open obligations, including BLOCKED,
    # and does not depend on an executable due_at.
    assert migrated.status in {
        FollowUpStatus.PENDING,
        FollowUpStatus.BLOCKED,
    }


def _set_stored_binding(
    repository: FixtureRepository | MongoDBRepository,
    follow_up: FollowUpRecord,
    fields: dict[str, object],
) -> None:
    if isinstance(repository, FixtureRepository):
        repository._follow_ups[follow_up.follow_up_id] = FollowUpRecord.model_validate(
            {**follow_up.model_dump(), **fields}
        )
        return
    repository._collection.update_one(
        {'_id': repository._record_id('follow_up', follow_up.follow_up_id)},
        {'$set': fields},
    )


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
@pytest.mark.parametrize(
    ('fields', 'bound'),
    [
        # Compatible partial binding: only the missing fields are filled.
        ({'policy_id': 'incomplete_claim_follow_up'}, True),
        ({'policy_version': 1}, True),
        # Explicit null is the same unbound state as an absent field.
        ({'policy_id': None, 'policy_version': None}, True),
        # Contradictory immutable coordinates are never rewritten.
        ({'policy_id': 'some_other_policy', 'policy_version': 7}, False),
        ({'policy_version': 7}, False),
        ({'policy_id': 'some_other_policy'}, False),
    ],
)
def test_backfill_fills_only_compatible_bindings_and_fails_closed_on_contradiction(
    kind: str,
    fields: dict[str, object],
    bound: bool,
) -> None:
    repository = _repository(kind)
    label = f'binding-{kind}-{len(fields)}-{bound}'
    legacy = _seed_legacy(repository, label)
    _set_stored_binding(repository, legacy, fields)

    counts = repository.backfill_incomplete_claim_recovery(recorded_at=MIGRATION_TIME)

    migrated = repository.get_follow_up(legacy.claim_id, legacy.follow_up_id, f'cus_{label}')
    assert migrated is not None
    assert migrated.due_at == legacy.due_at
    assert migrated.created_at == legacy.created_at
    assert migrated.attempt_count == legacy.attempt_count
    if bound:
        assert counts == (1, 0)
        assert (migrated.policy_id, migrated.policy_version) == ('incomplete_claim_follow_up', 1)
        # Interruption time, never migration time, is the clock origin.
        assert migrated.deadline_at == NOW + timedelta(days=7)
        assert migrated.status is FollowUpStatus.PENDING
        return
    assert counts == (0, 1)
    assert migrated.status is FollowUpStatus.BLOCKED
    assert migrated.reason_code is FollowUpReasonCode.POLICY_BINDING_INVALID
    assert migrated.policy_id == fields.get('policy_id')
    assert migrated.policy_version == fields.get('policy_version')
    assert migrated.deadline_at is None
    # A policy-blocked record keeps the claimant's real contact authority.
    assert migrated.contact_permission is FollowUpContactPermission.AUTHORISED


@pytest.mark.parametrize('changed', ['source_session', 'follow_up'])
def test_mongo_backfill_detects_concurrent_source_or_target_change(changed: str) -> None:
    repository = _repository('mongodb')
    assert isinstance(repository, MongoDBRepository)
    legacy = _seed_legacy(repository, f'concurrent-{changed}')
    collection = repository._collection
    original_find_one = collection.find_one
    reads = {'count': 0}

    def racing_find_one(*args, **kwargs):  # type: ignore[no-untyped-def]
        result = original_find_one(*args, **kwargs)
        reads['count'] += 1
        # After both authoritative reads (Follow-up, then Session) a competing
        # writer commits before this record's conditional writes.
        if reads['count'] == 2:
            if changed == 'source_session':
                collection.update_one(
                    {'_id': repository._record_id('session', legacy.source_session_id)},
                    {'$set': {'recovery_context.interrupted_at': MIGRATION_TIME.isoformat()}},
                )
            else:
                collection.update_one(
                    {'_id': repository._record_id('follow_up', legacy.follow_up_id)},
                    {'$set': {'policy_version': 7}},
                )
        return result

    collection.find_one = racing_find_one  # type: ignore[method-assign]
    try:
        with pytest.raises(IdempotencyConflict):
            repository.backfill_incomplete_claim_recovery(recorded_at=MIGRATION_TIME)
    finally:
        collection.find_one = original_find_one  # type: ignore[method-assign]

    stored = collection.find_one({'_id': repository._record_id('follow_up', legacy.follow_up_id)})
    assert stored is not None
    assert stored.get('deadline_at') is None
    assert stored.get('policy_id') is None
    assert repository.list_audit_events_internal(follow_up_backfill_subject(legacy)) == []


def test_operator_backfill_script_delegates_to_repository_contract() -> None:
    from scripts.backfill_follow_up_policy import backfill_follow_ups

    repository = _repository('mongodb')
    assert isinstance(repository, MongoDBRepository)
    valid = _seed_legacy(repository, 'script-valid')
    conflicting = _seed_legacy(repository, 'script-conflicting')
    _set_stored_binding(repository, conflicting, {'policy_version': 7})

    dry_run = backfill_follow_ups(repository, recorded_at=MIGRATION_TIME)
    assert dry_run['bound'] == [repository._record_id('follow_up', valid.follow_up_id)]
    assert dry_run['fail_closed'] == [repository._record_id('follow_up', conflicting.follow_up_id)]
    untouched = repository.get_follow_up(valid.claim_id, valid.follow_up_id, 'cus_script-valid')
    assert untouched is not None and untouched.deadline_at is None

    applied = backfill_follow_ups(repository, apply=True, recorded_at=MIGRATION_TIME)
    assert applied['applied'] == {'bound': 1, 'fail_closed': 1}
    kept = repository.get_follow_up(
        conflicting.claim_id, conflicting.follow_up_id, 'cus_script-conflicting'
    )
    assert kept is not None and kept.policy_version == 7
