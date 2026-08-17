from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from backend.adapters.policy_history import (
    ProviderLookupEnvelope,
    ProviderUncertainty,
    map_history_provider_payload,
    map_policy_provider_payload,
)
from backend.domain.models import FraudSignal, WorkflowState
from backend.domain.retrieval import ReviewSignalRecord
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyConflict
from backend.services.retrieval_review import persist_retrieval_record


def create_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    *,
    key: str,
) -> str:
    response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    claim_id = response.json()['claim']['claim_id']
    assert isinstance(claim_id, str)
    return claim_id


def test_policy_retrieval_persists_provenance_and_review_only_signal(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = create_claim(client, auth_headers, key='retrieval-policy-claim')
    before = repository.get_claim(claim_id, 'cus_demo')
    assert before is not None

    record = map_policy_provider_payload(
        retrieval_id='ret_policy_001',
        claim_id=claim_id,
        envelope=ProviderLookupEnvelope(
            provider='synthetic-policy-service',
            provider_reference='pol-provider-001',
            retrieved_at=datetime(2026, 8, 16, 1, 0, tzinfo=UTC),
            payload={
                'policy_reference': 'POL-001',
                'product': 'Comprehensive Motor',
                'status': 'active',
                'excess_amount': 500.0,
                'currency': 'NZD',
                'coverage_sections': ['collision'],
                'fraud_finding': 'high_risk',
                'risk_score': 0.99,
            },
            uncertainty=[
                ProviderUncertainty(
                    code='COVERAGE_WORDING_AMBIGUOUS',
                    detail='The provider result does not resolve which collision wording applies.',
                ),
                ProviderUncertainty(
                    code='EXCESS_CONFIRMATION_REQUIRED',
                    detail='The excess should be confirmed by a claims professional.',
                ),
            ],
        ),
    )

    signals = persist_retrieval_record(repository, record, 'cus_demo')

    stored_records = repository.list_retrieval_records(claim_id, 'cus_demo')
    stored_signals = repository.list_review_signals(claim_id, 'cus_demo')
    after = repository.get_claim(claim_id, 'cus_demo')

    assert stored_records == [record]
    assert stored_signals == signals
    assert len(signals) == 1
    signal = signals[0]
    assert signal.review_type == 'professional_review'
    assert signal.code == 'POLICY_RETRIEVAL_UNCERTAINTY'
    assert signal.source_refs == ['ret_policy_001', 'pol-provider-001']
    assert signal.reason_codes == [
        'COVERAGE_WORDING_AMBIGUOUS',
        'EXCESS_CONFIRMATION_REQUIRED',
    ]
    assert 'fraud' not in signal.summary.lower()

    assert after is not None
    assert after.revision == before.revision
    assert after.claim_state == before.claim_state
    assert after.claim_state.fraud_signal is FraudSignal.NONE
    assert after.claim_state.workflow_state is WorkflowState.COLLECTING


def test_provider_risk_fields_do_not_create_a_review_signal_without_domain_uncertainty(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = create_claim(client, auth_headers, key='retrieval-no-signal-claim')
    record = map_history_provider_payload(
        retrieval_id='ret_history_clean',
        claim_id=claim_id,
        envelope=ProviderLookupEnvelope(
            provider='synthetic-history-service',
            provider_reference='hist-provider-clean',
            retrieved_at=datetime(2026, 8, 16, 1, 5, tzinfo=UTC),
            payload={
                'history_reference': 'HIST-001',
                'incident_type': 'motor',
                'status': 'closed',
                'outcome': 'paid',
                'fraud_label': 'provider-only-label',
                'risk_score': 0.98,
            },
        ),
    )

    signals = persist_retrieval_record(repository, record, 'cus_demo')

    assert signals == []
    assert repository.list_retrieval_records(claim_id, 'cus_demo') == [record]
    assert repository.list_review_signals(claim_id, 'cus_demo') == []
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    assert claim.revision == 1
    assert claim.claim_state.fraud_signal is FraudSignal.NONE
    assert claim.claim_state.workflow_state is WorkflowState.COLLECTING


def test_history_uncertainty_maps_to_sourced_reasoned_professional_review_signal(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = create_claim(client, auth_headers, key='retrieval-history-claim')
    record = map_history_provider_payload(
        retrieval_id='ret_history_uncertain',
        claim_id=claim_id,
        envelope=ProviderLookupEnvelope(
            provider='synthetic-history-service',
            provider_reference='hist-provider-uncertain',
            retrieved_at=datetime(2026, 8, 16, 1, 10, tzinfo=UTC),
            payload={
                'history_reference': 'HIST-002',
                'incident_type': 'motor',
                'status': 'closed',
                'outcome': 'withdrawn',
            },
            uncertainty=[
                ProviderUncertainty(
                    code='HISTORY_MATCH_UNCERTAIN',
                    detail='The returned history record may refer to a different incident.',
                )
            ],
        ),
    )

    signals = persist_retrieval_record(repository, record, 'cus_demo')

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_id == 'sig_ret_history_uncertain'
    assert signal.code == 'CLAIM_HISTORY_RETRIEVAL_UNCERTAINTY'
    assert signal.source_refs == ['ret_history_uncertain', 'hist-provider-uncertain']
    assert signal.reason_codes == ['HISTORY_MATCH_UNCERTAIN']
    assert repository.list_review_signals(claim_id, 'cus_demo') == [signal]


def test_retrieval_bundle_is_idempotent_but_rejects_conflicting_rewrites(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = create_claim(client, auth_headers, key='retrieval-idempotency-claim')
    envelope = ProviderLookupEnvelope(
        provider='synthetic-policy-service',
        provider_reference='pol-provider-idem',
        retrieved_at=datetime(2026, 8, 16, 1, 15, tzinfo=UTC),
        payload={'policy_reference': 'POL-IDEM', 'status': 'active'},
        uncertainty=[
            ProviderUncertainty(
                code='POLICY_STATUS_CONFIRMATION_REQUIRED',
                detail='A professional should confirm the status before relying on it.',
            )
        ],
    )
    record = map_policy_provider_payload(
        retrieval_id='ret_policy_idem',
        claim_id=claim_id,
        envelope=envelope,
    )

    first = persist_retrieval_record(repository, record, 'cus_demo')
    second = persist_retrieval_record(repository, record, 'cus_demo')
    assert second == first
    assert repository.list_retrieval_records(claim_id, 'cus_demo') == [record]
    assert repository.list_review_signals(claim_id, 'cus_demo') == first

    conflicting = record.model_copy(
        update={'facts': record.facts.model_copy(update={'status': 'cancelled'})}
    )
    with pytest.raises(IdempotencyConflict):
        persist_retrieval_record(repository, conflicting, 'cus_demo')

    assert repository.list_retrieval_records(claim_id, 'cus_demo') == [record]
    assert repository.list_review_signals(claim_id, 'cus_demo') == first


def test_retrieval_bundle_enforces_claim_ownership_and_signal_provenance(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = create_claim(client, auth_headers, key='retrieval-provenance-claim')
    record = map_policy_provider_payload(
        retrieval_id='ret_policy_provenance',
        claim_id=claim_id,
        envelope=ProviderLookupEnvelope(
            provider='synthetic-policy-service',
            provider_reference='pol-provider-provenance',
            retrieved_at=datetime(2026, 8, 16, 1, 20, tzinfo=UTC),
            payload={'policy_reference': 'POL-PROV', 'status': 'active'},
        ),
    )

    with pytest.raises(KeyError):
        persist_retrieval_record(repository, record, 'cus_other')

    invalid_signal = ReviewSignalRecord(
        signal_id='sig_invalid_provenance',
        claim_id=claim_id,
        code='POLICY_RETRIEVAL_UNCERTAINTY',
        source_refs=['different_retrieval'],
        reason_codes=['SOURCE_REQUIRED'],
        summary='This signal deliberately points at the wrong retrieval record.',
        created_at=record.source.retrieved_at,
    )
    with pytest.raises(KeyError):
        repository.save_retrieval_bundle(record, [invalid_signal], 'cus_demo')

    assert repository.list_retrieval_records(claim_id, 'cus_other') == []
    assert repository.list_review_signals(claim_id, 'cus_other') == []
    assert repository.list_retrieval_records(claim_id, 'cus_demo') == []
    assert repository.list_review_signals(claim_id, 'cus_demo') == []


def test_demo_reset_clears_retrieval_and_review_signal_stores(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id = create_claim(client, auth_headers, key='retrieval-reset-claim')
    record = map_policy_provider_payload(
        retrieval_id='ret_policy_reset',
        claim_id=claim_id,
        envelope=ProviderLookupEnvelope(
            provider='synthetic-policy-service',
            provider_reference='pol-provider-reset',
            retrieved_at=datetime(2026, 8, 16, 1, 25, tzinfo=UTC),
            payload={'policy_reference': 'POL-RESET', 'status': 'active'},
            uncertainty=[
                ProviderUncertainty(
                    code='POLICY_RESET_REVIEW_REQUIRED',
                    detail='Synthetic uncertainty used to verify demo reset ownership.',
                )
            ],
        ),
    )
    signals = persist_retrieval_record(repository, record, 'cus_demo')
    assert len(signals) == 1

    first = repository.reset_demo_state()
    assert first['retrievals'] == 1
    assert first['review_signals'] == 1

    second = repository.reset_demo_state()
    assert second['retrievals'] == 0
    assert second['review_signals'] == 0
