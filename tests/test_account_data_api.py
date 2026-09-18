import logging
from base64 import urlsafe_b64decode
from typing import Any, cast

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.audit import AuditSubject, AuditSubjectType
from backend.repositories.account_data import PolicySelectionConflict
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import RevisionConflict
from backend.services.protected_values import UnavailableProtectedValueAdapter


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post('/api/v1/auth/sessions', json={'email': email, 'password': password})
    assert response.status_code == 201
    token = cast(dict[str, Any], response.json())['access_token']
    return {'Authorization': f'Bearer {token}'}


def _post(
    client: TestClient,
    headers: dict[str, str],
    path: str,
    key: str,
    payload: dict[str, str],
) -> dict[str, Any]:
    response = client.post(path, headers={**headers, 'Idempotency-Key': key}, json=payload)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_profile_migrates_display_name_to_one_compatible_name_projection(
    client: TestClient,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    initial = client.get('/api/v1/account', headers=owner)
    updated = client.patch(
        '/api/v1/account/profile',
        headers={**owner, 'If-Match': str(initial.json()['revision'])},
        json={
            'legal_name': 'Synthetic Legal Name',
            'preferred_name': 'Synthetic Preferred Name',
            'date_of_birth': '1990-02-03',
            'phone': '020 000 0000',
            'residential_address': '1 Example Street, Auckland',
        },
    )
    stale = client.patch(
        '/api/v1/account/profile',
        headers={**owner, 'If-Match': str(initial.json()['revision'])},
        json={'preferred_name': 'Stale Name'},
    )
    incompatible = client.patch(
        '/api/v1/account/profile',
        headers={**owner, 'If-Match': str(updated.json()['revision'])},
        json={'legal_name': 'One Name', 'display_name': 'Another Name'},
    )

    assert updated.status_code == 200, updated.text
    profile = updated.json()['profile']
    assert profile == {
        'display_name': 'Synthetic Preferred Name',
        'legal_name': 'Synthetic Legal Name',
        'preferred_name': 'Synthetic Preferred Name',
        'date_of_birth': '1990-02-03',
        'email': 'claimant.one@example.invalid',
        'phone': '020 000 0000',
        'residential_address': '1 Example Street, Auckland',
    }
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert incompatible.status_code == 422


def test_protected_account_records_are_masked_owned_revisioned_and_idempotent(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    other = _login(client, 'claimant.two@example.invalid', 'northwind-demo-two')
    bank_number = '12-3456-1234567-00'
    passport_number = 'PA1234567'
    payment = _post(
        client,
        owner,
        '/api/v1/account/payment-destinations',
        'payment-create',
        {'account_type': 'cheque', 'account_number': bank_number},
    )
    identity = _post(
        client,
        owner,
        '/api/v1/account/identity-documents',
        'identity-create',
        {'document_type': 'passport', 'document_number': passport_number},
    )
    replay = client.post(
        '/api/v1/account/payment-destinations',
        headers={**owner, 'Idempotency-Key': 'payment-create'},
        json={'account_type': 'cheque', 'account_number': bank_number},
    )
    changed_replay = client.post(
        '/api/v1/account/payment-destinations',
        headers={**owner, 'Idempotency-Key': 'payment-create'},
        json={'account_type': 'savings', 'account_number': bank_number},
    )
    owner_list = client.get('/api/v1/account/payment-destinations', headers=owner)
    other_list = client.get('/api/v1/account/payment-destinations', headers=other)
    staff_list = client.get(
        '/api/v1/account/payment-destinations',
        headers={'Authorization': 'Bearer synthetic-staff'},
    )
    invalid_number = client.post(
        '/api/v1/account/payment-destinations',
        headers={**owner, 'Idempotency-Key': 'invalid-sensitive-number'},
        json={'account_type': 'cheque', 'account_number': 'XYZ'},
    )
    concealed = client.patch(
        f'/api/v1/account/payment-destinations/{payment["payment_destination_id"]}',
        headers={**other, 'If-Match': '1'},
        json={'account_type': 'savings'},
    )
    stale_payment = client.patch(
        f'/api/v1/account/payment-destinations/{payment["payment_destination_id"]}',
        headers={**owner, 'If-Match': '99'},
        json={'account_type': 'savings'},
    )
    updated_payment = client.patch(
        f'/api/v1/account/payment-destinations/{payment["payment_destination_id"]}',
        headers={**owner, 'If-Match': '1'},
        json={'account_type': 'savings', 'account_number': '12-3456-7654321-99'},
    )
    updated = client.patch(
        f'/api/v1/account/identity-documents/{identity["identity_id"]}',
        headers={**owner, 'If-Match': '1'},
        json={'document_type': 'driver_licence', 'document_number': 'DL7654321'},
    )
    retired = client.delete(
        f'/api/v1/account/payment-destinations/{payment["payment_destination_id"]}',
        headers={**owner, 'If-Match': '2'},
    )
    retired_identity = client.delete(
        f'/api/v1/account/identity-documents/{identity["identity_id"]}',
        headers={**owner, 'If-Match': '2'},
    )
    repeated_identity_retirement = client.delete(
        f'/api/v1/account/identity-documents/{identity["identity_id"]}',
        headers={**owner, 'If-Match': '3'},
    )

    assert payment['masked_account_number'] == '****6700'
    assert identity['masked_document_number'] == '****4567'
    assert bank_number not in str(payment)
    assert passport_number not in str(identity)
    assert replay.status_code == 201 and replay.json() == payment
    assert changed_replay.status_code == 409
    assert owner_list.json()['items'] == [payment]
    assert other_list.json()['items'] == []
    assert staff_list.status_code == 403
    assert invalid_number.status_code == 422
    assert 'XYZ' not in invalid_number.text
    assert concealed.status_code == 404
    assert stale_payment.status_code == 409
    assert updated_payment.status_code == 200
    assert updated_payment.json()['account_type'] == 'savings'
    assert updated_payment.json()['masked_account_number'] == '****2199'
    assert updated.status_code == 200
    assert updated.json()['document_type'] == 'driver_licence'
    assert updated.json()['masked_document_number'] == '****4321'
    assert retired.status_code == 204
    assert retired_identity.status_code == 204
    assert repeated_identity_retirement.status_code == 204
    stored_payment = repository.get_payment_destination(
        payment['payment_destination_id'], 'cus_demo'
    )
    assert stored_payment is not None
    assert stored_payment.protected_value != bank_number
    events = repository.list_audit_events_internal(
        AuditSubject(
            subject_type=AuditSubjectType.PAYMENT_DESTINATION,
            subject_id=payment['payment_destination_id'],
        )
    )
    assert events
    assert all(bank_number not in event.model_dump_json() for event in events)


def test_saved_policy_prefills_registered_claim_field_without_coverage_inference(
    client: TestClient,
) -> None:
    owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
    policy = _post(
        client,
        owner,
        '/api/v1/account/policies',
        'policy-create',
        {'policy_number': 'NW-SYNTHETIC-10001'},
    )
    claim_response = client.post(
        '/api/v1/claims',
        headers={**owner, 'Idempotency-Key': 'policy-claim-create'},
        json={'channel': 'web_agent', 'locale': 'en-NZ'},
    )
    claim = claim_response.json()['claim']
    route = f'/api/v1/claims/{claim["claim_id"]}/policy-selections'
    headers = {
        **owner,
        'Idempotency-Key': 'policy-select',
        'If-Match': str(claim['revision']),
    }
    selected = client.post(route, headers=headers, json={'policy_id': policy['policy_id']})
    replay = client.post(route, headers=headers, json={'policy_id': policy['policy_id']})
    detail = client.get(f'/api/v1/claims/{claim["claim_id"]}', headers=owner)
    second_policy = _post(
        client,
        owner,
        '/api/v1/account/policies',
        'policy-create-2',
        {'policy_number': 'NW-SYNTHETIC-10002'},
    )
    first_page = client.get('/api/v1/account/policies?limit=1', headers=owner)
    second_page = client.get(
        '/api/v1/account/policies',
        headers=owner,
        params={'limit': 1, 'cursor': first_page.json()['page']['next_cursor']},
    )
    missing_update = client.patch(
        '/api/v1/account/policies/pol_00000000000000000000',
        headers={**owner, 'If-Match': '1'},
        json={'policy_number': 'NW-MISSING'},
    )
    stale_update = client.patch(
        f'/api/v1/account/policies/{policy["policy_id"]}',
        headers={**owner, 'If-Match': '99'},
        json={'policy_number': 'NW-STALE'},
    )
    policy_update = client.patch(
        f'/api/v1/account/policies/{policy["policy_id"]}',
        headers={**owner, 'If-Match': '1'},
        json={'policy_number': 'NW-SYNTHETIC-UPDATED'},
    )
    policy_retirement = client.delete(
        f'/api/v1/account/policies/{policy["policy_id"]}',
        headers={**owner, 'If-Match': '2'},
    )

    assert selected.status_code == 201, selected.text
    assert replay.json() == selected.json()
    assert selected.json()['proposed_field']['value'] == 'NW-SYNTHETIC-10001'
    assert selected.json()['proposed_field']['status'] == 'proposed'
    assert detail.json()['form']['policy.policy_number']['value'] == 'NW-SYNTHETIC-10001'
    assert 'coverage' not in selected.text.lower()
    assert 'provider' not in selected.text.lower()
    assert first_page.json()['page']['next_cursor'] is not None
    assert second_page.json()['page']['next_cursor'] is None
    assert {
        first_page.json()['items'][0]['policy_id'],
        second_page.json()['items'][0]['policy_id'],
    } == {policy['policy_id'], second_policy['policy_id']}
    assert 'account_number' not in detail.text
    assert 'document_number' not in detail.text
    assert missing_update.status_code == 404
    assert stale_update.status_code == 409
    assert policy_update.status_code == 200
    assert policy_update.json()['policy_number'] == 'NW-SYNTHETIC-UPDATED'
    assert policy_retirement.status_code == 204


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
@pytest.mark.parametrize('conflict_kind', ['claim', 'policy', 'unavailable'])
def test_policy_selection_conflicts_preserve_claim_revision_and_identify_policy(
    adapter: str, conflict_kind: str
) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        repository = MongoDBRepository(mongomock.MongoClient(), f'policy_conflict_{conflict_kind}')
        repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    app = create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER), repository)
    with TestClient(app) as client:
        owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
        policy = _post(
            client,
            owner,
            '/api/v1/account/policies',
            f'conflict-policy-{adapter}-{conflict_kind}',
            {'policy_number': f'NW-CONFLICT-{adapter}-{conflict_kind}'},
        )
        claim = client.post(
            '/api/v1/claims',
            headers={**owner, 'Idempotency-Key': f'conflict-claim-{adapter}-{conflict_kind}'},
            json={'channel': 'web_agent', 'locale': 'en-NZ'},
        ).json()['claim']

        def conflict_save(*args: object, **kwargs: object) -> None:
            del args, kwargs
            if conflict_kind == 'claim':
                raise RevisionConflict(claim['revision'] + 1)
            raise PolicySelectionConflict(
                policy['policy_id'],
                reason='unavailable' if conflict_kind == 'unavailable' else 'changed',
                current_revision=2 if conflict_kind == 'policy' else None,
            )

        original_save = repository.save_policy_selection
        repository.save_policy_selection = conflict_save  # type: ignore[method-assign]
        response = client.post(
            f'/api/v1/claims/{claim["claim_id"]}/policy-selections',
            headers={
                **owner,
                'Idempotency-Key': f'conflict-selection-{adapter}-{conflict_kind}',
                'If-Match': str(claim['revision']),
            },
            json={'policy_id': policy['policy_id']},
        )
        repository.save_policy_selection = original_save  # type: ignore[method-assign]

    assert response.status_code == 409
    body = response.json()['error']
    if conflict_kind == 'claim':
        assert body['code'] == 'REVISION_CONFLICT'
        assert body['current_revision'] == claim['revision'] + 1
    else:
        assert body['code'] == 'POLICY_SELECTION_CONFLICT'
        assert body.get('current_revision') is None
        assert body['details'] == [
            {
                'field': 'policy_id',
                'reason': 'unavailable' if conflict_kind == 'unavailable' else 'changed',
            }
        ]
    stored_claim = repository.get_claim(claim['claim_id'], 'cus_demo')
    assert stored_claim is not None
    assert stored_claim.revision == claim['revision']


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
def test_fixture_and_mongodb_protected_record_parity(adapter: str) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        repository = MongoDBRepository(mongomock.MongoClient(), 'account_data_parity')
        repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    app = create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER), repository)
    with TestClient(app) as client:
        owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
        created = _post(
            client,
            owner,
            '/api/v1/account/identity-documents',
            f'identity-{adapter}',
            {'document_type': 'driver_licence', 'document_number': 'DL-SYNTH-9988'},
        )
        listing = client.get('/api/v1/account/identity-documents', headers=owner)
        updated = client.patch(
            f'/api/v1/account/identity-documents/{created["identity_id"]}',
            headers={**owner, 'If-Match': '1'},
            json={'document_number': 'DL-SYNTH-8877'},
        )
        policy = _post(
            client,
            owner,
            '/api/v1/account/policies',
            f'policy-{adapter}',
            {'policy_number': 'NW-SYNTHETIC-PARITY'},
        )
        claim_response = client.post(
            '/api/v1/claims',
            headers={**owner, 'Idempotency-Key': f'claim-{adapter}'},
            json={'channel': 'web_agent', 'locale': 'en-NZ'},
        )
        claim = claim_response.json()['claim']
        selected = client.post(
            f'/api/v1/claims/{claim["claim_id"]}/policy-selections',
            headers={
                **owner,
                'Idempotency-Key': f'policy-selection-{adapter}',
                'If-Match': str(claim['revision']),
            },
            json={'policy_id': policy['policy_id']},
        )

    assert listing.status_code == 200
    assert listing.json()['items'] == [created]
    assert updated.status_code == 200
    assert updated.json()['masked_document_number'] == '****8877'
    assert selected.status_code == 201, selected.text
    assert selected.json()['proposed_field']['value'] == 'NW-SYNTHETIC-PARITY'
    stored = repository.get_identity_document(created['identity_id'], 'cus_demo')
    assert stored is not None
    assert stored.protected_value != 'DL-SYNTH-9988'
    assert stored.masked_value == '****8877'
    if isinstance(repository, MongoDBRepository):
        document = repository._collection.find_one({'record_type': 'identity_document'})
        assert document is not None
        assert 'DL-SYNTH-9988' not in str(document)


