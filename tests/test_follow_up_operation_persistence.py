from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Any
from unittest.mock import MagicMock

import mongomock
import pytest
from pymongo.collection import Collection

from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    FollowUpContactPermission,
    FollowUpOperation,
    FollowUpOperationResult,
    FollowUpOperationStatus,
    FollowUpReasonCode,
    FollowUpRecord,
    FollowUpResolutionCode,
    FollowUpStatus,
    PreferredChannel,
    ResponsibleParty,
    RetentionOperation,
    RetentionOperationStatus,
    WorkingClaim,
)
from backend.domain.recovery_time import recovery_timestamp
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyConflict
from scripts.backfill_follow_up_policy import backfill_follow_ups


def _commit_bundle(repository: Any) -> tuple[Any, ...]:
    from dataclasses import replace

    from backend.domain.audit import AuditEventEnvelope
    from backend.domain.recovery import follow_up_commit_fingerprint
    from backend.repositories.protocols import IdempotencyRecord

    claim, follow_up = _seed(repository)
    operation = _operation()
    repository.save_follow_up_operation(operation)
    committed = FollowUpOperation.model_validate(
        {
            **operation.model_dump(),
            'status': 'committed',
            'result_code': 'in_app_committed',
            'committed_at': operation.created_at,
        }
    )
    aggregate = follow_up.model_copy(
        update={'attempt_count': 1, 'due_at': follow_up.created_at + timedelta(hours=24)}
    )
    updated = claim.model_copy(update={'revision': 3})
    idem = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='internal:follow_up',
        key=operation.operation_id,
        request_fingerprint='synthetic-operation',
        claim_id=claim.claim_id,
        session_id='',
        follow_up_id=follow_up.follow_up_id,
        response_payload={'operation_id': operation.operation_id},
    )
    audit = AuditEventEnvelope.model_validate(
        {
            'event_id': 'aud_follow_up_commit',
            'event_type': 'action.completed',
            'outcome': 'succeeded',
            'subject': {
                'subject_type': 'claim',
                'subject_id': claim.claim_id,
                'claim_id': claim.claim_id,
            },
            'actor': {'actor_type': 'system', 'actor_id': 'recovery', 'auth_source': 'test'},
            'reason': 'Synthetic in-app operation committed.',
            'visibility': 'internal_only',
            'correlation_id': operation.operation_id,
            'claim_revision': 3,
            'created_at': claim.created_at,
        }
    )
    idem = replace(
        idem,
        request_fingerprint=follow_up_commit_fingerprint(
            operation, committed, follow_up, aggregate, updated, (audit,)
        ),
    )
    return operation, committed, follow_up, aggregate, updated, idem, (audit,)


def test_commit_bundle_advances_aggregate_and_preserves_exact_replay(
    recovery_repository: Any,
) -> None:
    repository = recovery_repository
    bundle = _commit_bundle(repository)
    operation, committed, follow_up, aggregate, claim, idem, audit = bundle
    with pytest.raises(ValueError, match='commit_follow_up_operation'):
        repository.advance_follow_up_operation(operation, committed)
    assert repository.commit_follow_up_operation(*bundle) == committed
    assert repository.commit_follow_up_operation(*bundle) == committed
    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert (
        repository.get_follow_up(claim.claim_id, follow_up.follow_up_id, claim.customer_id)
        == aggregate
    )
    assert repository.find_idempotency(idem.actor_id, idem.route, idem.key) == idem
    with pytest.raises(IdempotencyConflict):
        repository.commit_follow_up_operation(
            *bundle[:-1], (audit[0].model_copy(update={'reason': 'changed'}),)
        )


@pytest.mark.parametrize('change', ['revision', 'follow_up', 'audit', 'deadline', 'session'])
def test_commit_rejection_leaves_reservation_and_aggregate_unchanged(
    recovery_repository: Any, change: str
) -> None:
    from backend.repositories.protocols import RevisionConflict

    repository = recovery_repository
    bundle = list(_commit_bundle(repository))
    operation, _, original, _, claim, idem, _ = bundle
    if change == 'revision':
        bundle[4] = claim.model_copy(update={'revision': 4})
    elif change == 'follow_up':
        bundle[2] = original.model_copy(update={'outcome': 'stale'})
    elif change == 'audit':
        bundle[6] = ()
    elif change == 'deadline':
        bundle[1] = bundle[1].model_copy(
            update={'committed_at': original.deadline_at, 'updated_at': original.deadline_at}
        )
    else:
        bundle[3] = bundle[3].model_copy(update={'source_session_id': 'wrong'})
    from dataclasses import replace

    from backend.domain.recovery import follow_up_commit_fingerprint

    bundle[5] = replace(
        idem,
        request_fingerprint=follow_up_commit_fingerprint(
            bundle[0], bundle[1], bundle[2], bundle[3], bundle[4], bundle[6]
        ),
    )
    with pytest.raises((ValueError, KeyError, IdempotencyConflict, RevisionConflict)):
        repository.commit_follow_up_operation(*bundle)
    assert repository.get_follow_up_operation(operation.operation_id) == operation
    assert (
        repository.get_follow_up(claim.claim_id, original.follow_up_id, claim.customer_id)
        == original
    )
    assert repository.find_idempotency(idem.actor_id, idem.route, idem.key) is None


