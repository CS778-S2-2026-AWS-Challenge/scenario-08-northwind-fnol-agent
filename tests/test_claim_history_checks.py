"""Lodging checks retain unknowns and do not depend on model tool selection."""

from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest

from backend.domain.claim_history import LodgedClaimHistory, history_window_start
from backend.domain.models import WorkingClaim
from backend.repositories.fixture import FixtureRepository
from backend.services.claim_history_checks import check_lodging_history

NOW = datetime(2026, 10, 6, tzinfo=UTC)


def _claim(value: object, *, status: str = 'confirmed') -> WorkingClaim:
    return WorkingClaim.model_validate(
        {
            'claim_id': 'clm_current',
            'customer_id': 'customer-1',
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': 'motor',
            'created_at': NOW,
            'updated_at': NOW,
            'customer_next_step': {
                'status': 'ready',
                'summary': 'Lodge.',
                'responsible_party': 'claimant',
            },
            'form': {
                'incident.occurred_at': {
                    'value': value,
                    'source': 'claimant',
                    'status': status,
                    'needed_for': 'current_action',
                    'updated_at': NOW,
                    'updated_by': {'actor_type': 'claimant', 'actor_id': 'customer-1'},
                }
            },
        }
    )


@pytest.mark.parametrize('count', [0, 1, 2])
def test_lodging_checks_use_complete_count_and_dedicated_duplicate_query(
    count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = FixtureRepository()
    history_query = Mock(
        return_value=LodgedClaimHistory(
            count_past_12_months=count,
            claims=[],
            as_of=NOW,
            window_start=history_window_start(NOW),
        )
    )
    duplicate_query = Mock(return_value=['clm_older'])
    monkeypatch.setattr(repository, 'query_lodged_claim_history', history_query)
    monkeypatch.setattr(repository, 'find_duplicate_lodged_claim_ids', duplicate_query)
    checks = check_lodging_history(
        repository, _claim({'date': '2026-10-05', 'precision': 'partial'}), as_of=NOW
    )
    assert checks.count_past_12_months == count
    assert checks.prior_claims_12m == ('hit' if count >= 2 else 'clear')
    assert checks.possible_duplicate == 'hit'
    assert checks.duplicate_claim_ids == ['clm_older']
    duplicate_query.assert_called_once_with(
        'customer-1',
        'clm_current',
        product_family='motor',
        incident_date=date(2026, 10, 5),
        as_of=NOW,
    )


@pytest.mark.parametrize(
    'incident',
    [None, 'yesterday', {'start': '2026-10-01', 'end': '2026-10-06', 'precision': 'range'}],
)
def test_unknown_date_is_not_a_negative_duplicate_finding(
    incident: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = FixtureRepository()
    duplicate_query = Mock()
    monkeypatch.setattr(repository, 'find_duplicate_lodged_claim_ids', duplicate_query)
    checks = check_lodging_history(repository, _claim(incident), as_of=NOW)
    assert checks.possible_duplicate == 'not_checked'
    assert checks.limitations
    duplicate_query.assert_not_called()


def test_history_dependency_failure_keeps_both_checks_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FixtureRepository()
    monkeypatch.setattr(repository, 'query_lodged_claim_history', Mock(side_effect=TimeoutError))
    monkeypatch.setattr(
        repository, 'find_duplicate_lodged_claim_ids', Mock(side_effect=TimeoutError)
    )
    checks = check_lodging_history(repository, _claim('2026-10-05'), as_of=NOW)
    assert checks.count_past_12_months is None
    assert checks.prior_claims_12m == checks.possible_duplicate == 'not_checked'
    assert len(checks.limitations) == 2


def test_clear_duplicate_check_preserves_not_confirmed_dates() -> None:
    repository = FixtureRepository()
    checks = check_lodging_history(repository, _claim('2026-10-05'), as_of=NOW)
    assert checks.possible_duplicate == 'clear'
    checks = check_lodging_history(repository, _claim('2026-10-05', status='proposed'), as_of=NOW)
    assert checks.possible_duplicate == 'not_checked'
