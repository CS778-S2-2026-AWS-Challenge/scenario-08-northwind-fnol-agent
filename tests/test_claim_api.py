from datetime import timedelta

from fastapi.testclient import TestClient
from httpx import Response

from backend.domain.models import SessionRecord, SessionStatus
from backend.repositories.fixture import FixtureRepository


def create_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    key: str = 'claim-1',
) -> Response:
    headers = {**auth_headers, 'Idempotency-Key': key}
    return client.post(
        '/api/v1/claims',
        headers=headers,
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )


def test_create_claim_returns_claim_and_first_session(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = create_claim(client, auth_headers)

    assert response.status_code == 201
    payload = response.json()
    claim = payload['claim']
    session = payload['session']
    assert claim['claim_id'].startswith('clm_')
    assert claim['revision'] == 1
    assert claim['workflow_state'] == 'collecting'
    assert claim['form'] == {}
    assert claim['customer_next_step']['status'] == 'describe_incident'
    assert session['session_id'].startswith('ses_')
    assert session['claim_id'] == claim['claim_id']
    assert session['status'] == 'active'
    assert 'customer_id' not in claim
    assert 'fraud_signal' not in claim


def test_create_claim_is_idempotent_and_conflicting_reuse_is_rejected(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    first = create_claim(client, auth_headers, key='retry-1')
    second = create_claim(client, auth_headers, key='retry-1')
    conflicting = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'retry-1'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'home'},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()['claim']['claim_id'] == first.json()['claim']['claim_id']
    assert conflicting.status_code == 409
    assert conflicting.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_read_claim_and_session_use_same_fixture_state(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers)
    claim = created.json()['claim']
    session = created.json()['session']

    read_claim = client.get(f'/api/v1/claims/{claim["claim_id"]}', headers=auth_headers)
    read_session = client.get(
        f'/api/v1/claims/{claim["claim_id"]}/sessions/{session["session_id"]}',
        headers=auth_headers,
    )

    assert read_claim.status_code == 200
    assert read_claim.json()['claim_id'] == claim['claim_id']
    assert read_session.status_code == 200
    assert read_session.json()['session_id'] == session['session_id']
    assert read_session.json()['resume']['unresolved_questions'] == []


def test_start_session_requires_idempotency_and_reuses_active_session(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers)
    claim = created.json()['claim']
    first_session = created.json()['session']

    missing_key = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/sessions',
        headers=auth_headers,
        json={'intent': 'resume'},
    )
    resumed = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'session-1'},
        json={'intent': 'resume'},
    )

    assert missing_key.status_code == 400
    assert missing_key.json()['error']['code'] == 'VALIDATION_ERROR'
    assert resumed.status_code == 201
    assert resumed.json()['session_id'] == first_session['session_id']


