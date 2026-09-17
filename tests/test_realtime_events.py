from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from queue import Queue
from threading import Event, Thread
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api import claims as claims_api
from backend.api.realtime import realtime_stream
from backend.core.auth import Principal
from backend.domain.realtime import (
    RealtimeAudience,
    RealtimeCursor,
    RealtimeDelivery,
    RealtimeEvent,
    RealtimeResource,
    cursor_for,
    cursor_is_after,
    new_realtime_event,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyConflict
from backend.services.realtime import (
    RealtimeDispatcher,
    RealtimeScope,
    RealtimeSubscription,
    delivery_for,
)

NOW = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)


def _event(
    suffix: int,
    *,
    customer_id: str = 'cus_one',
    resources: tuple[RealtimeResource, ...] = (RealtimeResource.CLAIM,),
    claimant_resources: tuple[RealtimeResource, ...] | None = None,
) -> RealtimeEvent:
    return new_realtime_event(
        claim_id='clm_one',
        customer_id=customer_id,
        occurred_at=NOW + timedelta(seconds=suffix),
        claim_revision=suffix + 1,
        resources=resources,
        claimant_resources=claimant_resources,
    )


def test_cursor_round_trip_preserves_stable_ordering_coordinates() -> None:
    event = _event(1)

    cursor = RealtimeCursor.decode(cursor_for(event))

    assert cursor.event_id == event.event_id
    assert cursor.occurred_at == event.occurred_at


def test_cursor_round_trip_preserves_mongo_commit_sequence() -> None:
    event = new_realtime_event(
        claim_id='clm_one',
        customer_id='cus_one',
        occurred_at=NOW,
        claim_revision=2,
        sequence=7,
        resources=(RealtimeResource.CLAIM,),
    )

    cursor = RealtimeCursor.decode(cursor_for(event))

    assert cursor.sequence == 7
    assert (
        cursor.ordering_key
        < RealtimeCursor(
            occurred_at=NOW,
            event_id='rte_ffffffffffffffffffff',
            sequence=8,
        ).ordering_key
    )


@pytest.mark.parametrize(
    ('overrides', 'message'),
    [
        ({'resources': ['claim', 'claim']}, 'resources must be unique'),
        ({'audiences': ['staff', 'staff']}, 'audiences must be unique'),
        (
            {'claimant_resources': ['evidence']},
            'Claimant resources must be a subset',
        ),
        (
            {'claimant_resources': [], 'audiences': ['claimant', 'staff']},
            'Claimant audience and resources must be declared together',
        ),
        (
            {
                'resources': ['claim', 'queue'],
                'claimant_resources': ['claim', 'queue'],
            },
            'staff-only resource hints',
        ),
    ],
)
def test_realtime_event_rejects_inconsistent_visibility_sets(
    overrides: dict[str, object],
    message: str,
) -> None:
    payload = _event(1).model_dump(mode='json')
    payload.update(overrides)

    with pytest.raises(ValidationError, match=message):
        RealtimeEvent.model_validate(payload)


def test_fixture_replay_requires_a_durable_anchor() -> None:
    repository = FixtureRepository()
    first = _event(1)
    second = _event(2)
    repository.append_realtime_event(first)
    repository.append_realtime_event(second)

    replay = repository.replay_realtime_events(
        RealtimeCursor(occurred_at=first.occurred_at, event_id=first.event_id),
        limit=10,
    )

    assert [event.event_id for event in replay] == [second.event_id]
    assert replay[0].sequence == 2
    with pytest.raises(ValueError, match='outside the available replay window'):
        repository.replay_realtime_events(
            RealtimeCursor(occurred_at=NOW, event_id='rte_00000000000000000000'),
            limit=10,
        )


