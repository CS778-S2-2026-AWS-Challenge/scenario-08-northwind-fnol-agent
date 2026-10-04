from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.adapters.policy_history import (
    ProviderLookupEnvelope,
    ProviderUncertainty,
    map_history_provider_payload,
    map_policy_provider_payload,
)
from backend.domain.models import FraudSignal, WorkflowState
from backend.repositories.fixture import FixtureRepository
from backend.services.retrieval_review import persist_retrieval_record

RAW_PROVIDER_ONLY_KEYS = {
    'fraud_label',
    'fraud_finding',
    'risk_score',
    'policy_conclusion',
    'provider_internal_note',
}


def _create_claim(
    client: TestClient,
    auth_headers: dict[str, str],
) -> str:
    response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'demo-policy-review-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    claim_id = response.json()['claim']['claim_id']
    assert isinstance(claim_id, str)
    return claim_id


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        dict_keys = set(value)
        for child in value.values():
            dict_keys.update(_keys(child))
        return dict_keys
    if isinstance(value, list):
        list_keys: set[str] = set()
        for child in value:
            list_keys.update(_keys(child))
        return list_keys
    return set()


def _signal(body: dict[str, Any], signal_id: str) -> dict[str, Any]:
    signals = cast(list[dict[str, Any]], body['items'])
    return next(item for item in signals if item.get('signal_id') == signal_id)


def _assign_fixture_staff(repository: FixtureRepository, claim_id: str) -> None:
    """Model a Claim already accepted by the synthetic staff principal."""
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    repository._claims[claim_id] = claim.model_copy(update={'assignee_id': 'stf_demo'})


def test_demo_policy_uncertainty_remains_sourced_through_staff_writeback(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = _create_claim(client, auth_headers)
    _assign_fixture_staff(repository, claim_id)
    initial_claim = repository.get_claim(claim_id, 'cus_demo')
    assert initial_claim is not None
    assert initial_claim.revision == 1

    retrieval = map_policy_provider_payload(
        retrieval_id='ret_demo_policy_review',
        claim_id=claim_id,
        envelope=ProviderLookupEnvelope(
            provider='synthetic-policy-service',
            provider_reference='provider-policy-demo-001',
            retrieved_at=datetime(2026, 8, 21, 0, 15, tzinfo=UTC),
            payload={
                'policy_reference': 'POL-DEMO-001',
                'product': 'Comprehensive Motor',
                'status': 'active',
                'excess_amount': 500.0,
                'currency': 'NZD',
                'coverage_sections': ['collision'],
                'fraud_label': 'high-risk',
                'fraud_finding': 'provider-says-fraud',
                'risk_score': 0.99,
                'policy_conclusion': 'automatically-covered',
                'provider_internal_note': 'do not expose this transport-only field',
            },
            uncertainty=[
                ProviderUncertainty(
                    code='POLICY_WORDING_REVIEW_REQUIRED',
                    detail='A claims professional must confirm which policy wording applies.',
                )
            ],
        ),
    )
    review_signals = persist_retrieval_record(repository, retrieval, 'cus_demo')
    assert len(review_signals) == 1
    review_signal = review_signals[0]

    persisted_claim = repository.get_claim(claim_id, 'cus_demo')
    assert persisted_claim is not None
    assert persisted_claim.revision == 1
    assert persisted_claim.claim_state.fraud_signal is FraudSignal.NONE
    assert persisted_claim.claim_state.workflow_state is WorkflowState.COLLECTING
    assert review_signal.source_refs == [
        retrieval.retrieval_id,
        retrieval.source.reference,
    ]
    assert review_signal.reason_codes == ['POLICY_WORDING_REVIEW_REQUIRED']

    workbench = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )
    assert workbench.status_code == 200
    workbench_body = cast(dict[str, Any], workbench.json())
    signals_response = client.get(
        f'/api/v1/workbench/claims/{claim_id}/signals', headers=staff_auth_headers
    )
    assert signals_response.status_code == 200
    projected_signal = _signal(signals_response.json(), review_signal.signal_id)
    assert projected_signal['source_refs'] == review_signal.source_refs
    assert projected_signal['reason_codes'] == review_signal.reason_codes
    assert projected_signal['source_evidence'] == [retrieval.model_dump(mode='json')]
    assert RAW_PROVIDER_ONLY_KEYS.isdisjoint(_keys(projected_signal))
    assert RAW_PROVIDER_ONLY_KEYS.isdisjoint(_keys(workbench_body))

    staff_summary = 'The policy source was reviewed; professional interpretation is still required.'
    decision = client.post(
        f'/api/v1/workbench/claims/{claim_id}/signals/{review_signal.signal_id}/decisions',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'demo-policy-review-decision',
            'If-Match': '1',
        },
        json={
            'decision': 'confirmed',
            'reason_codes': ['STAFF_CONFIRMED_INTERPRETATION_REQUIRED'],
            'summary': staff_summary,
            'evidence_refs': review_signal.source_refs,
        },
    )
    assert decision.status_code == 201
    decision_body = decision.json()
    assert decision_body['revision'] == 2
    stored_decision = decision_body['signal_decision']
    assert stored_decision['actor_id'] == 'stf_demo'
    assert stored_decision['reason_codes'] == ['STAFF_CONFIRMED_INTERPRETATION_REQUIRED']
    assert stored_decision['summary'] == staff_summary
    assert stored_decision['evidence_refs'] == review_signal.source_refs

    final_claim = repository.get_claim(claim_id, 'cus_demo')
    assert final_claim is not None
    assert final_claim.revision == 2
    assert final_claim.claim_state.fraud_signal is FraudSignal.NONE
    assert final_claim.claim_state.workflow_state is WorkflowState.COLLECTING
    assert repository.list_retrieval_records(claim_id, 'cus_demo') == [retrieval]
    assert repository.list_review_signals(claim_id, 'cus_demo') == [review_signal]


def test_demo_adapter_fails_closed_without_required_source_facts() -> None:
    policy_envelope = ProviderLookupEnvelope(
        provider='synthetic-policy-service',
        provider_reference='provider-policy-missing-reference',
        retrieved_at=datetime(2026, 8, 21, 0, 20, tzinfo=UTC),
        payload={
            'status': 'active',
            'fraud_label': 'provider-only-label',
            'policy_conclusion': 'provider-only-conclusion',
        },
    )
    with pytest.raises(ValidationError):
        map_policy_provider_payload(
            retrieval_id='ret_missing_policy_reference',
            claim_id='clm_demo',
            envelope=policy_envelope,
        )

    history_envelope = ProviderLookupEnvelope(
        provider='synthetic-history-service',
        provider_reference='provider-history-missing-reference',
        retrieved_at=datetime(2026, 8, 21, 0, 25, tzinfo=UTC),
        payload={
            'status': 'closed',
            'fraud_label': 'provider-only-label',
            'risk_score': 0.95,
        },
    )
    with pytest.raises(ValidationError):
        map_history_provider_payload(
            retrieval_id='ret_missing_history_reference',
            claim_id='clm_demo',
            envelope=history_envelope,
        )
