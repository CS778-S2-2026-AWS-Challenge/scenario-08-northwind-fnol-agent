from datetime import UTC, datetime
from typing import Any, cast

from fastapi.testclient import TestClient

from backend.adapters.policy_history import (
    ProviderLookupEnvelope,
    ProviderUncertainty,
    map_policy_provider_payload,
)
from backend.domain.models import FraudSignal, WorkflowState
from backend.domain.retrieval import PolicyRetrievalRecord, ReviewSignalRecord
from backend.repositories.fixture import FixtureRepository
from backend.services.retrieval_review import persist_retrieval_record


def seed_policy_review_signal(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    *,
    key_prefix: str,
) -> tuple[str, PolicyRetrievalRecord, ReviewSignalRecord]:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': f'{key_prefix}-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']
    assert isinstance(claim_id, str)

    record = map_policy_provider_payload(
        retrieval_id=f'ret_{key_prefix}',
        claim_id=claim_id,
        envelope=ProviderLookupEnvelope(
            provider='synthetic-policy-service',
            provider_reference=f'provider-{key_prefix}',
            retrieved_at=datetime(2026, 8, 16, 2, 0, tzinfo=UTC),
            payload={
                'policy_reference': f'POL-{key_prefix}',
                'status': 'active',
                'product': 'Comprehensive Motor',
            },
            uncertainty=[
                ProviderUncertainty(
                    code='POLICY_WORDING_REVIEW_REQUIRED',
                    detail='A claims professional must confirm the applicable wording.',
                )
            ],
        ),
    )
    signals = persist_retrieval_record(repository, record, 'cus_demo')
    assert len(signals) == 1
    return claim_id, record, signals[0]


def signal_from_detail(body: dict[str, Any], signal_id: str) -> dict[str, Any]:
    signals = cast(list[dict[str, Any]], body['signals'])
    return next(signal for signal in signals if signal.get('signal_id') == signal_id)


def test_workbench_review_decision_preserves_actor_reason_revision_and_source_evidence(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, record, signal = seed_policy_review_signal(
        client,
        auth_headers,
        repository,
        key_prefix='review-writeback',
    )
    before_claim = repository.get_claim(claim_id, 'cus_demo')
    before_records = repository.list_retrieval_records(claim_id, 'cus_demo')
    before_signals = repository.list_review_signals(claim_id, 'cus_demo')
    assert before_claim is not None
    assert before_claim.revision == 1
    assert before_records == [record]
    assert before_signals == [signal]

    detail = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )
    assert detail.status_code == 200
    projected = signal_from_detail(detail.json(), signal.signal_id)
    assert projected['review_type'] == 'professional_review'
    assert projected['reason_codes'] == ['POLICY_WORDING_REVIEW_REQUIRED']
    assert projected['source_refs'] == [record.retrieval_id, record.source.reference]
    assert projected['source_evidence'] == [record.model_dump(mode='json')]

    payload = {
        'decision': 'confirmed',
        'reason_codes': ['STAFF_CONFIRMED_REVIEW_REQUIREMENT'],
        'summary': (
            'The source was reviewed and the ambiguity is recorded for professional handling.'
        ),
        'evidence_refs': ['staff-note-001'],
    }
    decided = client.post(
        f'/api/v1/workbench/claims/{claim_id}/signals/{signal.signal_id}/decisions',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'review-writeback-decision',
            'If-Match': '1',
        },
        json=payload,
    )
    assert decided.status_code == 201
    body = decided.json()
    assert body['revision'] == 2
    decision = body['signal_decision']
    assert decision['signal_id'] == signal.signal_id
    assert decision['actor_id'] == 'stf_demo'
    assert decision['reason_codes'] == ['STAFF_CONFIRMED_REVIEW_REQUIREMENT']
    assert decision['summary'] == payload['summary']
    assert decision['evidence_refs'] == [
        record.retrieval_id,
        record.source.reference,
        'staff-note-001',
    ]

    after_claim = repository.get_claim(claim_id, 'cus_demo')
    assert after_claim is not None
    assert after_claim.revision == 2
    assert after_claim.claim_state.workflow_state is WorkflowState.COLLECTING
    assert after_claim.claim_state.fraud_signal is FraudSignal.NONE
    assert repository.list_retrieval_records(claim_id, 'cus_demo') == before_records
    assert repository.list_review_signals(claim_id, 'cus_demo') == before_signals

    stored_decisions = repository.list_signal_decisions(claim_id)
    assert len(stored_decisions) == 1
    assert stored_decisions[0].actor_id == 'stf_demo'
    assert stored_decisions[0].reason_codes == ['STAFF_CONFIRMED_REVIEW_REQUIREMENT']
    assert stored_decisions[0].evidence_refs[:2] == signal.source_refs

    refreshed = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )
    assert refreshed.status_code == 200
    refreshed_signal = signal_from_detail(refreshed.json(), signal.signal_id)
    assert refreshed_signal['source_evidence'] == [record.model_dump(mode='json')]
    assert len(refreshed_signal['decisions']) == 1
    assert refreshed_signal['decisions'][0]['actor_id'] == 'stf_demo'
    assert refreshed_signal['decisions'][0]['reason_codes'] == [
        'STAFF_CONFIRMED_REVIEW_REQUIREMENT'
    ]


def test_review_decision_is_idempotent_and_stale_revision_is_rejected(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, record, signal = seed_policy_review_signal(
        client,
        auth_headers,
        repository,
        key_prefix='review-retry',
    )
    payload = {
        'decision': 'dismissed',
        'reason_codes': ['STAFF_REVIEWED_SOURCE'],
        'summary': 'The source was reviewed and this signal does not require further action.',
        'evidence_refs': [],
    }
    headers = {
        **staff_auth_headers,
        'Idempotency-Key': 'review-retry-decision',
        'If-Match': '1',
    }
    first = client.post(
        f'/api/v1/workbench/claims/{claim_id}/signals/{signal.signal_id}/decisions',
        headers=headers,
        json=payload,
    )
    assert first.status_code == 201
    assert first.json()['revision'] == 2
    assert first.json()['signal_decision']['evidence_refs'] == [
        record.retrieval_id,
        record.source.reference,
    ]

    replay = client.post(
        f'/api/v1/workbench/claims/{claim_id}/signals/{signal.signal_id}/decisions',
        headers=headers,
        json=payload,
    )
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert len(repository.list_signal_decisions(claim_id)) == 1
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    assert claim.revision == 2

    reused_key = client.post(
        f'/api/v1/workbench/claims/{claim_id}/signals/{signal.signal_id}/decisions',
        headers=headers,
        json={**payload, 'summary': 'Different decision content under the same retry key.'},
    )
    assert reused_key.status_code == 409
    assert reused_key.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'

    stale = client.post(
        f'/api/v1/workbench/claims/{claim_id}/signals/{signal.signal_id}/decisions',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'review-retry-stale',
            'If-Match': '1',
        },
        json=payload,
    )
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert stale.json()['error']['current_revision'] == 2
    assert repository.list_retrieval_records(claim_id, 'cus_demo') == [record]
