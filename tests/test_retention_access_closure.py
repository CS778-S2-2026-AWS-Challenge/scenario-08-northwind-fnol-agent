from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import mongomock
import pytest
from fastapi.testclient import TestClient
from httpx import Response

from backend.domain.models import (
    ActorType,
    Channel,
    ClaimState,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.domain.retention import (
    INCOMPLETE_CLAIM_RETENTION_POLICY_ID,
    INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION,
    ResourceAccessClosed,
    RetentionOperation,
    RetentionOperationStatus,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import (
    IdempotencyRecord,
    PersistenceRepository,
)

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def _claim(
    *,
    claim_id: str,
    customer_id: str = 'cus_access',
) -> WorkingClaim:
    return WorkingClaim(
        claim_id=claim_id,
        customer_id=customer_id,
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id=f'ses_{claim_id}',
        customer_next_step=CustomerNextStep(
            status='collecting_details',
            summary='Continue the report.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def _session(
    claim: WorkingClaim,
) -> SessionRecord:
    return SessionRecord(
        session_id=claim.active_session_id or '',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.ACTIVE,
        context_revision=claim.revision,
        started_at=NOW,
        last_active_at=NOW,
    )


def _evidence(
    claim: WorkingClaim,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=f'evd_{claim.claim_id}',
        claim_id=claim.claim_id,
        kind='incident_photo',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        source=EvidenceSource.CLAIMANT,
        created_at=NOW,
        updated_at=NOW,
    )


def _seed_claimant_message(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    session: SessionRecord,
) -> tuple[
    WorkingClaim,
    SessionRecord,
    MessageRecord,
    IdempotencyRecord,
]:
    timestamp = NOW + timedelta(seconds=30)

    updated_claim = claim.model_copy(
        update={
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )

    updated_session = session.model_copy(
        update={
            'context_revision': updated_claim.revision,
            'last_active_at': timestamp,
        }
    )

    message = MessageRecord(
        message_id=f'msg_{claim.claim_id}',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        client_message_id=f'client_{claim.claim_id}',
        actor=ActorType.CLAIMANT,
        visibility=MessageVisibility.CLAIMANT_VISIBLE,
        content={
            'type': 'text',
            'text': 'Saved before retention closure.',
        },
        created_at=timestamp,
    )

    route = f'/api/v1/claims/{claim.claim_id}/sessions/{session.session_id}/messages'

    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=route,
        key=f'message_{claim.claim_id}',
        request_fingerprint='message-before-retention',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        message_id=message.message_id,
        revision_before_message=claim.revision,
        inbound_checkpoint=True,
    )

    repository.save_message_mutation(
        updated_claim,
        claim.revision,
        updated_session,
        message,
        idempotency,
    )

    return (
        updated_claim,
        updated_session,
        message,
        idempotency,
    )


def _operation(
    claim: WorkingClaim,
) -> RetentionOperation:
    return RetentionOperation(
        operation_id=f'ret_{claim.claim_id}',
        claim_id=claim.claim_id,
        source_terminal_ref=(f'claim-terminal:{claim.claim_id}:revision:{claim.revision}'),
        source_claim_revision=claim.revision,
        policy_id=INCOMPLETE_CLAIM_RETENTION_POLICY_ID,
        policy_version=INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION,
        revision=1,
        status=RetentionOperationStatus.RESERVED,
        access_closed_at=NOW + timedelta(minutes=1),
        source_refs=[f'claim-terminal:{claim.claim_id}:revision:{claim.revision}'],
        created_at=NOW,
        updated_at=NOW,
    )


def _repository(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> PersistenceRepository:
    if kind == 'fixture':
        return FixtureRepository()

    repository = MongoDBRepository(
        mongomock.MongoClient(),
        f'access_closure_{kind}',
    )

    monkeypatch.setattr(
        repository,
        '_atomic',
        lambda operation: operation(None),
    )

    return repository


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_retention_reservation_closes_claim_session_evidence_and_retry_access(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    claim = _claim(
        claim_id=f'clm_access_{kind}',
    )
    session = _session(claim)
    evidence = _evidence(claim)

    repository.create_claim(claim, session)
    repository.save_evidence(
        evidence,
        claim.customer_id,
    )

    route = f'/api/v1/claims/{claim.claim_id}/sessions'
    replay = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=route,
        key='old-resume',
        request_fingerprint='resume-fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        response_payload={
            'session_id': session.session_id,
        },
    )

    repository.save_idempotency(replay)

    assert repository.claimant_resource_access_open(
        claim.claim_id,
        claim.customer_id,
    )
    assert (
        repository.get_claim(
            claim.claim_id,
            claim.customer_id,
        )
        == claim
    )
    assert (
        repository.get_session(
            claim.claim_id,
            session.session_id,
            claim.customer_id,
        )
        == session
    )
    assert (
        repository.get_evidence(
            claim.claim_id,
            evidence.evidence_id,
            claim.customer_id,
        )
        == evidence
    )
    assert (
        repository.find_idempotency(
            claim.customer_id,
            route,
            replay.key,
        )
        == replay
    )

    operation = _operation(claim)

    assert repository.reserve_retention_operation(operation)

    assert not repository.claimant_resource_access_open(
        claim.claim_id,
        claim.customer_id,
    )

    # Concealed absence: caller cannot tell whether the retained internal
    # records still physically exist.
    assert (
        repository.get_claim(
            claim.claim_id,
            claim.customer_id,
        )
        is None
    )
    assert (
        repository.get_session(
            claim.claim_id,
            session.session_id,
            claim.customer_id,
        )
        is None
    )
    assert (
        repository.list_sessions_for_claim(
            claim.claim_id,
            claim.customer_id,
        )
        == []
    )
    assert (
        repository.get_evidence(
            claim.claim_id,
            evidence.evidence_id,
            claim.customer_id,
        )
        is None
    )
    assert (
        repository.list_evidence(
            claim.claim_id,
            claim.customer_id,
        )
        == []
    )
    assert evidence not in repository.list_evidence_for_customer(claim.customer_id)

    # The old retry authority remains consumed. It must not be presented as
    # an unused key because that could recreate Claim state on replay.
    with pytest.raises(ResourceAccessClosed):
        repository.find_idempotency(
            claim.customer_id,
            route,
            replay.key,
        )

    # Internal retention/audit authority is still present.
    assert repository.get_claim_internal(claim.claim_id) == claim
    assert repository.get_retention_operation_for_claim(claim.claim_id) == operation


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_delayed_claim_mutation_cannot_commit_after_access_closure(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    claim = _claim(
        claim_id=f'clm_delayed_{kind}',
    )

    repository.create_claim(
        claim,
        _session(claim),
    )

    operation = _operation(claim)

    assert repository.reserve_retention_operation(operation)

    delayed = claim.model_copy(
        update={
            'revision': claim.revision + 1,
            'updated_at': NOW + timedelta(minutes=2),
        }
    )

    with pytest.raises(ResourceAccessClosed):
        repository.save_claim(
            delayed,
            expected_revision=claim.revision,
        )

    internal = repository.get_claim_internal(claim.claim_id)
    assert internal is not None
    assert internal.revision == claim.revision


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_delayed_claimant_idempotency_write_cannot_recreate_retry_authority(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    claim = _claim(
        claim_id=f'clm_retry_{kind}',
    )

    repository.create_claim(
        claim,
        _session(claim),
    )

    assert repository.reserve_retention_operation(_operation(claim))

    stale = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/sessions',
        key='late-retry-authority',
        request_fingerprint='late-request',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
    )

    with pytest.raises(ResourceAccessClosed):
        repository.save_idempotency(stale)

    assert (
        repository.find_idempotency(
            claim.customer_id,
            stale.route,
            stale.key,
        )
        is None
    )


def test_closed_claim_create_replay_cannot_create_replacement_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    payload = {
        'channel': 'web_agent',
        'locale': 'en-NZ',
        'incident_type': 'motor',
    }
    headers = {
        **auth_headers,
        'Idempotency-Key': 'retention-create-replay',
    }

    created = client.post(
        '/api/v1/claims',
        headers=headers,
        json=payload,
    )

    assert created.status_code == 201

    claim_id = created.json()['claim']['claim_id']

    claim = repository.get_claim_internal(claim_id)

    assert claim is not None

    assert repository.reserve_retention_operation(_operation(claim))

    # This is the dangerous case: if find_idempotency() returned None, the
    # same old create request could allocate a second Claim.
    replay = client.post(
        '/api/v1/claims',
        headers=headers,
        json=payload,
    )

    assert replay.status_code == 404
    assert replay.json()['error']['code'] == 'RESOURCE_NOT_FOUND'
    assert repository.claim_count == 2

    # Closure is Claim-scoped, not an account ban. A genuinely new request
    # with a new retry identity may still create a separate Claim.
    fresh = client.post(
        '/api/v1/claims',
        headers={
            **auth_headers,
            'Idempotency-Key': 'retention-new-claim',
        },
        json=payload,
    )

    assert fresh.status_code == 201
    assert fresh.json()['claim']['claim_id'] != claim_id
    assert repository.claim_count == 3


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_closed_message_replay_surfaces_have_fixture_mongo_parity(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)

    original_claim = _claim(
        claim_id=f'clm_message_{kind}',
    )
    original_session = _session(original_claim)

    repository.create_claim(
        original_claim,
        original_session,
    )

    (
        claim,
        session,
        message,
        idempotency,
    ) = _seed_claimant_message(
        repository,
        original_claim,
        original_session,
    )

    assert (
        repository.get_message(
            claim.claim_id,
            session.session_id,
            message.message_id,
            claim.customer_id,
        )
        == message
    )

    assert (
        repository.find_message_by_client_id(
            claim.claim_id,
            message.client_message_id or '',
            claim.customer_id,
        )
        == message
    )

    assert (
        repository.find_message_turn_idempotency(
            claim.customer_id,
            idempotency.route,
            claim.claim_id,
            message.message_id,
        )
        == idempotency
    )

    assert (
        repository.find_message_checkpoint(
            claim.claim_id,
            message.message_id,
            claim.customer_id,
        )
        == idempotency
    )

    assert repository.reserve_retention_operation(_operation(claim))

    assert (
        repository.get_active_session(
            claim.claim_id,
            claim.customer_id,
        )
        is None
    )

    assert (
        repository.get_message(
            claim.claim_id,
            session.session_id,
            message.message_id,
            claim.customer_id,
        )
        is None
    )

    assert (
        repository.find_message_by_client_id(
            claim.claim_id,
            message.client_message_id or '',
            claim.customer_id,
        )
        is None
    )

    assert (
        repository.list_messages(
            claim.claim_id,
            session.session_id,
            claim.customer_id,
        )
        == []
    )

    assert (
        repository.get_follow_up(
            claim.claim_id,
            'follow-up-does-not-matter',
            claim.customer_id,
        )
        is None
    )

    assert (
        repository.list_follow_ups(
            claim.claim_id,
            claim.customer_id,
        )
        == []
    )

    with pytest.raises(ResourceAccessClosed):
        repository.find_message_turn_idempotency(
            claim.customer_id,
            idempotency.route,
            claim.claim_id,
            message.message_id,
        )

    with pytest.raises(ResourceAccessClosed):
        repository.find_message_checkpoint(
            claim.claim_id,
            message.message_id,
            claim.customer_id,
        )

    with pytest.raises(ResourceAccessClosed):
        repository.save_message_recovery(
            message,
            idempotency,
        )

    with pytest.raises(ResourceAccessClosed):
        repository.freeze_message_response(
            idempotency,
            {
                'claim_id': claim.claim_id,
                'session_id': session.session_id,
            },
        )


def test_closed_claimant_routes_use_concealed_absence(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={
            **auth_headers,
            'Idempotency-Key': 'closure-route-create',
        },
        json={
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': 'motor',
        },
    )

    assert created.status_code == 201

    body = created.json()
    claim_id = body['claim']['claim_id']
    session_id = body['session']['session_id']

    registered = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={**auth_headers, 'Idempotency-Key': 'closure-route-evidence', 'If-Match': '1'},
        json={
            'kind': 'police_report',
            'status': 'pending',
            'related_fields': ['authorities.police_report_reference'],
            'needed_for': ['later_action'],
        },
    )
    assert registered.status_code == 201
    evidence_id = registered.json()['evidence']['evidence_id']
    evidence_path = f'/api/v1/claims/{claim_id}/evidence/{evidence_id}'
    write_headers = {**auth_headers, 'If-Match': str(registered.json()['revision'])}
    action = {'source_claim_id': claim_id, 'proposal_ref': 'p', 'confirmation_ref': 'c'}

    claim = repository.get_claim_internal(claim_id)

    assert claim is not None

    assert repository.reserve_retention_operation(_operation(claim))

    def evidence_post(suffix: str, body: dict[str, object]) -> Response:
        return client.post(
            f'{evidence_path}/{suffix}',
            headers={**write_headers, 'Idempotency-Key': f'closure-evidence-{suffix}'},
            json=body,
        )

    requests: list[tuple[str, Callable[[], Response]]] = [
        (
            'PUT evidence content',
            lambda: client.put(
                f'{evidence_path}/content',
                headers={
                    **write_headers,
                    'Idempotency-Key': 'closure-evidence-content',
                    'Content-Type': 'image/jpeg',
                },
                content=b'bytes',
            ),
        ),
        (
            'POST evidence complete',
            lambda: evidence_post('complete', {'upload_checksum': 'sha256:' + '0' * 64}),
        ),
        (
            'POST evidence fact decision',
            lambda: evidence_post(
                'fact-decisions', {'field_codes': ['x'], 'decision': 'confirmed'}
            ),
        ),
        ('POST evidence remove', lambda: evidence_post('remove', action)),
        ('POST evidence reuse', lambda: evidence_post('reuse', action)),
        (
            'GET claim',
            lambda: client.get(
                f'/api/v1/claims/{claim_id}',
                headers=auth_headers,
            ),
        ),
        (
            'GET old session',
            lambda: client.get(
                (f'/api/v1/claims/{claim_id}/sessions/{session_id}'),
                headers=auth_headers,
            ),
        ),
        (
            'GET old message history',
            lambda: client.get(
                (f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'),
                headers=auth_headers,
            ),
        ),
        (
            'GET evidence',
            lambda: client.get(
                f'/api/v1/claims/{claim_id}/evidence',
                headers=auth_headers,
            ),
        ),
        (
            'POST stale resume',
            lambda: client.post(
                f'/api/v1/claims/{claim_id}/sessions',
                headers={
                    **auth_headers,
                    'Idempotency-Key': 'closure-stale-resume',
                },
                json={
                    'intent': 'resume',
                },
            ),
        ),
    ]

    for label, invoke in requests:
        response = invoke()

        assert response.status_code == 404, (
            label,
            response.text,
        )

        assert response.json()['error']['code'] == 'RESOURCE_NOT_FOUND', (
            label,
            response.text,
        )


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_low_level_retention_reservation_retires_claimant_retry_only(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(
        kind,
        monkeypatch,
    )

    claim = _claim(claim_id=f'clm_low_level_scope_{kind}')

    repository.create_claim(
        claim,
        _session(claim),
    )

    claimant_retry = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/retry',
        key=f'claimant-retry-{kind}',
        request_fingerprint='claimant-retry',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
        response_payload={
            'sensitive': 'claimant-result',
        },
    )

    internal_retry = IdempotencyRecord(
        actor_id='system-retention-reconciler',
        route='/internal/retention/reconcile',
        key=f'internal-retry-{kind}',
        request_fingerprint='internal-retry',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
        response_payload={
            'authority': 'internal-result',
        },
    )

    repository.save_idempotency(claimant_retry)

    repository.save_idempotency(internal_retry)

    reserved = repository.reserve_retention_operation(_operation(claim))

    assert reserved is True

    with pytest.raises(ResourceAccessClosed):
        repository.find_idempotency(
            claimant_retry.actor_id,
            claimant_retry.route,
            claimant_retry.key,
        )

    assert (
        repository.find_idempotency(
            internal_retry.actor_id,
            internal_retry.route,
            internal_retry.key,
        )
        == internal_retry
    )
