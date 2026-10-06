from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.domain.claim_history import lodged_claim_summary
from backend.domain.models import TemporalFactValue
from backend.repositories.fixture import FixtureRepository
from backend.services.business_seed import (
    BUSINESS_SEED_PATH,
    BusinessSeed,
    build_seed_claim,
    load_business_seed,
    provision_business_claims,
    provision_business_policies,
)


@pytest.mark.parametrize(
    'invalid_case',
    [
        'version',
        'owner',
        'duplicate',
        'period',
        'submission',
        'demo_owner',
        'demo_duplicate',
        'demo_field',
        'demo_timezone',
        'demo_contents',
    ],
)
def test_business_seed_rejects_invalid_contract(invalid_case: str) -> None:
    payload = load_business_seed(BUSINESS_SEED_PATH).model_dump(mode='json')
    if invalid_case == 'version':
        payload['version'] = 'unsupported'
    elif invalid_case == 'owner':
        payload['policies_in_system'][0]['customer_id'] = 'missing'
    elif invalid_case == 'duplicate':
        payload['customers'].append(payload['customers'][0])
    elif invalid_case == 'period':
        payload['policies_in_system'][0]['effective_to'] = '2020-01-01'
    elif invalid_case == 'submission':
        payload['prior_submitted_claims'][0]['submitted_date'] = '2020-01-01'
    elif invalid_case == 'demo_owner':
        payload['demo_cases'][0]['customer_id'] = 'missing'
    elif invalid_case == 'demo_duplicate':
        payload['demo_cases'].append(payload['demo_cases'][0])
    elif invalid_case == 'demo_field':
        payload['demo_cases'][0]['fields']['private.fake_field'] = {
            'value': 'unsupported',
            'status': 'confirmed',
        }
    elif invalid_case == 'demo_timezone':
        payload['demo_cases'][0]['recorded_at'] = '2026-09-08T01:00:00'
    else:
        payload['demo_cases'][0]['contents_descriptions'] = ['Unrelated motor item']
    with pytest.raises(ValidationError):
        BusinessSeed.model_validate(payload)


def test_seed_claim_preserves_incident_precision_and_can_be_queried_as_history() -> None:
    seed = load_business_seed(BUSINESS_SEED_PATH)
    record = seed.prior_submitted_claims[0]
    claim, session = build_seed_claim(record)
    summary = lodged_claim_summary(claim)
    assert isinstance(summary.occurred_at, TemporalFactValue)
    assert summary.occurred_at.date == record.incident_date.isoformat()
    assert summary.occurred_at.time is None
    assert summary.lodged_at == datetime(2026, 9, 4, tzinfo=UTC)
    assert session.customer_id == claim.customer_id == record.customer_id

    repository = FixtureRepository()
    provision_business_claims(repository, seed)
    history = repository.query_lodged_claim_history(
        record.customer_id, 'current', limit=10, as_of=datetime(2026, 10, 6, tzinfo=UTC)
    )
    assert [entry.claim_id for entry in history.claims] == [record.claim_id]
    assert history.count_past_12_months == 1


def test_seed_claim_repeated_provisioning_preserves_user_changes() -> None:
    seed = load_business_seed(BUSINESS_SEED_PATH)
    repository = FixtureRepository()
    provision_business_claims(repository, seed)
    record = seed.prior_submitted_claims[0]
    existing = repository.get_claim_internal(record.claim_id)
    assert existing is not None
    existing.locale = 'mi-NZ'
    existing.revision += 1
    repository.save_claim(existing, existing.revision - 1)
    provision_business_claims(repository, seed)
    saved = repository.get_claim_internal(record.claim_id)
    assert saved == existing


def test_seed_claim_rejects_another_owner_without_overwriting() -> None:
    seed = load_business_seed(BUSINESS_SEED_PATH)
    repository = FixtureRepository()
    provision_business_claims(repository, seed)
    record = seed.prior_submitted_claims[0]
    conflicting = seed.model_copy(deep=True)
    conflicting.prior_submitted_claims[0].customer_id = 'cus_2b67e9d14a3c508f'
    with pytest.raises(ValueError, match='another customer'):
        provision_business_claims(repository, conflicting)
    saved = repository.get_claim_internal(record.claim_id)
    assert saved is not None
    assert saved.customer_id == record.customer_id


def test_seed_policies_keep_owner_and_uncertainty_without_invented_terms() -> None:
    seed = load_business_seed(BUSINESS_SEED_PATH)
    repository = FixtureRepository()
    provision_business_policies(repository, seed)
    for policy in seed.policies_in_system:
        saved = repository.get_seed_policy(policy.customer_id, policy.policy_number)
        assert saved is not None
        assert saved.facts == policy.policy_facts()
        assert [entry.code for entry in saved.uncertainty] == policy.uncertainty
        assert repository.get_seed_policy('cus_2b67e9d14a3c508f', policy.policy_number) is None