@pytest.mark.parametrize('anonymous', [True, False])
def test_service_pause_resume_stores_valid_record_in_both_adapters(
    recovery_repository: Any, anonymous: bool
) -> None:
    from backend.core.auth import Principal
    from backend.domain.models import SessionRecord, StartSessionRequest
    from backend.services.claims import pause_session, start_session

    repository = recovery_repository
    now = datetime.now(UTC)
    customer = 'anonymous:synthetic' if anonymous else 'cus_operation_test'
    claim = WorkingClaim(
        claim_id='clm_resume_probe',
        customer_id=customer,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id='ses_resume_probe',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=now,
        updated_at=now,
    )
    session = SessionRecord(
        session_id='ses_resume_probe',
        claim_id=claim.claim_id,
        customer_id=customer,
        started_at=now,
        last_active_at=now,
    )
    repository.create_claim(claim, session)
    principal = Principal(
        subject=customer, actor_type='claimant', auth_source='anonymous' if anonymous else 'test'
    )
    pause_session(repository, principal, claim.claim_id, session.session_id, 'pause', '1')
    resumed = start_session(
        repository, principal, claim.claim_id, StartSessionRequest(intent='resume'), 'resume'
    )
    follow_ups = repository.list_follow_ups(claim.claim_id, customer)
    assert len(follow_ups) == 1
    stored = FollowUpRecord.model_validate(follow_ups[0].model_dump())
    assert stored.resolution_code is FollowUpResolutionCode.CLAIMANT_RESUMED
    assert stored.blocked_reason is None and stored.due_at is None
    assert repository.get_claim(claim.claim_id, customer).active_session_id == resumed.session_id


def test_blocked_exhaustion_preserves_contact_authority_and_deadline() -> None:
    source = _follow_up()
    blocked = FollowUpRecord.model_validate(
        {
            **source.model_dump(),
            'status': 'blocked',
            'blocked_reason': 'attempt_limit_reached',
            'due_at': None,
        }
    )
    assert blocked.contact_permission is FollowUpContactPermission.AUTHORISED
    assert blocked.deadline_at == source.deadline_at
    with pytest.raises(ValueError):
        FollowUpRecord.model_validate(
            {**blocked.model_dump(), 'blocked_reason': 'contact_not_authorised'}
        )


@pytest.mark.parametrize('replay', [False, True])
def test_mongo_concurrent_retention_insert_is_immutable(
    monkeypatch: pytest.MonkeyPatch, replay: bool
) -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'retention_race')
    claim, _ = _seed(repository)
    initial = _retention(claim)
    competing = initial if replay else initial.model_copy(update={'policy_version': 2})
    insert = repository._collection.insert_one
    barrier = Barrier(2)

    def synchronized(document: Any, **kwargs: Any) -> Any:
        barrier.wait(timeout=5)
        return insert(document, **kwargs)

    monkeypatch.setattr(repository._collection, 'insert_one', synchronized)

    def save(record: RetentionOperation) -> str:
        try:
            repository.save_retention_operation(record)
            return 'saved'
        except IdempotencyConflict:
            return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(save, [initial, competing]))
    assert outcomes == (['saved', 'saved'] if replay else ['conflict', 'saved'])
    assert repository.get_retention_operation(initial.operation_id) in [initial, competing]


def test_concurrent_cancellation_has_one_final_result(
    recovery_repository: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = recovery_repository
    _seed(repository)
    reserved = _operation()
    repository.save_follow_up_operation(reserved)
    first = FollowUpOperation.model_validate(
        {
            **reserved.model_dump(),
            'status': 'cancelled',
            'result_code': 'authority_lost',
            'cancelled_at': reserved.created_at,
        }
    )
    second = first.model_copy(update={'result_code': FollowUpOperationResult.STALE_REVISION})
    barrier = Barrier(2)
    if isinstance(repository, MongoDBRepository):
        replace = repository._collection.replace_one

        def synchronized(*args: Any, **kwargs: Any) -> Any:
            barrier.wait(timeout=5)
            return replace(*args, **kwargs)

        monkeypatch.setattr(repository._collection, 'replace_one', synchronized)

    def advance(record: FollowUpOperation) -> str:
        if isinstance(repository, FixtureRepository):
            barrier.wait(timeout=5)
        try:
            repository.advance_follow_up_operation(reserved, record)
            return 'saved'
        except IdempotencyConflict:
            return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(advance, [first, second])) == ['conflict', 'saved']
    assert repository.get_follow_up_operation(reserved.operation_id) in [first, second]


@pytest.mark.parametrize(
    'updates',
    [
        {'hold_reason': 'unexpected'},
        {'target_refs': ['a', 'a']},
        {'step_results': {'not-selected': 'deleted'}},
        {'step_results': {'object:a': 'invented'}},
        {'status': RetentionOperationStatus.COMPLETED},
    ],
)
def test_retention_rejects_unproven_completion_and_invalid_evidence(
    updates: dict[str, Any],
) -> None:
    claim, _ = _seed(FixtureRepository())
    with pytest.raises(ValueError):
        RetentionOperation.model_validate({**_retention(claim).model_dump(), **updates})


