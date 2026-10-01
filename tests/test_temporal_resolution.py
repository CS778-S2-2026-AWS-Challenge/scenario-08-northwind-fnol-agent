from datetime import UTC, datetime

import pytest

from backend.domain.temporal_resolution import resolve_reported_time

# 2026-10-01 17:40 in Auckland (NZDT, +13:00).
REPORTED_AT = datetime(2026, 10, 1, 4, 40, tzinfo=UTC)
QUOTE = 'about 20 minutes ago'


@pytest.mark.parametrize(
    'model_value',
    ['2023-10-07T09:20:00Z', '2023-10-11T10:40:00.000Z', 'PT20M', 'current_approx', QUOTE],
)
def test_the_claimants_words_win_over_whatever_the_model_wrote(model_value: str) -> None:
    assert resolve_reported_time(model_value, QUOTE, REPORTED_AT) == '2026-10-01T17:20+13:00'


@pytest.mark.parametrize(
    ('quote', 'expected'),
    [
        ('half an hour ago', '2026-10-01T17:10+13:00'),
        ('a couple of hours ago', '2026-10-01T15:40+13:00'),
        ('just now', '2026-10-01T17:40+13:00'),
        ('this morning around 9', '2026-10-01 morning'),
        ('this morning at 9:15', '2026-10-01T09:15+13:00'),
        ('last night', '2026-09-30 night'),
        ('yesterday evening about 7pm', '2026-09-30T19:00+13:00'),
        ('at 5:20pm', '2026-10-01T17:20+13:00'),
        ('at 11pm', '2026-09-30T23:00+13:00'),
    ],
)
def test_relative_and_clock_wording_resolves_in_new_zealand_time(quote: str, expected: str) -> None:
    assert resolve_reported_time(quote, quote, REPORTED_AT) == expected


def test_a_plausible_model_date_is_kept_and_an_invented_one_is_not() -> None:
    assert resolve_reported_time('2026-09-28', 'on Monday', REPORTED_AT) == '2026-09-28'
    assert resolve_reported_time('2023-10-07', 'on Monday', REPORTED_AT) == 'on Monday'
    assert resolve_reported_time('2026-10-09T10:00:00Z', None, REPORTED_AT) is None


def test_internal_tokens_never_become_stored_values() -> None:
    assert resolve_reported_time('current_approx', None, REPORTED_AT) is None
    assert resolve_reported_time('PT', None, REPORTED_AT) is None
    assert resolve_reported_time('sometime last week', None, REPORTED_AT) == 'sometime last week'
    assert resolve_reported_time({'date': '2026-10-01'}, None, REPORTED_AT) == {
        'date': '2026-10-01'
    }
