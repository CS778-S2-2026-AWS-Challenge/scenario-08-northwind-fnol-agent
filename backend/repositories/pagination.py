"""Opaque keyset cursors shared by persistence adapters."""

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass
from datetime import datetime

from pydantic import TypeAdapter

_DATETIME_ADAPTER = TypeAdapter(datetime)
FOLLOW_UP_DISCOVERY_MAX_LIMIT = 1000


class InvalidRepositoryCursorError(ValueError):
    """A repository cursor is malformed or belongs to another resource scope."""


@dataclass(frozen=True)
class ContentsEvidenceAssociationCursor:
    claim_id: str
    customer_id: str
    item_id: str
    created_at: datetime
    association_id: str


@dataclass(frozen=True)
class FollowUpDiscoveryCursor:
    """Stable keyset cursor for internal P17 due/deadline discovery."""

    scope: str
    boundary: datetime
    ordered_at: datetime
    follow_up_id: str


def repository_datetime_value(value: datetime) -> str:
    """Return the datetime representation persisted by repository adapters.

    Args:
        value: A timezone-aware domain timestamp.

    Returns:
        The Pydantic JSON representation used in MongoDB documents and cursors.
    """
    return str(_DATETIME_ADAPTER.dump_python(value, mode='json'))


def encode_contents_evidence_association_cursor(
    cursor: ContentsEvidenceAssociationCursor,
) -> str:
    """Encode an item-scoped association keyset as an opaque client cursor.

    Args:
        cursor: The resource scope and final stable ordering key in the current page.

    Returns:
        A URL-safe continuation cursor.
    """
    payload = {
        'v': 1,
        'claim_id': cursor.claim_id,
        'customer_id': cursor.customer_id,
        'item_id': cursor.item_id,
        'created_at': repository_datetime_value(cursor.created_at),
        'association_id': cursor.association_id,
    }
    encoded = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
    return urlsafe_b64encode(encoded).decode().rstrip('=')