def test_operations_cannot_be_created_with_unearned_terminal_evidence(
    recovery_repository: Any,
) -> None:
    repository = recovery_repository
    claim, _ = _seed(repository)
    operation = _operation()
    final = FollowUpOperation.model_validate(
        {
            **operation.model_dump(),
            'status': 'committed',
            'result_code': 'in_app_committed',
            'committed_at': operation.created_at,
        }
    )
    with pytest.raises(ValueError):
        repository.save_follow_up_operation(final)
    with pytest.raises(ValueError):
        repository.save_retention_operation(
            _retention(claim).model_copy(
                update={'status': RetentionOperationStatus.EXECUTING, 'revision': 2}
            )
        )
    reserved = _retention(claim)
    repository.save_retention_operation(reserved)
    with pytest.raises(IdempotencyConflict):
        repository.save_retention_operation(reserved.model_copy(update={'policy_version': 2}))
    with pytest.raises(ValueError):
        repository.advance_retention_operation(
            reserved,
            reserved.model_copy(
                update={
                    'status': RetentionOperationStatus.EXECUTING,
                    'revision': 2,
                    'policy_version': 2,
                }
            ),
        )
    with pytest.raises(ValueError):
        repository.advance_retention_operation(
            reserved,
            reserved.model_copy(
                update={
                    'status': RetentionOperationStatus.EXECUTING,
                    'revision': 2,
                    'step_results': {'object:a': 'deleted'},
                }
            ),
        )


def test_mongo_failed_commit_uses_transaction_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    from copy import deepcopy

    repository = MongoDBRepository(mongomock.MongoClient(), 'rollback_probe')
    bundle = _commit_bundle(repository)
    before = list(repository._collection.find())
    transaction = MagicMock()
    transaction.__enter__.return_value = transaction

    def rollback(callback: Any) -> Any:
        snapshot = deepcopy(list(repository._collection.find()))
        try:
            return callback(None)
        except RuntimeError:
            repository._collection.delete_many({})
            repository._collection.insert_many(snapshot)
            raise

    transaction.with_transaction.side_effect = rollback
    monkeypatch.setattr(repository._client, 'start_session', lambda: transaction)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError('injected final operation write failure')

    monkeypatch.setattr(repository, '_advance_recovery_operation', fail)
    with pytest.raises(RuntimeError, match='injected'):
        repository.commit_follow_up_operation(*bundle)
    assert list(repository._collection.find()) == before
    transaction.with_transaction.assert_called_once()


@pytest.fixture(params=['fixture', 'mongo'])
def recovery_repository(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Any:
    if request.param == 'fixture':
        return FixtureRepository()
    repository = MongoDBRepository(mongomock.MongoClient(), 'recovery_regression')
    # Adapter control-flow evidence only, not a real Mongo transaction claim.
    monkeypatch.setattr(repository, '_atomic', lambda callback: callback(None))
    return repository


def _seed(repository: Any) -> tuple[WorkingClaim, FollowUpRecord]:
    from backend.domain.models import SessionRecord, SessionStatus

    follow_up = _follow_up()
    claim = WorkingClaim(
        claim_id=follow_up.claim_id,
        customer_id='cus_operation_test',
        revision=2,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        customer_next_step=CustomerNextStep(
            status='resume_claim',
            summary='Resume saved claim.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=follow_up.created_at,
        updated_at=follow_up.updated_at,
    )
    session = SessionRecord(
        session_id=follow_up.source_session_id,
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.PAUSED,
        started_at=claim.created_at,
        last_active_at=claim.updated_at,
    )
    if isinstance(repository, FixtureRepository):
        repository._claims[claim.claim_id] = claim
        repository._sessions[session.session_id] = session
        repository._follow_ups[follow_up.follow_up_id] = follow_up
    else:
        for kind, identifier, record in [
            ('claim', claim.claim_id, claim),
            ('session', session.session_id, session),
        ]:
            repository._collection.insert_one(
                {
                    **record.model_dump(mode='json'),
                    '_id': kind + ':' + identifier,
                    'record_type': kind,
                }
            )
        repository._collection.insert_one(
            {
                **follow_up.model_dump(mode='json'),
                '_id': 'follow_up:' + follow_up.follow_up_id,
                'record_type': 'follow_up',
                'customer_id': claim.customer_id,
            }
        )
    return claim, follow_up


@pytest.mark.parametrize('same_identity', [True, False])
def test_concurrent_operation_create_has_one_winner(
    recovery_repository: Any, monkeypatch: pytest.MonkeyPatch, same_identity: bool
) -> None:
    repository = recovery_repository
    _seed(repository)
    first = _operation()
    second = first.model_copy(
        update={'based_on_claim_revision': 3}
        if same_identity
        else {'operation_id': 'fop_abcdef0123456789abcd'}
    )
    barrier = Barrier(2)
    if isinstance(repository, MongoDBRepository):
        insert = repository._collection.insert_one

        def synchronized(document: Any, **kwargs: Any) -> Any:
            barrier.wait(timeout=5)
            return insert(document, **kwargs)

        monkeypatch.setattr(repository._collection, 'insert_one', synchronized)

    def save(operation: FollowUpOperation) -> str:
        if isinstance(repository, FixtureRepository):
            barrier.wait(timeout=5)
        try:
            repository.save_follow_up_operation(operation)
            return 'saved'
        except IdempotencyConflict:
            return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, [first, second])) == ['conflict', 'saved']
    stored = repository.list_follow_up_operations(first.follow_up_id)
    assert len(stored) == 1 and stored[0] in [first, second]


