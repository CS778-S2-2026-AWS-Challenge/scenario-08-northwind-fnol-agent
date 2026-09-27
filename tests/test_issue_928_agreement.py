from datetime import timedelta
from typing import Any, cast

from fastapi.testclient import TestClient

from backend.domain.models import CustomerNextStep, ResponsibleParty
from backend.repositories.fixture import FixtureRepository
from backend.services.support import now_utc


def _login(
    client: TestClient,
    claimant: str = 'one',
) -> dict[str, str]:
    response = client.post(
        '/api/v1/auth/sessions',
        json={
            'email': f'claimant.{claimant}@example.invalid',
            'password': 'northwind-demo-' + claimant,
        },
    )
    assert response.status_code == 201, response.text
    token = cast(dict[str, Any], response.json())['access_token']
    return {'Authorization': f'Bearer {token}'}


def _prepare_step4(
    client: TestClient,
    repository: FixtureRepository,
) -> tuple[dict[str, str], dict[str, Any]]:
    owner = _login(client)

    destination = client.post(
        '/api/v1/account/payment-destinations',
        headers={**owner, 'Idempotency-Key': 'issue928-payment'},
        json={
            'account_type': 'cheque',
            'account_number': '12-3456-1111222-00',
            'bank_name': 'Northwind Test Bank',
            'account_holder_name': 'Claimant One',
        },
    )
    assert destination.status_code == 201, destination.text

    created = client.post(
        '/api/v1/claims',
        headers={**owner, 'Idempotency-Key': 'issue928-claim'},
        json={
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': 'home',
        },
    )
    assert created.status_code == 201, created.text

    claim = cast(dict[str, Any], created.json()['claim'])
    claim_id = cast(str, claim['claim_id'])

    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None

    repository._claims[claim_id] = stored.model_copy(
        deep=True,
        update={
            'customer_next_step': CustomerNextStep(
                status='ready_to_create',
                summary='Ready for payout and contact selection.',
                responsible_party=ResponsibleParty.CLAIMANT,
                required_items=[],
            )
        },
    )

    payout = client.post(
        f'/api/v1/claims/{claim_id}/payout-contact-selections',
        headers={
            **owner,
            'Idempotency-Key': 'issue928-payout',
            'If-Match': str(claim['revision']),
        },
        json={
            'payment_destination_id': destination.json()['payment_destination_id'],
            'contact_preference': 'in_app',
        },
    )
    assert payout.status_code == 201, payout.text

    detail = client.get(
        f'/api/v1/claims/{claim_id}',
        headers=owner,
    )
    assert detail.status_code == 200, detail.text

    return owner, cast(dict[str, Any], detail.json())


