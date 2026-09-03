from datetime import UTC, datetime
from typing import Any, cast

from fastapi.testclient import TestClient

from backend.adapters.policy_history import (
    ProviderLookupEnvelope,
    ProviderUncertainty,
    map_policy_provider_payload,
)
from backend.domain.models import FraudSignal, WorkflowState
from backend.repositories.fixture import FixtureRepository
from backend.services.retrieval_review import persist_retrieval_record


def _assign_fixture_staff(repository: FixtureRepository, claim_id: str) -> None:
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    repository._claims[claim_id] = claim.model_copy(update={'assignee_id': 'stf_demo'})


def test_staff_review_writeback_uses_current_revision_and_stays_internal(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'day5-staff-revision-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']
    _assign_fixture_staff(repository, claim_id)
    assert isinstance(claim_id, str)
    assert created.json()['claim']['revision'] == 1

    retrieval = map_policy_provider_payload(
        retrieval_id='ret_day5_staff_revision',
        claim_id=claim_id,
        envelope=ProviderLookupEnvelope(
            provider='synthetic-policy-service',
            provider_reference='provider-day5-staff-revision',
            retrieved_at=datetime(2026, 8, 16, 2, 0, tzinfo=UTC),
            payload={
                'policy_reference': 'POL-DAY5-STAFF',
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
    signals = persist_retrieval_record(repository, retrieval, 'cus_demo')
    assert len(signals) == 1
    signal = signals[0]

    claimant_before = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert claimant_before.status_code == 200
    claimant_before_body = cast(dict[str, Any], claimant_before.json())
    assert claimant_before_body['revision'] == 1
    assert 'signals' not in claimant_before_body
    assert 'retrieval_records' not in claimant_before_body
    assert 'signal_decisions' not in claimant_before_body
    assert 'fraud_signal' not in claimant_before_body
    assert 'customer_id' not in claimant_before_body

    staff_before = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )
    assert staff_before.status_code == 200
    projected_signals = cast(
        list[dict[str, Any]],
        client.get(
            f'/api/v1/workbench/claims/{claim_id}/signals', headers=staff_auth_headers
        ).json()['items'],
    )
    projected_signal = next(
        item for item in projected_signals if item.get('signal_id') == signal.signal_id
    )
    assert projected_signal['reason_codes'] == ['POLICY_WORDING_REVIEW_REQUIRED']
    assert projected_signal['source_refs'] == [retrieval.retrieval_id, retrieval.source.reference]
    assert projected_signal['source_evidence'] == [retrieval.model_dump(mode='json')]

    payload: dict[str, Any] = {
        'decision': 'confirmed',
        'reason_codes': ['STAFF_CONFIRMED_REVIEW_REQUIREMENT'],
        'summary': 'A staff reviewer confirmed this wording requires professional review.',
        'evidence_refs': ['staff-note-day5'],
    }
    decided = client.post(
        f'/api/v1/workbench/claims/{claim_id}/signals/{signal.signal_id}/decisions',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'day5-staff-revision-decision',
            'If-Match': '1',
        },
        json=payload,
    )
    assert decided.status_code == 201
    decided_body = cast(dict[str, Any], decided.json())
    assert decided_body['revision'] == 2
    assert decided_body['signal_decision']['actor_id'] == 'stf_demo'
    assert decided_body['signal_decision']['reason_codes'] == payload['reason_codes']
    assert decided_body['signal_decision']['summary'] == payload['summary']
    assert decided_body['signal_decision']['evidence_refs'] == [
        retrieval.retrieval_id,
        retrieval.source.reference,
        'staff-note-day5',
    ]

    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_claim.revision == 2
    assert stored_claim.claim_state.workflow_state is WorkflowState.COLLECTING
    assert stored_claim.claim_state.fraud_signal is FraudSignal.NONE
    assert repository.list_retrieval_records(claim_id, 'cus_demo') == [retrieval]
    assert repository.list_review_signals(claim_id, 'cus_demo') == [signal]
    stored_decisions = repository.list_signal_decisions(claim_id)
    assert len(stored_decisions) == 1
    assert stored_decisions[0].actor_id == 'stf_demo'

    claimant_after = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert claimant_after.status_code == 200
    claimant_after_body = cast(dict[str, Any], claimant_after.json())
    assert claimant_after_body['revision'] == 2
    assert claimant_after_body['workflow_state'] == 'collecting'
    assert 'signals' not in claimant_after_body
    assert 'retrieval_records' not in claimant_after_body
    assert 'signal_decisions' not in claimant_after_body
    assert 'fraud_signal' not in claimant_after_body
    assert payload['summary'] not in str(claimant_after_body)
    assert 'STAFF_CONFIRMED_REVIEW_REQUIREMENT' not in str(claimant_after_body)

    stale = client.post(
        f'/api/v1/workbench/claims/{claim_id}/signals/{signal.signal_id}/decisions',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'day5-staff-revision-stale',
            'If-Match': '1',
        },
        json=payload,
    )
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert stale.json()['error']['current_revision'] == 2
    assert len(repository.list_signal_decisions(claim_id)) == 1
    final_claim = repository.get_claim(claim_id, 'cus_demo')
    assert final_claim is not None
    assert final_claim.revision == 2
