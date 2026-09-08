import hashlib
import json
import re
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TypeVar

from backend.core.errors import ApiError, ErrorDetail
from backend.domain.models import PageInfo

PageItemT = TypeVar('PageItemT')

IF_MATCH_PATTERN = re.compile(r'^"?(\d+)"?$')


def now_utc() -> datetime:
    return datetime.now(UTC)


def request_fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def encode_cursor(offset: int) -> str:
    return urlsafe_b64encode(str(offset).encode()).decode().rstrip('=')


def decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        padded = cursor + '=' * (-len(cursor) % 4)
        offset = int(urlsafe_b64decode(padded).decode())
    except (Base64Error, UnicodeDecodeError, ValueError) as error:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The pagination cursor is invalid.',
            details=[ErrorDetail(field='cursor', reason='Use a cursor returned by this API.')],
        ) from error
    if offset < 0:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The pagination cursor is invalid.',
            details=[ErrorDetail(field='cursor', reason='Use a cursor returned by this API.')],
        )
    return offset


def paginate(
    items: Sequence[PageItemT], limit: int, cursor: str | None
) -> tuple[list[PageItemT], PageInfo]:
    """Apply the repository's opaque offset cursor contract to an in-memory result set."""
    offset = decode_cursor(cursor)
    bounded_limit = min(max(limit, 1), 100)
    selected = list(items)[offset : offset + bounded_limit]
    next_offset = offset + len(selected)
    next_cursor = encode_cursor(next_offset) if next_offset < len(items) else None
    return selected, PageInfo(next_cursor=next_cursor)


def require_idempotency_key(key: str | None) -> str:
    if key is None or not key.strip():
        raise ApiError(
            status_code=400,
            code='VALIDATION_ERROR',
            message='Idempotency-Key is required for this operation.',
            details=[ErrorDetail(field='Idempotency-Key', reason='The header is required.')],
        )
    if len(key) > 200:
        raise ApiError(
            status_code=400,
            code='VALIDATION_ERROR',
            message='Idempotency-Key is too long.',
            details=[
                ErrorDetail(field='Idempotency-Key', reason='Maximum length is 200 characters.')
            ],
        )
    return key.strip()


def parse_if_match(value: str | None) -> int:
    if value is None:
        raise ApiError(
            status_code=409,
            code='REVISION_REQUIRED',
            message='If-Match is required when changing an existing claim.',
        )
    match = IF_MATCH_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ApiError(
            status_code=409,
            code='REVISION_REQUIRED',
            message='If-Match must contain the expected numeric revision.',
        )
    return int(match.group(1))