def _accept(
    client: TestClient,
    owner: dict[str, str],
    claim: dict[str, Any],
    *,
    key: str = 'issue928-accept',
) -> dict[str, Any]:
    agreement = cast(dict[str, Any], claim['submission_agreement'])
    confirmations = {
        cast(str, item['key']): True
        for item in cast(list[dict[str, Any]], agreement['confirmations'])
        if item['required']
    }

    response = client.post(
        f'/api/v1/claims/{claim["claim_id"]}/agreement-acceptances',
        headers={
            **owner,
            'Idempotency-Key': key,
            'If-Match': str(claim['revision']),
        },
        json={
            'agreement_id': agreement['agreement_id'],
            'version': agreement['version'],
            'confirmations': confirmations,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_step4_is_server_projected_and_creation_cannot_bypass_it(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    owner, claim = _prepare_step4(client, repository)
    claim_id = cast(str, claim['claim_id'])

    assert claim['customer_next_step']['status'] == 'agreement_required'
    assert claim['primary_action']['action_code'] == 'claimant.review_agreement'
    assert claim['submission_agreement']['agreement_id'] == ('northwind-fnol-claim-submission')

    bypass = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **owner,
            'Idempotency-Key': 'issue928-bypass',
            'If-Match': str(claim['revision']),
        },
    )
    assert bypass.status_code == 409
    assert bypass.json()['error']['code'] == 'INVALID_STATE_TRANSITION'


def test_acceptance_is_revisioned_audited_idempotent_and_claimant_safe(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    owner, claim = _prepare_step4(client, repository)
    claim_id = cast(str, claim['claim_id'])
    agreement = cast(dict[str, Any], claim['submission_agreement'])
    confirmations = {
        cast(str, item['key']): True
        for item in cast(list[dict[str, Any]], agreement['confirmations'])
        if item['required']
    }
    payload = {
        'agreement_id': agreement['agreement_id'],
        'version': agreement['version'],
        'confirmations': confirmations,
    }
    headers = {
        **owner,
        'Idempotency-Key': 'issue928-idempotent',
        'If-Match': str(claim['revision']),
    }

    accepted = client.post(
        f'/api/v1/claims/{claim_id}/agreement-acceptances',
        headers=headers,
        json=payload,
    )
    replay = client.post(
        f'/api/v1/claims/{claim_id}/agreement-acceptances',
        headers=headers,
        json=payload,
    )

    assert accepted.status_code == 201, accepted.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == accepted.json()

    body = cast(dict[str, Any], accepted.json())
    assert body['revision'] == claim['revision'] + 1
    assert body['primary_action']['action_code'] == 'claimant.create_claim'
    assert 'customer_id' not in body['acceptance']
    assert 'accepted_against_claim_revision' not in body['acceptance']

    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    assert len(stored.agreement_acceptances) == 1
    assert stored.agreement_acceptances[0].customer_id == 'cus_demo'

    changed_reuse = client.post(
        f'/api/v1/claims/{claim_id}/agreement-acceptances',
        headers=headers,
        json={**payload, 'version': 'changed'},
    )
    assert changed_reuse.status_code == 409
    assert changed_reuse.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'


def test_false_confirmation_wrong_version_foreign_claimant_and_stale_revision_fail_closed(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    owner, claim = _prepare_step4(client, repository)
    claim_id = cast(str, claim['claim_id'])
    agreement = cast(dict[str, Any], claim['submission_agreement'])
    confirmation_key = cast(str, agreement['confirmations'][0]['key'])

    false_confirmation = client.post(
        f'/api/v1/claims/{claim_id}/agreement-acceptances',
        headers={
            **owner,
            'Idempotency-Key': 'issue928-false',
            'If-Match': str(claim['revision']),
        },
        json={
            'agreement_id': agreement['agreement_id'],
            'version': agreement['version'],
            'confirmations': {confirmation_key: False},
        },
    )
    assert false_confirmation.status_code == 422

    wrong_version = client.post(
        f'/api/v1/claims/{claim_id}/agreement-acceptances',
        headers={
            **owner,
            'Idempotency-Key': 'issue928-version',
            'If-Match': str(claim['revision']),
        },
        json={
            'agreement_id': agreement['agreement_id'],
            'version': 'wrong',
            'confirmations': {confirmation_key: True},
        },
    )
    assert wrong_version.status_code == 409

    stale = client.post(
        f'/api/v1/claims/{claim_id}/agreement-acceptances',
        headers={
            **owner,
            'Idempotency-Key': 'issue928-stale',
            'If-Match': str(claim['revision'] - 1),
        },
        json={
            'agreement_id': agreement['agreement_id'],
            'version': agreement['version'],
            'confirmations': {confirmation_key: True},
        },
    )
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'

    foreign = _login(client, 'two')
    concealed = client.post(
        f'/api/v1/claims/{claim_id}/agreement-acceptances',
        headers={
            **foreign,
            'Idempotency-Key': 'issue928-foreign',
            'If-Match': str(claim['revision']),
        },
        json={
            'agreement_id': agreement['agreement_id'],
            'version': agreement['version'],
            'confirmations': {confirmation_key: True},
        },
    )
    assert concealed.status_code == 404

    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    assert stored.agreement_acceptances == []


def test_later_claim_revision_invalidates_previous_acceptance(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    owner, claim = _prepare_step4(client, repository)
    claim_id = cast(str, claim['claim_id'])

    accepted = _accept(client, owner, claim)
    assert accepted['primary_action']['action_code'] == 'claimant.create_claim'

    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None

    repository._claims[claim_id] = stored.model_copy(
        deep=True,
        update={
            'revision': stored.revision + 1,
            'updated_at': now_utc() + timedelta(seconds=1),
        },
    )

    refreshed = client.get(
        f'/api/v1/claims/{claim_id}',
        headers=owner,
    )
    assert refreshed.status_code == 200
    body = cast(dict[str, Any], refreshed.json())
    assert body['primary_action']['action_code'] == 'claimant.review_agreement'

    bypass = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **owner,
            'Idempotency-Key': 'issue928-stale-acceptance-create',
            'If-Match': str(body['revision']),
        },
    )
    assert bypass.status_code == 409
    assert bypass.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
