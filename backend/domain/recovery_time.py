"""Canonical P17 ordering timestamps shared by persistence and migration."""

from datetime import UTC, datetime

RECOVERY_TIMESTAMP_PATTERN = r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[.][0-9]{6}Z$'


def recovery_timestamp(value: datetime) -> str:
    """Serialize an instant with fixed precision for lexicographic ordering.

    Args:
        value: Timezone-aware recovery timestamp.
    Returns:
        UTC timestamp with six fractional digits and a Z suffix.
    Raises:
        ValueError: The input has no timezone authority.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Recovery timestamps require an explicit timezone.')
    return value.astimezone(UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')
