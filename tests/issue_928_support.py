from hashlib import sha256
from typing import Any, cast

from fastapi.testclient import TestClient


def _session_headers(
    client: TestClient,
    headers: dict[str, str],
) -> dict[str, str]:
    """Upgrade the developer compatibility token only where account APIs require a session.

    Existing claimant journey tests intentionally use the developer synthetic token.
    Account-owned payout data is stricter: it requires a real claimant session.
    Demo Claimant One is the same persisted customer (cus_demo), so logging in here
    preserves Claim ownership while exercising the real account/session boundary.
    """

    if headers.get('Authorization') != 'Bearer synthetic-claimant':
        return dict(headers)

    response = client.post(
        '/api/v1/auth/sessions',
        json={
            'email': 'claimant.one@example.invalid',
            'password': 'northwind-demo-one',
        },
    )
    assert response.status_code == 201, response.text

    body = cast(dict[str, Any], response.json())
    return {
        'Authorization': f'Bearer {body["access_token"]}',
    }


def prepare_claim_submission(
    client: TestClient,
    headers: dict[str, str],
    claim_id: str,
    revision: int | str,
    *,
    key: str,
) -> int:
    """Complete #926 Step 3 and #928 Step 4 through their public claimant APIs."""

    session_headers = _session_headers(client, headers)
    expected_revision = int(revision)

    suffix = int(sha256(key.encode()).hexdigest()[:8], 16) % 10_000_000
    account_number = f'12-3456-{suffix:07d}-00'

    destination = client.post(
        '/api/v1/account/payment-destinations',
        headers={
            **session_headers,
            'Idempotency-Key': f'{key}-payment',
        },
        json={
            'account_type': 'cheque',
            'account_number': account_number,
            'bank_name': 'Northwind Test Bank',
            'account_holder_name': 'Claimant One',
        },
    )
    assert destination.status_code == 201, destination.text

    destination_body = cast(dict[str, Any], destination.json())
    payment_destination_id = cast(
        str,
        destination_body['payment_destination_id'],
    )

    selected = client.post(
        f'/api/v1/claims/{claim_id}/payout-contact-selections',
        headers={
            **session_headers,
            'Idempotency-Key': f'{key}-payout',
            'If-Match': str(expected_revision),
        },
        json={
            'payment_destination_id': payment_destination_id,
            'contact_preference': 'in_app',
        },
    )
    assert selected.status_code == 201, selected.text

    selected_body = cast(dict[str, Any], selected.json())

    assert selected_body['customer_next_step']['status'] == 'agreement_required'
    assert selected_body['primary_action']['action_code'] == 'claimant.review_agreement'

    detail = client.get(
        f'/api/v1/claims/{claim_id}',
        headers=session_headers,
    )
    assert detail.status_code == 200, detail.text

    claim = cast(dict[str, Any], detail.json())

    assert claim['revision'] == selected_body['revision']
    assert claim['primary_action']['action_code'] == 'claimant.review_agreement'

    agreement = cast(dict[str, Any], claim['submission_agreement'])

    confirmations = {
        cast(str, confirmation['key']): True
        for confirmation in cast(
            list[dict[str, Any]],
            agreement['confirmations'],
        )
        if confirmation['required']
    }

    accepted = client.post(
        f'/api/v1/claims/{claim_id}/agreement-acceptances',
        headers={
            **session_headers,
            'Idempotency-Key': f'{key}-agreement',
            'If-Match': str(claim['revision']),
        },
        json={
            'agreement_id': agreement['agreement_id'],
            'version': agreement['version'],
            'confirmations': confirmations,
        },
    )
    assert accepted.status_code == 201, accepted.text

    accepted_body = cast(dict[str, Any], accepted.json())

    assert accepted_body['revision'] == claim['revision'] + 1
    assert accepted_body['primary_action']['action_code'] == 'claimant.create_claim'

    return cast(int, accepted_body['revision'])
