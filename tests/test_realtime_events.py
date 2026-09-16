from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from fastapi.testclient import TestClient

from backend.core.auth import Principal
from backend.domain.realtime import (
    RealtimeAudience,
    RealtimeCursor,
    RealtimeEvent,
    RealtimeResource,
    cursor_for,
    new_realtime_event,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.realtime import RealtimeDispatcher, RealtimeScope, RealtimeSubscription

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

    assert replay == [second]
    with pytest.raises(ValueError, match='outside the available replay window'):
        repository.replay_realtime_events(
            RealtimeCursor(occurred_at=NOW, event_id='rte_00000000000000000000'),
            limit=10,
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

    monkeypatch.setattr('backend.repositories.fixture.new_realtime_event', fail_event)

    with pytest.raises(RuntimeError, match='event construction failed'):
        client.post(
            '/api/v1/claims',
            headers={**auth_headers, 'Idempotency-Key': 'realtime-atomic-failure'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
        )

    assert repository.claim_count == 0
    assert repository.replay_realtime_events(None, limit=10) == []


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