def test_form_update_records_registered_field_and_revision(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers)
    claim = created.json()['claim']

    response = client.patch(
        f'/api/v1/claims/{claim["claim_id"]}/form',
        headers={**auth_headers, 'If-Match': '"1"'},
        json={
            'updates': [
                {
                    'field_code': 'incident.description',
                    'value': 'A rear-end collision.',
                    'status': 'confirmed',
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()['revision'] == 2
    assert response.json()['updated_fields']['incident.description']['source'] == 'claimant'
    assert (
        response.json()['updated_fields']['incident.description']['updated_by']['actor_id']
        == 'cus_demo'
    )


def test_form_update_rejects_stale_revision_unknown_field_and_silent_overwrite(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers)
    claim_id = created.json()['claim']['claim_id']
    update_url = f'/api/v1/claims/{claim_id}/form'
    first = {
        'updates': [
            {'field_code': 'incident.description', 'value': 'First description'},
        ]
    }
    client.patch(update_url, headers={**auth_headers, 'If-Match': '1'}, json=first)

    stale = client.patch(update_url, headers={**auth_headers, 'If-Match': '1'}, json=first)
    unknown = client.patch(
        update_url,
        headers={**auth_headers, 'If-Match': '2'},
        json={'updates': [{'field_code': 'invented.field', 'value': 'x'}]},
    )
    overwrite = client.patch(
        update_url,
        headers={**auth_headers, 'If-Match': '2'},
        json={'updates': [{'field_code': 'incident.description', 'value': 'Changed'}]},
    )

    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert stale.json()['error']['current_revision'] == 2
    assert unknown.status_code == 422
    assert unknown.json()['error']['code'] == 'VALIDATION_ERROR'
    assert overwrite.status_code == 409
    assert overwrite.json()['error']['code'] == 'INVALID_STATE_TRANSITION'


def test_claim_routes_require_the_synthetic_claimant_token(client: TestClient) -> None:
    response = client.post(
        '/api/v1/claims',
        headers={'Idempotency-Key': 'unauthenticated'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'


def test_claim_creation_rejects_missing_and_overlong_idempotency_keys(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    missing = client.post(
        '/api/v1/claims',
        headers=auth_headers,
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    overlong = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'x' * 201},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )

    assert missing.status_code == 400
    assert missing.json()['error']['code'] == 'VALIDATION_ERROR'
    assert overlong.status_code == 400
    assert overlong.json()['error']['code'] == 'VALIDATION_ERROR'


def test_form_update_requires_a_valid_if_match_header(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers)
    claim_id = created.json()['claim']['claim_id']
    update_url = f'/api/v1/claims/{claim_id}/form'
    body = {'updates': [{'field_code': 'incident.description', 'value': 'A description'}]}

    missing = client.patch(update_url, headers=auth_headers, json=body)
    malformed = client.patch(update_url, headers={**auth_headers, 'If-Match': 'bad'}, json=body)

    assert missing.status_code == 409
    assert missing.json()['error']['code'] == 'REVISION_REQUIRED'
    assert malformed.status_code == 409
    assert malformed.json()['error']['code'] == 'REVISION_REQUIRED'


def test_claim_and_session_reads_return_not_found_for_unknown_resources(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    claim = client.get('/api/v1/claims/clm_missing', headers=auth_headers)
    session = client.get(
        '/api/v1/claims/clm_missing/sessions/ses_missing',
        headers=auth_headers,
    )

    assert claim.status_code == 404
    assert claim.json()['error']['code'] == 'RESOURCE_NOT_FOUND'
    assert session.status_code == 404
    assert session.json()['error']['code'] == 'RESOURCE_NOT_FOUND'


def test_resumed_session_idempotency_replays_and_rejects_conflicting_payload(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_claim(client, auth_headers)
    claim_id = created.json()['claim']['claim_id']
    endpoint = f'/api/v1/claims/{claim_id}/sessions'
    headers = {**auth_headers, 'Idempotency-Key': 'resume-1'}

    first = client.post(endpoint, headers=headers, json={'intent': 'resume'})
    replay = client.post(endpoint, headers=headers, json={'intent': 'resume'})
    conflict = client.post(endpoint, headers=headers, json={'intent': 'handoff'})

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()['session_id'] == first.json()['session_id']
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_claim_collection_filters_ownership_and_paginates_updated_claims(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    first = create_claim(client, auth_headers, key='list-1').json()['claim']
    second = create_claim(client, auth_headers, key='list-2').json()['claim']
    client.patch(
        f'/api/v1/claims/{first["claim_id"]}/form',
        headers={**auth_headers, 'If-Match': '1'},
        json={'updates': [{'field_code': 'incident.description', 'value': 'Updated'}]},
    )

    owned_claim = repository.get_claim(second['claim_id'], 'cus_demo')
    assert owned_claim is not None
    updated_claim = repository.get_claim(first['claim_id'], 'cus_demo')
    assert updated_claim is not None
    repository.save_claim(
        updated_claim.model_copy(
            update={'updated_at': owned_claim.updated_at + timedelta(seconds=1)}
        ),
        expected_revision=updated_claim.revision,
    )
    other_claim = owned_claim.model_copy(
        update={
            'claim_id': 'clm_other',
            'customer_id': 'cus_other',
            'active_session_id': 'ses_other',
        }
    )
    other_session = SessionRecord(
        session_id='ses_other',
        claim_id=other_claim.claim_id,
        customer_id=other_claim.customer_id,
        started_at=other_claim.created_at,
        last_active_at=other_claim.created_at,
    )
    repository.create_claim(other_claim, other_session)

    page_one = client.get(
        '/api/v1/claims?limit=1&workflow_state=collecting',
        headers=auth_headers,
    )
    cursor = page_one.json()['page']['next_cursor']
    page_two = client.get(f'/api/v1/claims?limit=1&cursor={cursor}', headers=auth_headers)
    updated_after = client.get(
        '/api/v1/claims',
        headers=auth_headers,
        params={'updated_after': second['updated_at']},
    )

    assert page_one.status_code == 200
    assert page_one.json()['items'][0]['claim_id'] == first['claim_id']
    assert page_one.json()['items'][0]['revision'] == 2
    assert page_one.json()['items'][0]['can_resume'] is True
    assert 'customer_id' not in page_one.json()['items'][0]
    assert 'fraud_signal' not in page_one.json()['items'][0]
    assert cursor is not None
    assert page_two.status_code == 200
    assert page_two.json()['items'][0]['claim_id'] == second['claim_id']
    assert page_two.json()['page']['next_cursor'] is None
    assert updated_after.status_code == 200
    assert [item['claim_id'] for item in updated_after.json()['items']] == [first['claim_id']]


def test_claim_collection_rejects_invalid_filter_and_cursor(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    invalid_state = client.get(
        '/api/v1/claims?workflow_state=invented',
        headers=auth_headers,
    )
    invalid_cursor = client.get('/api/v1/claims?cursor=not-a-cursor', headers=auth_headers)
    missing_timezone = client.get(
        '/api/v1/claims?updated_after=2026-08-11T10:00:00',
        headers=auth_headers,
    )

    assert invalid_state.status_code == 422
    assert invalid_state.json()['error']['code'] == 'VALIDATION_ERROR'
    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json()['error']['code'] == 'VALIDATION_ERROR'
    assert missing_timezone.status_code == 422
    assert missing_timezone.json()['error']['code'] == 'VALIDATION_ERROR'
    assert missing_timezone.json()['error']['details'][0]['field'] == 'updated_after'


def test_claim_remains_readable_across_multiple_persisted_sessions(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = create_claim(client, auth_headers, key='multiple-sessions').json()
    claim_id = created['claim']['claim_id']
    first_session_id = created['session']['session_id']
    first_session = repository.get_session(claim_id, first_session_id, 'cus_demo')
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert first_session is not None
    assert claim is not None

    paused_session = first_session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            'summary': 'The claimant confirmed the first incident description.',
        }
    )
    repository.save_session(paused_session)
    second_session = SessionRecord(
        session_id='ses_second',
        claim_id=claim_id,
        customer_id='cus_demo',
        context_revision=claim.revision,
        started_at=first_session.started_at + timedelta(seconds=1),
        last_active_at=first_session.last_active_at + timedelta(seconds=1),
    )
    repository.save_session(second_session)
    repository.save_claim(
        claim.model_copy(
            update={
                'active_session_id': second_session.session_id,
                'revision': claim.revision + 1,
                'updated_at': second_session.started_at,
            }
        ),
        expected_revision=claim.revision,
    )

    first_read = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{first_session_id}',
        headers=auth_headers,
    )
    second_read = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{second_session.session_id}',
        headers=auth_headers,
    )
    claim_read = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)

    assert first_read.status_code == 200
    assert first_read.json()['status'] == 'paused'
    assert first_read.json()['resume']['summary'] == paused_session.summary
    assert second_read.status_code == 200
    assert second_read.json()['status'] == 'active'
    assert claim_read.status_code == 200
    assert claim_read.json()['revision'] == 2
    assert [
        session.session_id for session in repository.list_sessions_for_claim(claim_id, 'cus_demo')
    ] == [
        first_session_id,
        second_session.session_id,
    ]
