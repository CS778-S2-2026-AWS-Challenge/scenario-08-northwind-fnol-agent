"""Durable signal bundle and staff projection regressions.

Mongo mock assertions prove preflight ordering and stored contracts, not real
transaction rollback or concurrent execution.
"""

import os
from datetime import UTC, datetime
from typing import Any

import mongomock
import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.knowledge import KnowledgeCitation
from backend.domain.models import ActorType
from backend.domain.realtime import RealtimeResource
from backend.domain.retrieval import ReviewSignalRecord
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyConflict, IdempotencyRecord
from backend.services.workbench import list_workbench_signals
from tests.test_mongodb_repository import _claim, _decision, _message, _session


@pytest.fixture(params=['fixture', 'mongo'])
def bundle(request: pytest.FixtureRequest) -> tuple[Any, dict[str, Any], ReviewSignalRecord]:
    if request.param == 'fixture':
        repository: Any = FixtureRepository()
    else:
        repository = MongoDBRepository(mongomock.MongoClient(), 'policy_judgment_turn')
        repository._atomic = lambda operation: operation(None)
    return _bundle(repository)


def _bundle(repository: Any) -> tuple[Any, dict[str, Any], ReviewSignalRecord]:
    original = _claim()
    session = _session(original)
    repository.create_claim(original, session)
    claim = original.model_copy(update={'revision': 2})
    session = session.model_copy(update={'context_revision': 2})
    inbound = _message(claim, session)
    reply = inbound.model_copy(
        update={
            'message_id': 'msg_policy_reply',
            'client_message_id': None,
            'actor': ActorType.AGENT,
            'in_reply_to': inbound.message_id,
        }
    )
    decision = _decision(claim, session, inbound)
    key = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='/messages',
        key='policy-turn',
        request_fingerprint='policy-turn',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id=inbound.message_id,
        agent_message_id=reply.message_id,
        decision_id=decision.decision_id,
    )
    signal = ReviewSignalRecord(
        signal_id='sig_policy',
        claim_id=claim.claim_id,
        code='POLICY_JUDGMENT_PROPOSAL',
        source_refs=['chunk_policy'],
        reason_codes=['JUDGMENT_POINT:liability_split'],
        summary='Staff review is needed.',
        judgment_point_kind='liability_split',
        proposed_assessment='Needs review.',
        proposal_rationale='Reported facts may engage the cited clause.',
        created_at=claim.updated_at,
        policy_sources=[
            KnowledgeCitation(
                document_id='doc_policy',
                chunk_id='chunk_policy',
                title='Motor policy',
                section_path='MTR-COV-02',
                source_uri='northwind://policy/motor',
                version='2026.1',
                checksum='synthetic-checksum',
                text='Professional review applies.',
            )
        ],
    )
    return (
        repository,
        dict(
            claim=claim,
            expected_revision=1,
            session=session,
            claimant_message=inbound,
            agent_message=reply,
            decision=decision,
            idempotency=key,
        ),
        signal,
    )


def test_turn_signal_is_durable_and_staff_only(
    bundle: tuple[Any, dict[str, Any], ReviewSignalRecord],
) -> None:
    repository, args, signal = bundle
    repository.save_agent_turn(**args, review_signals=[signal])
    claim = args['claim']
    assert repository.list_review_signals(claim.claim_id, claim.customer_id) == [signal]
    assert repository.list_review_signals(claim.claim_id, 'cus_other') == []
    staff = Principal('staff_test', 'staff', scopes=frozenset({'workbench:read'}))
    projected = list_workbench_signals(repository, staff, claim.claim_id, 20, None).items[0]
    assert projected.judgment_point_kind == signal.judgment_point_kind
    assert projected.proposed_assessment == signal.proposed_assessment
    assert projected.proposal_rationale == signal.proposal_rationale
    assert projected.source_evidence == [signal.policy_sources[0].model_dump(mode='json')]
    event = repository.replay_realtime_events(None, limit=20)[-1]
    assert RealtimeResource.SIGNALS in event.resources
    assert RealtimeResource.SIGNALS not in event.claimant_resources
    with pytest.raises(ApiError) as forbidden:
        list_workbench_signals(
            repository, Principal(claim.customer_id, 'claimant'), claim.claim_id, 20, None
        )
    assert forbidden.value.status_code == 403
    assert (
        repository.get_claim(claim.claim_id, claim.customer_id).customer_next_step
        == claim.customer_next_step
    )


