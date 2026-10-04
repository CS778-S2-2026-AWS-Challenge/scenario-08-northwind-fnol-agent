from datetime import UTC, datetime

import pytest

from backend.domain.temporal_resolution import check_reported_time

# 2026-10-01 17:40 in Auckland (NZDT, +13:00).
REPORTED_AT = datetime(2026, 10, 1, 4, 40, tzinfo=UTC)
QUOTE = 'about 20 minutes ago'


def test_a_time_the_model_worked_out_is_stored_in_new_zealand_form() -> None:
    assert check_reported_time('2026-10-01T17:20+13:00', QUOTE, REPORTED_AT) == (
        '2026-10-01T17:20+13:00'
    )
    assert check_reported_time('2026-10-01T04:20:00Z', QUOTE, REPORTED_AT) == (
        '2026-10-01T17:20+13:00'
    )
    assert check_reported_time('2026-09-30 night', 'last night', REPORTED_AT) == '2026-09-30 night'
    assert check_reported_time('2026-09-28', 'on Monday', REPORTED_AT) == '2026-09-28'


def test_an_implausible_or_malformed_value_keeps_the_claimants_words() -> None:
    assert check_reported_time('2023-10-07T09:20:00Z', QUOTE, REPORTED_AT) == QUOTE
    assert check_reported_time('2026-10-09T10:00+13:00', 'next week', REPORTED_AT) == 'next week'
    assert check_reported_time('PT20M', QUOTE, REPORTED_AT) == QUOTE


def test_a_value_with_no_claimant_words_is_kept_only_when_it_reads_as_words() -> None:
    assert check_reported_time('current_approx', None, REPORTED_AT) is None
    assert check_reported_time('PT20M', None, REPORTED_AT) is None
    assert check_reported_time('2023-10-07', None, REPORTED_AT) is None
    assert check_reported_time('sometime last week', None, REPORTED_AT) == 'sometime last week'
    assert check_reported_time({'date': '2026-10-01'}, None, REPORTED_AT) == {'date': '2026-10-01'}


# #1171: 10:47 in Auckland on 2 October, before the 4pm the claimant names.
MORNING_AFTER = datetime(2026, 10, 1, 21, 47, tzinfo=UTC)


@pytest.mark.parametrize(
    ('value', 'words', 'stored'),
    [
        ('2026-09-05T16:00+12:00', 'Saturday 5 September at about 4pm', '2026-09-05T16:00+12:00'),
        ('2026-09-05T16:10+12:00', 'On 5 September at 4:10pm', '2026-09-05T16:10+12:00'),
        ('2026-09-05T16:00+12:00', '5/9/2026 about 4pm', '2026-09-05T16:00+12:00'),
        ('2026-09-05T04:00:00Z', '5 September at 4pm', '2026-09-05T16:00+12:00'),
        ('2026-09-05T16:10+13:00', 'On 5 September at 4:10pm', '2026-09-05T16:10+12:00'),
        ('2026-08-31', 'Monday 31 August', '2026-08-31'),
    ],
)
def test_a_named_date_is_stored_as_that_date_not_today(value: str, words: str, stored: str) -> None:
    # The model's reading of the named date is kept; the clock time in the
    # words never moves it to today or yesterday.
    assert check_reported_time(value, words, MORNING_AFTER) == stored