def test_fixture_sequence_preserves_append_order_for_live_and_reconnect() -> None:
    repository = FixtureRepository()
    stop = Event()
    received: Queue[RealtimeEvent] = Queue()

    def collect() -> None:
        for event in repository.watch_realtime_events(stop):
            received.put(event)
            if received.qsize() == 3:
                stop.set()
                return

    watcher = Thread(target=collect)
    watcher.start()
    first = _event(1).model_copy(
        update={'event_id': 'rte_ffffffffffffffffffff', 'occurred_at': NOW}
    )
    second = _event(2).model_copy(
        update={'event_id': 'rte_00000000000000000000', 'occurred_at': NOW}
    )
    rolled_back_clock = _event(3).model_copy(
        update={
            'event_id': 'rte_11111111111111111111',
            'occurred_at': NOW - timedelta(days=1),
        }
    )

    repository.append_realtime_event(first)
    repository.append_realtime_event(first)
    repository.append_realtime_event(second)
    repository.append_realtime_event(rolled_back_clock)

    live = [received.get(timeout=2) for _ in range(3)]
    watcher.join(timeout=2)
    assert not watcher.is_alive()
    assert [event.event_id for event in live] == [
        first.event_id,
        second.event_id,
        rolled_back_clock.event_id,
    ]
    assert [event.sequence for event in live] == [1, 2, 3]

    replay = repository.replay_realtime_events(
        RealtimeCursor(
            occurred_at=live[0].occurred_at,
            event_id=live[0].event_id,
            sequence=live[0].sequence,
        ),
        limit=10,
    )
    assert replay == live[1:]

    with pytest.raises(IdempotencyConflict):
        repository.append_realtime_event(
            first.model_copy(update={'customer_id': 'cus_conflicting_duplicate'})
        )


def test_claimant_scope_filters_customer_and_internal_message_resources() -> None:
    dispatcher = RealtimeDispatcher(FixtureRepository())
    scope = RealtimeScope(RealtimeAudience.CLAIMANT, 'cus_one')
    allowed = _event(
        1,
        resources=(RealtimeResource.CLAIM, RealtimeResource.MESSAGES),
        claimant_resources=(RealtimeResource.CLAIM,),
    )
    foreign = _event(2, customer_id='cus_two')
    anchor = _event(0)
    dispatcher._repository.append_realtime_event(anchor)
    dispatcher._repository.append_realtime_event(allowed)
    dispatcher._repository.append_realtime_event(foreign)

    deliveries = dispatcher.replay(scope, cursor_for(anchor))

    assert len(deliveries) == 1
    assert deliveries[0].data['claim_id'] == 'clm_one'
    assert deliveries[0].data['resources'] == ['claim']


def test_claimant_delivery_filters_staff_resources_and_correlation() -> None:
    event = new_realtime_event(
        claim_id='clm_one',
        customer_id='cus_one',
        occurred_at=NOW,
        resources=(
            RealtimeResource.CLAIM,
            RealtimeResource.QUEUE,
            RealtimeResource.WORK_ITEMS,
        ),
        operation_correlation='staff-idempotency-key',
    )

    claimant = delivery_for(event, RealtimeAudience.CLAIMANT)
    staff = delivery_for(event, RealtimeAudience.STAFF)

    assert claimant.data['resources'] == ['claim']
    assert 'operation_correlation' not in claimant.data
    assert staff.data['resources'] == ['claim', 'queue', 'work_items']
    assert staff.data['operation_correlation'] == 'staff-idempotency-key'


def test_sequence_cursor_advances_after_legacy_cursor() -> None:
    legacy = _event(1)
    sequenced = new_realtime_event(
        claim_id='clm_one',
        customer_id='cus_one',
        occurred_at=legacy.occurred_at - timedelta(seconds=10),
        sequence=1,
        resources=(RealtimeResource.CLAIM,),
    )

    assert cursor_is_after(cursor_for(sequenced), cursor_for(legacy)) is True
    assert cursor_is_after(cursor_for(legacy), cursor_for(sequenced)) is False


def test_subscription_ignores_duplicate_and_out_of_order_events() -> None:
    subscription = RealtimeSubscription(
        RealtimeScope(RealtimeAudience.STAFF, 'stf_one'),
        capacity=4,
    )
    older = _event(1)
    newer = _event(2)

    subscription.offer(newer)
    subscription.offer(newer)
    subscription.offer(older)

    assert subscription.next(0.01).cursor == cursor_for(newer)  # type: ignore[union-attr]
    assert subscription.next(0.01) is None


def test_closed_subscription_rejects_events_and_resync_signals() -> None:
    subscription = RealtimeSubscription(
        RealtimeScope(RealtimeAudience.STAFF, 'stf_one'),
        capacity=1,
    )

    subscription.close()
    subscription.offer(_event(1))
    subscription.require_resync('source_failed')

    assert subscription.next(0.01) is None


