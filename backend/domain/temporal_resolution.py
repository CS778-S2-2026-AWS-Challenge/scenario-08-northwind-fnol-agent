"""Resolve a claimant's incident time against the moment they reported it.

Claimants say "about 20 minutes ago", "last night" or "this morning around 9".
The model does not know the current time and may return an invented date, an
ISO duration such as ``PT20M`` or an internal token. Runtime stores one of two
readable forms, in New Zealand local time:

- ``2026-10-01T17:20+13:00`` when a clock time is known (or derivable);
- ``2026-10-01`` optionally followed by a part of day, e.g. ``2026-10-01 evening``.

When neither the claimant's words nor the model's value can be resolved, the
claimant's own words are kept. Precision (exact / approximate) is recorded
separately on the field from the claimant's wording.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

NZ = ZoneInfo('Pacific/Auckland')
MAX_PAST = timedelta(days=730)
FUTURE_TOLERANCE = timedelta(hours=1)

_NUMBER_WORDS = {
    'a': 1,
    'an': 1,
    'one': 1,
    'a couple of': 2,
    'couple of': 2,
    'two': 2,
    'three': 3,
    'a few': 5,
    'few': 5,
    'four': 4,
    'five': 5,
    'ten': 10,
    'fifteen': 15,
    'twenty': 20,
    'thirty': 30,
    'forty': 40,
    'forty-five': 45,
}
_AGO = re.compile(
    r'\b(?P<amount>\d+|a couple of|couple of|a few|few|an|a|one|two|three|four|five|ten|'
    r'fifteen|twenty|thirty|forty-five|forty)\s*(?:or so\s*)?'
    r'(?P<unit>minutes?|mins?|hours?|hrs?)\s+ago\b',
    re.IGNORECASE,
)
_HALF_HOUR_AGO = re.compile(r'\bhalf an hour ago\b', re.IGNORECASE)
_JUST_NOW = re.compile(r'\b(?:just now|just happened|moments? ago|a moment ago)\b', re.IGNORECASE)
_ISO_DURATION = re.compile(r'^P?T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?$', re.IGNORECASE)
_CLOCK = re.compile(
    r'\b(?P<hour>[01]?\d|2[0-3])(?:[:.](?P<minute>[0-5]\d))?\s*(?P<meridiem>a\.?m\.?|p\.?m\.?)?'
    r'(?=\b|\s|$)',
    re.IGNORECASE,
)
_PARTS = (
    ('last night', -1, 'night'),
    ('yesterday morning', -1, 'morning'),
    ('yesterday afternoon', -1, 'afternoon'),
    ('yesterday evening', -1, 'evening'),
    ('yesterday', -1, None),
    ('this morning', 0, 'morning'),
    ('this afternoon', 0, 'afternoon'),
    ('this evening', 0, 'evening'),
    ('tonight', 0, 'evening'),
    ('earlier today', 0, None),
    ('today', 0, None),
)
_ISO_VALUE = re.compile(r'^\d{4}-\d{2}-\d{2}(?:[T ][0-2]\d:[0-5]\d)?')


def _local(moment: datetime) -> datetime:
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(NZ)


def _format_moment(moment: datetime) -> str:
    local = _local(moment).replace(second=0, microsecond=0)
    offset = local.strftime('%z')
    return f'{local:%Y-%m-%dT%H:%M}{offset[:3]}:{offset[3:]}'


def _format_day(day: date, part: str | None) -> str:
    return f'{day.isoformat()} {part}' if part else day.isoformat()


def _amount(word: str) -> int:
    return int(word) if word.isdigit() else _NUMBER_WORDS.get(word.casefold(), 0)


def _clock(text: str, part: str | None) -> tuple[int, int] | None:
    for match in _CLOCK.finditer(text):
        meridiem = (match.group('meridiem') or '').casefold().replace('.', '')
        if not meridiem and match.group('minute') is None:
            continue  # a bare number ("2 cars") is not a time
        hour = int(match.group('hour'))
        minute = int(match.group('minute') or 0)
        if meridiem == 'pm' and hour < 12:
            hour += 12
        elif meridiem == 'am' and hour == 12:
            hour = 0
        elif not meridiem and part in {'afternoon', 'evening', 'night'} and hour < 12:
            hour += 12
        return hour, minute
    return None


def _from_words(text: str, reported_at: datetime) -> str | None:
    now = _local(reported_at)
    if _JUST_NOW.search(text):
        return _format_moment(now)
    if _HALF_HOUR_AGO.search(text):
        return _format_moment(now - timedelta(minutes=30))
    ago = _AGO.search(text)
    if ago:
        amount = _amount(ago.group('amount'))
        if amount:
            unit = ago.group('unit').casefold()
            delta = timedelta(hours=amount) if unit.startswith('h') else timedelta(minutes=amount)
            return _format_moment(now - delta)
    lowered = text.casefold()
    for phrase, day_offset, part in _PARTS:
        if phrase in lowered:
            day = now.date() + timedelta(days=day_offset)
            clock = _clock(text, part)
            if clock is not None:
                moment = datetime(day.year, day.month, day.day, clock[0], clock[1], tzinfo=NZ)
                return _format_moment(moment)
            return _format_day(day, part)
    clock = _clock(text, None)
    if clock is not None:
        # A clock time alone ("at 5:20pm") means today, or yesterday when that
        # time has not happened yet today.
        moment = now.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
        if moment > now + FUTURE_TOLERANCE:
            moment -= timedelta(days=1)
        return _format_moment(moment)
    return None


def _from_value(value: str, reported_at: datetime) -> str | None:
    now = _local(reported_at)
    duration = _ISO_DURATION.match(value.strip())
    if duration and (duration.group('h') or duration.group('m')):
        delta = timedelta(
            hours=int(duration.group('h') or 0), minutes=int(duration.group('m') or 0)
        )
        return _format_moment(now - delta)
    text = value.strip()
    if not _ISO_VALUE.match(text):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00').replace(' ', 'T', 1))
    except ValueError:
        return None
    if len(text) == 10:
        day = parsed.date()
        if now.date() - day > MAX_PAST or day > now.date():
            return None
        return day.isoformat()
    moment = parsed if parsed.tzinfo else parsed.replace(tzinfo=NZ)
    if moment > now + FUTURE_TOLERANCE or now - moment > MAX_PAST:
        return None
    return _format_moment(moment)


def _looks_internal(value: str) -> bool:
    text = value.strip()
    # An ISO value reaching here failed the plausibility check (future, or more
    # than two years back without the claimant saying so): it is invented.
    if _ISO_VALUE.match(text):
        return True
    return bool(re.fullmatch(r'[a-z]+(?:_[a-z]+)+|P?T\w*', text)) or text.casefold() in {
        'unknown',
        'now',
        'current',
    }


def resolve_reported_time(
    value: object,
    reported_text: str | None,
    reported_at: datetime,
) -> object:
    """Return the stored form of a claimant's time statement.

    The claimant's own words win over the model's value, because the model does
    not know the current time. Non-string values (already structured) pass through.
    Returns None when nothing usable was said (an internal token and no quote);
    the caller drops that change.
    """

    if not isinstance(value, str):
        return value
    for text in (reported_text, value):
        if text:
            resolved = _from_words(text, reported_at)
            if resolved is not None:
                return resolved
    resolved = _from_value(value, reported_at)
    if resolved is not None:
        return resolved
    if reported_text and reported_text.strip():
        return reported_text.strip()
    if not value.strip() or _looks_internal(value):
        return None
    return value.strip()
