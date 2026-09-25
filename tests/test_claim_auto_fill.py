from typing import Any, cast

from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post('/api/v1/auth/sessions', json={'email': email, 'password': password})
    assert response.status_code == 201
    return {'Authorization': f'Bearer {response.json()["access_token"]}'}


def _post(
    client: TestClient,
    path: str,
    headers: dict[str, str],
    key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(path, headers={**headers, 'Idempotency-Key': key}, json=payload)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_claim_auto_fill_manifest_is_owner_scoped_preference_gated_and_read_only(
    client: TestClient,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    other = _login(client, 'claimant.two@example.invalid', 'northwind-demo-two')
    claim = _post(
        client,
        '/api/v1/claims',
        owner,
        'auto-fill-claim',
        {'channel': 'web_agent', 'locale': 'en-NZ'},
    )['claim']
    _post(
        client,
        '/api/v1/account/policies',
        owner,
        'auto-fill-policy',
        {'policy_number': 'POL-SENSITIVE-123'},
    )
    _post(
        client,
        '/api/v1/account/assets',
        owner,
        'auto-fill-asset',
        {
            'asset_type': 'vehicle',
            'display_name': 'Saved car',
            'details': {'registration': 'SECRET-REG'},
        },
    )
    _post(
        client,
        '/api/v1/account/payment-destinations',
        owner,
        'auto-fill-payment',
        {
            'account_type': 'cheque',
            'account_number': '12-3456-1234567-00',
            'bank_name': 'Synthetic Bank',
            'account_holder_name': 'Synthetic Claimant',
        },
    )
    _post(
        client,
        '/api/v1/account/identity-documents',
        owner,
        'auto-fill-identity',
        {'document_type': 'passport', 'document_number': 'PA1234567'},
    )
    path = f'/api/v1/claims/{claim["claim_id"]}/auto-fill-suggestions'

    disabled = client.get(path, headers=owner)
    account = client.get('/api/v1/account', headers=owner).json()
    enabled = client.patch(
        '/api/v1/account/claim-auto-fill-preferences',
        headers={**owner, 'If-Match': str(account['revision'])},
        json={
            'personal_details': True,
            'policy_number': True,
            'saved_assets': True,
            'payment_details': True,
            'identity_information': True,
        },
    )
    projected = client.get(path, headers=owner)
    concealed = client.get(path, headers=other)
    claim_after = client.get(f'/api/v1/claims/{claim["claim_id"]}', headers=owner)

    assert disabled.status_code == 200
    assert all(
        not item['enabled'] and not item['eligible'] for item in disabled.json()['suggestions']
    )
    assert all(item['available'] for item in disabled.json()['suggestions'])
    assert enabled.status_code == 200
    assert projected.status_code == 200
    assert all(item['enabled'] and item['eligible'] for item in projected.json()['suggestions'])
    assert {item['category']: item['action'] for item in projected.json()['suggestions']} == {
        'personal_details': 'review_and_confirm',
        'policy_number': 'select_policy',
        'saved_assets': 'select_asset',
        'payment_details': 'confirm_separately',
        'identity_information': 'confirm_separately',
    }
    serialized = projected.text
    assert 'POL-SENSITIVE-123' not in serialized
    assert 'SECRET-REG' not in serialized
    assert '1234567' not in serialized
    assert 'PA1234567' not in serialized
    assert concealed.status_code == 404
    assert concealed.json()['error']['code'] == 'RESOURCE_NOT_FOUND'
    assert claim_after.json()['revision'] == claim['revision']


def test_claim_auto_fill_manifest_keeps_enabled_categories_ineligible_without_saved_data(
    client: TestClient,
) -> None:
    owner = _login(client, 'claimant.two@example.invalid', 'northwind-demo-two')
    claim = _post(
        client,
        '/api/v1/claims',
        owner,
        'auto-fill-empty-claim',
        {'channel': 'web_agent', 'locale': 'en-NZ'},
    )['claim']
    account = client.get('/api/v1/account', headers=owner).json()
    updated = client.patch(
        '/api/v1/account/claim-auto-fill-preferences',
        headers={**owner, 'If-Match': str(account['revision'])},
        json={key: True for key in account['claim_auto_fill_preferences']},
    )

    response = client.get(
        f'/api/v1/claims/{claim["claim_id"]}/auto-fill-suggestions', headers=owner
    )

    assert updated.status_code == 200
    suggestions = {item['category']: item for item in response.json()['suggestions']}
    assert suggestions['personal_details']['eligible'] is True
    for category in (
        'policy_number',
        'saved_assets',
        'payment_details',
        'identity_information',
    ):
        assert suggestions[category]['enabled'] is True
        assert suggestions[category]['available'] is False
        assert suggestions[category]['eligible'] is False
