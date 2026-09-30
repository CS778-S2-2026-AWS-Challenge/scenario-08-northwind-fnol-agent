from datetime import UTC, datetime, timedelta

import mongomock
import pytest
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
    SessionRecord,
    SessionRecoveryContext,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
)


def _repository(kind: str) -> FixtureRepository | MongoDBRepository:
    if kind == 'fixture':
        return FixtureRepository()

    repository = MongoDBRepository(
        mongomock.MongoClient(),
        'follow_up_operation_test',
    )
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


def _seed_recovery(
    repository: FixtureRepository | MongoDBRepository,
) -> tuple[WorkingClaim, FollowUpRecord, datetime]:
    now = datetime(2026, 9, 28, 4, 0, tzinfo=UTC)

    claim = WorkingClaim(
        claim_id='clm_follow_up_operation',
        customer_id='cus_follow_up_operation',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='motor',
        claim_state=ClaimState(),
        active_session_id='ses_follow_up_operation',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Continue describing the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=now,
        updated_at=now,
    )

    session = SessionRecord(
        session_id='ses_follow_up_operation',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.ACTIVE,
        context_revision=claim.revision,
        started_at=now,
        last_active_at=now,
    )

    repository.create_claim(claim, session)

    recovery = SessionRecoveryContext(
        interrupted_at=now,
        last_meaningful_activity_at=now,
        last_meaningful_activity_source_ref=(f'claim:{claim.claim_id}:revision:{claim.revision}'),
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
            'updated_at': now,
        }
    )

    follow_up = FollowUpRecord(
        follow_up_id='fup_follow_up_operation',
        claim_id=claim.claim_id,
        source_session_id=session.session_id,
        policy_id='incomplete_claim_follow_up',
        policy_version=1,
        deadline_at=now + timedelta(days=7),
        responsible_party=ResponsibleParty.SYSTEM,
        source_refs=[f'session:{session.session_id}'],
        contact_permission=FollowUpContactPermission.AUTHORISED,
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=now,
        created_at=now,
        updated_at=now,
    )

    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/test/follow-up-operation/pause',
        key='follow-up-operation-pause',
        request_fingerprint='follow-up-operation-pause',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        follow_up_id=follow_up.follow_up_id,
    )

    repository.save_incomplete_checkpoint(
        paused_claim,
        expected_revision=1,
        session=paused_session,
        follow_up=follow_up,
        idempotency=idempotency,
    )

    return paused_claim, follow_up, now


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_follow_up_operation_lifecycle_identity_and_owner_parity(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, follow_up, now = _seed_recovery(repository)

    scheduled = FollowUpOperation(
        operation_id='fop_1',
        follow_up_id=follow_up.follow_up_id,
        claim_id=claim.claim_id,
        sequence=1,
        policy_id=follow_up.policy_id,
        policy_version=follow_up.policy_version,
        based_on_claim_revision=claim.revision,
        scheduled_at=now + timedelta(hours=1),
        source_refs=[
            f'follow-up:{follow_up.follow_up_id}',
            f'claim:{claim.claim_id}:revision:{claim.revision}',
        ],
        created_at=now + timedelta(hours=1),
        updated_at=now + timedelta(hours=1),
    )

    repository.save_follow_up_operation(
        scheduled,
        claim.customer_id,
    )

    repository.save_follow_up_operation(
        scheduled,
        claim.customer_id,
    )

    committed_at = now + timedelta(hours=1, minutes=1)

    committed = scheduled.model_copy(
        update={
            'status': FollowUpOperationStatus.COMMITTED,
            'result': FollowUpOperationResult.DELIVERED_IN_APP,
            'committed_at': committed_at,
        }
    )

    repository.save_follow_up_operation(
        committed,
        claim.customer_id,
    )

    settled = committed.model_copy(
        update={
            'status': FollowUpOperationStatus.SETTLED,
            'result': FollowUpOperationResult.NO_RESPONSE,
            'settled_at': committed_at + timedelta(minutes=1),
        }
    )

    repository.save_follow_up_operation(
        settled,
        claim.customer_id,
    )

    assert (
        repository.get_follow_up_operation(
            claim.claim_id,
            scheduled.operation_id,
            claim.customer_id,
        )
        == settled
    )

    assert repository.list_follow_up_operations(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    ) == [settled]

    assert (
        repository.get_follow_up_operation(
            claim.claim_id,
            scheduled.operation_id,
            'cus_other',
        )
        is None
    )

    assert (
        repository.list_follow_up_operations(
            claim.claim_id,
            follow_up.follow_up_id,
            'cus_other',
        )
        == []
    )

    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(
            scheduled,
            claim.customer_id,
        )


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_follow_up_operation_sequence_policy_revision_and_deadline_parity(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, follow_up, now = _seed_recovery(repository)

    first = FollowUpOperation(
        operation_id='fop_first',
        follow_up_id=follow_up.follow_up_id,
        claim_id=claim.claim_id,
        sequence=1,
        policy_id=follow_up.policy_id,
        policy_version=follow_up.policy_version,
        based_on_claim_revision=claim.revision,
        scheduled_at=now + timedelta(hours=1),
        created_at=now + timedelta(hours=1),
        updated_at=now + timedelta(hours=1),
    )

    repository.save_follow_up_operation(
        first,
        claim.customer_id,
    )

    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(
            first.model_copy(
                update={
                    'operation_id': 'fop_duplicate_sequence',
                }
            ),
            claim.customer_id,
        )

    with pytest.raises(KeyError):
        repository.save_follow_up_operation(
            FollowUpOperation(
                operation_id='fop_wrong_policy',
                follow_up_id=follow_up.follow_up_id,
                claim_id=claim.claim_id,
                sequence=2,
                policy_id=follow_up.policy_id,
                policy_version=2,
                based_on_claim_revision=claim.revision,
                scheduled_at=now + timedelta(hours=2),
                created_at=now + timedelta(hours=2),
                updated_at=now + timedelta(hours=2),
            ),
            claim.customer_id,
        )

    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(
            FollowUpOperation(
                operation_id='fop_wrong_revision',
                follow_up_id=follow_up.follow_up_id,
                claim_id=claim.claim_id,
                sequence=2,
                policy_id=follow_up.policy_id,
                policy_version=follow_up.policy_version,
                based_on_claim_revision=claim.revision - 1,
                scheduled_at=now + timedelta(hours=2),
                created_at=now + timedelta(hours=2),
                updated_at=now + timedelta(hours=2),
            ),
            claim.customer_id,
        )

    with pytest.raises(KeyError):
        repository.save_follow_up_operation(
            FollowUpOperation(
                operation_id='fop_deadline_tie',
                follow_up_id=follow_up.follow_up_id,
                claim_id=claim.claim_id,
                sequence=2,
                policy_id=follow_up.policy_id,
                policy_version=follow_up.policy_version,
                based_on_claim_revision=claim.revision,
                scheduled_at=follow_up.deadline_at,
                created_at=follow_up.deadline_at,
                updated_at=follow_up.deadline_at,
            ),
            claim.customer_id,
        )

    second = FollowUpOperation(
        operation_id='fop_second',
        follow_up_id=follow_up.follow_up_id,
        claim_id=claim.claim_id,
        sequence=2,
        policy_id=follow_up.policy_id,
        policy_version=follow_up.policy_version,
        based_on_claim_revision=claim.revision,
        scheduled_at=now + timedelta(hours=2),
        created_at=now + timedelta(hours=2),
        updated_at=now + timedelta(hours=2),
    )

    repository.save_follow_up_operation(
        second,
        claim.customer_id,
    )

    assert repository.list_follow_up_operations(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    ) == [first, second]


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
def test_follow_up_operation_identity_is_immutable_and_transitions_are_conditional(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, follow_up, now = _seed_recovery(repository)
    customer_id = claim.customer_id
    reserved = FollowUpOperation(
        operation_id='fop_transition',
        follow_up_id=follow_up.follow_up_id,
        claim_id=claim.claim_id,
        sequence=1,
        policy_id='incomplete_claim_follow_up',
        policy_version=1,
        based_on_claim_revision=claim.revision,
        scheduled_at=now + timedelta(hours=1),
        created_at=now + timedelta(hours=1),
        updated_at=now + timedelta(hours=1),
    )
    repository.save_follow_up_operation(reserved, customer_id)

    # Same identity, different immutable payload: conflict, evidence kept.
    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(
            reserved.model_copy(update={'scheduled_at': now + timedelta(hours=2)}),
            customer_id,
        )

    committed = reserved.model_copy(
        update={
            'status': FollowUpOperationStatus.COMMITTED,
            'result': FollowUpOperationResult.DELIVERED_IN_APP,
            'committed_at': now + timedelta(hours=1, minutes=1),
        }
    )
    repository.save_follow_up_operation(committed, customer_id)
    # Exact replay of the settled transition is stable.
    repository.save_follow_up_operation(committed, customer_id)

    # A competing worker that still holds the stale reservation loses.
    stale_cancel = reserved.model_copy(
        update={
            'status': FollowUpOperationStatus.CANCELLED,
            'result': FollowUpOperationResult.AUTHORITY_LOST,
            'cancelled_at': now + timedelta(hours=1, minutes=2),
        }
    )
    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(stale_cancel, customer_id)

    settled = committed.model_copy(
        update={
            'status': FollowUpOperationStatus.SETTLED,
            'result': FollowUpOperationResult.NO_RESPONSE,
            'settled_at': now + timedelta(hours=1, minutes=3),
        }
    )
    repository.save_follow_up_operation(settled, customer_id)

    # Terminal evidence cannot be rewritten to a different final result.
    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(
            settled.model_copy(update={'result': FollowUpOperationResult.SUPERSEDED_BY_RESUME}),
            customer_id,
        )

    stored = repository.get_follow_up_operation(claim.claim_id, reserved.operation_id, customer_id)
    assert stored == settled
    immutable = {
        'operation_id',
        'follow_up_id',
        'claim_id',
        'sequence',
        'policy_id',
        'policy_version',
        'based_on_claim_revision',
        'scheduled_at',
        'created_at',
    }
    assert stored.model_dump(include=immutable) == reserved.model_dump(include=immutable)


# Backend persistence and policy compatibility regression cases.


def backend_contract_seed_claim(
    repository: FixtureRepository | MongoDBRepository,
    follow_up: FollowUpRecord,
) -> None:
    claim = WorkingClaim(
        claim_id=follow_up.claim_id,
        customer_id='cus_operation_test',
        revision=2,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Continue describing the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=follow_up.created_at,
        updated_at=follow_up.updated_at,
    )
    if isinstance(repository, FixtureRepository):
        repository._claims[claim.claim_id] = claim
    else:
        repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository._put(
            'claim', claim.claim_id, claim, customer_id=claim.customer_id, claim_id=claim.claim_id
        )


def backend_contract_retention(claim_id: str, now: datetime) -> RetentionOperation:
    return RetentionOperation(
        operation_id='rop_0123456789abcdef0123',
        claim_id=claim_id,
        source_terminal_ref=f'claim-terminal:{claim_id}:revision:2',
        source_claim_revision=2,
        policy_id='incomplete_claim_retention',
        policy_version=1,
        status=RetentionOperationStatus.RESERVED,
        access_closed_at=now,
        source_refs=[f'claim:{claim_id}'],
        created_at=now,
        updated_at=now,
    )


def backend_contract__follow_up() -> FollowUpRecord:
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    return FollowUpRecord(
        follow_up_id='fup_operation_test',
        claim_id='clm_operation_test',
        source_session_id='ses_operation_test',
        policy_id='incomplete_claim_follow_up',
        policy_version=1,
        responsible_party=ResponsibleParty.SYSTEM,
        contact_permission=FollowUpContactPermission.AUTHORISED,
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=now,
        deadline_at=now + timedelta(days=7),
        created_at=now,
        updated_at=now,
    )


def backend_contract__operation(
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


def test_backend_contract_fixture_operation_identity_and_sequence_are_idempotent() -> None:
    repository = FixtureRepository()
    follow_up = backend_contract__follow_up()
    repository._follow_ups[follow_up.follow_up_id] = follow_up
    backend_contract_seed_claim(repository, follow_up)
    operation = backend_contract__operation()
    repository.save_follow_up_operation(operation, 'cus_operation_test')
    repository.save_follow_up_operation(operation, 'cus_operation_test')
    assert (
        repository.get_follow_up_operation(
            operation.claim_id, operation.operation_id, 'cus_operation_test'
        )
        == operation
    )
    conflicting = operation.model_copy(update={'operation_id': 'fop_abcdef0123456789abcd'})
    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(conflicting, 'cus_operation_test')


def test_backend_contract_fixture_due_and_deadline_queries_are_bounded_and_ordered() -> None:
    repository = FixtureRepository()
    first = backend_contract__follow_up()
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
    due, _ = repository.list_due_follow_ups(first.due_at, limit=10)
    assert [item.follow_up_id for item in due] == [first.follow_up_id]
    expiring, cursor = repository.list_expiring_follow_ups(second.deadline_at, limit=1)
    assert [item.follow_up_id for item in expiring] == [first.follow_up_id]
    page_two, _ = repository.list_expiring_follow_ups(second.deadline_at, limit=10, cursor=cursor)
    assert [item.follow_up_id for item in page_two] == [second.follow_up_id]


def test_attempt_limit_block_preserves_contact_authority_without_due_work() -> None:
    follow_up = backend_contract__follow_up().model_copy(
        update={
            'status': FollowUpStatus.BLOCKED,
            'due_at': None,
            'blocked_reason': FollowUpReasonCode.ATTEMPT_LIMIT_REACHED,
            'attempt_count': 3,
        }
    )

    validated = FollowUpRecord.model_validate(follow_up.model_dump())

    assert validated.contact_permission is FollowUpContactPermission.AUTHORISED
    assert validated.channel is PreferredChannel.IN_APP
    assert validated.due_at is None
    assert validated.blocked_reason is FollowUpReasonCode.ATTEMPT_LIMIT_REACHED


def test_backend_contract_mongo_due_deadline_and_operation_contracts() -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'recovery_test')
    now = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    follow_up = backend_contract__follow_up()
    repository._collection.insert_one(
        {
            **follow_up.model_dump(mode='json'),
            '_id': 'follow_up:fup_operation_test',
            'record_type': 'follow_up',
            'claim_id': follow_up.claim_id,
            'customer_id': 'cus_operation_test',
        }
    )
    assert (
        repository.list_due_follow_ups(now, limit=10)[0][0].follow_up_id == follow_up.follow_up_id
    )
    assert (
        repository.list_expiring_follow_ups(now + timedelta(days=7), limit=10)[0][0].follow_up_id
        == follow_up.follow_up_id
    )
    backend_contract_seed_claim(repository, follow_up)
    operation = backend_contract__operation()
    repository.save_follow_up_operation(operation, 'cus_operation_test')
    repository.save_follow_up_operation(operation, 'cus_operation_test')
    assert repository.list_follow_up_operations(
        follow_up.claim_id, follow_up.follow_up_id, 'cus_operation_test'
    ) == [operation]
    with pytest.raises(IdempotencyConflict):
        repository.save_follow_up_operation(
            operation.model_copy(update={'operation_id': 'fop_abcdef0123456789abcd'}),
            'cus_operation_test',
        )


def test_backend_contract_mongo_retention_operation_is_replay_safe() -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'retention_test')
    follow_up = backend_contract__follow_up()
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
        {**claim.model_dump(mode='json'), '_id': f'claim:{claim.claim_id}', 'record_type': 'claim'}
    )
    operation = backend_contract_retention(claim.claim_id, now)
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    assert repository.reserve_retention_operation(operation) is True
    assert repository.reserve_retention_operation(operation) is False
    assert repository.get_retention_operation(operation.operation_id) == operation


def test_backend_contract_model_guards_cover_invalid_lifecycle_combinations() -> None:
    follow_up = backend_contract__follow_up()
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
            backend_contract__operation()
            .model_copy(update={'updated_at': now - timedelta(seconds=1)})
            .model_dump()
        )
    with pytest.raises(ValueError):
        FollowUpOperation.model_validate(
            backend_contract__operation(FollowUpOperationStatus.COMMITTED).model_dump()
        )
    with pytest.raises(ValueError):
        FollowUpOperation.model_validate(
            backend_contract__operation(FollowUpOperationStatus.CANCELLED).model_dump()
        )
    with pytest.raises(ValueError):
        RetentionOperation.model_validate(
            {
                'operation_id': 'rop_0123456789abcdef0123',
                'claim_id': 'claim',
                'target_refs': ['target'],
                'status': RetentionOperationStatus.HELD,
                'created_at': now,
                'updated_at': now,
            }
        )


