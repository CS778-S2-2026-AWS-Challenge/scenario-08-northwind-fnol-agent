from fastapi.testclient import TestClient
from httpx import Response


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
