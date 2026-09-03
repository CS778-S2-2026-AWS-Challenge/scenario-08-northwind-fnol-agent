from typing import cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.policy_history import (
    MockPolicyHistoryAdapter,
    RetrievalUnavailable,
)
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository

INTEGRATION_AUTH = {'Authorization': 'Bearer synthetic-integration'}
POLICY_SEARCH = '/internal/v1/policy/search'
HISTORY_SEARCH = '/internal/v1/claim-history/search'


@pytest.fixture
def retrieval_adapter() -> MockPolicyHistoryAdapter:
    return MockPolicyHistoryAdapter()


@pytest.fixture
def retrieval_repository() -> FixtureRepository:
    return FixtureRepository()


@pytest.fixture
def retrieval_client(
    retrieval_repository: FixtureRepository,
    retrieval_adapter: MockPolicyHistoryAdapter,
) -> TestClient:
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
        retrieval_repository,
        policy_history_adapter=retrieval_adapter,
    )
    return TestClient(app)


def create_claim(client: TestClient, key: str) -> str:
    response = client.post(
        '/api/v1/claims',
        headers={'Authorization': 'Bearer synthetic-claimant', 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return str(cast(dict[str, object], response.json()['claim'])['claim_id'])


def test_policy_retrieval_returns_facts_with_their_source_and_drops_provider_conclusions(
    retrieval_client: TestClient,
    retrieval_repository: FixtureRepository,
) -> None:
    with retrieval_client as client:
        claim_id = create_claim(client, 'policy-evidence-claim')
        response = client.post(
            POLICY_SEARCH,
            headers=INTEGRATION_AUTH,
            json={'claim_id': claim_id, 'policy_reference': 'synthetic-policy-101'},
        )

    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'evidence_found'
    assert body['connection_state'] == 'using_fixture'
    assert body['errors'] == []
    assert body['source']['system'] == 'fixture_policy_administration'
    assert body['source']['reference'] == 'synthetic-policy-101'
    assert body['source']['retrieved_at']
    assert body['facts']['policy_reference'] == 'synthetic-policy-101'
    assert body['facts']['excess_amount'] == 500.0
    assert body['uncertainty'] == []

    # The fixture payload carries provider-only scoring and a coverage verdict.
    # None of it may cross the adapter boundary in the response or in storage.
    payload = response.text
    for banned in ('fraud_label', 'risk_score', 'policy_conclusion', 'elevated', 'covered'):
        assert banned not in payload

    stored = retrieval_repository.list_retrieval_records(claim_id, 'cus_demo')
    assert len(stored) == 1
    assert stored[0].retrieval_id == body['result_id']
    assert stored[0].source.reference == 'synthetic-policy-101'
    assert 'fraud_label' not in stored[0].facts.model_dump()


def test_policy_uncertainty_becomes_a_staff_review_signal_not_a_conclusion(
    retrieval_client: TestClient,
    retrieval_repository: FixtureRepository,
) -> None:
    with retrieval_client as client:
        claim_id = create_claim(client, 'policy-ambiguous-claim')
        response = client.post(
            POLICY_SEARCH,
            headers=INTEGRATION_AUTH,
            json={'claim_id': claim_id, 'policy_reference': 'synthetic-policy-ambiguous'},
        )

    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'ambiguous'
    assert [item['code'] for item in body['uncertainty']] == ['COVERAGE_SECTION_INCOMPLETE']

    signals = retrieval_repository.list_review_signals(claim_id, 'cus_demo')
    assert len(signals) == 1
    assert signals[0].review_type == 'professional_review'
    assert signals[0].reason_codes == ['COVERAGE_SECTION_INCOMPLETE']
    assert body['result_id'] in signals[0].source_refs


def test_unavailable_provider_reports_the_limitation_and_stores_nothing(
    retrieval_client: TestClient,
    retrieval_repository: FixtureRepository,
    retrieval_adapter: MockPolicyHistoryAdapter,
) -> None:
    retrieval_adapter.set_outage(
        RetrievalUnavailable(
            code='PROVIDER_TIMEOUT',
            detail='The policy provider did not respond within the request budget.',
        )
    )

    with retrieval_client as client:
        claim_id = create_claim(client, 'policy-outage-claim')
        response = client.post(
            POLICY_SEARCH,
            headers=INTEGRATION_AUTH,
            json={'claim_id': claim_id, 'policy_reference': 'synthetic-policy-101'},
        )
        readiness = client.get('/health/ready')

    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'timeout'
    assert body['connection_state'] == 'degraded'
    assert body['errors'] == [
        {
            'code': 'timeout',
            'message': 'The policy provider did not respond within the request budget.',
            'retryable': True,
        }
    ]
    assert body['limitations'] == ['The policy provider did not respond within the request budget.']
    assert body['facts'] is None
    assert body['source'] is None
    assert retrieval_repository.list_retrieval_records(claim_id, 'cus_demo') == []
    assert retrieval_repository.list_review_signals(claim_id, 'cus_demo') == []
    assert readiness.json()['checks']['policy'] == 'unavailable'
    assert readiness.json()['checks']['claim_history'] == 'unavailable'


def test_unknown_reference_is_no_evidence_rather_than_a_negative_finding(
    retrieval_client: TestClient,
    retrieval_repository: FixtureRepository,
) -> None:
    with retrieval_client as client:
        claim_id = create_claim(client, 'policy-missing-claim')
        response = client.post(
            POLICY_SEARCH,
            headers=INTEGRATION_AUTH,
            json={'claim_id': claim_id, 'policy_reference': 'synthetic-policy-absent'},
        )

    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'no_evidence'
    assert body['connection_state'] == 'using_fixture'
    assert body['errors'] == []
    assert body['facts'] is None
    assert body['limitations'] == ['The provider holds no record for the requested reference.']
    assert retrieval_repository.list_retrieval_records(claim_id, 'cus_demo') == []


def test_history_retrieval_is_purpose_limited_and_carries_no_fraud_finding(
    retrieval_client: TestClient,
    retrieval_repository: FixtureRepository,
) -> None:
    with retrieval_client as client:
        claim_id = create_claim(client, 'history-claim')
        allowed = client.post(
            HISTORY_SEARCH,
            headers=INTEGRATION_AUTH,
            json={
                'claim_id': claim_id,
                'history_reference': 'synthetic-history-204',
                'purpose': 'relevant_history_review',
            },
        )
        widened = client.post(
            HISTORY_SEARCH,
            headers=INTEGRATION_AUTH,
            json={
                'claim_id': claim_id,
                'history_reference': 'synthetic-history-204',
                'purpose': 'fraud_screening',
            },
        )

    assert allowed.status_code == 200
    body = allowed.json()
    assert body['status'] == 'evidence_found'
    assert body['connection_state'] == 'using_fixture'
    assert body['errors'] == []
    assert body['facts']['history_reference'] == 'synthetic-history-204'
    assert body['facts']['outcome'] == 'settled'
    for banned in ('fraud_finding', 'internal_note', 'Provider-only commentary'):
        assert banned not in allowed.text
    assert widened.status_code == 422
    stored = retrieval_repository.list_retrieval_records(claim_id, 'cus_demo')
    assert [record.kind.value for record in stored] == ['claim_history']


def test_retrieval_requires_an_integration_principal_and_a_known_claim(
    retrieval_client: TestClient,
) -> None:
    with retrieval_client as client:
        claim_id = create_claim(client, 'retrieval-auth-claim')
        body = {'claim_id': claim_id, 'policy_reference': 'synthetic-policy-101'}
        missing_auth = client.post(POLICY_SEARCH, json=body)
        claimant_auth = client.post(
            POLICY_SEARCH,
            headers={'Authorization': 'Bearer synthetic-claimant'},
            json=body,
        )
        unknown_claim = client.post(
            POLICY_SEARCH,
            headers=INTEGRATION_AUTH,
            json={'claim_id': 'clm_missing', 'policy_reference': 'synthetic-policy-101'},
        )

    assert missing_auth.status_code == 401
    assert claimant_auth.status_code == 403
    assert unknown_claim.status_code == 404
    assert unknown_claim.json()['error']['code'] == 'RESOURCE_NOT_FOUND'


def test_history_retrieval_reports_outage_and_missing_records_without_inventing_facts(
    retrieval_client: TestClient,
    retrieval_repository: FixtureRepository,
    retrieval_adapter: MockPolicyHistoryAdapter,
) -> None:
    with retrieval_client as client:
        claim_id = create_claim(client, 'history-degraded-claim')
        absent = client.post(
            HISTORY_SEARCH,
            headers=INTEGRATION_AUTH,
            json={'claim_id': claim_id, 'history_reference': 'synthetic-history-absent'},
        )
        retrieval_adapter.set_outage(
            RetrievalUnavailable(
                code='PROVIDER_UNAVAILABLE',
                detail='Traceback: mongodb://user:secret@example.invalid',
            )
        )
        unavailable = client.post(
            HISTORY_SEARCH,
            headers=INTEGRATION_AUTH,
            json={'claim_id': claim_id, 'history_reference': 'synthetic-history-204'},
        )

    assert absent.json()['status'] == 'no_evidence'
    assert absent.json()['facts'] is None
    assert unavailable.json()['status'] == 'unavailable'
    assert unavailable.json()['connection_state'] == 'unavailable'
    assert unavailable.json()['errors'] == [
        {
            'code': 'unavailable',
            'message': 'The claim-history provider is temporarily unavailable.',
            'retryable': True,
        }
    ]
    assert unavailable.json()['facts'] is None
    assert unavailable.json()['source'] is None
    assert unavailable.json()['limitations'] == [
        'The claim-history provider is temporarily unavailable.'
    ]
    assert 'secret' not in unavailable.text
    assert 'mongodb://' not in unavailable.text
    assert retrieval_repository.list_retrieval_records(claim_id, 'cus_demo') == []


def test_connection_state_drift_fails_closed_before_persisting_retrieval(
    retrieval_client: TestClient,
    retrieval_repository: FixtureRepository,
    retrieval_adapter: MockPolicyHistoryAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retrieval_adapter, 'connection_status', lambda: 'pending_confirmation')

    with retrieval_client as client:
        claim_id = create_claim(client, 'policy-connection-drift')
        response = client.post(
            POLICY_SEARCH,
            headers=INTEGRATION_AUTH,
            json={'claim_id': claim_id, 'policy_reference': 'synthetic-policy-101'},
        )

    assert response.status_code == 200
    assert response.json()['status'] == 'unavailable'
    assert response.json()['connection_state'] == 'unavailable'
    assert response.json()['facts'] is None
    assert response.json()['source'] is None
    assert retrieval_repository.list_retrieval_records(claim_id, 'cus_demo') == []


def test_demo_reset_clears_retrieval_state_and_restores_the_provider(
    retrieval_client: TestClient,
    retrieval_adapter: MockPolicyHistoryAdapter,
) -> None:
    retrieval_adapter.set_outage(
        RetrievalUnavailable(code='PROVIDER_UNAVAILABLE', detail='Simulated outage.')
    )

    with retrieval_client as client:
        claim_id = create_claim(client, 'retrieval-reset-claim')
        client.post(
            POLICY_SEARCH,
            headers=INTEGRATION_AUTH,
            json={'claim_id': claim_id, 'policy_reference': 'synthetic-policy-101'},
        )
        reset = client.post(
            '/api/v1/workbench/demo/reset',
            headers={'Authorization': 'Bearer synthetic-staff'},
        )
        readiness = client.get('/health/ready')

    assert reset.status_code == 200
    assert 'mock_retrieval_lookups' in reset.json()['cleared']
    assert readiness.json()['checks']['policy'] == 'using_fixture'