def test_backend_contract_fixture_query_and_operation_rejection_paths() -> None:
    repository = FixtureRepository()
    with pytest.raises(ValueError):
        repository.list_due_follow_ups(datetime.now(UTC), limit=0)
    with pytest.raises(ValueError):
        repository.list_expiring_follow_ups(datetime.now(UTC), limit=0)
    with pytest.raises(KeyError):
        repository.save_follow_up_operation(backend_contract__operation(), 'cus_operation_test')
    retention = backend_contract_retention('missing', datetime.now(UTC))
    with pytest.raises(KeyError):
        repository.save_retention_operation(retention, expected_revision=1)


@pytest.mark.parametrize('legacy_contact_block', [False, True])
def test_missing_policy_binding_is_readable_blocked_and_never_synthesized(
    legacy_contact_block: bool,
) -> None:
    bound = backend_contract__follow_up()
    payload = bound.model_dump(mode='json')
    payload.pop('policy_id')
    payload.pop('policy_version')
    if legacy_contact_block:
        payload.update(status='blocked', contact_permission='not_authorised', channel=None)
        payload['reason_code'] = FollowUpReasonCode.CONTACT_NOT_AUTHORISED
    unbound = FollowUpRecord.model_validate(payload)
    assert unbound.policy_id is None and unbound.policy_version is None
    assert unbound.status is FollowUpStatus.BLOCKED
    assert unbound.blocked_reason is FollowUpReasonCode.POLICY_BINDING_INVALID
    assert unbound.due_at == bound.due_at
    assert unbound.created_at == bound.created_at
    repository = FixtureRepository()
    backend_contract_seed_claim(repository, unbound)
    repository._follow_ups[unbound.follow_up_id] = unbound
    assert repository.list_due_follow_ups(unbound.created_at, limit=10) == ([], None)