def test_cancel_transition_replays_and_rejects_stale_or_terminal_rewrites(
    recovery_repository: Any,
) -> None:
    repository = recovery_repository
    _seed(repository)
    reserved = _operation()
    repository.save_follow_up_operation(reserved)
    cancelled = FollowUpOperation.model_validate(
        {
            **reserved.model_dump(),
            'status': 'cancelled',
            'result_code': 'superseded_by_resume',
            'cancelled_at': reserved.created_at,
        }
    )
    assert repository.advance_follow_up_operation(reserved, cancelled) == cancelled
    assert repository.advance_follow_up_operation(reserved, cancelled) == cancelled
    repository.save_follow_up_operation(cancelled)
    competing = cancelled.model_copy(update={'result_code': FollowUpOperationResult.AUTHORITY_LOST})
    with pytest.raises(IdempotencyConflict):
        repository.advance_follow_up_operation(reserved, competing)
    with pytest.raises(ValueError):
        repository.advance_follow_up_operation(cancelled, competing)
    with pytest.raises(ValueError):
        repository.advance_follow_up_operation(
            reserved, cancelled.model_copy(update={'policy_version': 2})
        )


def _retention(claim: WorkingClaim) -> RetentionOperation:
    return RetentionOperation(
        operation_id='rop_0123456789abcdef0123',
        claim_id=claim.claim_id,
        policy_id='synthetic_retention',
        policy_version=1,
        based_on_claim_revision=claim.revision,
        source_refs=['terminal:synthetic'],
        target_refs=['object:a', 'claim:b'],
        status=RetentionOperationStatus.ELIGIBLE,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )


def test_retention_restart_preserves_success_and_only_retries_unfinished_steps(
    recovery_repository: Any,
) -> None:
    repository = recovery_repository
    claim, _ = _seed(repository)
    initial = _retention(claim)
    repository.save_retention_operation(initial)
    executing = initial.model_copy(
        update={'revision': 2, 'status': RetentionOperationStatus.EXECUTING}
    )
    repository.advance_retention_operation(initial, executing)
    partial = executing.model_copy(
        update={
            'revision': 3,
            'status': RetentionOperationStatus.RECONCILIATION_REQUIRED,
            'step_results': {'object:a': 'deleted', 'claim:b': 'unknown'},
        }
    )
    repository.advance_retention_operation(executing, partial)
    assert repository.advance_retention_operation(executing, partial) == partial
    stored = repository.get_retention_operation(initial.operation_id)
    retry = stored.model_copy(update={'revision': 4, 'status': RetentionOperationStatus.EXECUTING})
    repository.advance_retention_operation(stored, retry)
    with pytest.raises(ValueError):
        repository.advance_retention_operation(
            retry,
            retry.model_copy(
                update={'revision': 5, 'step_results': {'object:a': 'failed', 'claim:b': 'deleted'}}
            ),
        )
    completed = retry.model_copy(
        update={
            'revision': 5,
            'status': RetentionOperationStatus.COMPLETED,
            'step_results': {'object:a': 'deleted', 'claim:b': 'already_absent'},
        }
    )
    repository.advance_retention_operation(retry, completed)
    assert repository.advance_retention_operation(retry, completed) == completed
    with pytest.raises(ValueError):
        repository.advance_retention_operation(
            completed, completed.model_copy(update={'revision': 6})
        )
    with pytest.raises(IdempotencyConflict):
        repository.advance_retention_operation(initial, executing)


@pytest.mark.parametrize(
    'fields,expected',
    [
        ({}, 'applied'),
        ({'policy_id': 'incomplete_claim_follow_up'}, 'applied'),
        (
            {'policy_id': 'incomplete_claim_follow_up', 'policy_version': 1, 'deadline_at': None},
            'applied',
        ),
        ({'policy_id': 'wrong', 'policy_version': 7}, 'rejected'),
        ({'deadline_at': '2026-10-01T00:00:00+00:00'}, 'rejected'),
    ],
)
def test_migration_partial_null_and_conflicting_bindings(
    monkeypatch: pytest.MonkeyPatch, fields: dict[str, Any], expected: str
) -> None:
    collection: Collection[dict[str, Any]] = mongomock.MongoClient().db.records
    source = {
        '_id': 'session:s',
        'record_type': 'session',
        'session_id': 's',
        'claim_id': 'c',
        'recovery_context': {'interrupted_at': '2026-09-09T00:00:00+00:00'},
    }
    original = {
        '_id': 'follow_up:f',
        'record_type': 'follow_up',
        'follow_up_id': 'f',
        'claim_id': 'c',
        'source_session_id': 's',
        **fields,
    }
    collection.insert_many([source, original])
    transaction = MagicMock()
    transaction.__enter__.return_value = transaction
    transaction.with_transaction.side_effect = lambda callback: callback(None)
    monkeypatch.setattr(collection.database.client, 'start_session', lambda: transaction)
    result = backfill_follow_ups(collection, apply=True)
    assert len(result[expected]) == 1
    stored = collection.find_one({'_id': 'follow_up:f'})
    assert stored is not None
    if expected == 'rejected':
        assert all(stored.get(key) == value for key, value in original.items())
        assert stored['recovery_discovery_ready'] is False
        assert stored['recovery_migration_reason']
    else:
        assert stored['policy_version'] == 1
        assert stored['deadline_at'] == '2026-09-16T00:00:00.000000Z'