def test_protected_writes_fail_closed_without_a_configured_adapter() -> None:
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
        FixtureRepository(),
        protected_value_adapter=UnavailableProtectedValueAdapter(),
    )
    with TestClient(app) as client:
        owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
        response = client.post(
            '/api/v1/account/identity-documents',
            headers={**owner, 'Idempotency-Key': 'unavailable-protected-store'},
            json={'document_type': 'passport', 'document_number': 'PA-SYNTH-1234'},
        )

    assert response.status_code == 503
    assert response.json()['error']['code'] == 'PROTECTED_DATA_UNAVAILABLE'
    assert 'PA-SYNTH-1234' not in response.text


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
def test_account_keyset_cursor_survives_updates_and_rejects_scope_mismatch(
    adapter: str,
) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        repository = MongoDBRepository(mongomock.MongoClient(), f'keyset_{adapter}')
        repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    app = create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER), repository)
    with TestClient(app) as client:
        owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
        other_owner = _login(client, 'claimant.two@example.invalid', 'northwind-demo-two')
        for number in range(3):
            _post(
                client,
                owner,
                '/api/v1/account/policies',
                f'keyset-policy-{number}',
                {'policy_number': f'NW-KEYSET-{number}'},
            )
        ordered = client.get('/api/v1/account/policies?limit=100', headers=owner).json()['items']
        first = client.get('/api/v1/account/policies?limit=1', headers=owner)
        cursor = first.json()['page']['next_cursor']
        decoded_cursor = urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)).decode()
        middle = ordered[1]
        updated = client.patch(
            f'/api/v1/account/policies/{middle["policy_id"]}',
            headers={**owner, 'If-Match': str(middle['revision'])},
            json={'policy_number': 'NW-KEYSET-UPDATED'},
        )
        second = client.get(
            '/api/v1/account/policies',
            headers=owner,
            params={'limit': 1, 'cursor': cursor},
        )
        third = client.get(
            '/api/v1/account/policies',
            headers=owner,
            params={'limit': 1, 'cursor': second.json()['page']['next_cursor']},
        )
        wrong_resource = client.get(
            '/api/v1/account/payment-destinations',
            headers=owner,
            params={'cursor': cursor},
        )
        wrong_filter = client.get(
            '/api/v1/account/policies',
            headers=owner,
            params={'cursor': cursor, 'include_inactive': True},
        )
        wrong_owner = client.get(
            '/api/v1/account/policies',
            headers=other_owner,
            params={'cursor': cursor},
        )
        invalid = client.get(
            '/api/v1/account/policies', headers=owner, params={'cursor': 'not-a-cursor'}
        )

    assert updated.status_code == 200
    assert first.json()['items'][0]['policy_id'] == ordered[0]['policy_id']
    assert 'cus_demo' not in decoded_cursor
    assert second.json()['items'][0]['policy_id'] == ordered[1]['policy_id']
    assert third.json()['items'][0]['policy_id'] == ordered[2]['policy_id']
    assert third.json()['page']['next_cursor'] is None
    assert wrong_resource.status_code == 422
    assert wrong_filter.status_code == 422
    assert wrong_owner.status_code == 422
    assert invalid.status_code == 422