@pytest.mark.parametrize(
    'failure', ['wrong_claim', 'duplicate', 'existing_identity', 'wrong_decision']
)
def test_invalid_signal_bundle_has_no_partial_turn(
    bundle: tuple[Any, dict[str, Any], ReviewSignalRecord],
    failure: str,
) -> None:
    repository, args, signal = bundle
    signals = [signal]
    if failure == 'wrong_claim':
        signals = [signal.model_copy(update={'claim_id': 'clm_other'})]
    elif failure == 'duplicate':
        signals = [signal, signal]
    elif failure == 'existing_identity':
        if isinstance(repository, FixtureRepository):
            repository._review_signals[signal.signal_id] = signal
        else:
            repository._put(
                'review_signal',
                signal.signal_id,
                signal,
                customer_id=args['claim'].customer_id,
                claim_id=signal.claim_id,
            )
    else:
        args['decision'] = args['decision'].model_copy(update={'claim_id': 'clm_other'})
    before = repository.get_claim(args['claim'].claim_id, args['claim'].customer_id)
    before_signals = repository.list_review_signals(signal.claim_id, args['claim'].customer_id)
    with pytest.raises((KeyError, IdempotencyConflict)):
        repository.save_agent_turn(**args, review_signals=signals)
    assert repository.get_claim(before.claim_id, before.customer_id) == before
    assert repository.list_review_signals(before.claim_id, before.customer_id) == before_signals
    assert (
        repository.list_messages(before.claim_id, args['session'].session_id, before.customer_id)
        == []
    )
    key = args['idempotency']
    assert repository.find_idempotency(key.actor_id, key.route, key.key) is None


@pytest.mark.integration
def test_real_mongodb_policy_signal_rolls_back_and_then_reads_durably(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late transaction failure cannot leave advice detached from its turn."""
    uri = os.environ.get(
        'NORTHWIND_MONGODB_TEST_URI',
        'mongodb://localhost:27017/?replicaSet=rs0&directConnection=true',
    )
    client: MongoClient[Any] = MongoClient(uri, serverSelectionTimeoutMS=750)
    database = f'northwind_policy_judgment_{datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")}'
    created = False
    try:
        try:
            hello = client.admin.command('hello')
        except (PyMongoError, ValueError) as error:
            pytest.skip(f'real MongoDB replica set unavailable: {type(error).__name__}')
        if not hello.get('setName') or not hello.get('isWritablePrimary'):
            pytest.skip('real MongoDB replica set has no writable primary')
        repository = MongoDBRepository(client, database)
        created = True
        _, args, signal = _bundle(repository)
        claim = args['claim']
        before = repository.get_claim(claim.claim_id, claim.customer_id)
        events = repository.replay_realtime_events(None, limit=20)
        original_append = repository._append_realtime_mutation

        def reject_publication(*_args: Any, **kwargs: Any) -> None:
            # Assert the child really reached the transaction before failing.
            assert (
                repository._get(
                    'review_signal',
                    signal.signal_id,
                    ReviewSignalRecord,
                    session=kwargs['mongo_session'],
                )
                == signal
            )
            raise RuntimeError('forced policy signal transaction rollback')

        monkeypatch.setattr(repository, '_append_realtime_mutation', reject_publication)
        with pytest.raises(RuntimeError, match='forced policy signal transaction rollback'):
            repository.save_agent_turn(**args, review_signals=[signal])
        assert repository.get_claim(claim.claim_id, claim.customer_id) == before
        assert repository.list_review_signals(claim.claim_id, claim.customer_id) == []
        assert (
            repository.list_messages(claim.claim_id, args['session'].session_id, claim.customer_id)
            == []
        )
        key = args['idempotency']
        assert repository.find_idempotency(key.actor_id, key.route, key.key) is None
        assert repository.replay_realtime_events(None, limit=20) == events

        monkeypatch.setattr(repository, '_append_realtime_mutation', original_append)
        repository.save_agent_turn(**args, review_signals=[signal])
        fresh = MongoDBRepository(client, database)
        assert fresh.list_review_signals(claim.claim_id, claim.customer_id) == [signal]
        assert fresh.get_claim(claim.claim_id, claim.customer_id) == claim
        assert (
            fresh.get_agent_decision(
                claim.claim_id, args['decision'].decision_id, claim.customer_id
            )
            == args['decision']
        )
        assert (
            len(fresh.list_messages(claim.claim_id, args['session'].session_id, claim.customer_id))
            == 2
        )
        assert fresh.find_idempotency(key.actor_id, key.route, key.key) is not None
    finally:
        if created:
            client.drop_database(database)
        client.close()