def decode_contents_evidence_association_cursor(
    value: str,
    *,
    claim_id: str,
    customer_id: str,
    item_id: str,
) -> ContentsEvidenceAssociationCursor:
    """Decode and validate an association cursor against the requested resource scope.

    Args:
        value: The opaque cursor supplied by the API client.
        claim_id: The Claim being listed.
        customer_id: The authenticated owner of the Claim.
        item_id: The ContentsItem being listed.

    Returns:
        The validated stable ordering key carried by the cursor.

    Raises:
        InvalidRepositoryCursorError: The cursor is malformed or belongs to another scope.
    """
    try:
        padded = value + '=' * (-len(value) % 4)
        payload = json.loads(urlsafe_b64decode(padded).decode())
        if not isinstance(payload, dict) or payload.get('v') != 1:
            raise ValueError
        cursor = ContentsEvidenceAssociationCursor(
            claim_id=str(payload['claim_id']),
            customer_id=str(payload['customer_id']),
            item_id=str(payload['item_id']),
            created_at=datetime.fromisoformat(str(payload['created_at'])),
            association_id=str(payload['association_id']),
        )
    except (Base64Error, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as error:
        raise InvalidRepositoryCursorError from error
    if (
        cursor.claim_id != claim_id
        or cursor.customer_id != customer_id
        or cursor.item_id != item_id
        or cursor.created_at.tzinfo is None
        or not cursor.association_id
    ):
        raise InvalidRepositoryCursorError
    return cursor


def encode_follow_up_discovery_cursor(
    cursor: FollowUpDiscoveryCursor,
) -> str:
    """Encode a due/deadline Follow-up keyset as an opaque cursor."""

    if cursor.scope not in {'due', 'deadline'}:
        raise InvalidRepositoryCursorError
    if (
        cursor.boundary.tzinfo is None
        or cursor.ordered_at.tzinfo is None
        or not cursor.follow_up_id
    ):
        raise InvalidRepositoryCursorError

    payload = {
        'v': 1,
        'resource': 'follow_up_discovery',
        'scope': cursor.scope,
        'boundary': repository_datetime_value(cursor.boundary),
        'ordered_at': repository_datetime_value(cursor.ordered_at),
        'follow_up_id': cursor.follow_up_id,
    }
    encoded = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
    return urlsafe_b64encode(encoded).decode().rstrip('=')


def decode_follow_up_discovery_cursor(
    value: str,
    *,
    scope: str,
    boundary: datetime,
) -> FollowUpDiscoveryCursor:
    """Decode and scope-check a P17 due/deadline discovery cursor."""

    if scope not in {'due', 'deadline'} or boundary.tzinfo is None:
        raise InvalidRepositoryCursorError

    try:
        padded = value + '=' * (-len(value) % 4)
        payload = json.loads(urlsafe_b64decode(padded).decode())
        if (
            not isinstance(payload, dict)
            or payload.get('v') != 1
            or payload.get('resource') != 'follow_up_discovery'
        ):
            raise ValueError

        cursor = FollowUpDiscoveryCursor(
            scope=str(payload['scope']),
            boundary=datetime.fromisoformat(str(payload['boundary'])),
            ordered_at=datetime.fromisoformat(str(payload['ordered_at'])),
            follow_up_id=str(payload['follow_up_id']),
        )
    except (
        Base64Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
    ) as error:
        raise InvalidRepositoryCursorError from error

    if (
        cursor.scope != scope
        or cursor.boundary != boundary
        or cursor.boundary.tzinfo is None
        or cursor.ordered_at.tzinfo is None
        or not cursor.follow_up_id
    ):
        raise InvalidRepositoryCursorError

    return cursor


RETENTION_DISCOVERY_MAX_LIMIT = 100
RETENTION_DISCOVERY_SCOPES = frozenset({'handoff', 'pending'})


@dataclass(frozen=True)
class RetentionDiscoveryCursor:
    """Keyset position in one retention discovery sweep.

    ``handoff`` orders eligible terminal Claims by terminal ``recorded_at`` then Claim
    ID; ``pending`` orders unfinished RetentionOperations by ``updated_at`` then
    operation ID.
    """

    scope: str
    ordered_at: datetime
    record_id: str


def encode_retention_discovery_cursor(cursor: RetentionDiscoveryCursor) -> str:
    """Encode a retention discovery keyset as an opaque cursor.

    Args:
        cursor: The last position returned by a discovery page.

    Returns:
        An opaque URL-safe cursor.

    Raises:
        InvalidRepositoryCursorError: The scope is unknown, the time is naive, or the
            record identity is empty.
    """

    if (
        cursor.scope not in RETENTION_DISCOVERY_SCOPES
        or cursor.ordered_at.tzinfo is None
        or not cursor.record_id
    ):
        raise InvalidRepositoryCursorError

    payload = {
        'v': 1,
        'resource': 'retention_discovery',
        'scope': cursor.scope,
        'ordered_at': repository_datetime_value(cursor.ordered_at),
        'record_id': cursor.record_id,
    }
    encoded = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
    return urlsafe_b64encode(encoded).decode().rstrip('=')


def decode_retention_discovery_cursor(value: str, *, scope: str) -> RetentionDiscoveryCursor:
    """Decode and scope-check a retention discovery cursor.

    Args:
        value: Cursor returned by the same discovery scope.
        scope: ``handoff`` or ``pending``.

    Returns:
        The decoded keyset position.

    Raises:
        InvalidRepositoryCursorError: The cursor is malformed or belongs to another scope.
    """

    if scope not in RETENTION_DISCOVERY_SCOPES:
        raise InvalidRepositoryCursorError

    try:
        padded = value + '=' * (-len(value) % 4)
        payload = json.loads(urlsafe_b64decode(padded).decode())
        if (
            not isinstance(payload, dict)
            or payload.get('v') != 1
            or payload.get('resource') != 'retention_discovery'
        ):
            raise ValueError
        cursor = RetentionDiscoveryCursor(
            scope=str(payload['scope']),
            ordered_at=datetime.fromisoformat(str(payload['ordered_at'])),
            record_id=str(payload['record_id']),
        )
    except (Base64Error, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as error:
        raise InvalidRepositoryCursorError from error

    if cursor.scope != scope or cursor.ordered_at.tzinfo is None or not cursor.record_id:
        raise InvalidRepositoryCursorError
    return cursor