@pytest.mark.parametrize('source_changed', [True, False])
def test_migration_conflicting_source_or_binding_does_not_apply(
    monkeypatch: pytest.MonkeyPatch, source_changed: bool
) -> None:
    collection: Collection[dict[str, Any]] = mongomock.MongoClient().db.records
    collection.insert_many(
        [
            {
                '_id': 'session:s',
                'record_type': 'session',
                'session_id': 's',
                'claim_id': 'c',
                'recovery_context': {'interrupted_at': '2026-09-09T00:00:00+00:00'},
            },
            {
                '_id': 'follow_up:f',
                'record_type': 'follow_up',
                'follow_up_id': 'f',
                'claim_id': 'c',
                'source_session_id': 's',
            },
        ]
    )
    transaction = MagicMock()
    transaction.__enter__.return_value = transaction

    def concurrent(callback: Any) -> Any:
        target = 'session:s' if source_changed else 'follow_up:f'
        update: dict[str, Any] = (
            {'recovery_context.interrupted_at': '2026-09-10T00:00:00+00:00'}
            if source_changed
            else {'policy_version': 7}
        )
        collection.update_one({'_id': target}, {'$set': update})
        return callback(None)

    transaction.with_transaction.side_effect = concurrent
    monkeypatch.setattr(collection.database.client, 'start_session', lambda: transaction)
    result = backfill_follow_ups(collection, apply=True)
    assert result['conflicts'] == ['f']
    stored = collection.find_one({'_id': 'follow_up:f'})
    assert stored is not None and 'deadline_at' not in stored


def test_cancelled_history_allows_retry_without_counting_cancellation(
    recovery_repository: Any,
) -> None:
    from dataclasses import replace

    from backend.domain.recovery import follow_up_commit_fingerprint
    from backend.repositories.protocols import RevisionConflict

    repository = recovery_repository
    initial = _commit_bundle(repository)
    reserved, committed, previous, aggregate, claim, idem, audits = initial
    authoritative = repository.get_claim(claim.claim_id, claim.customer_id)
    changed = authoritative.model_copy(update={'revision': 3})
    if isinstance(repository, FixtureRepository):
        repository._claims[claim.claim_id] = changed
    else:
        repository._collection.update_one(
            {'_id': 'claim:' + claim.claim_id}, {'$set': {'revision': 3}}
        )
    with pytest.raises(RevisionConflict):
        repository.commit_follow_up_operation(*initial)
    cancelled = reserved.model_copy(
        update={
            'status': FollowUpOperationStatus.CANCELLED,
            'result_code': FollowUpOperationResult.STALE_REVISION,
            'cancelled_at': reserved.created_at,
        }
    )
    repository.advance_follow_up_operation(reserved, cancelled)
    fresh = repository.get_claim(claim.claim_id, claim.customer_id)
    fresh_follow_up = repository.get_follow_up(
        claim.claim_id, previous.follow_up_id, claim.customer_id
    )
    assert fresh_follow_up.attempt_count == 0
    retry = reserved.model_copy(
        update={
            'operation_id': 'fop_abcdef0123456789abcd',
            'sequence': repository.next_follow_up_operation_sequence(previous.follow_up_id),
            'based_on_claim_revision': fresh.revision,
        }
    )
    assert retry.sequence == 2
    repository.save_follow_up_operation(retry)
    competitor = retry.model_copy(
        update={'operation_id': 'fop_11111111111111111111', 'sequence': 3}
    )
    repository.save_follow_up_operation(competitor)

    def bundle(operation: FollowUpOperation, count: int = 1) -> tuple[Any, ...]:
        result = committed.model_copy(
            update={
                'operation_id': operation.operation_id,
                'sequence': operation.sequence,
                'based_on_claim_revision': fresh.revision,
            }
        )
        next_claim = fresh.model_copy(update={'revision': fresh.revision + 1})
        next_aggregate = aggregate.model_copy(update={'attempt_count': count})
        events = (
            audits[0].model_copy(
                update={
                    'event_id': 'aud_' + operation.operation_id,
                    'correlation_id': operation.operation_id,
                    'claim_revision': next_claim.revision,
                }
            ),
        )
        replay = replace(
            idem,
            key=operation.operation_id,
            response_payload={'operation_id': operation.operation_id},
            request_fingerprint=follow_up_commit_fingerprint(
                operation, result, fresh_follow_up, next_aggregate, next_claim, events
            ),
        )
        return operation, result, fresh_follow_up, next_aggregate, next_claim, replay, events

    with pytest.raises(ValueError):
        repository.commit_follow_up_operation(*bundle(retry, count=2))
    winning = bundle(retry)
    assert repository.commit_follow_up_operation(*winning) == winning[1]
    assert repository.commit_follow_up_operation(*winning) == winning[1]
    with pytest.raises((IdempotencyConflict, RevisionConflict)):
        repository.commit_follow_up_operation(*bundle(competitor))
    stored = repository.get_follow_up(claim.claim_id, previous.follow_up_id, claim.customer_id)
    assert stored.attempt_count == 1
    assert repository.get_follow_up_operation(reserved.operation_id) == cancelled
    assert repository.get_follow_up_operation(competitor.operation_id) == competitor


