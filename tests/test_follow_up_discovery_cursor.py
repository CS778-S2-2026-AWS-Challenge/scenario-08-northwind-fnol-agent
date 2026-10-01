"""The opaque P17 discovery cursor rejects foreign, malformed or naive keysets."""

import json
from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta

import pytest

from backend.repositories.pagination import (
    FollowUpDiscoveryCursor,
    InvalidRepositoryCursorError,
    decode_follow_up_discovery_cursor,
    encode_follow_up_discovery_cursor,
)

BOUNDARY = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
CURSOR = FollowUpDiscoveryCursor(
    scope='due',
    boundary=BOUNDARY,
    ordered_at=BOUNDARY - timedelta(hours=1),
    follow_up_id='fup_cursor',
)


def _raw(payload: object) -> str:
    return urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')


def test_cursor_round_trips_within_its_scope() -> None:
    encoded = encode_follow_up_discovery_cursor(CURSOR)

    assert decode_follow_up_discovery_cursor(encoded, scope='due', boundary=BOUNDARY) == CURSOR

    # A cursor minted for one discovery page never continues another.
    with pytest.raises(InvalidRepositoryCursorError):
        decode_follow_up_discovery_cursor(encoded, scope='deadline', boundary=BOUNDARY)


@pytest.mark.parametrize(
    'cursor',
    [
        FollowUpDiscoveryCursor('expired', BOUNDARY, BOUNDARY, 'fup_cursor'),
        FollowUpDiscoveryCursor('due', BOUNDARY.replace(tzinfo=None), BOUNDARY, 'fup_cursor'),
        FollowUpDiscoveryCursor('due', BOUNDARY, BOUNDARY.replace(tzinfo=None), 'fup_cursor'),
        FollowUpDiscoveryCursor('due', BOUNDARY, BOUNDARY, ''),
    ],
    ids=['unknown-scope', 'naive-boundary', 'naive-ordered-at', 'missing-id'],
)
def test_cursor_encoding_rejects_an_invalid_keyset(cursor: FollowUpDiscoveryCursor) -> None:
    with pytest.raises(InvalidRepositoryCursorError):
        encode_follow_up_discovery_cursor(cursor)


@pytest.mark.parametrize(
    ('value', 'scope', 'boundary'),
    [
        ('anything', 'expired', BOUNDARY),
        ('anything', 'due', BOUNDARY.replace(tzinfo=None)),
        ('%%%not-base64%%%', 'due', BOUNDARY),
        (_raw(['not', 'an', 'object']), 'due', BOUNDARY),
        (_raw({'v': 1, 'resource': 'claims'}), 'due', BOUNDARY),
        (_raw({'v': 1, 'resource': 'follow_up_discovery', 'scope': 'due'}), 'due', BOUNDARY),
    ],
    ids=[
        'unknown-scope',
        'naive-boundary',
        'not-base64',
        'not-an-object',
        'other-resource',
        'missing-fields',
    ],
)
def test_cursor_decoding_rejects_foreign_or_malformed_values(
    value: str,
    scope: str,
    boundary: datetime,
) -> None:
    with pytest.raises(InvalidRepositoryCursorError):
        decode_follow_up_discovery_cursor(value, scope=scope, boundary=boundary)
