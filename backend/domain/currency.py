"""Reference conversion of claimant-stated amounts into NZD, for intake triage only.

Northwind policies pay in NZD, and triage compares a loss with an NZD threshold. An
amount stated in another currency is converted with the fixed reference table below.
The table is a dated snapshot, not a live rate, and is never used to value a claim.

Source: European Central Bank reference rates as published by the Frankfurter API
(`https://api.frankfurter.dev/v1/latest?base=NZD`), retrieved 2026-09-30. Each value
is the number of units of that currency per 1 NZD.
"""

from backend.domain.models import MoneyAmount

REFERENCE_RATES_AS_OF = '2026-09-30'
REFERENCE_RATES_SOURCE = 'ECB reference rates via Frankfurter, base NZD'
UNITS_PER_NZD: dict[str, float] = {
    'AUD': 0.81019,
    'BRL': 2.937,
    'CAD': 0.80065,
    'CHF': 0.47119,
    'CNY': 3.7847,
    'CZK': 12.1501,
    'DKK': 3.7164,
    'EUR': 0.49714,
    'GBP': 0.42487,
    'HKD': 4.4293,
    'HUF': 182.05,
    'IDR': 10099.0,
    'ILS': 1.7351,
    'INR': 54.099,
    'ISK': 68.108,
    'JPY': 88.63,
    'KRW': 765.13,
    'MXN': 10.2322,
    'MYR': 2.3021,
    'NOK': 5.4196,
    'PHP': 35.398,
    'PLN': 2.172,
    'RON': 2.6243,
    'SEK': 5.6331,
    'SGD': 0.721,
    'THB': 18.9476,
    'TRY': 27.671,
    'USD': 0.5645,
    'ZAR': 9.2529,
}


def to_nzd(value: MoneyAmount) -> float | None:
    """Return the amount in NZD, or None when the currency is not in the table."""
    if value.currency == 'NZD':
        return value.amount
    rate = UNITS_PER_NZD.get(value.currency)
    return None if rate is None else value.amount / rate
