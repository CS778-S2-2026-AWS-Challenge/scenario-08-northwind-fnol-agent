from fastapi.testclient import TestClient


def test_workbench_requires_staff_token(client: TestClient) -> None:
    response = client.get('/api/v1/workbench/claims')

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'


def test_claimant_token_cannot_access_workbench(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get('/api/v1/workbench/claims', headers=auth_headers)

    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AUTHENTICATION_REQUIRED'


def test_staff_can_list_and_read_workbench_claim(client: TestClient, auth_headers: dict[str, str]) -> None:
    create_response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'workbench-claim-1'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert create_response.status_code == 201
    claim_id = create_response.json()['claim']['claim_id']

    staff_headers = {'Authorization': 'Bearer synthetic-staff'}
    list_response = client.get('/api/v1/workbench/claims', headers=staff_headers)

    assert list_response.status_code == 200
    items = list_response.json()['items']
    assert len(items) == 1
    assert items[0]['claim_id'] == claim_id
    assert items[0]['customer_reference'].startswith('customer-')

    detail_response = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail['claim_id'] == claim_id
    assert detail['customer_reference'].startswith('customer-')
    assert 'internal_notes' in detail
    assert 'customer_next_step' in detail