def test_account_list_caps_limit_above_one_hundred() -> None:
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER), FixtureRepository()
    )
    with TestClient(app) as client:
        owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
        for number in range(101):
            _post(
                client,
                owner,
                '/api/v1/account/policies',
                f'cap-policy-{number}',
                {'policy_number': f'NW-CAP-{number:03d}'},
            )
        response = client.get('/api/v1/account/policies?limit=101', headers=owner)

    assert response.status_code == 200
    assert len(response.json()['items']) == 100
    assert response.json()['page']['next_cursor'] is not None


def test_account_operation_logs_are_correlated_and_exclude_protected_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bank_number = '12-3456-1234567-00'
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER), FixtureRepository()
    )
    with (
        TestClient(app) as client,
        caplog.at_level(logging.INFO, logger='backend.api.account_data'),
    ):
        owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
        created = client.post(
            '/api/v1/account/payment-destinations',
            headers={
                **owner,
                'Idempotency-Key': 'logged-payment',
                'X-Request-ID': 'account-log-success',
            },
            json={'account_type': 'cheque', 'account_number': bank_number},
        )
        rejected = client.patch(
            f'/api/v1/account/payment-destinations/{created.json()["payment_destination_id"]}',
            headers={**owner, 'If-Match': '99', 'X-Request-ID': 'account-log-rejected'},
            json={'account_type': 'savings'},
        )

    success = next(
        record for record in caplog.records if record.msg == 'payment_destination.create'
    )
    failure = next(
        record for record in caplog.records if record.msg == 'payment_destination.update'
    )
    assert created.status_code == 201
    assert rejected.status_code == 409
    assert success.__dict__['request_id'] == 'account-log-success'
    assert success.__dict__['customer_id'] == 'cus_demo'
    assert success.__dict__['outcome'] == 'succeeded'
    assert success.__dict__['revision'] == 1
    assert failure.__dict__['request_id'] == 'account-log-rejected'
    assert failure.__dict__['outcome'] == 'rejected'
    assert failure.__dict__['error_code'] == 'REVISION_CONFLICT'
    rendered_logs = str([record.__dict__ for record in caplog.records])
    assert bank_number not in rendered_logs
    assert created.json()['masked_account_number'] not in rendered_logs


