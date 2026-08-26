import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from datetime import datetime

from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.models import (
    ClaimantMessage,
    MessageListResponse,
    MessageRecord,
    MessageVisibility,
    PageInfo,
)
from backend.repositories.protocols import PersistenceRepository


def _session_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The session was not found.',
    )


def _invalid_cursor(error: Exception | None = None) -> ApiError:
    validation = ApiError(
        status_code=422,
        code='VALIDATION_ERROR',
        message='The pagination cursor is invalid.',
        details=[ErrorDetail(field='cursor', reason='Use a cursor returned by this API.')],
    )
    if error is not None:
        validation.__cause__ = error
    return validation


def _claimant_message(message: MessageRecord) -> ClaimantMessage:
    return ClaimantMessage(
        message_id=message.message_id,
        actor=message.actor,
        content=message.content,
        evidence_refs=message.evidence_refs,
        in_reply_to=message.in_reply_to,
        created_at=message.created_at,
    )


def _message_key(message: MessageRecord) -> tuple[datetime, str]:
    return message.created_at, message.message_id


def _encode_message_cursor(message: MessageRecord) -> str:
    payload = json.dumps(
        [message.created_at.isoformat(), message.message_id],
        separators=(',', ':'),
    ).encode()
    return urlsafe_b64encode(payload).decode().rstrip('=')


def _decode_message_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    try:
        padded = cursor + '=' * (-len(cursor) % 4)
        raw = json.loads(urlsafe_b64decode(padded).decode())
        if (
            not isinstance(raw, list)
            or len(raw) != 2
            or not isinstance(raw[0], str)
            or not isinstance(raw[1], str)
            or not raw[1]
        ):
            raise ValueError('cursor shape')
        created_at = datetime.fromisoformat(raw[0])
        if created_at.utcoffset() is None:
            raise ValueError('cursor timestamp timezone')
        return created_at, raw[1]
    except (Base64Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise _invalid_cursor(error) from error


def list_claim_messages(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    session_id: str,
    *,
    limit: int,
    cursor: str | None,
    before: datetime | None,
    after: datetime | None,
) -> MessageListResponse:
    if repository.get_session(claim_id, session_id, principal.subject) is None:
        raise _session_not_found()
    for field_name, timestamp in {'before': before, 'after': after}.items():
        if timestamp is not None and timestamp.utcoffset() is None:
            raise ApiError(
                status_code=422,
                code='VALIDATION_ERROR',
                message=f'The {field_name} filter must include a timezone offset.',
                details=[
                    ErrorDetail(
                        field=field_name,
                        reason='Use an ISO 8601 timestamp with a timezone offset.',
                    )
                ],
            )

    visible_messages = sorted(
        (
            message
            for message in repository.list_messages(
                claim_id,
                session_id,
                principal.subject,
            )
            if message.visibility is not MessageVisibility.INTERNAL_ONLY
        ),
        key=_message_key,
    )
    if before is not None:
        visible_messages = [message for message in visible_messages if message.created_at < before]
    if after is not None:
        visible_messages = [message for message in visible_messages if message.created_at > after]

    cursor_key = _decode_message_cursor(cursor)
    if cursor_key is not None:
        visible_messages = [
            message for message in visible_messages if _message_key(message) > cursor_key
        ]

    page_messages = visible_messages[:limit]
    next_cursor = (
        _encode_message_cursor(page_messages[-1])
        if page_messages and len(visible_messages) > limit
        else None
    )
    return MessageListResponse(
        items=[_claimant_message(message) for message in page_messages],
        page=PageInfo(next_cursor=next_cursor),
    )
