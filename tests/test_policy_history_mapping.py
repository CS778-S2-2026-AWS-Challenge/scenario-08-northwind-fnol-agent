import datetime
import json

import pytest

from backend.domain.claim_history import LodgedClaimHistory
from backend.domain.retrieval import ClaimHistorySearchRequest

RETRIEVED_AT = datetime.datetime(2026, 8, 17, 0, 15, tzinfo=datetime.UTC)


def collect_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys: set[str] = set()
        for key, nested in value.items():
            keys.add(str(key))
            keys.update(collect_keys(nested))
        return keys
    if isinstance(value, list):
        keys = set()
        for item in value:
            keys.update(collect_keys(item))
        return keys
    return set()


def test_policy_provider_payload_maps_to_provider_neutral_domain_record() -> None:
    import backend.adapters.policy_history as policy_history

    envelope = policy_history.ProviderLookupEnvelope(
        provider='synthetic_policy_provider',
        provider_reference='provider-policy-001',
        retrieved_at=RETRIEVED_AT,
        payload={
            'policy_reference': 'POL-SYNTH-001',
            'product': 'motor',
            'status': 'active',
            'effective_from': '2026-01-01T00:00:00Z',
            'effective_to': '2026-12-31T23:59:59Z',
            'excess_amount': 500,
            'currency': 'NZD',
            'coverage_sections': ['vehicle_damage', 'third_party_property'],
            'internal_policy_note': 'provider-only note',
            'aws_object_key': 'must-not-cross-domain-boundary',
        },
        uncertainty=[
            policy_history.ProviderUncertainty(
                code='POLICY_WORDING_REVIEW',
                detail='A policy wording question requires professional interpretation.',
            )
        ],
    )

    record = policy_history.map_policy_provider_payload(
        retrieval_id='ret_policy_001',
        claim_id='clm_fixture',
        envelope=envelope,
    )

    assert record.kind.value == 'policy'
    assert record.claim_id == 'clm_fixture'
    assert record.source.system == 'synthetic_policy_provider'
    assert record.source.reference == 'provider-policy-001'
    assert record.source.retrieved_at == RETRIEVED_AT
    assert record.facts.policy_reference == 'POL-SYNTH-001'
    assert record.facts.excess_amount == 500
    assert record.facts.currency == 'NZD'
    assert record.uncertainty[0].code == 'POLICY_WORDING_REVIEW'

    dumped = record.model_dump(mode='json')
    keys = collect_keys(dumped)
    encoded = json.dumps(dumped)
    assert 'payload' not in keys
    assert 'internal_policy_note' not in keys
    assert 'aws_object_key' not in keys
    assert 'provider-only note' not in encoded
    assert 'must-not-cross-domain-boundary' not in encoded


def test_history_consultation_maps_bounded_projection_without_provider_scoring() -> None:
    from backend.adapters.policy_history import ProviderLookupEnvelope, map_history_provider_payload

    history = LodgedClaimHistory(
        count_past_12_months=0,
        claims=[],
        as_of=RETRIEVED_AT,
        window_start=RETRIEVED_AT.replace(year=2025),
    )
    envelope = ProviderLookupEnvelope(
        provider='repository_history',
        provider_reference='current',
        retrieved_at=RETRIEVED_AT,
        history=history,
        payload={'provider_risk_score': 0.91, 'provider_fraud_label': 'do-not-copy'},
    )
    record = map_history_provider_payload(
        retrieval_id='his_consultation',
        claim_id='current',
        envelope=envelope,
        query=ClaimHistorySearchRequest(claim_id='current', limit=3),
    )
    assert record.history == history
    assert record.query is not None and record.query.limit == 3
    assert record.facts is None
    assert record.source.retrieved_at == RETRIEVED_AT
    assert 'do-not-copy' not in record.model_dump_json()
    with pytest.raises(ValueError, match='scoped history'):
        map_history_provider_payload(
            retrieval_id='his_foreign',
            claim_id='other',
            envelope=envelope,
            query=ClaimHistorySearchRequest(claim_id='current'),
        )


def test_mapping_rejects_provider_payload_without_required_domain_reference() -> None:
    import backend.adapters.policy_history as policy_history

    envelope = policy_history.ProviderLookupEnvelope(
        provider='synthetic_policy_provider',
        provider_reference='provider-policy-invalid',
        retrieved_at=RETRIEVED_AT,
        payload={'status': 'active'},
    )

    try:
        policy_history.map_policy_provider_payload(
            retrieval_id='ret_policy_invalid',
            claim_id='clm_fixture',
            envelope=envelope,
        )
    except ValueError:
        return
    raise AssertionError('Mapping must reject a provider payload without a policy reference.')


def test_issue_108_does_not_expand_claimant_api_with_provider_records() -> None:
    from backend.domain.models import ClaimantClaim

    public_fields = set(ClaimantClaim.model_fields)

    assert 'provider_payload' not in public_fields
    assert 'policy_retrievals' not in public_fields
    assert 'history_retrievals' not in public_fields


def test_repository_history_adapter_uses_lodged_seed_and_explicit_missing_claim() -> None:
    import pytest

    from backend.adapters.policy_history import RepositoryClaimHistoryAdapter
    from backend.domain.retrieval import ClaimHistorySearchRequest, PolicySearchRequest
    from backend.repositories.fixture import FixtureRepository
    from backend.services.business_seed import (
        BUSINESS_SEED_PATH,
        load_business_seed,
        provision_business_claims,
    )

    repository = FixtureRepository()
    seed = load_business_seed(BUSINESS_SEED_PATH)
    provision_business_claims(repository, seed)
    history_claim = repository.get_claim_internal('clm_6d9231ab40e85fc7')
    assert history_claim is not None
    current = history_claim.model_copy(update={'claim_id': 'current', 'active_session_id': None})
    repository._claims[current.claim_id] = current
    adapter = RepositoryClaimHistoryAdapter(repository)
    envelope = adapter.search_claim_history(ClaimHistorySearchRequest(claim_id='current'))
    assert envelope.history is not None
    assert envelope.history.claims[0].claim_id == history_claim.claim_id
    assert envelope.history.claims[0].occurred_at != history_claim.created_at
    assert envelope.payload == {}
    missing = adapter.search_claim_history(
        ClaimHistorySearchRequest(claim_id='current', history_reference='not-owned')
    )
    assert missing.history is not None and missing.history.claims == []
    with pytest.raises(LookupError):
        adapter.search_claim_history(ClaimHistorySearchRequest(claim_id='missing'))
    with pytest.raises(LookupError):
        adapter.search_policy(PolicySearchRequest(claim_id='current', policy_reference='ignored'))