def test_slow_subscription_receives_explicit_resync() -> None:
    subscription = RealtimeSubscription(
        RealtimeScope(RealtimeAudience.STAFF, 'stf_one'),
        capacity=1,
    )

    subscription.offer(_event(1))
    subscription.offer(_event(2))

    delivery = subscription.next(0.01)
    assert delivery is not None
    assert delivery.event == 'resync_required'
    assert delivery.data == {'reason': 'subscriber_overflow'}


class _SingleEventSource:
    def __init__(self, event: RealtimeEvent, *, fail: bool = False) -> None:
        self.event = event
        self.fail = fail
        self.watch_calls = 0

    def replay_realtime_events(
        self, after: RealtimeCursor | None, *, limit: int
    ) -> list[RealtimeEvent]:
        return []

    def watch_realtime_events(self, stop: Event) -> Iterator[RealtimeEvent]:
        self.watch_calls += 1
        if self.fail:
            raise RuntimeError('source unavailable')
        yield self.event
        stop.wait(0.2)


def test_dispatcher_uses_one_watcher_for_multiple_subscribers() -> None:
    source = _SingleEventSource(_event(1))
    dispatcher = RealtimeDispatcher(source)  # type: ignore[arg-type]
    first = dispatcher.subscribe(RealtimeScope(RealtimeAudience.STAFF, 'stf_one'))
    second = dispatcher.subscribe(RealtimeScope(RealtimeAudience.STAFF, 'stf_two'))

    dispatcher.start()
    try:
        assert first.next(1.0) is not None
        assert second.next(1.0) is not None
        assert source.watch_calls == 1
    finally:
        dispatcher.stop()


def test_dispatcher_failure_requires_resync() -> None:
    source = _SingleEventSource(_event(1), fail=True)
    dispatcher = RealtimeDispatcher(source)  # type: ignore[arg-type]
    subscription = dispatcher.subscribe(RealtimeScope(RealtimeAudience.STAFF, 'stf_one'))

    dispatcher.start()
    try:
        delivery = subscription.next(1.0)
        assert delivery is not None
        assert delivery.event == 'resync_required'
        assert delivery.data == {'reason': 'event_source_unavailable'}
    finally:
        dispatcher.stop()