def test_competing_retry_reservations_claim_one_next_sequence(
    recovery_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = recovery_repository
    _seed(repository)
    reserved = _operation()
    repository.save_follow_up_operation(reserved)
    repository.advance_follow_up_operation(
        reserved,
        reserved.model_copy(
            update={
                'status': FollowUpOperationStatus.CANCELLED,
                'result_code': FollowUpOperationResult.STALE_REVISION,
                'cancelled_at': reserved.created_at,
            }
        ),
    )
    candidates = [
        reserved.model_copy(
            update={
                'operation_id': 'fop_' + digit * 20,
                'sequence': repository.next_follow_up_operation_sequence(reserved.follow_up_id),
            }
        )
        for digit in ('a', 'b')
    ]
    barrier = Barrier(2)
    if isinstance(repository, MongoDBRepository):
        insert = repository._collection.insert_one

        def synchronized(document: Any, **kwargs: Any) -> Any:
            barrier.wait(timeout=5)
            return insert(document, **kwargs)

        monkeypatch.setattr(repository._collection, 'insert_one', synchronized)

    def save(operation: FollowUpOperation) -> str:
        if isinstance(repository, FixtureRepository):
            barrier.wait(timeout=5)
        try:
            repository.save_follow_up_operation(operation)
            return 'saved'
        except IdempotencyConflict:
            return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, candidates)) == ['conflict', 'saved']
    history = repository.list_follow_up_operations(reserved.follow_up_id)
    assert [item.sequence for item in history] == [1, 2]
    assert history[0].status is FollowUpOperationStatus.CANCELLED
    assert repository.next_follow_up_operation_sequence(reserved.follow_up_id) == 3


@pytest.mark.parametrize('field', ['due_at', 'deadline_at'])
def test_backfill_then_paginate_mixed_offsets_and_fractional_times(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    from datetime import timezone

    repository = MongoDBRepository(mongomock.MongoClient(), 'pagination_regression')
    collection = repository._collection
    base = _follow_up()
    assert base.due_at is not None and base.deadline_at is not None
    variants = [
        ('missing', 0),
        ('offset', 0),
        ('utc_iso', 0),
        ('z', 0),
        ('new', 0),
        ('fraction', 1),
    ]
    expected = []
    for index, (representation, microseconds) in enumerate(variants):
        instant = base.created_at + timedelta(microseconds=microseconds)
        deadline = instant + timedelta(days=7)
        identifier = f'fup_page_{index}'
        expected.append(identifier)
        record = base.model_copy(
            update={
                'follow_up_id': identifier,
                'claim_id': f'clm_page_{index}',
                'source_session_id': f'ses_page_{index}',
                'due_at': instant,
                'deadline_at': deadline,
            }
        ).model_dump(mode='json')
        if representation == 'missing':
            record.pop('deadline_at')
            record['due_at'] = instant.isoformat()
        elif representation in {'offset', 'utc_iso', 'z'}:
            offset = timezone(timedelta(hours=13)) if representation == 'offset' else UTC
            for key, value in [('due_at', instant), ('deadline_at', deadline)]:
                text = value.astimezone(offset).isoformat()
                record[key] = text.replace('+00:00', 'Z') if representation == 'z' else text
        collection.insert_one(
            {**record, '_id': 'follow_up:' + identifier, 'record_type': 'follow_up'}
        )
        collection.insert_one(
            {
                '_id': 'session:' + record['source_session_id'],
                'record_type': 'session',
                'session_id': record['source_session_id'],
                'claim_id': record['claim_id'],
                'recovery_context': {'interrupted_at': instant.isoformat()},
            }
        )
    query = (
        repository.list_due_follow_ups
        if field == 'due_at'
        else (repository.list_expiring_follow_ups)
    )
    cutoff = base.due_at if field == 'due_at' else base.deadline_at
    # Noncanonical legacy records remain excluded until authoritative backfill.
    original = list(collection.find({'record_type': 'follow_up'}).sort('_id', 1))
    backfill_follow_ups(collection)
    assert list(collection.find({'record_type': 'follow_up'}).sort('_id', 1)) == original
    transaction = MagicMock()
    transaction.__enter__.return_value = transaction
    transaction.with_transaction.side_effect = lambda callback: callback(None)
    monkeypatch.setattr(collection.database.client, 'start_session', lambda: transaction)
    report = backfill_follow_ups(collection, apply=True)
    assert len(report['applied']) == 6
    assert backfill_follow_ups(collection, apply=True)['candidate_count'] == 0
    assert [item.follow_up_id for item in query(cutoff, limit=10)] == expected[:-1]
    cursor = None
    observed = []
    for _ in range(8):
        page = query(cutoff + timedelta(microseconds=1), limit=1, cursor=cursor)
        if not page:
            break
        item = page[0]
        observed.append(item.follow_up_id)
        cursor = (getattr(item, field).astimezone(timezone(timedelta(hours=-4))), item.follow_up_id)
    assert observed == expected
    for document in collection.find({'record_type': 'follow_up'}):
        assert document['policy_id'] == base.policy_id
        assert document['policy_version'] == base.policy_version
        assert datetime.fromisoformat(document['deadline_at']) - datetime.fromisoformat(
            document['due_at']
        ) == timedelta(days=7)


def test_unmigratable_follow_up_is_quarantined_without_blocking_healthy_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'recovery_isolation')
    healthy = _follow_up()
    repository._collection.insert_one(
        {
            **healthy.model_dump(mode='json'),
            '_id': 'follow_up:' + healthy.follow_up_id,
            'record_type': 'follow_up',
        }
    )
    repository._collection.insert_one(
        {
            '_id': 'session:' + healthy.source_session_id,
            'record_type': 'session',
            'session_id': healthy.source_session_id,
            'claim_id': healthy.claim_id,
            'recovery_context': {'interrupted_at': healthy.created_at.isoformat()},
        }
    )
    legacy = healthy.model_dump(mode='json')
    legacy.update(
        {
            '_id': 'follow_up:fup_unmigratable',
            'record_type': 'follow_up',
            'follow_up_id': 'fup_unmigratable',
            'claim_id': 'clm_other',
            'source_session_id': 'ses_missing',
            'status': 'blocked',
            'contact_permission': 'not_authorised',
            'due_at': None,
            'deadline_at': '2026-09-16T01:00:00+00:00',
        }
    )
    repository._collection.insert_one(legacy)
    transaction = MagicMock()
    transaction.__enter__.return_value = transaction
    transaction.with_transaction.side_effect = lambda callback: callback(None)
    monkeypatch.setattr(
        repository._collection.database.client, 'start_session', lambda: transaction
    )
    report = backfill_follow_ups(repository._collection, apply=True)
    assert report['applied'] == [healthy.follow_up_id]
    rejected = next(
        item for item in report['rejected'] if item['follow_up_id'] == 'fup_unmigratable'
    )
    assert rejected['reason_code'] == 'source_state_inconsistent'
    stored = repository._collection.find_one({'_id': legacy['_id']})
    assert stored is not None
    assert stored['deadline_at'] == legacy['deadline_at']
    assert stored['recovery_discovery_ready'] is False
    assert stored['recovery_migration_reason'] == 'source_state_inconsistent'
    assert healthy.deadline_at is not None
    assert [
        item.follow_up_id
        for item in repository.list_expiring_follow_ups(
            healthy.deadline_at + timedelta(days=1), limit=10
        )
    ] == [healthy.follow_up_id]


