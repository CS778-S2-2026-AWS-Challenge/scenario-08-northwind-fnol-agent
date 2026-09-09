from datetime import UTC, datetime

import mongomock
from fastapi.testclient import TestClient

from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    FollowUpRecord,
    FollowUpStatus,
    ResponsibleParty,
    SessionRecord,
    SessionRecoveryContext,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyRecord, RevisionConflict


def _create_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    key: str,
) -> dict[str, object]:
    response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': key},
        json={
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': 'motor',
        },
    )
    assert response.status_code == 201
    return response.json()


def test_pause_checkpoint_is_durable_visible_idempotent_and_resumable(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = _create_claim(client, auth_headers, 'p17-create')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    revision = int(claim['revision'])

    pause_headers = {
        **auth_headers,
        'Idempotency-Key': 'p17-pause',
        'If-Match': f'"{revision}"',
    }
    paused = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause',
        headers=pause_headers,
    )
    assert paused.status_code == 200
    body = paused.json()
    assert body['session']['status'] == 'paused'
    assert body['claim']['revision'] == revision + 1
    assert body['claim']['incomplete_context']['follow_up_status'] == 'pending'

    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    stored_session = repository.get_session(claim_id, session_id, 'cus_demo')
    follow_ups = repository.list_follow_ups(claim_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_session is not None
    assert stored_claim.active_session_id is None
    assert stored_session.status is SessionStatus.PAUSED
    assert stored_session.recovery_context is not None
    assert len(follow_ups) == 1
    assert follow_ups[0].source_session_id == session_id
    assert follow_ups[0].attempt_count == 0

    replay = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause',
        headers=pause_headers,
    )
    assert replay.status_code == 200
    assert replay.json() == body
    assert len(repository.list_follow_ups(claim_id, 'cus_demo')) == 1
    assert repository.get_claim(claim_id, 'cus_demo').revision == revision + 1

    claimant_read = client.get(
        f'/api/v1/claims/{claim_id}',
        headers=auth_headers,
    )
    assert claimant_read.status_code == 200
    assert claimant_read.json()['incomplete_context']['resume_point']

    claimant_list = client.get('/api/v1/claims', headers=auth_headers)
    assert claimant_list.status_code == 200
    list_item = next(item for item in claimant_list.json()['items'] if item['claim_id'] == claim_id)
    assert list_item['incomplete_context']['follow_up_status'] == 'pending'

    staff_read = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers={'Authorization': 'Bearer synthetic-staff'},
    )
    assert staff_read.status_code == 200
    incomplete = staff_read.json()['work_summary']['incomplete_context']
    assert incomplete['follow_up_status'] == 'pending'
    assert incomplete['follow_up_attempts'] == 0
    assert incomplete['resume_point']

    resumed = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'p17-resume'},
        json={'intent': 'resume'},
    )
    assert resumed.status_code == 201
    assert resumed.json()['session_id'] != session_id
    assert repository.claim_count == 1
    final_claim = repository.get_claim(claim_id, 'cus_demo')
    assert final_claim is not None
    assert final_claim.active_session_id == resumed.json()['session_id']
    assert len(repository.list_follow_ups(claim_id, 'cus_demo')) == 1


def test_pause_checkpoint_rejects_stale_revision_without_partial_write(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = _create_claim(client, auth_headers, 'p17-stale-create')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    revision = int(claim['revision'])

    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p17-stale-pause',
            'If-Match': f'"{revision + 1}"',
        },
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'
    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    stored_session = repository.get_session(claim_id, session_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_session is not None
    assert stored_claim.revision == revision
    assert stored_claim.active_session_id == session_id
    assert stored_session.status is SessionStatus.ACTIVE
    assert repository.list_follow_ups(claim_id, 'cus_demo') == []


def _mongo_bundle() -> tuple[
    MongoDBRepository,
    WorkingClaim,
    SessionRecord,
    WorkingClaim,
    SessionRecord,
    FollowUpRecord,
    IdempotencyRecord,
]:
    repository = MongoDBRepository(mongomock.MongoClient(), 'p17_test')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    timestamp = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id='clm_p17_mongo',
        customer_id='cus_p17_mongo',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id='ses_p17_mongo',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Continue describing the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id='ses_p17_mongo',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.ACTIVE,
        context_revision=claim.revision,
        started_at=timestamp,
        last_active_at=timestamp,
    )
    repository.create_claim(claim, session)
    recovery = SessionRecoveryContext(
        interrupted_at=timestamp,
        last_meaningful_activity_at=timestamp,
        resume_point='Continue describing the incident.',
    )
    paused_session = session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            'recovery_context': recovery,
        }
    )
    updated_claim = claim.model_copy(
        update={
            'revision': 2,
            'active_session_id': None,
            'updated_at': timestamp,
        }
    )
    follow_up = FollowUpRecord(
        follow_up_id='fup_p17_mongo',
        claim_id=claim.claim_id,
        source_session_id=session.session_id,
        responsible_party=ResponsibleParty.SYSTEM,
        status=FollowUpStatus.PENDING,
        created_at=timestamp,
        updated_at=timestamp,
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/sessions/{session.session_id}/pause',
        key='p17-mongo-pause',
        request_fingerprint='p17-mongo-fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        follow_up_id=follow_up.follow_up_id,
    )
    return (
        repository,
        claim,
        session,
        updated_claim,
        paused_session,
        follow_up,
        idempotency,
    )


def test_mongodb_persists_incomplete_checkpoint_with_fixture_equivalent_shape() -> None:
    (
        repository,
        claim,
        _,
        updated_claim,
        paused_session,
        follow_up,
        idempotency,
    ) = _mongo_bundle()

    repository.save_incomplete_checkpoint(
        updated_claim,
        expected_revision=claim.revision,
        session=paused_session,
        follow_up=follow_up,
        idempotency=idempotency,
    )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == updated_claim
    assert (
        repository.get_session(
            claim.claim_id,
            paused_session.session_id,
            claim.customer_id,
        )
        == paused_session
    )
    assert repository.list_follow_ups(claim.claim_id, claim.customer_id) == [follow_up]
    assert (
        repository.find_idempotency(
            claim.customer_id,
            idempotency.route,
            idempotency.key,
        )
        == idempotency
    )


def test_mongodb_stale_incomplete_checkpoint_has_no_partial_children() -> None:
    (
        repository,
        claim,
        session,
        updated_claim,
        paused_session,
        follow_up,
        idempotency,
    ) = _mongo_bundle()

    try:
        repository.save_incomplete_checkpoint(
            updated_claim,
            expected_revision=claim.revision + 1,
            session=paused_session,
            follow_up=follow_up,
            idempotency=idempotency,
        )
    except RevisionConflict:
        pass
    else:
        raise AssertionError('Expected a stale revision conflict.')

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert (
        repository.get_session(
            claim.claim_id,
            session.session_id,
            claim.customer_id,
        )
        == session
    )
    assert repository.list_follow_ups(claim.claim_id, claim.customer_id) == []
    assert (
        repository.find_idempotency(
            claim.customer_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )
