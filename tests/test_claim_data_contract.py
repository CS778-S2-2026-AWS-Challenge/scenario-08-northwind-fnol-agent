import logging
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast

import mongomock
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.models import (
    ActorReference,
    ActorType,
    Channel,
    ClaimState,
    ContentsEvidencePurpose,
    ContentsItem,
    ContentsItemEvidenceAssociation,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    FormSource,
    FormStatus,
    MotorOtherDriverRecord,
    NeededFor,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyConflict, IdempotencyRecord


def _create_claim(
    client: TestClient,
    headers: dict[str, str],
    *,
    incident_type: str,
    key: str,
) -> dict[str, Any]:
    response = client.post(
        '/api/v1/claims',
        headers={**headers, 'Idempotency-Key': key},
        json={
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': incident_type,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json()['claim'])


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post('/api/v1/auth/sessions', json={'email': email, 'password': password})
    assert response.status_code == 201, response.text
    return {'Authorization': f'Bearer {response.json()["access_token"]}'}


def test_motor_other_driver_is_bounded_idempotent_and_role_safe(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger='backend.api.claims')
    claim = _create_claim(
        client,
        auth_headers,
        incident_type='motor',
        key='motor-other-driver-claim',
    )
    claim_id = claim['claim_id']
    route = f'/api/v1/claims/{claim_id}/motor-other-driver'
    headers = {
        **auth_headers,
        'Idempotency-Key': 'motor-other-driver-create',
        'If-Match': str(claim['revision']),
    }
    payload = {
        'name': 'Synthetic Other Driver',
        'phone': '+64 21 555 0101',
        'email': 'other-driver@example.invalid',
        'vehicle_registration': 'OTH123',
    }

    created = client.post(route, headers=headers, json=payload)
    replay = client.post(route, headers=headers, json=payload)
    changed_replay = client.post(route, headers=headers, json={'name': 'Changed replay'})
    second = client.post(
        route,
        headers={
            **auth_headers,
            'Idempotency-Key': 'motor-other-driver-second',
            'If-Match': str(claim['revision'] + 1),
        },
        json={'name': 'Different person'},
    )
    claimant = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    staff = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers)

    assert created.status_code == 201, created.text
    assert replay.status_code == 201
    assert replay.json() == created.json()
    assert changed_replay.status_code == 409
    assert changed_replay.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert second.status_code == 409
    assert second.json()['error']['code'] == 'RESOURCE_CONFLICT'
    assert claimant.status_code == 200
    assert claimant.json()['motor_other_driver']['vehicle_registration'] == 'OTH123'
    assert staff.status_code == 200
    assert staff.json()['motor_other_driver']['email'] == payload['email']
    assert 'customer_id' not in claimant.text
    assert 'source_refs' not in claimant.json()['motor_other_driver']
    stored_claim = repository.get_claim_internal(claim_id)
    assert stored_claim is not None
    assert payload['email'] not in stored_claim.model_dump_json()
    assert len(repository._motor_other_drivers) == 1
    mutation_logs = [
        record
        for record in caplog.records
        if record.getMessage() == 'claim_data.motor_other_driver.create'
    ]
    assert {record.__dict__['outcome'] for record in mutation_logs} == {'succeeded', 'rejected'}
    assert mutation_logs[0].__dict__['claim_id'] == claim_id
    assert mutation_logs[0].__dict__['claim_revision'] == claim['revision'] + 1
    serialized_logs = repr([record.__dict__ for record in mutation_logs])
    assert payload['name'] not in serialized_logs
    assert payload['phone'] not in serialized_logs
    assert payload['email'] not in serialized_logs
    assert payload['vehicle_registration'] not in serialized_logs


@pytest.mark.parametrize('field', ['name', 'phone', 'email', 'vehicle_registration'])
def test_motor_other_driver_rejects_blank_text_without_any_mutation(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    field: str,
) -> None:
    claim = _create_claim(
        client,
        auth_headers,
        incident_type='motor',
        key=f'motor-blank-{field}-claim',
    )
    claim_id = claim['claim_id']
    route = f'/api/v1/claims/{claim_id}/motor-other-driver'
    idempotency_key = f'motor-blank-{field}'
    before_claim = repository.get_claim_internal(claim_id)
    before_children = deepcopy(repository._motor_other_drivers)
    before_idempotency = deepcopy(repository._idempotency)
    before_events = repository.replay_realtime_events(None, limit=1000)

    response = client.post(
        route,
        headers={
            **auth_headers,
            'Idempotency-Key': idempotency_key,
            'If-Match': str(claim['revision']),
        },
        json={field: '   '},
    )

    assert response.status_code == 422
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'
    assert repository.get_claim_internal(claim_id) == before_claim
    assert repository._motor_other_drivers == before_children
    assert repository._idempotency == before_idempotency
    assert repository.replay_realtime_events(None, limit=1000) == before_events
    assert repository.find_idempotency('cus_demo', route, idempotency_key) is None


def test_motor_other_driver_is_optional_and_rejected_outside_motor(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    home = _create_claim(
        client,
        auth_headers,
        incident_type='home',
        key='home-no-motor-party',
    )
    read = client.get(f'/api/v1/claims/{home["claim_id"]}', headers=auth_headers)
    absent_record = client.get(
        f'/api/v1/claims/{home["claim_id"]}/motor-other-driver',
        headers=auth_headers,
    )
    rejected = client.post(
        f'/api/v1/claims/{home["claim_id"]}/motor-other-driver',
        headers={
            **auth_headers,
            'Idempotency-Key': 'home-motor-party-rejected',
            'If-Match': str(home['revision']),
        },
        json={'name': 'Not a Motor participant'},
    )

    assert read.status_code == 200
    assert read.json()['motor_other_driver'] is None
    assert absent_record.status_code == 404
    assert rejected.status_code == 409
    assert rejected.json()['error']['code'] == 'INVALID_FIELD_BRANCH'


def test_home_registered_facts_and_optional_evidence_remain_canonical(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
) -> None:
    claim = _create_claim(
        client,
        auth_headers,
        incident_type='home',
        key='home-mapping-claim',
    )
    claim_id = claim['claim_id']
    updated = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={**auth_headers, 'If-Match': str(claim['revision'])},
        json={
            'updates': [
                {'field_code': 'incident.occurred_at', 'value': '2026-09-18T08:00:00+12:00'},
                {
                    'field_code': 'incident.description',
                    'value': 'A synthetic pipe leak damaged the kitchen.',
                },
                {'field_code': 'property.affected_areas', 'value': ['kitchen']},
            ]
        },
    )
    assert updated.status_code == 200, updated.text
    revision = updated.json()['revision']
    for key, kind, note in (
        ('home-damage-photo', 'photo', 'Synthetic property damage photo.'),
        ('home-emergency-receipt', 'receipt', 'Synthetic emergency repair receipt.'),
    ):
        response = client.post(
            f'/api/v1/claims/{claim_id}/evidence',
            headers={
                **auth_headers,
                'Idempotency-Key': key,
                'If-Match': str(revision),
            },
            json={
                'kind': kind,
                'status': 'pending',
                'needed_for': ['later_action'],
                'claimant_note': note,
            },
        )
        assert response.status_code == 201, response.text
        revision = response.json()['revision']

    claimant = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    claimant_evidence = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=auth_headers)
    staff_evidence = client.get(
        f'/api/v1/workbench/claims/{claim_id}/evidence', headers=staff_auth_headers
    )

    assert claimant.status_code == 200
    assert set(claimant.json()['form']) >= {
        'incident.occurred_at',
        'incident.description',
        'property.affected_areas',
    }
    assert 'authorities.police_report_reference' in REGISTERED_FIELD_CODES
    assert claimant.json()['workflow_state'] == 'collecting'
    assert {item['kind'] for item in claimant_evidence.json()['items']} == {
        'photo',
        'receipt',
    }
    assert {item['kind'] for item in staff_evidence.json()['items']} == {
        'photo',
        'receipt',
    }
    assert all('storage_key' not in item for item in claimant_evidence.json()['items'])


def _contents_item(timestamp: datetime) -> ContentsItem:
    return ContentsItem(
        item_id='itm_00000000000000000001',
        description='Synthetic laptop',
        category='electronics',
        brand='Example Brand',
        model='Model One',
        source=FormSource.CLAIMANT,
        source_refs=['asset:ase_00000000000000000001:revision:1'],
        status=FormStatus.PROPOSED,
        needed_for=NeededFor.CURRENT_ACTION,
        updated_at=timestamp,
        updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_demo'),
    )


def test_confirmed_contents_item_rejects_unknown_required_facts() -> None:
    timestamp = datetime.now(UTC)
    with pytest.raises(ValidationError, match='requires category, loss_type, and ownership'):
        ContentsItem(
            item_id='itm_00000000000000000002',
            description='Incomplete synthetic item',
            source=FormSource.CLAIMANT,
            status=FormStatus.CONFIRMED,
            needed_for=NeededFor.CURRENT_ACTION,
            updated_at=timestamp,
            updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_demo'),
        )


def _evidence(claim_id: str, evidence_id: str, timestamp: datetime) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        claim_id=claim_id,
        kind='receipt',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        original_filename='synthetic-receipt.pdf',
        media_type='application/pdf',
        size_bytes=128,
        source=EvidenceSource.CLAIMANT,
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_contents_asset_upload_and_evidence_association_public_journey(
    client: TestClient,
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger='backend.api.claims')
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    asset_response = client.post(
        '/api/v1/account/assets',
        headers={**owner, 'Idempotency-Key': 'contents-public-asset'},
        json={
            'asset_type': 'contents',
            'display_name': 'Synthetic laptop',
            'details': {
                'description': 'Synthetic laptop',
                'category': 'electronics',
                'brand': 'Example Brand',
                'model': 'Model One',
            },
        },
    )
    assert asset_response.status_code == 201, asset_response.text
    claim = _create_claim(client, owner, incident_type='contents', key='contents-public-claim')
    claim_id = claim['claim_id']
    selected = client.post(
        f'/api/v1/claims/{claim_id}/asset-selections',
        headers={
            **owner,
            'Idempotency-Key': 'contents-public-select',
            'If-Match': str(claim['revision']),
        },
        json={'asset_id': asset_response.json()['asset_id']},
    )
    assert selected.status_code == 201, selected.text
    item = selected.json()['proposed_contents_item']
    item_id = item['item_id']

    content = b'synthetic receipt'
    upload = client.post(
        f'/api/v1/claims/{claim_id}/evidence/uploads',
        headers={
            **owner,
            'Idempotency-Key': 'contents-public-upload',
            'If-Match': str(selected.json()['revision']),
        },
        json={
            'kind': 'receipt',
            'original_filename': 'synthetic-receipt.pdf',
            'media_type': 'application/pdf',
            'size_bytes': len(content),
        },
    )
    assert upload.status_code == 201, upload.text
    evidence_id = upload.json()['evidence_id']
    uploaded = client.put(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/content',
        headers={**owner, 'Content-Type': 'application/pdf'},
        content=content,
    )
    assert uploaded.status_code == 204, uploaded.text
    completed = client.post(
        f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
        headers={
            **owner,
            'Idempotency-Key': 'contents-public-complete',
            'If-Match': str(upload.json()['revision']),
        },
        json={'upload_checksum': f'sha256:{sha256(content).hexdigest()}'},
    )
    assert completed.status_code == 202, completed.text

    events_before_association = repository.replay_realtime_events(None, limit=1000)
    route = f'/api/v1/claims/{claim_id}/contents-items/{item_id}/evidence-associations'
    headers = {
        **owner,
        'Idempotency-Key': 'contents-association-create',
        'If-Match': str(completed.json()['revision']),
    }
    payload = {
        'evidence_id': evidence_id,
        'purpose': 'proof_of_purchase',
    }
    created = client.post(route, headers=headers, json=payload)
    replay = client.post(route, headers=headers, json=payload)
    listed = client.get(route, headers=owner)
    claimant = client.get(f'/api/v1/claims/{claim_id}', headers=owner)
    staff = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers)
    events_after_association = repository.replay_realtime_events(None, limit=1000)

    assert created.status_code == 201, created.text
    assert created.json()['revision'] == completed.json()['revision'] + 1
    assert replay.status_code == 201
    assert replay.json() == created.json()
    assert listed.status_code == 200
    assert listed.json()['items'] == [created.json()['association']]
    assert listed.json()['page']['next_cursor'] is None
    claimant_item = claimant.json()['contents_items'][0]
    assert claimant_item['brand'] == 'Example Brand'
    assert claimant_item['model'] == 'Model One'
    assert claimant_item['loss_type'] is None
    assert claimant_item['ownership'] is None
    assert claimant_item['evidence_links'] == [created.json()['association']]
    assert staff.json()['contents_items'][0]['brand'] == 'Example Brand'
    assert staff.json()['contents_item_evidence_associations'] == [created.json()['association']]
    assert 'customer_id' not in claimant.text
    assert 'storage' not in created.text.casefold()
    assert len(events_after_association) == len(events_before_association) + 1
    association_event = events_after_association[-1]
    assert association_event.claim_id == claim_id
    assert association_event.claim_revision == created.json()['revision']
    assert {resource.value for resource in association_event.resources} >= {'claim', 'queue'}
    association_logs = [
        record
        for record in caplog.records
        if record.getMessage() == 'claim_data.contents_item_evidence.create'
    ]
    assert association_logs[-1].__dict__['claim_id'] == claim_id
    assert association_logs[-1].__dict__['item_id'] == item_id
    assert association_logs[-1].__dict__['claim_revision'] == created.json()['revision']
    assert evidence_id not in repr([record.__dict__ for record in association_logs])

    def authoritative_state() -> tuple[object, object, object, object]:
        return (
            repository.get_claim_internal(claim_id),
            deepcopy(repository._contents_item_evidence_associations),
            deepcopy(repository._idempotency),
            repository.replay_realtime_events(None, limit=1000),
        )

    unchanged = authoritative_state()
    stale = client.post(
        route,
        headers={
            **owner,
            'Idempotency-Key': 'contents-association-stale',
            'If-Match': str(completed.json()['revision']),
        },
        json=payload,
    )
    duplicate = client.post(
        route,
        headers={
            **owner,
            'Idempotency-Key': 'contents-association-duplicate',
            'If-Match': str(created.json()['revision']),
        },
        json=payload,
    )
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert duplicate.status_code == 409
    assert duplicate.json()['error']['code'] == 'RESOURCE_CONFLICT'
    assert authoritative_state() == unchanged

    foreign_claim = _create_claim(
        client,
        owner,
        incident_type='contents',
        key='contents-public-foreign-claim',
    )
    foreign_evidence = client.post(
        f'/api/v1/claims/{foreign_claim["claim_id"]}/evidence',
        headers={
            **owner,
            'Idempotency-Key': 'contents-public-foreign-evidence',
            'If-Match': str(foreign_claim['revision']),
        },
        json={'kind': 'receipt', 'status': 'pending'},
    )
    assert foreign_evidence.status_code == 201, foreign_evidence.text
    unchanged = authoritative_state()
    cross_claim = client.post(
        route,
        headers={
            **owner,
            'Idempotency-Key': 'contents-association-cross-claim',
            'If-Match': str(created.json()['revision']),
        },
        json={
            'evidence_id': foreign_evidence.json()['evidence']['evidence_id'],
            'purpose': 'proof_of_purchase',
        },
    )
    assert cross_claim.status_code == 404
    assert cross_claim.json()['error']['code'] == 'RESOURCE_NOT_FOUND'
    assert authoritative_state() == unchanged

    second_evidence = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={
            **owner,
            'Idempotency-Key': 'contents-public-second-evidence',
            'If-Match': str(created.json()['revision']),
        },
        json={'kind': 'item_photo', 'status': 'pending'},
    )
    assert second_evidence.status_code == 201, second_evidence.text
    unchanged = authoritative_state()

    def fail_event(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError('event construction failed')

    with monkeypatch.context() as event_patch:
        event_patch.setattr(
            'backend.repositories.fixture.realtime_event_from_publication',
            fail_event,
        )
        with pytest.raises(RuntimeError, match='event construction failed'):
            client.post(
                route,
                headers={
                    **owner,
                    'Idempotency-Key': 'contents-association-atomic-failure',
                    'If-Match': str(second_evidence.json()['revision']),
                },
                json={
                    'evidence_id': second_evidence.json()['evidence']['evidence_id'],
                    'purpose': 'item_condition',
                },
            )
    assert authoritative_state() == unchanged


def test_contents_evidence_link_rejects_cross_claim_and_stale_revision(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    target = _create_claim(
        client,
        auth_headers,
        incident_type='contents',
        key='contents-target-claim',
    )
    source = _create_claim(
        client,
        auth_headers,
        incident_type='contents',
        key='contents-source-claim',
    )
    timestamp = datetime.now(UTC)
    target_claim = repository.get_claim_internal(target['claim_id'])
    assert target_claim is not None
    item = _contents_item(timestamp)
    repository.save_claim(
        target_claim.model_copy(
            update={
                'revision': target_claim.revision + 1,
                'contents_items': [item],
                'updated_at': timestamp,
            }
        ),
        expected_revision=target_claim.revision,
    )
    foreign = _evidence(source['claim_id'], 'evd_contents_other_claim', timestamp)
    repository.save_evidence(foreign, 'cus_demo')
    route = (
        f'/api/v1/claims/{target["claim_id"]}/contents-items/{item.item_id}/evidence-associations'
    )

    stale = client.post(
        route,
        headers={
            **auth_headers,
            'Idempotency-Key': 'contents-link-stale',
            'If-Match': str(target_claim.revision),
        },
        json={'evidence_id': foreign.evidence_id, 'purpose': 'proof_of_purchase'},
    )
    cross_claim = client.post(
        route,
        headers={
            **auth_headers,
            'Idempotency-Key': 'contents-link-cross-claim',
            'If-Match': str(target_claim.revision + 1),
        },
        json={'evidence_id': foreign.evidence_id, 'purpose': 'proof_of_purchase'},
    )

    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert cross_claim.status_code == 404
    assert cross_claim.json()['error']['code'] == 'RESOURCE_NOT_FOUND'
    assert repository.list_contents_item_evidence_associations(target['claim_id'], 'cus_demo') == []


def test_contents_evidence_association_list_uses_stable_item_scoped_pages(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = _create_claim(
        client,
        auth_headers,
        incident_type='contents',
        key='contents-paged-associations-claim',
    )
    claim = repository.get_claim_internal(created['claim_id'])
    assert claim is not None
    timestamp = datetime(2026, 9, 18, 1, 30, tzinfo=UTC)
    target_item = _contents_item(timestamp)
    other_item = target_item.model_copy(update={'item_id': 'itm_00000000000000000002'})
    repository.save_claim(
        claim.model_copy(
            update={
                'revision': claim.revision + 1,
                'contents_items': [target_item, other_item],
                'updated_at': timestamp,
            }
        ),
        expected_revision=claim.revision,
    )
    records = [
        ContentsItemEvidenceAssociation(
            association_id=f'iea_0000000000000000000{index}',
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            item_id=target_item.item_id if index < 4 else other_item.item_id,
            evidence_id=f'evd_0000000000000000000{index}',
            purpose=ContentsEvidencePurpose.PROOF_OF_PURCHASE,
            created_at=timestamp,
        )
        for index in range(1, 5)
    ]
    repository._contents_item_evidence_associations.update(
        {record.association_id: record for record in reversed(records)}
    )
    route = (
        f'/api/v1/claims/{claim.claim_id}/contents-items/'
        f'{target_item.item_id}/evidence-associations'
    )

    first = client.get(route, headers=auth_headers, params={'limit': 2})
    assert first.status_code == 200, first.text
    first_payload = first.json()
    cursor = first_payload['page']['next_cursor']
    assert cursor is not None
    assert [item['association_id'] for item in first_payload['items']] == [
        records[0].association_id,
        records[1].association_id,
    ]

    second = client.get(route, headers=auth_headers, params={'limit': 2, 'cursor': cursor})
    assert second.status_code == 200, second.text
    second_payload = second.json()
    assert [item['association_id'] for item in second_payload['items']] == [
        records[2].association_id
    ]
    assert second_payload['page']['next_cursor'] is None
    assert {
        item['association_id'] for item in first_payload['items'] + second_payload['items']
    } == {record.association_id for record in records[:3]}
    assert records[3].association_id not in first.text + second.text

    invalid = client.get(route, headers=auth_headers, params={'cursor': 'not-a-cursor'})
    assert invalid.status_code == 422
    assert invalid.json()['error']['code'] == 'VALIDATION_ERROR'

    wrong_scope = client.get(
        (
            f'/api/v1/claims/{claim.claim_id}/contents-items/'
            f'{other_item.item_id}/evidence-associations'
        ),
        headers=auth_headers,
        params={'cursor': cursor},
    )
    assert wrong_scope.status_code == 422
    assert wrong_scope.json()['error']['code'] == 'VALIDATION_ERROR'


def _repository_claim() -> tuple[WorkingClaim, SessionRecord]:
    timestamp = datetime(2026, 9, 18, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id='clm_contract_001',
        customer_id='cus_contract_001',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='contents',
        claim_state=ClaimState(),
        active_session_id='ses_contract_001',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Tell me what happened.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        contents_items=[_contents_item(timestamp)],
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id=claim.active_session_id,
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.ACTIVE,
        started_at=timestamp,
        last_active_at=timestamp,
    )
    return claim, session


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
def test_claim_data_child_records_have_fixture_mongodb_parity(adapter: str) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(mongomock.MongoClient(), f'claim_data_{adapter}')
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo
    claim, session = _repository_claim()
    repository.create_claim(claim, session)
    evidence = _evidence(claim.claim_id, 'evd_contract_001', claim.created_at)
    repository.save_evidence(evidence, claim.customer_id)
    association = ContentsItemEvidenceAssociation(
        association_id='iea_00000000000000000001',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        item_id=claim.contents_items[0].item_id,
        evidence_id=evidence.evidence_id,
        purpose=ContentsEvidencePurpose.PROOF_OF_PURCHASE,
        created_at=claim.created_at,
    )
    updated = claim.model_copy(update={'revision': 2})
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='association-test',
        key='association-test',
        request_fingerprint='association-test',
        claim_id=claim.claim_id,
        session_id=session.session_id,
    )

    repository.save_contents_item_evidence_association_mutation(
        updated, claim.revision, association, idempotency
    )

    assert repository.list_contents_item_evidence_associations(
        claim.claim_id, claim.customer_id
    ) == [association]
    with pytest.raises(IdempotencyConflict):
        repository.save_contents_item_evidence_association_mutation(
            updated.model_copy(update={'revision': 3}),
            2,
            association,
            IdempotencyRecord(
                actor_id=claim.customer_id,
                route='association-test-second',
                key='association-test-second',
                request_fingerprint='association-test-second',
                claim_id=claim.claim_id,
                session_id=session.session_id,
            ),
        )


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
def test_contents_evidence_association_pages_have_fixture_mongodb_parity(adapter: str) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(mongomock.MongoClient(), f'claim_data_page_{adapter}')
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo
    claim, session = _repository_claim()
    other_item = claim.contents_items[0].model_copy(update={'item_id': 'itm_00000000000000000002'})
    claim = claim.model_copy(update={'contents_items': [*claim.contents_items, other_item]})
    repository.create_claim(claim, session)
    associations = [
        ContentsItemEvidenceAssociation(
            association_id=f'iea_0000000000000000000{index}',
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            item_id=claim.contents_items[0].item_id if index < 4 else other_item.item_id,
            evidence_id=f'evd_0000000000000000000{index}',
            purpose=ContentsEvidencePurpose.PROOF_OF_PURCHASE,
            created_at=claim.created_at,
        )
        for index in range(1, 5)
    ]
    if isinstance(repository, FixtureRepository):
        repository._contents_item_evidence_associations.update(
            {record.association_id: record for record in reversed(associations)}
        )
    else:
        for record in reversed(associations):
            repository._put(
                'contents_item_evidence_association',
                record.association_id,
                record,
                customer_id=claim.customer_id,
                claim_id=claim.claim_id,
            )

    first, cursor = repository.list_contents_item_evidence_association_page(
        claim.claim_id,
        claim.customer_id,
        claim.contents_items[0].item_id,
        limit=2,
        cursor=None,
    )
    assert first == associations[:2]
    assert cursor is not None
    second, final_cursor = repository.list_contents_item_evidence_association_page(
        claim.claim_id,
        claim.customer_id,
        claim.contents_items[0].item_id,
        limit=2,
        cursor=cursor,
    )
    assert second == associations[2:3]
    assert final_cursor is None


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
def test_motor_other_driver_has_fixture_mongodb_zero_or_one_parity(adapter: str) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(mongomock.MongoClient(), f'motor_party_{adapter}')
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo
    claim, session = _repository_claim()
    claim = claim.model_copy(update={'incident_type': 'motor', 'contents_items': []})
    repository.create_claim(claim, session)
    record = MotorOtherDriverRecord(
        participant_id='par_00000000000000000001',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        name='Synthetic Other Driver',
        source_refs=['msg_synthetic'],
        created_at=claim.created_at,
        updated_at=claim.created_at,
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route='motor-party-test',
        key='motor-party-test',
        request_fingerprint='motor-party-test',
        claim_id=claim.claim_id,
        session_id=session.session_id,
    )

    assert repository.get_motor_other_driver(claim.claim_id, claim.customer_id) is None
    repository.save_motor_other_driver_mutation(
        claim.model_copy(update={'revision': 2}), claim.revision, record, idempotency
    )
    assert repository.get_motor_other_driver(claim.claim_id, claim.customer_id) == record
    with pytest.raises(IdempotencyConflict):
        repository.save_motor_other_driver_mutation(
            claim.model_copy(update={'revision': 3}),
            2,
            record.model_copy(update={'participant_id': 'par_00000000000000000002'}),
            IdempotencyRecord(
                actor_id=claim.customer_id,
                route='motor-party-test-second',
                key='motor-party-test-second',
                request_fingerprint='motor-party-test-second',
                claim_id=claim.claim_id,
                session_id=session.session_id,
            ),
        )