def test_retirement_logs_include_final_revision_for_all_account_resources(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bank_number = '12-3456-7654321-00'
    document_number = 'DL-RETIRE-9988'
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER), FixtureRepository()
    )
    with (
        TestClient(app) as client,
        caplog.at_level(logging.INFO, logger='backend.api.account_data'),
    ):
        owner = _login(client, 'claimant.one@example.invalid', 'northwind-demo-one')
        policy = _post(
            client,
            owner,
            '/api/v1/account/policies',
            'retire-log-policy',
            {'policy_number': 'NW-RETIRE-LOG'},
        )
        payment = _post(
            client,
            owner,
            '/api/v1/account/payment-destinations',
            'retire-log-payment',
            {'account_type': 'cheque', 'account_number': bank_number},
        )
        identity = _post(
            client,
            owner,
            '/api/v1/account/identity-documents',
            'retire-log-identity',
            {'document_type': 'driver_licence', 'document_number': document_number},
        )
        operations = (
            ('account_policy.retire', policy['policy_id']),
            ('payment_destination.retire', payment['payment_destination_id']),
            ('identity_document.retire', identity['identity_id']),
        )
        responses: list[int] = []
        resource_paths = ('policies', 'payment-destinations', 'identity-documents')
        for index, (_operation, resource_id) in enumerate(operations):
            resource_path = resource_paths[index]
            first = client.delete(
                f'/api/v1/account/{resource_path}/{resource_id}',
                headers={**owner, 'If-Match': '1', 'X-Request-ID': f'retire-first-{index}'},
            )
            repeated = client.delete(
                f'/api/v1/account/{resource_path}/{resource_id}',
                headers={**owner, 'If-Match': '2', 'X-Request-ID': f'retire-repeat-{index}'},
            )
            responses.extend((first.status_code, repeated.status_code))

    assert all(response == 204 for response in responses)
    retirement_logs = [
        record
        for record in caplog.records
        if record.msg in {operation for operation, _ in operations}
    ]
    assert len(retirement_logs) == 6
    for record in retirement_logs:
        assert record.__dict__['outcome'] == 'succeeded'
        assert record.__dict__['revision'] == 2
    rendered_logs = str([record.__dict__ for record in retirement_logs])
    assert bank_number not in rendered_logs
    assert document_number not in rendered_logs
