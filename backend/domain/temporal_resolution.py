"""Check an incident time the model worked out against the moment of reporting.

The model reads ``turn_focus.reported_at_local`` and turns the claimant's words
("about 20 minutes ago", "last night") into one of two New Zealand forms:

- ``2026-10-01T17:20+13:00`` when a clock time is known or derivable;
- ``2026-10-01``, optionally followed by a part of day, e.g. ``2026-10-01 evening``.

Runtime does not interpret the claimant's words. It checks the shape and that the
time is neither in the future nor more than two years back, like any input check.
A value that fails keeps the claimant's own words instead, so nothing invented is
stored; with no words to keep, the change is dropped.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NZ = ZoneInfo('Pacific/Auckland')
MAX_PAST = timedelta(days=730)
FUTURE_TOLERANCE = timedelta(hours=1)
PARTS_OF_DAY = ('morning', 'afternoon', 'evening', 'night')

_MOMENT = re.compile(
    r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$'
)
_DAY = re.compile(rf'^(\d{{4}}-\d{{2}}-\d{{2}})(?: ({"|".join(PARTS_OF_DAY)}))?$')


def _moment(text: str, reported_at: datetime) -> str | None:
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00').replace(' ', 'T', 1))
    except ValueError:
        return None
    moment = (parsed if parsed.tzinfo else parsed.replace(tzinfo=NZ)).astimezone(NZ)
    if moment > reported_at + FUTURE_TOLERANCE or reported_at - moment > MAX_PAST:
        return None
    offset = moment.strftime('%z')
    return f'{moment:%Y-%m-%dT%H:%M}{offset[:3]}:{offset[3:]}'


def _day(text: str, reported_at: datetime) -> str | None:
    match = _DAY.match(text)
    if match is None:
        return None
    try:
        day = datetime.fromisoformat(match.group(1)).date()
    except ValueError:
        return None
    today = reported_at.astimezone(NZ).date()
    if day > today or today - day > MAX_PAST:
        return None
    return text


def check_reported_time(
    value: object,
    reported_text: str | None,
    reported_at: datetime,
) -> object:
    """Return the value to store for a time field, or None to drop the change.

    Non-string values pass through. A well-formed, plausible time is stored in
    the canonical NZ form; anything else falls back to the claimant's words.
    """

    if not isinstance(value, str):
        return value
    text = value.strip()
    checked = _moment(text, reported_at) if _MOMENT.match(text) else _day(text, reported_at)
    if checked is not None:
        return checked
    words = (reported_text or '').strip()
    if words:
        return words
    # Free wording ("sometime last week") is kept; a token such as PT20M,
    # current_approx or a rejected date is not something the claimant said.
    return text if ' ' in text and '_' not in text and not text[:1].isdigit() else None