def test_fixture_event_construction_failure_leaves_no_claim(
    client: TestClient,
    repository: FixtureRepository,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_event(**_: object) -> RealtimeEvent:
        raise RuntimeError('event construction failed')

    with monkeypatch.context() as event_patch:
        event_patch.setattr('backend.repositories.fixture.new_realtime_event', fail_event)
        with pytest.raises(RuntimeError, match='event construction failed'):
            client.post(
                '/api/v1/claims',
                headers={**auth_headers, 'Idempotency-Key': 'realtime-atomic-failure'},
                json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
            )

    assert repository.claim_count == 0
    assert repository.replay_realtime_events(None, limit=10) == []

    def fail_sequence() -> int:
        raise RuntimeError('sequence allocation failed')

    with monkeypatch.context() as sequence_patch:
        sequence_patch.setattr(repository, '_next_realtime_sequence', fail_sequence)
        with pytest.raises(RuntimeError, match='sequence allocation failed'):
            client.post(
                '/api/v1/claims',
                headers={**auth_headers, 'Idempotency-Key': 'realtime-sequence-failure'},
                json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
            )

    assert repository.claim_count == 0
    assert repository.replay_realtime_events(None, limit=10) == []

    response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'realtime-after-failure'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    events = repository.replay_realtime_events(None, limit=10)
    assert [event.sequence for event in events] == [1]


def test_scope_for_unsupported_principal_is_rejected() -> None:
    from backend.services.realtime import scope_for

    principal = Principal(subject='svc_one', actor_type='integration_service')

    with pytest.raises(ValueError, match='claimant and staff'):
        scope_for(principal)


def test_realtime_endpoint_rejects_invalid_cursor_before_streaming(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        '/api/v1/realtime/events',
        headers=auth_headers,
        params={'cursor': 'not-a-cursor'},
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'INVALID_EVENT_CURSOR'


def test_workbench_realtime_endpoint_requires_staff_identity(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        '/api/v1/workbench/realtime/events',
        headers=auth_headers,
        params={'cursor': 'not-a-cursor'},
    )

    assert response.status_code == 403


class _StreamRequest:
    def __init__(self, dispatcher: object, *, disconnect_after: int = 100) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(realtime_dispatcher=dispatcher))
        self._disconnect_after = disconnect_after
        self._checks = 0

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > self._disconnect_after


async def _stream_body(response: object) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return ''.join(chunks)


def test_realtime_stream_replays_changes_then_requires_resync() -> None:
    repository = FixtureRepository()
    anchor = _event(0)
    first = _event(1)
    second = _event(2)
    for event in (anchor, first, second):
        repository.append_realtime_event(event)
    stored_anchor, stored_first, _ = repository.replay_realtime_events(None, limit=10)
    dispatcher = RealtimeDispatcher(repository, replay_limit=1)
    request = _StreamRequest(dispatcher)

    response = realtime_stream(
        cast(Request, request),
        Principal(subject='cus_one', actor_type='claimant'),
        cursor=cursor_for(stored_anchor),
    )
    body = asyncio.run(_stream_body(response))

    assert body.startswith('retry: 1500\n: connected\n\n')
    assert f'id: {cursor_for(stored_first)}' in body
    assert 'event: resources.changed' in body
    assert '"resources":["claim"]' in body
    assert 'event: resync_required' in body
    assert '"reason":"replay_window_exceeded"' in body
    assert dispatcher._subscriptions == set()


def test_realtime_stream_preserves_legacy_claim_updated_shape() -> None:
    repository = FixtureRepository()
    anchor = _event(0)
    changed = _event(1)
    repository.append_realtime_event(anchor)
    repository.append_realtime_event(changed)
    dispatcher = RealtimeDispatcher(repository)
    request = _StreamRequest(dispatcher, disconnect_after=0)

    response = realtime_stream(
        cast(Request, request),
        Principal(subject='cus_one', actor_type='claimant'),
        cursor=cursor_for(anchor),
        claim_id='clm_one',
        legacy_session_id='ses_one',
        legacy_after_revision=1,
        legacy_current_revision=2,
    )
    body = asyncio.run(_stream_body(response))

    assert body.count('event: claim.updated') == 2
    assert 'id: 2' in body
    assert '"session_id":"ses_one"' in body
    assert '"resources":["claim","messages"]' in body


def test_legacy_claim_route_treats_last_event_id_as_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(claims_api, 'repository_for', lambda request: object())
    monkeypatch.setattr(
        claims_api,
        'claimant_event_revision',
        lambda repository, principal, claim_id, session_id: 4,
    )

    def capture_stream(request: object, principal: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(claims_api, 'realtime_stream', capture_stream)

    result = claims_api.read_claim_events(
        'clm_one',
        'ses_one',
        cast(Request, SimpleNamespace()),
        Principal(subject='cus_one', actor_type='claimant'),
        after_revision=0,
        last_event_id='4',
    )

    assert result is not None
    assert captured['cursor'] is None
    assert captured['legacy_after_revision'] == 4
    assert captured['legacy_current_revision'] == 4


class _LiveSubscription:
    def __init__(self, deliveries: list[RealtimeDelivery | None]) -> None:
        self._deliveries = iter(deliveries)
        self.closed = False

    def next(self, timeout: float) -> RealtimeDelivery | None:
        assert timeout == 15.0
        return next(self._deliveries)

    def close(self) -> None:
        self.closed = True


class _LiveDispatcher:
    def __init__(self, deliveries: list[RealtimeDelivery | None]) -> None:
        self.subscription = _LiveSubscription(deliveries)

    def subscribe(self, scope: RealtimeScope) -> _LiveSubscription:
        assert scope == RealtimeScope(RealtimeAudience.STAFF, 'stf_one')
        return self.subscription

    def replay(self, scope: RealtimeScope, cursor: str | None) -> list[RealtimeDelivery]:
        assert cursor is None
        return []

    def unsubscribe(self, subscription: _LiveSubscription) -> None:
        assert subscription is self.subscription
        subscription.close()


def test_realtime_stream_heartbeats_and_stops_after_live_resync() -> None:
    dispatcher = _LiveDispatcher(
        [
            None,
            RealtimeDelivery(event='resync_required', data={'reason': 'event_source_unavailable'}),
        ]
    )
    request = _StreamRequest(dispatcher)

    response = realtime_stream(
        cast(Request, request),
        Principal(subject='stf_one', actor_type='staff'),
        cursor=None,
    )
    body = asyncio.run(_stream_body(response))

    assert ': keep-alive\n\n' in body
    assert 'event: resync_required' in body
    assert '"reason":"event_source_unavailable"' in body
    assert dispatcher.subscription.closed is True