def _follow_up() -> FollowUpRecord:
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    return FollowUpRecord(
        follow_up_id='fup_operation_test',
        claim_id='clm_operation_test',
        source_session_id='ses_operation_test',
        responsible_party=ResponsibleParty.SYSTEM,
        contact_permission=FollowUpContactPermission.AUTHORISED,
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=now,
        deadline_at=now + timedelta(days=7),
        created_at=now,
        updated_at=now,
    )


def _operation(
    status: FollowUpOperationStatus = FollowUpOperationStatus.RESERVED,
) -> FollowUpOperation:
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    return FollowUpOperation(
        operation_id='fop_0123456789abcdef0123',
        follow_up_id='fup_operation_test',
        claim_id='clm_operation_test',
        sequence=1,
        policy_id='incomplete_claim_follow_up',
        policy_version=1,
        based_on_claim_revision=2,
        scheduled_at=now,
        status=status,
        created_at=now,
        updated_at=now,
    )


def test_fixture_operation_identity_and_sequence_are_idempotent() -> None:
    repository = FixtureRepository()
    follow_up = _follow_up()
    repository._follow_ups[follow_up.follow_up_id] = follow_up
    operation = _operation()

    repository.save_follow_up_operation(operation)
    repository.save_follow_up_operation(operation)
    assert repository.get_follow_up_operation(operation.operation_id) == operation

    conflicting = operation.model_copy(update={'operation_id': 'fop_abcdef0123456789abcd'})
    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(conflicting)


def test_fixture_due_and_deadline_queries_are_bounded_and_ordered() -> None:
    repository = FixtureRepository()
    first = _follow_up()
    assert first.due_at is not None
    assert first.deadline_at is not None
    second = first.model_copy(
        update={
            'follow_up_id': 'fup_operation_test_2',
            'due_at': first.due_at + timedelta(hours=1),
            'deadline_at': first.deadline_at + timedelta(hours=1),
        }
    )
    repository._follow_ups[first.follow_up_id] = first
    repository._follow_ups[second.follow_up_id] = second
    assert second.deadline_at is not None

    due = repository.list_due_follow_ups(first.due_at, limit=10)
    assert [item.follow_up_id for item in due] == [first.follow_up_id]
    expiring = repository.list_expiring_follow_ups(second.deadline_at, limit=1)
    assert [item.follow_up_id for item in expiring] == [first.follow_up_id]
    page_two = repository.list_expiring_follow_ups(
        second.deadline_at,
        limit=10,
        cursor=(first.deadline_at, first.follow_up_id),
    )
    assert [item.follow_up_id for item in page_two] == [second.follow_up_id]


def test_follow_up_policy_backfill_is_read_only_until_apply() -> None:
    collection: Collection[dict[str, Any]] = mongomock.MongoClient().db.records
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    collection.insert_many(
        [
            {
                '_id': 'session:ses_migration',
                'record_type': 'session',
                'session_id': 'ses_migration',
                'claim_id': 'clm_migration',
                'recovery_context': {'interrupted_at': now.isoformat()},
            },
            {
                '_id': 'follow_up:fup_migration',
                'record_type': 'follow_up',
                'follow_up_id': 'fup_migration',
                'claim_id': 'clm_migration',
                'source_session_id': 'ses_migration',
                'status': 'blocked',
                'contact_permission': 'not_authorised',
            },
        ]
    )
    dry_run = backfill_follow_ups(collection)
    assert dry_run['eligible'] == ['fup_migration']
    stored_before = collection.find_one({'_id': 'follow_up:fup_migration'})
    assert stored_before is not None
    assert 'deadline_at' not in stored_before
    from unittest.mock import MagicMock, patch

    transaction = MagicMock()
    transaction.__enter__.return_value = transaction
    transaction.with_transaction.side_effect = lambda callback: callback(None)
    with patch.object(collection.database.client, 'start_session', return_value=transaction):
        applied = backfill_follow_ups(collection, apply=True)
    assert applied['applied'] == ['fup_migration']
    stored = collection.find_one({'_id': 'follow_up:fup_migration'})
    assert stored is not None
    assert stored['policy_id'] == 'incomplete_claim_follow_up'
    assert stored['deadline_at'] == recovery_timestamp(now + timedelta(days=7))
    assert stored['blocked_reason'] == 'contact_not_authorised'


