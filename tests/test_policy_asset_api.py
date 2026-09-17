from typing import Any, cast

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.audit import AuditSubject, AuditSubjectType
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.services.agent import ControlledAgent


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post('/api/v1/auth/sessions', json={'email': email, 'password': password})
    assert response.status_code == 201
    token = cast(dict[str, Any], response.json())['access_token']
    return {'Authorization': f'Bearer {token}'}


def _create_policy(
    client: TestClient,
    headers: dict[str, str],
    *,
    key: str = 'policy-create-1',
    number: str = 'NW-MOTOR-10001',
    family: str = 'motor',
) -> dict[str, Any]:
    response = client.post(
        '/api/v1/account/policies',
        headers={**headers, 'Idempotency-Key': key},
        json={
            'policy_number': number,
            'display_name': f'Synthetic {family} policy',
            'product_family': family,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _create_vehicle(
    client: TestClient,
    headers: dict[str, str],
    policy_id: str,
) -> dict[str, Any]:
    response = client.post(
        '/api/v1/account/assets',
        headers={**headers, 'Idempotency-Key': 'policy-asset-create'},
        json={
            'asset_type': 'vehicle',
            'display_name': 'Synthetic policy-linked vehicle',
            'details': {'registration': 'SYN123'},
            'policy_id': policy_id,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_policy_summaries_are_owned_revisioned_paginated_and_audited(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    other = _login(client, 'claimant.two@example.invalid', 'northwind-demo-two')
    policy = _create_policy(client, owner)

    replay = client.post(
        '/api/v1/account/policies',
        headers={**owner, 'Idempotency-Key': 'policy-create-1'},
        json={
            'policy_number': 'NW-MOTOR-10001',
            'display_name': 'Synthetic motor policy',
            'product_family': 'motor',
        },
    )
    conflict = client.post(
        '/api/v1/account/policies',
        headers={**owner, 'Idempotency-Key': 'policy-create-1'},
        json={
            'policy_number': 'NW-HOME-20001',
            'display_name': 'Different policy',
            'product_family': 'home',
        },
    )
    concealed = client.get(f'/api/v1/account/policies/{policy["policy_id"]}', headers=other)
    stale = client.patch(
        f'/api/v1/account/policies/{policy["policy_id"]}',
        headers={**owner, 'If-Match': '99'},
        json={'display_name': 'Stale'},
    )
    updated = client.patch(
        f'/api/v1/account/policies/{policy["policy_id"]}',
        headers={**owner, 'If-Match': '1'},
        json={'display_name': 'Updated synthetic policy'},
    )
    second = _create_policy(
        client,
        owner,
        key='policy-create-2',
        number='NW-HOME-20001',
        family='home',
    )
    first_page = client.get('/api/v1/account/policies?limit=1', headers=owner)
    second_page = client.get(
        '/api/v1/account/policies',
        headers=owner,
        params={'limit': 1, 'cursor': first_page.json()['page']['next_cursor']},
    )
    removed = client.delete(
        f'/api/v1/account/policies/{policy["policy_id"]}',
        headers={**owner, 'If-Match': '2'},
    )
    active = client.get('/api/v1/account/policies', headers=owner)
    all_records = client.get('/api/v1/account/policies?include_inactive=true', headers=owner)

    assert replay.status_code == 201
    assert replay.json() == policy
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert concealed.status_code == 404
    assert stale.status_code == 409
    assert stale.json()['error']['current_revision'] == 1
    assert updated.status_code == 200
    assert updated.json()['revision'] == 2
    assert first_page.json()['page']['next_cursor'] is not None
    assert second_page.json()['page']['next_cursor'] is None
    assert removed.status_code == 204
    assert [item['policy_id'] for item in active.json()['items']] == [second['policy_id']]
    inactive = next(
        item for item in all_records.json()['items'] if item['policy_id'] == policy['policy_id']
    )
    assert inactive['active'] is False
    assert inactive['revision'] == 3
    events = repository.list_audit_events_internal(
        AuditSubject(
            subject_type=AuditSubjectType.POLICY,
            subject_id=policy['policy_id'],
        )
    )
    assert len(events) == 3
    assert all(policy['policy_number'] not in event.model_dump_json() for event in events)


def test_asset_policy_association_is_owned_family_safe_and_snapshotted(
    client: TestClient,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    other = _login(client, 'claimant.two@example.invalid', 'northwind-demo-two')
    motor_policy = _create_policy(client, owner)
    home_policy = _create_policy(
        client,
        owner,
        key='home-policy',
        number='NW-HOME-20001',
        family='home',
    )
    other_policy = _create_policy(
        client,
        other,
        key='other-policy',
        number='NW-MOTOR-OTHER',
    )

    cross_owner = client.post(
        '/api/v1/account/assets',
        headers={**owner, 'Idempotency-Key': 'cross-owner-policy'},
        json={
            'asset_type': 'vehicle',
            'display_name': 'Invalid vehicle',
            'details': {'registration': 'BAD001'},
            'policy_id': other_policy['policy_id'],
        },
    )
    wrong_family = client.post(
        '/api/v1/account/assets',
        headers={**owner, 'Idempotency-Key': 'wrong-family-policy'},
        json={
            'asset_type': 'vehicle',
            'display_name': 'Invalid vehicle',
            'details': {'registration': 'BAD002'},
            'policy_id': home_policy['policy_id'],
        },
    )
    asset = _create_vehicle(client, owner, motor_policy['policy_id'])
    claim = client.post(
        '/api/v1/claims',
        headers={**owner, 'Idempotency-Key': 'policy-linked-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    ).json()['claim']
    selected = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/asset-selections',
        headers={
            **owner,
            'Idempotency-Key': 'policy-linked-selection',
            'If-Match': str(claim['revision']),
        },
        json={'asset_id': asset['asset_id']},
    )

    assert cross_owner.status_code == 404
    assert wrong_family.status_code == 422
    assert wrong_family.json()['error']['code'] == 'VALIDATION_ERROR'
    assert asset['policy_id'] == motor_policy['policy_id']
    assert selected.status_code == 201, selected.text
    assert set(selected.json()['proposed_fields']) == {
        'claim.product_family',
        'policy.policy_number',
        'vehicle.registration',
    }
    policy_fact = selected.json()['proposed_fields']['policy.policy_number']
    assert policy_fact['status'] == 'proposed'
    assert policy_fact['value'] == motor_policy['policy_number']
    assert policy_fact['source_refs'] == [f'policy:{motor_policy["policy_id"]}:revision:1']
    snapshot = selected.json()['snapshot']
    assert snapshot['policy'] == {
        'policy_id': motor_policy['policy_id'],
        'policy_revision': 1,
        'policy_number': motor_policy['policy_number'],
        'product_family': 'motor',
        'verification_status': 'unverified',
    }

    changed_policy = client.patch(
        f'/api/v1/account/policies/{motor_policy["policy_id"]}',
        headers={**owner, 'If-Match': '1'},
        json={'policy_number': 'NW-MOTOR-UPDATED'},
    )
    snapshots = client.get(
        f'/api/v1/claims/{claim["claim_id"]}/asset-snapshots',
        headers=owner,
    )
    assert changed_policy.status_code == 200
    assert snapshots.json()['items'][0]['policy'] == snapshot['policy']


def test_archived_policy_blocks_new_selection_without_partial_claim_write(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    policy = _create_policy(client, owner)
    asset = _create_vehicle(client, owner, policy['policy_id'])
    claim = client.post(
        '/api/v1/claims',
        headers={**owner, 'Idempotency-Key': 'archived-policy-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    ).json()['claim']
    removed = client.delete(
        f'/api/v1/account/policies/{policy["policy_id"]}',
        headers={**owner, 'If-Match': '1'},
    )
    route = f'/api/v1/claims/{claim["claim_id"]}/asset-selections'
    response = client.post(
        route,
        headers={
            **owner,
            'Idempotency-Key': 'archived-policy-selection',
            'If-Match': str(claim['revision']),
        },
        json={'asset_id': asset['asset_id']},
    )

    assert removed.status_code == 204
    assert response.status_code == 404
    stored_claim = repository.get_claim_internal(claim['claim_id'])
    assert stored_claim is not None
    assert stored_claim.revision == claim['revision']
    assert repository.list_claim_asset_snapshots(claim['claim_id'], stored_claim.customer_id) == (
        [],
        False,
    )
    assert (
        repository.find_idempotency(
            stored_claim.customer_id,
            route,
            'archived-policy-selection',
        )
        is None
    )


def test_policy_revision_race_rejects_asset_create_without_partial_write(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    policy = _create_policy(client, owner)
    original_create = repository.create_asset

    def concurrent_create(*args: Any, **kwargs: Any) -> None:
        stored = repository._policy_summaries[policy['policy_id']]
        repository._policy_summaries[policy['policy_id']] = stored.model_copy(
            update={'revision': stored.revision + 1}
        )
        original_create(*args, **kwargs)

    repository.create_asset = concurrent_create  # type: ignore[method-assign]
    response = client.post(
        '/api/v1/account/assets',
        headers={**owner, 'Idempotency-Key': 'policy-race-asset'},
        json={
            'asset_type': 'vehicle',
            'display_name': 'Racing vehicle',
            'details': {'registration': 'RACE01'},
            'policy_id': policy['policy_id'],
        },
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'
    customer_id = repository._policy_summaries[policy['policy_id']].customer_id
    assert repository.list_assets(customer_id) == ([], False)
    assert (
        repository.find_idempotency(
            customer_id,
            '/api/v1/account/assets',
            'policy-race-asset',
        )
        is None
    )


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
def test_policy_asset_selection_has_fixture_and_mongodb_api_parity(adapter: str) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(mongomock.MongoClient(), f'policy_asset_parity_{adapter}')
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
        repository,
        ControlledAgent(),
    )
    with TestClient(app) as test_client:
        owner = _login(test_client, 'claimant.one@example.invalid', 'northwind-demo-one')
        policy = _create_policy(test_client, owner, key=f'parity-policy-{adapter}')
        asset = _create_vehicle(test_client, owner, policy['policy_id'])
        claim = test_client.post(
            '/api/v1/claims',
            headers={**owner, 'Idempotency-Key': f'parity-claim-{adapter}'},
            json={'channel': 'web_agent', 'locale': 'en-NZ'},
        ).json()['claim']
        selected = test_client.post(
            f'/api/v1/claims/{claim["claim_id"]}/asset-selections',
            headers={
                **owner,
                'Idempotency-Key': f'parity-selection-{adapter}',
                'If-Match': str(claim['revision']),
            },
            json={'asset_id': asset['asset_id']},
        )

    assert selected.status_code == 201, selected.text
    assert selected.json()['snapshot']['policy']['policy_id'] == policy['policy_id']
    assert (
        selected.json()['proposed_fields']['policy.policy_number']['value']
        == (policy['policy_number'])
    )


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
def test_policy_revision_race_blocks_selection_without_partial_write(adapter: str) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(mongomock.MongoClient(), f'policy_race_parity_{adapter}')
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
        repository,
        ControlledAgent(),
    )
    with TestClient(app) as test_client:
        owner = _login(test_client, 'claimant.one@example.invalid', 'northwind-demo-one')
        policy = _create_policy(test_client, owner, key=f'race-policy-{adapter}')
        asset = _create_vehicle(test_client, owner, policy['policy_id'])
        claim = test_client.post(
            '/api/v1/claims',
            headers={**owner, 'Idempotency-Key': f'race-claim-{adapter}'},
            json={'channel': 'web_agent', 'locale': 'en-NZ'},
        ).json()['claim']
        original_save = repository.save_asset_selection

        def racing_save(*args: Any, **kwargs: Any) -> None:
            if isinstance(repository, FixtureRepository):
                stored = repository._policy_summaries[policy['policy_id']]
                repository._policy_summaries[policy['policy_id']] = stored.model_copy(
                    update={'revision': stored.revision + 1}
                )
            else:
                repository._collection.update_one(
                    {
                        '_id': repository._record_id('policy_summary', policy['policy_id']),
                        'record_type': 'policy_summary',
                    },
                    {'$inc': {'revision': 1}},
                )
            original_save(*args, **kwargs)

        repository.save_asset_selection = racing_save  # type: ignore[method-assign]
        route = f'/api/v1/claims/{claim["claim_id"]}/asset-selections'
        response = test_client.post(
            route,
            headers={
                **owner,
                'Idempotency-Key': f'race-selection-{adapter}',
                'If-Match': str(claim['revision']),
            },
            json={'asset_id': asset['asset_id']},
        )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'
    assert response.json()['error']['current_revision'] == 2
    stored_claim = repository.get_claim_internal(claim['claim_id'])
    assert stored_claim is not None
    assert stored_claim.revision == claim['revision']
    assert repository.list_claim_asset_snapshots(claim['claim_id'], stored_claim.customer_id) == (
        [],
        False,
    )
    assert repository.list_branch_evaluations(claim['claim_id'], stored_claim.customer_id) == []
    assert (
        repository.find_idempotency(
            stored_claim.customer_id,
            route,
            f'race-selection-{adapter}',
        )
        is None
    )
    assert (
        repository.list_audit_events_internal(
            AuditSubject(
                subject_type=AuditSubjectType.CLAIM,
                subject_id=claim['claim_id'],
                claim_id=claim['claim_id'],
            )
        )
        == []
    )
