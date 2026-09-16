from typing import Any, cast

import pytest
from fastapi.testclient import TestClient


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post('/api/v1/auth/sessions', json={'email': email, 'password': password})
    assert response.status_code == 201
    token = cast(dict[str, Any], response.json())['access_token']
    return {'Authorization': f'Bearer {token}'}


def _create_asset(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post(
        '/api/v1/account/assets',
        headers={**headers, 'Idempotency-Key': 'asset-create-1'},
        json={
            'asset_type': 'vehicle',
            'display_name': 'Synthetic family car',
            'details': {
                'registration': 'SYN123',
                'registered_owner': 'Synthetic Claimant',
                'make': 'Example Motors',
                'model': 'Model One',
                'year': 2024,
            },
            'policy_reference': {
                'policy_number': 'POL-SYN-001',
                'product_family': 'motor',
            },
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_account_assets_are_owned_paginated_revisioned_and_soft_deleted(
    client: TestClient,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    other = _login(client, 'claimant.two@example.invalid', 'northwind-demo-two')
    asset = _create_asset(client, owner)
    asset_id = asset['asset_id']

    different_replay = client.post(
        '/api/v1/account/assets',
        headers={**owner, 'Idempotency-Key': 'asset-create-1'},
        json={
            'asset_type': 'contents',
            'display_name': 'Different request',
            'details': {'description': 'Synthetic laptop'},
        },
    )

    replay = client.post(
        '/api/v1/account/assets',
        headers={**owner, 'Idempotency-Key': 'asset-create-1'},
        json={
            'asset_type': 'vehicle',
            'display_name': 'Synthetic family car',
            'details': {
                'registration': 'SYN123',
                'registered_owner': 'Synthetic Claimant',
                'make': 'Example Motors',
                'model': 'Model One',
                'year': 2024,
            },
            'policy_reference': {
                'policy_number': 'POL-SYN-001',
                'product_family': 'motor',
            },
        },
    )
    concealed = client.get(f'/api/v1/account/assets/{asset_id}', headers=other)
    readable = client.get(f'/api/v1/account/assets/{asset_id}', headers=owner)
    stale = client.patch(
        f'/api/v1/account/assets/{asset_id}',
        headers={**owner, 'If-Match': '99'},
        json={'display_name': 'Stale update'},
    )
    updated = client.patch(
        f'/api/v1/account/assets/{asset_id}',
        headers={**owner, 'If-Match': '1'},
        json={'display_name': 'Updated synthetic car'},
    )
    second_asset = client.post(
        '/api/v1/account/assets',
        headers={**owner, 'Idempotency-Key': 'asset-create-2'},
        json={
            'asset_type': 'contents',
            'display_name': 'Synthetic laptop',
            'details': {'description': 'Synthetic laptop'},
        },
    )
    listing = client.get('/api/v1/account/assets?limit=1', headers=owner)
    next_listing = client.get(
        f'/api/v1/account/assets?limit=1&cursor={listing.json()["page"]["next_cursor"]}',
        headers=owner,
    )
    removed = client.delete(
        f'/api/v1/account/assets/{asset_id}',
        headers={**owner, 'If-Match': '2'},
    )
    active_listing = client.get('/api/v1/account/assets', headers=owner)
    all_listing = client.get('/api/v1/account/assets?include_inactive=true', headers=owner)
    repeated_delete = client.delete(
        f'/api/v1/account/assets/{asset_id}',
        headers={**owner, 'If-Match': '3'},
    )

    assert different_replay.status_code == 409
    assert different_replay.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert replay.status_code == 201
    assert replay.json()['asset_id'] == asset_id
    assert concealed.status_code == 404
    assert readable.status_code == 200
    assert stale.status_code == 409
    assert stale.json()['error']['current_revision'] == 1
    assert updated.status_code == 200
    assert updated.json()['revision'] == 2
    assert second_asset.status_code == 201
    assert len(listing.json()['items']) == 1
    assert listing.json()['page']['next_cursor'] is not None
    assert len(next_listing.json()['items']) == 1
    assert next_listing.json()['page']['next_cursor'] is None
    assert {
        listing.json()['items'][0]['asset_id'],
        next_listing.json()['items'][0]['asset_id'],
    } == {
        asset_id,
        second_asset.json()['asset_id'],
    }
    assert removed.status_code == 204
    assert [item['asset_id'] for item in active_listing.json()['items']] == [
        second_asset.json()['asset_id']
    ]
    removed_projection = next(
        item for item in all_listing.json()['items'] if item['asset_id'] == asset_id
    )
    assert removed_projection['active'] is False
    assert removed_projection['revision'] == 3
    assert repeated_delete.status_code == 204


def test_asset_selection_prefills_proposals_and_snapshot_remains_immutable(
    client: TestClient,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    asset = _create_asset(client, owner)
    created_claim = client.post(
        '/api/v1/claims',
        headers={**owner, 'Idempotency-Key': 'asset-claim-create'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    assert created_claim.status_code == 201, created_claim.text
    claim = created_claim.json()['claim']
    route = f'/api/v1/claims/{claim["claim_id"]}/asset-selections'
    selection_headers = {
        **owner,
        'Idempotency-Key': 'asset-selection-1',
        'If-Match': str(claim['revision']),
    }
    selected = client.post(route, headers=selection_headers, json={'asset_id': asset['asset_id']})
    replay = client.post(route, headers=selection_headers, json={'asset_id': asset['asset_id']})

    assert selected.status_code == 201, selected.text
    assert replay.status_code == 201
    assert replay.json() == selected.json()
    assert set(selected.json()['proposed_fields']) == {
        'claim.product_family',
        'policy.policy_number',
        'vehicle.registration',
    }
    assert all(
        field['status'] == 'proposed' for field in selected.json()['proposed_fields'].values()
    )
    assert all(
        f'asset:{asset["asset_id"]}:revision:1' in field['source_refs']
        for field in selected.json()['proposed_fields'].values()
    )

    changed = client.patch(
        f'/api/v1/account/assets/{asset["asset_id"]}',
        headers={**owner, 'If-Match': '1'},
        json={
            'details': {'registration': 'NEW456'},
            'policy_reference': None,
        },
    )
    snapshots = client.get(f'/api/v1/claims/{claim["claim_id"]}/asset-snapshots', headers=owner)
    staff_snapshots = client.get(
        f'/api/v1/workbench/claims/{claim["claim_id"]}/asset-snapshots',
        headers={'Authorization': 'Bearer synthetic-staff'},
    )

    assert changed.status_code == 200, changed.text
    assert changed.json()['details']['registration'] == 'NEW456'
    assert snapshots.status_code == 200
    assert snapshots.json()['items'][0]['details']['registration'] == 'SYN123'
    assert snapshots.json()['items'][0]['policy_reference']['policy_number'] == 'POL-SYN-001'
    assert staff_snapshots.status_code == 200
    assert staff_snapshots.json()['items'] == snapshots.json()['items']
    assert 'customer_id' not in snapshots.text


def test_asset_contract_rejects_type_policy_mismatch_and_anonymous_account_access(
    client: TestClient,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    mismatch = client.post(
        '/api/v1/account/assets',
        headers={**owner, 'Idempotency-Key': 'asset-mismatch'},
        json={
            'asset_type': 'vehicle',
            'display_name': 'Invalid asset',
            'details': {'registration': 'SYN123'},
            'policy_reference': {
                'policy_number': 'POL-HOME-001',
                'product_family': 'home',
            },
        },
    )
    fixed_token = client.get(
        '/api/v1/account/assets', headers={'Authorization': 'Bearer synthetic-claimant'}
    )

    assert mismatch.status_code == 422
    assert fixed_token.status_code == 401


@pytest.mark.parametrize(
    ('asset_type', 'details', 'family', 'expected_fields'),
    [
        (
            'property',
            {'address': '1 Synthetic Street, Wellington'},
            'home',
            {'claim.product_family', 'property.address'},
        ),
        (
            'contents',
            {'description': 'Synthetic laptop', 'brand': 'Example'},
            'contents',
            {'claim.product_family'},
        ),
    ],
)
def test_property_and_contents_assets_prefill_only_their_approved_claim_facts(
    client: TestClient,
    asset_type: str,
    details: dict[str, object],
    family: str,
    expected_fields: set[str],
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    created_asset = client.post(
        '/api/v1/account/assets',
        headers={**owner, 'Idempotency-Key': f'create-{asset_type}'},
        json={
            'asset_type': asset_type,
            'display_name': f'Synthetic {asset_type}',
            'details': details,
        },
    )
    created_claim = client.post(
        '/api/v1/claims',
        headers={**owner, 'Idempotency-Key': f'claim-{asset_type}'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    claim = created_claim.json()['claim']
    selected = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/asset-selections',
        headers={
            **owner,
            'Idempotency-Key': f'select-{asset_type}',
            'If-Match': str(claim['revision']),
        },
        json={'asset_id': created_asset.json()['asset_id']},
    )

    assert selected.status_code == 201, selected.text
    assert set(selected.json()['proposed_fields']) == expected_fields
    assert selected.json()['proposed_fields']['claim.product_family']['value'] == family


def test_asset_selection_errors_are_concealed_and_revision_safe(client: TestClient) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    asset = _create_asset(client, owner)
    created_claim = client.post(
        '/api/v1/claims',
        headers={**owner, 'Idempotency-Key': 'error-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    ).json()['claim']
    route = f'/api/v1/claims/{created_claim["claim_id"]}/asset-selections'

    stale = client.post(
        route,
        headers={**owner, 'Idempotency-Key': 'stale-select', 'If-Match': '99'},
        json={'asset_id': asset['asset_id']},
    )
    missing_asset = client.post(
        route,
        headers={
            **owner,
            'Idempotency-Key': 'missing-asset-select',
            'If-Match': str(created_claim['revision']),
        },
        json={'asset_id': 'ast_00000000000000000000'},
    )
    missing_claim = client.post(
        '/api/v1/claims/clm_missing/asset-selections',
        headers={**owner, 'Idempotency-Key': 'missing-claim-select', 'If-Match': '1'},
        json={'asset_id': asset['asset_id']},
    )
    missing_snapshots = client.get('/api/v1/claims/clm_missing/asset-snapshots', headers=owner)
    missing_update = client.patch(
        '/api/v1/account/assets/ast_00000000000000000000',
        headers={**owner, 'If-Match': '1'},
        json={'display_name': 'Missing'},
    )
    missing_delete = client.delete(
        '/api/v1/account/assets/ast_00000000000000000000',
        headers={**owner, 'If-Match': '1'},
    )

    assert stale.status_code == 409
    assert stale.json()['error']['current_revision'] == created_claim['revision']
    assert missing_asset.status_code == 404
    assert missing_claim.status_code == 404
    assert missing_snapshots.status_code == 404
    assert missing_update.status_code == 404
    assert missing_delete.status_code == 404
