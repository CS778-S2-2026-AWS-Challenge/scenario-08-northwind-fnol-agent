import datetime
import json

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


def test_history_provider_payload_maps_without_provider_risk_scoring() -> None:
    import backend.adapters.policy_history as policy_history

    envelope = policy_history.ProviderLookupEnvelope(
        provider='synthetic_history_provider',
        provider_reference='provider-history-009',
        retrieved_at=RETRIEVED_AT,
        payload={
            'history_reference': 'HIST-SYNTH-009',
            'incident_type': 'motor',
            'occurred_at': '2025-11-03T02:00:00Z',
            'status': 'closed',
            'outcome': 'settled',
            'provider_risk_score': 0.91,
            'provider_fraud_label': 'do-not-copy',
            'internal_notes': {'reviewer': 'synthetic-only'},
        },
        uncertainty=[
            policy_history.ProviderUncertainty(
                code='HISTORY_MATCH_UNCERTAIN',
                detail='The historical record may be relevant but is not a fraud finding.',
            )
        ],
    )

    record = policy_history.map_history_provider_payload(
        retrieval_id='ret_history_009',
        claim_id='clm_fixture',
        envelope=envelope,
    )

    assert record.kind.value == 'claim_history'
    assert record.facts.history_reference == 'HIST-SYNTH-009'
    assert record.facts.incident_type == 'motor'
    assert record.facts.status == 'closed'
    assert record.facts.outcome == 'settled'
    assert record.uncertainty[0].code == 'HISTORY_MATCH_UNCERTAIN'

    dumped = record.model_dump(mode='json')
    keys = collect_keys(dumped)
    encoded = json.dumps(dumped)
    assert 'provider_risk_score' not in keys
    assert 'provider_fraud_label' not in keys
    assert 'internal_notes' not in keys
    assert 'do-not-copy' not in encoded
    assert 'synthetic-only' not in encoded


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
