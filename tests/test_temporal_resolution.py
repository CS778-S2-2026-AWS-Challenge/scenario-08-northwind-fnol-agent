from datetime import UTC, datetime

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