@pytest.mark.parametrize('kind', ['fixture', 'mongodb'])
@pytest.mark.parametrize('anonymous', [True, False])
def test_service_pause_resume_stores_valid_resolved_record_in_both_adapters(
    kind: str,
    anonymous: bool,
) -> None:
    from backend.core.auth import Principal
    from backend.domain.models import StartSessionRequest
    from backend.services.claims import pause_session, start_session

    repository = _repository(kind)
    now = datetime.now(UTC)
    customer = 'anonymous:synthetic' if anonymous else 'cus_resume_probe'
    claim = WorkingClaim(
        claim_id='clm_resume_probe',
        customer_id=customer,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
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
        status=SessionStatus.ACTIVE,
        context_revision=1,
        started_at=now,
        last_active_at=now,
    )
    repository.create_claim(claim, session)
    principal = Principal(
        subject=customer,
        actor_type='claimant',
        auth_source='anonymous:browser_session' if anonymous else 'test',
    )

    pause_session(repository, principal, claim.claim_id, session.session_id, 'pause', '1')
    (paused,) = repository.list_follow_ups(claim.claim_id, customer)
    if anonymous:
        assert paused.status is FollowUpStatus.BLOCKED
        assert paused.blocked_reason is FollowUpReasonCode.CONTACT_NOT_AUTHORISED
    else:
        assert paused.status is FollowUpStatus.PENDING
        assert paused.due_at is not None

    resumed = start_session(
        repository, principal, claim.claim_id, StartSessionRequest(intent='resume'), 'resume'
    )

    (stored,) = repository.list_follow_ups(claim.claim_id, customer)
    # A fresh round-trip through the model must validate the persisted shape.
    stored = FollowUpRecord.model_validate(stored.model_dump(mode='json'))
    assert stored.status is FollowUpStatus.RESOLVED
    assert stored.resolution_code is FollowUpResolutionCode.CLAIMANT_RESUMED
    assert stored.blocked_reason is None
    assert stored.due_at is None
    assert stored.active_operation_id is None
    current = repository.get_claim(claim.claim_id, customer)
    assert current is not None
    assert current.active_session_id == resumed.session_id
    assert resumed.session_id != session.session_id
    # No executable recovery work remains after resume.
    due, _ = repository.list_due_follow_ups(now + timedelta(days=30), limit=10, cursor=None)
    assert claim.claim_id not in {item.claim_id for item in due}
