"""Role-safe multiplexed realtime event streams."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from backend.core.auth import Principal, require_claimant, require_workbench_read
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.realtime import cursor_is_after
from backend.services.realtime import RealtimeDispatcher, scope_for

claimant_router = APIRouter(prefix='/api/v1/realtime', tags=['realtime'])
workbench_router = APIRouter(prefix='/api/v1/workbench/realtime', tags=['workbench-realtime'])


def dispatcher_for(request: Request) -> RealtimeDispatcher:
    return cast(RealtimeDispatcher, request.app.state.realtime_dispatcher)


def _format_sse(event: str, data: dict[str, object], cursor: str | None = None) -> str:
    lines: list[str] = []
    if cursor:
        lines.append(f'id: {cursor}')
    lines.append(f'event: {event}')
    lines.append(f'data: {json.dumps(data, separators=(",", ":"))}')
    return '\n'.join(lines) + '\n\n'


def realtime_stream(
    request: Request,
    principal: Principal,
    *,
    cursor: str | None,
    claim_id: str | None = None,
) -> StreamingResponse:
    dispatcher = dispatcher_for(request)
    scope = scope_for(principal, claim_id=claim_id)
    subscription = dispatcher.subscribe(scope)
    try:
        replay = dispatcher.replay(scope, cursor)
    except ValueError as error:
        dispatcher.unsubscribe(subscription)
        raise ApiError(
            status_code=409,
            code='INVALID_EVENT_CURSOR',
            message='The realtime cursor is invalid or cannot be replayed.',
            retryable=True,
            details=[ErrorDetail(field='cursor', reason=str(error))],
        ) from error

    async def events() -> AsyncIterator[str]:
        last_cursor = cursor

        try:
            yield 'retry: 1500\n: connected\n\n'
            for delivery in replay:
                if delivery.cursor and not cursor_is_after(delivery.cursor, last_cursor):
                    continue
                if delivery.cursor:
                    last_cursor = delivery.cursor
                yield _format_sse(delivery.event, delivery.data, delivery.cursor)
                if delivery.event == 'resync_required':
                    return
            while not await request.is_disconnected():
                live_delivery = await asyncio.to_thread(subscription.next, 15.0)
                if live_delivery is None:
                    yield ': keep-alive\n\n'
                    continue
                if live_delivery.cursor and not cursor_is_after(live_delivery.cursor, last_cursor):
                    continue
                if live_delivery.cursor:
                    last_cursor = live_delivery.cursor
                yield _format_sse(
                    live_delivery.event,
                    live_delivery.data,
                    live_delivery.cursor,
                )
                if live_delivery.event == 'resync_required':
                    return
        finally:
            dispatcher.unsubscribe(subscription)

    return StreamingResponse(
        events(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'},
    )


@claimant_router.get('/events', responses={200: {'content': {'text/event-stream': {}}}})
def claimant_events(
    request: Request,
    principal: Principal = Depends(require_claimant),
    cursor: str | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias='Last-Event-ID'),
) -> StreamingResponse:
    return realtime_stream(request, principal, cursor=last_event_id or cursor)


@workbench_router.get('/events', responses={200: {'content': {'text/event-stream': {}}}})
def workbench_events(
    request: Request,
    principal: Principal = Depends(require_workbench_read),
    cursor: str | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias='Last-Event-ID'),
) -> StreamingResponse:
    return realtime_stream(request, principal, cursor=last_event_id or cursor)