def test_mongo_due_deadline_and_operation_contracts() -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'recovery_test')
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    follow_up = _follow_up()
    repository._collection.insert_one(
        {
            **follow_up.model_dump(mode='json'),
            '_id': 'follow_up:fup_operation_test',
            'record_type': 'follow_up',
            'claim_id': follow_up.claim_id,
            'customer_id': 'cus_operation_test',
        }
    )
    assert repository.list_due_follow_ups(now, limit=10)[0].follow_up_id == follow_up.follow_up_id
    assert (
        repository.list_expiring_follow_ups(now + timedelta(days=7), limit=10)[0].follow_up_id
        == follow_up.follow_up_id
    )
    operation = _operation()
    repository.save_follow_up_operation(operation)
    repository.save_follow_up_operation(operation)
    assert repository.list_follow_up_operations(follow_up.follow_up_id) == [operation]
    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(
            operation.model_copy(update={'operation_id': 'fop_abcdef0123456789abcd'})
        )


def test_mongo_retention_operation_is_replay_safe() -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'retention_test')
    follow_up = _follow_up()
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id=follow_up.claim_id,
        customer_id='cus_operation_test',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Continue describing the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=now,
        updated_at=now,
    )
    repository._collection.insert_one(
        {
            **claim.model_dump(mode='json'),
            '_id': f'claim:{claim.claim_id}',
            'record_type': 'claim',
        }
    )
    operation = RetentionOperation(
        operation_id='rop_0123456789abcdef0123',
        policy_id='synthetic_retention',
        policy_version=1,
        based_on_claim_revision=1,
        source_refs=['terminal:synthetic'],
        claim_id=claim.claim_id,
        target_refs=['claim:clm_operation_test'],
        status=RetentionOperationStatus.ELIGIBLE,
        created_at=now,
        updated_at=now,
    )
    repository.save_retention_operation(operation)
    repository.save_retention_operation(operation)
    assert repository.get_retention_operation(operation.operation_id) == operation


def test_model_guards_cover_invalid_lifecycle_combinations() -> None:
    follow_up = _follow_up()
    with pytest.raises(ValueError):
        FollowUpRecord.model_validate(
            follow_up.model_copy(
                update={'blocked_reason': FollowUpReasonCode.CONTACT_NOT_AUTHORISED}
            ).model_dump()
        )
    with pytest.raises(ValueError):
        FollowUpRecord.model_validate(
            follow_up.model_copy(
                update={
                    'status': FollowUpStatus.BLOCKED,
                    'contact_permission': FollowUpContactPermission.NOT_AUTHORISED,
                    'channel': None,
                    'due_at': None,
                    'resolution_code': FollowUpResolutionCode.CLAIMANT_RESUMED,
                }
            ).model_dump()
        )
    with pytest.raises(ValueError):
        follow_up.model_copy(
            update={
                'status': FollowUpStatus.RESOLVED,
                'contact_permission': FollowUpContactPermission.NOT_AUTHORISED,
                'channel': None,
                'due_at': None,
            }
        )
        FollowUpRecord.model_validate(
            follow_up.model_copy(
                update={
                    'status': FollowUpStatus.RESOLVED,
                    'contact_permission': FollowUpContactPermission.NOT_AUTHORISED,
                    'channel': None,
                    'due_at': None,
                }
            ).model_dump()
        )
    now = follow_up.created_at
    with pytest.raises(ValueError):
        FollowUpOperation.model_validate(
            _operation().model_copy(update={'updated_at': now - timedelta(seconds=1)}).model_dump()
        )
    with pytest.raises(ValueError):
        FollowUpOperation.model_validate(_operation(FollowUpOperationStatus.COMMITTED).model_dump())
    with pytest.raises(ValueError):
        FollowUpOperation.model_validate(_operation(FollowUpOperationStatus.CANCELLED).model_dump())
    with pytest.raises(ValueError):
        RetentionOperation(
            operation_id='rop_0123456789abcdef0123',
            policy_id='synthetic_retention',
            policy_version=1,
            based_on_claim_revision=1,
            source_refs=['terminal:synthetic'],
            claim_id='claim',
            target_refs=['target'],
            status=RetentionOperationStatus.HELD,
            created_at=now,
            updated_at=now,
        )


def test_fixture_query_and_operation_rejection_paths() -> None:
    repository = FixtureRepository()
    with pytest.raises(ValueError):
        repository.list_due_follow_ups(datetime.now(UTC), limit=0)
    with pytest.raises(ValueError):
        repository.list_expiring_follow_ups(datetime.now(UTC), limit=0)
    with pytest.raises(KeyError):
        repository.save_follow_up_operation(_operation())
    retention = RetentionOperation(
        operation_id='rop_abcdef0123456789abcd',
        policy_id='synthetic_retention',
        policy_version=1,
        based_on_claim_revision=1,
        source_refs=['terminal:synthetic'],
        claim_id='missing',
        target_refs=['target'],
        status=RetentionOperationStatus.ELIGIBLE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with pytest.raises(KeyError):
        repository.save_retention_operation(retention)
