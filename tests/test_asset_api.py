from dataclasses import replace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.domain.assets import ClaimAssetSnapshot
from backend.domain.audit import AuditEventEnvelope, AuditSubject, AuditSubjectType
from backend.domain.models import (
    ActorReference,
    ActorType,
    BranchEvaluationRecord,
    ClaimCreationStatus,
    ClaimTerminalDisposition,
    ExternalClaimResult,
    IntegrationSource,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyRecord


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
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_account_assets_are_owned_paginated_revisioned_and_soft_deleted(
    client: TestClient,
    repository: FixtureRepository,
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
    asset_events = repository.list_audit_events_internal(
        AuditSubject(subject_type=AuditSubjectType.ASSET, subject_id=asset_id)
    )
    assert [event.reason for event in asset_events] == [
        'Claimant created the account Asset.',
        'Claimant updated the account Asset.',
        'Claimant deactivated the account Asset.',
    ]
    assert all('SYN123' not in event.model_dump_json() for event in asset_events)


def test_asset_selection_prefills_proposals_and_snapshot_remains_immutable(
    client: TestClient,
    repository: FixtureRepository,
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
    changed_revision = client.post(
        route,
        headers={**selection_headers, 'If-Match': str(claim['revision'] + 1)},
        json={'asset_id': asset['asset_id']},
    )
    changed_asset = client.post(
        route,
        headers=selection_headers,
        json={'asset_id': 'ase_00000000000000000000'},
    )
    missing_if_match = client.post(
        route,
        headers={
            **owner,
            'Idempotency-Key': selection_headers['Idempotency-Key'],
        },
        json={'asset_id': asset['asset_id']},
    )
    malformed_if_match = client.post(
        route,
        headers={**selection_headers, 'If-Match': 'not-a-revision'},
        json={'asset_id': asset['asset_id']},
    )

    assert selected.status_code == 201, selected.text
    assert replay.status_code == 201
    assert replay.json() == selected.json()
    assert changed_revision.status_code == 409
    assert changed_revision.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert changed_asset.status_code == 409
    assert changed_asset.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert missing_if_match.status_code == 409
    assert missing_if_match.json()['error']['code'] == 'REVISION_REQUIRED'
    assert malformed_if_match.status_code == 409
    assert malformed_if_match.json()['error']['code'] == 'REVISION_REQUIRED'
    assert set(selected.json()['proposed_fields']) == {
        'claim.product_family',
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
        json={'details': {'registration': 'NEW456'}},
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
    assert 'policy_reference' not in snapshots.json()['items'][0]
    assert staff_snapshots.status_code == 200
    assert staff_snapshots.json()['items'] == snapshots.json()['items']
    assert 'customer_id' not in snapshots.text
    selection_events = repository.list_audit_events_internal(
        AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim['claim_id'],
            claim_id=claim['claim_id'],
        )
    )
    assert len(selection_events) == 1
    assert selection_events[0].claim_revision == selected.json()['revision']
    assert selection_events[0].idempotency_key == 'asset-selection-1'
    assert asset['details']['registration'] not in selection_events[0].model_dump_json()


@pytest.mark.parametrize('disposition', list(TerminalDispositionValue))
def test_terminal_claim_rejects_asset_selection_without_any_write(
    client: TestClient,
    repository: FixtureRepository,
    disposition: TerminalDispositionValue,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    asset = _create_asset(client, owner)
    created = client.post(
        '/api/v1/claims',
        headers={**owner, 'Idempotency-Key': f'terminal-claim-{disposition.value}'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    ).json()['claim']
    current = repository.get_claim_internal(created['claim_id'])
    assert current is not None
    external_claim = (
        ExternalClaimResult(
            external_claim_id=f'ext_{current.claim_id}',
            claim_number=f'NW-{current.claim_id}',
            creation_status=ClaimCreationStatus.CREATED,
            route='standard_motor_intake',
            next_step='A claims professional will review the created Claim.',
            source=IntegrationSource.FIXTURE,
            created_at=current.updated_at,
        )
        if disposition is TerminalDispositionValue.COMPLETED
        else None
    )
    reason = {
        TerminalDispositionValue.COMPLETED: TerminalDispositionReasonCode.CLAIM_CREATED,
        TerminalDispositionValue.ABANDONED: (
            TerminalDispositionReasonCode.ABANDONMENT_POLICY_APPLIED
        ),
        TerminalDispositionValue.CLOSED: TerminalDispositionReasonCode.AUTHORISED_CLOSURE,
    }[disposition]
    terminal = current.model_copy(
        update={
            'external_claim': external_claim,
            'terminal_disposition': ClaimTerminalDisposition(
                value=disposition,
                reason_code=reason,
                source_refs=[f'terminal:{disposition.value}'],
                recorded_by=ActorReference(
                    actor_type=ActorType.SYSTEM,
                    actor_id='asset-terminal-test',
                ),
                recorded_at=current.updated_at,
                recorded_revision=current.revision,
            ),
        }
    )
    repository._claims[current.claim_id] = terminal
    route = f'/api/v1/claims/{current.claim_id}/asset-selections'
    branch_count = len(repository._branch_evaluations)
    audit_count = len(repository._audit_events)
    idempotency_key = f'terminal-selection-{disposition.value}'

    response = client.post(
        route,
        headers={
            **owner,
            'Idempotency-Key': idempotency_key,
            'If-Match': str(current.revision),
        },
        json={'asset_id': asset['asset_id']},
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert repository.get_claim_internal(current.claim_id) == terminal
    assert repository.list_claim_asset_snapshots(current.claim_id, current.customer_id) == (
        [],
        False,
    )
    assert len(repository._branch_evaluations) == branch_count
    assert len(repository._audit_events) == audit_count
    assert repository.find_idempotency(current.customer_id, route, idempotency_key) is None


def test_asset_contract_rejects_unapproved_policy_fields_and_anonymous_account_access(
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
            'policy_reference': {'policy_id': 'pol_unverified'},
        },
    )
    fixed_token = client.get(
        '/api/v1/account/assets', headers={'Authorization': 'Bearer synthetic-claimant'}
    )

    assert mismatch.status_code == 422
    assert fixed_token.status_code == 401


@pytest.mark.parametrize(
    ('payload', 'expected_field'),
    [
        ({'display_name': None}, 'body.display_name'),
        ({'details': None}, 'body.details'),
        ({'details': {'address': '1 Synthetic Street'}}, 'details'),
    ],
)
def test_asset_patch_rejects_null_and_cross_type_content_without_mutation(
    client: TestClient,
    payload: dict[str, object],
    expected_field: str,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    asset = _create_asset(client, owner)
    route = f'/api/v1/account/assets/{asset["asset_id"]}'

    response = client.patch(route, headers={**owner, 'If-Match': '1'}, json=payload)
    stored = client.get(route, headers=owner)

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'
    assert any(
        item['field'].startswith(expected_field)
        for item in response.json()['error'].get('details', [])
    )
    assert stored.status_code == 200
    assert stored.json() == asset


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
        json={'asset_id': 'ase_00000000000000000000'},
    )
    missing_claim = client.post(
        '/api/v1/claims/clm_missing/asset-selections',
        headers={**owner, 'Idempotency-Key': 'missing-claim-select', 'If-Match': '1'},
        json={'asset_id': asset['asset_id']},
    )
    missing_snapshots = client.get('/api/v1/claims/clm_missing/asset-snapshots', headers=owner)
    missing_update = client.patch(
        '/api/v1/account/assets/ase_00000000000000000000',
        headers={**owner, 'If-Match': '1'},
        json={'display_name': 'Missing'},
    )
    missing_delete = client.delete(
        '/api/v1/account/assets/ase_00000000000000000000',
        headers={**owner, 'If-Match': '1'},
    )

    assert stale.status_code == 409
    assert stale.json()['error']['current_revision'] == created_claim['revision']
    assert missing_asset.status_code == 404
    assert missing_claim.status_code == 404
    assert missing_snapshots.status_code == 404
    assert missing_update.status_code == 404
    assert missing_delete.status_code == 404


@pytest.mark.parametrize(
    ('race_mode', 'expected_status'),
    [('revision', 409), ('unavailable', 404)],
)
def test_asset_selection_race_is_typed_and_leaves_no_partial_write(
    client: TestClient,
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    race_mode: str,
    expected_status: int,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    asset = _create_asset(client, owner)
    claim = client.post(
        '/api/v1/claims',
        headers={**owner, 'Idempotency-Key': f'race-claim-{race_mode}'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    ).json()['claim']
    route = f'/api/v1/claims/{claim["claim_id"]}/asset-selections'
    original_save = repository.save_asset_selection
    branch_count = len(repository._branch_evaluations)
    audit_count = len(repository._audit_events)

    def race_save(
        updated_claim: WorkingClaim,
        expected_revision: int,
        snapshot: ClaimAssetSnapshot,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord,
        audit_event: AuditEventEnvelope,
    ) -> None:
        current = repository.get_asset(snapshot.asset_id, updated_claim.customer_id)
        assert current is not None
        repository._assets[current.asset_id] = current.model_copy(
            update={
                'revision': current.revision + 1,
                'active': race_mode != 'unavailable',
            }
        )
        original_save(
            updated_claim,
            expected_revision,
            snapshot,
            idempotency,
            branch_evaluation,
            audit_event,
        )

    monkeypatch.setattr(repository, 'save_asset_selection', race_save)
    response = client.post(
        route,
        headers={
            **owner,
            'Idempotency-Key': f'race-selection-{race_mode}',
            'If-Match': str(claim['revision']),
        },
        json={'asset_id': asset['asset_id']},
    )

    assert response.status_code == expected_status
    assert response.json()['error']['code'] == (
        'REVISION_CONFLICT' if race_mode == 'revision' else 'RESOURCE_NOT_FOUND'
    )
    if race_mode == 'revision':
        assert response.json()['error']['current_revision'] == asset['revision'] + 1
    stored_claim = repository.get_claim_internal(claim['claim_id'])
    assert stored_claim is not None
    assert stored_claim.revision == claim['revision']
    assert repository.list_claim_asset_snapshots(claim['claim_id'], stored_claim.customer_id) == (
        [],
        False,
    )
    assert len(repository._branch_evaluations) == branch_count
    assert len(repository._audit_events) == audit_count
    assert (
        repository.find_idempotency(stored_claim.customer_id, route, f'race-selection-{race_mode}')
        is None
    )


def test_asset_selection_maps_concurrent_idempotency_conflict(
    client: TestClient,
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    asset = _create_asset(client, owner)
    claim = client.post(
        '/api/v1/claims',
        headers={**owner, 'Idempotency-Key': 'idempotency-race-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    ).json()['claim']
    route = f'/api/v1/claims/{claim["claim_id"]}/asset-selections'
    original_save = repository.save_asset_selection
    audit_count = len(repository._audit_events)

    def conflicting_save(
        updated_claim: WorkingClaim,
        expected_revision: int,
        snapshot: ClaimAssetSnapshot,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord,
        audit_event: AuditEventEnvelope,
    ) -> None:
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        repository._idempotency[lookup] = replace(
            idempotency, request_fingerprint='concurrent-different-request'
        )
        original_save(
            updated_claim,
            expected_revision,
            snapshot,
            idempotency,
            branch_evaluation,
            audit_event,
        )

    monkeypatch.setattr(repository, 'save_asset_selection', conflicting_save)
    response = client.post(
        route,
        headers={
            **owner,
            'Idempotency-Key': 'idempotency-race-selection',
            'If-Match': str(claim['revision']),
        },
        json={'asset_id': asset['asset_id']},
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert len(repository._audit_events) == audit_count
