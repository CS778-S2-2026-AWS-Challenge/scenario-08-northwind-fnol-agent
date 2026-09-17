from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from queue import Queue
from threading import Event, Thread
from time import monotonic, sleep
from types import SimpleNamespace
from typing import cast

import mongomock
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api import claims as claims_api
from backend.api.realtime import realtime_stream
from backend.core.auth import Principal
from backend.domain.realtime import (
    AUTHORITATIVE_RECORD_PROJECTION_IMPACTS,
    REALTIME_MUTATION_RESOURCES,
    REALTIME_RESOURCE_READ_APIS,
    RealtimeAudience,
    RealtimeCursor,
    RealtimeDelivery,
    RealtimeEvent,
    RealtimeMutation,
    RealtimePublication,
    RealtimeResource,
    cursor_for,
    cursor_is_after,
    realtime_publication_for,
    realtime_resources_for_records,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services.realtime import (
    RealtimeDispatcher,
    RealtimeDispatcherState,
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
    safe_resources = tuple(
        resource
        for resource in resources
        if resource
        in {
            RealtimeResource.CLAIM,
            RealtimeResource.MESSAGES,
            RealtimeResource.EVIDENCE,
            RealtimeResource.HANDOFFS,
            RealtimeResource.EXTERNAL_TASKS,
        }
    )
    visible = safe_resources if claimant_resources is None else claimant_resources
    return RealtimeEvent(
        event_id=f'rte_{suffix:020x}',
        claim_id='clm_one',
        customer_id=customer_id,
        occurred_at=NOW + timedelta(seconds=suffix),
        claim_revision=suffix + 1,
        resources=resources,
        claimant_resources=visible,
        audiences=(
            (RealtimeAudience.CLAIMANT, RealtimeAudience.STAFF)
            if visible
            else (RealtimeAudience.STAFF,)
        ),
    )


def _publication(
    suffix: int,
    *,
    mutation: RealtimeMutation = RealtimeMutation.CLAIM_OWNER_CHANGED,
    customer_id: str = 'cus_one',
    claimant_resources: tuple[RealtimeResource, ...] | None = None,
) -> RealtimePublication:
    return realtime_publication_for(
        mutation=mutation,
        claim_id='clm_one',
        customer_id=customer_id,
        claim_revision=suffix + 1,
        operation_correlation=f'op_{suffix}',
        claimant_resources=claimant_resources,
    )


def test_cursor_round_trip_preserves_stable_ordering_coordinates() -> None:
    event = _event(1)

    cursor = RealtimeCursor.decode(cursor_for(event))

    assert cursor.event_id == event.event_id
    assert cursor.occurred_at == event.occurred_at


def test_cursor_round_trip_preserves_mongo_commit_sequence() -> None:
    event = _event(1).model_copy(update={'occurred_at': NOW, 'sequence': 7})

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
    first = repository.append_realtime_publication(_publication(1))
    second = repository.append_realtime_publication(_publication(2))

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
    first = repository.append_realtime_publication(_publication(1))
    second = repository.append_realtime_publication(_publication(2))
    rolled_back_clock = repository.append_realtime_publication(_publication(3))

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


@pytest.fixture(params=('fixture', 'mongo'))
def realtime_repository(request: pytest.FixtureRequest) -> PersistenceRepository:
    if request.param == 'fixture':
        return FixtureRepository()
    repository = MongoDBRepository(mongomock.MongoClient(), 'realtime_contract')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


def test_realtime_publication_coordinates_are_repository_owned_across_adapters(
    realtime_repository: PersistenceRepository,
) -> None:
    first = realtime_repository.append_realtime_publication(_publication(1))
    stored_first = realtime_repository.replay_realtime_events(None, limit=10)[0]
    first_cursor = cursor_for(stored_first)

    second = realtime_repository.append_realtime_publication(_publication(2))
    stored = realtime_repository.replay_realtime_events(None, limit=10)
    assert first == stored_first
    assert first.event_id != second.event_id
    assert [event.sequence for event in stored] == [1, 2]
    assert realtime_repository.realtime_high_watermark() == second
    assert realtime_repository.replay_realtime_events(
        RealtimeCursor.decode(first_cursor),
        limit=10,
    ) == [stored[1]]


@pytest.mark.parametrize('mutation', tuple(RealtimeMutation))
def test_registered_mutation_projection_is_equivalent_across_adapters(
    realtime_repository: PersistenceRepository,
    mutation: RealtimeMutation,
) -> None:
    publication = realtime_publication_for(
        mutation=mutation,
        claim_id='clm_registry_matrix',
        customer_id='cus_registry_matrix',
        claim_revision=3,
        operation_correlation='staff-operation',
    )

    event = realtime_repository.append_realtime_publication(publication)
    replay = realtime_repository.replay_realtime_events(None, limit=10)

    assert replay == [event]
    assert event.resources == REALTIME_MUTATION_RESOURCES[mutation]
    assert event.event_id.startswith('rte_')
    assert event.sequence == 1
    staff = delivery_for(event, RealtimeAudience.STAFF)
    claimant = delivery_for(event, RealtimeAudience.CLAIMANT)
    assert staff.data['resources'] == [resource.value for resource in event.resources]
    assert staff.data['operation_correlation'] == 'staff-operation'
    claimant_resources = cast(list[str], claimant.data['resources'])
    assert set(claimant_resources).isdisjoint({'queue', 'work_items'})
    assert 'operation_correlation' not in claimant.data


def test_composite_resource_inventory_tracks_concrete_agent_children() -> None:
    resources = realtime_resources_for_records(
        RealtimeMutation.AGENT_TURN_COMMITTED,
        ('message', 'evidence', 'handoff', 'runtime_work_item'),
    )

    assert resources == (
        RealtimeResource.CLAIM,
        RealtimeResource.MESSAGES,
        RealtimeResource.EVIDENCE,
        RealtimeResource.HANDOFFS,
        RealtimeResource.WORK_ITEMS,
        RealtimeResource.QUEUE,
    )
    publication = realtime_publication_for(
        mutation=RealtimeMutation.AGENT_TURN_COMMITTED,
        claim_id='clm_composite',
        customer_id='cus_composite',
        resources=resources,
    )
    assert publication.resources == resources

    with pytest.raises(ValidationError, match='required mutation projection'):
        publication.model_copy(update={'resources': (RealtimeResource.EVIDENCE,)}).model_validate(
            {
                **publication.model_dump(),
                'resources': (RealtimeResource.EVIDENCE,),
                'claimant_resources': (RealtimeResource.EVIDENCE,),
            }
        )


def test_public_projection_matrix_covers_every_resource_and_independent_staff_reads() -> None:
    assert set(REALTIME_RESOURCE_READ_APIS) == set(RealtimeResource)
    assert AUTHORITATIVE_RECORD_PROJECTION_IMPACTS['customer_update'] == (
        RealtimeResource.CUSTOMER_UPDATES,
    )
    assert AUTHORITATIVE_RECORD_PROJECTION_IMPACTS['signal_decision'] == (RealtimeResource.SIGNALS,)
    assert AUTHORITATIVE_RECORD_PROJECTION_IMPACTS['collaboration_request'] == (
        RealtimeResource.COLLABORATION_REQUESTS,
    )
    assert AUTHORITATIVE_RECORD_PROJECTION_IMPACTS['claim_asset_snapshot'] == (
        RealtimeResource.ASSET_SNAPSHOTS,
    )
    with pytest.raises(ValueError, match='missing from the projection-impact matrix'):
        realtime_resources_for_records(
            RealtimeMutation.AGENT_TURN_COMMITTED,
            ('unregistered_child',),
        )


@pytest.mark.parametrize(
    'resources',
    [
        (
            RealtimeResource.CLAIM,
            RealtimeResource.MESSAGES,
            RealtimeResource.EVIDENCE,
            RealtimeResource.QUEUE,
        ),
        (
            RealtimeResource.MESSAGES,
            RealtimeResource.CLAIM,
            RealtimeResource.QUEUE,
        ),
    ],
)
def test_publication_rejects_unregistered_or_noncanonical_resources(
    resources: tuple[RealtimeResource, ...],
) -> None:
    claimant_resources = tuple(
        resource for resource in resources if resource is not RealtimeResource.QUEUE
    )

    with pytest.raises(ValidationError, match='mutation contract|canonical registry order'):
        RealtimePublication(
            mutation=RealtimeMutation.MESSAGE_MUTATION_COMMITTED,
            claim_id='clm_invalid_resources',
            customer_id='cus_invalid_resources',
            resources=resources,
            claimant_resources=claimant_resources,
            audiences=(RealtimeAudience.CLAIMANT, RealtimeAudience.STAFF),
        )


def test_scope_rejects_event_without_requested_audience() -> None:
    claimant_scope = RealtimeScope(RealtimeAudience.CLAIMANT, 'cus_one')
    staff_only = _event(1).model_copy(
        update={
            'claimant_resources': (),
            'audiences': (RealtimeAudience.STAFF,),
        }
    )

    assert claimant_scope.permits(staff_only) is False


def test_fixture_replay_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError, match='between 1 and 1000'):
        FixtureRepository().replay_realtime_events(None, limit=0)


def test_claimant_scope_filters_customer_and_internal_message_resources() -> None:
    dispatcher = RealtimeDispatcher(FixtureRepository())
    scope = RealtimeScope(RealtimeAudience.CLAIMANT, 'cus_one')
    anchor = dispatcher._repository.append_realtime_publication(_publication(0))
    dispatcher._repository.append_realtime_publication(
        _publication(
            1,
            mutation=RealtimeMutation.AGENT_TURN_COMMITTED,
            claimant_resources=(RealtimeResource.CLAIM,),
        )
    )
    dispatcher._repository.append_realtime_publication(_publication(2, customer_id='cus_two'))

    deliveries = dispatcher.replay(scope, cursor_for(anchor))

    assert len(deliveries) == 1
    assert deliveries[0].data['claim_id'] == 'clm_one'
    assert deliveries[0].data['resources'] == ['claim']


def test_claimant_delivery_filters_staff_resources_and_correlation() -> None:
    event = RealtimeEvent(
        event_id='rte_aaaaaaaaaaaaaaaaaaaa',
        claim_id='clm_one',
        customer_id='cus_one',
        occurred_at=NOW,
        resources=(
            RealtimeResource.CLAIM,
            RealtimeResource.QUEUE,
            RealtimeResource.WORK_ITEMS,
        ),
        claimant_resources=(RealtimeResource.CLAIM,),
        audiences=(RealtimeAudience.CLAIMANT, RealtimeAudience.STAFF),
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
    sequenced = _event(2).model_copy(
        update={'occurred_at': legacy.occurred_at - timedelta(seconds=10), 'sequence': 1}
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
        self.available = False
        self.release_watch = Event()

    def realtime_high_watermark(self) -> RealtimeEvent | None:
        return None

    def replay_realtime_events(
        self, after: RealtimeCursor | None, *, limit: int
    ) -> list[RealtimeEvent]:
        if after is None and self.available:
            return [self.event][:limit]
        return []

    def watch_realtime_events(self, stop: Event) -> Iterator[RealtimeEvent]:
        self.watch_calls += 1
        if self.fail:
            raise RuntimeError('source unavailable')
        self.release_watch.wait(1.0)
        self.available = True
        yield self.event
        stop.wait(0.2)


def test_dispatcher_uses_one_watcher_for_multiple_subscribers() -> None:
    source = _SingleEventSource(_event(1))
    dispatcher = RealtimeDispatcher(source)  # type: ignore[arg-type]
    dispatcher.start()
    try:
        first = dispatcher.subscribe(RealtimeScope(RealtimeAudience.STAFF, 'stf_one'))
        second = dispatcher.subscribe(RealtimeScope(RealtimeAudience.STAFF, 'stf_two'))
        source.release_watch.set()
        assert first.next(1.0) is not None
        assert second.next(1.0) is not None
        assert source.watch_calls == 1
    finally:
        dispatcher.stop()


def test_dispatcher_source_failure_still_drains_durable_event() -> None:
    source = _SingleEventSource(_event(1), fail=True)
    dispatcher = RealtimeDispatcher(
        source,  # type: ignore[arg-type]
        durable_poll_seconds=0.01,
        source_retry_seconds=0.01,
    )
    dispatcher.start()
    try:
        subscription = dispatcher.subscribe(RealtimeScope(RealtimeAudience.STAFF, 'stf_one'))
        source.available = True
        dispatcher._wake.set()
        delivery = subscription.next(1.0)
        assert delivery is not None
        assert delivery.event == 'resources.changed'
        assert delivery.data['claim_revision'] == 2
    finally:
        dispatcher.stop()


class _DurableHintSource:
    def __init__(self, events: list[RealtimeEvent] | None = None) -> None:
        self.events = list(events or [])
        self.watch_started = Event()
        self.fail_watch = False
        self.invalidate_anchor = False
        self.replay_calls = 0

    def realtime_high_watermark(self) -> RealtimeEvent | None:
        return self.events[-1] if self.events else None

    def replay_realtime_events(
        self, after: RealtimeCursor | None, *, limit: int
    ) -> list[RealtimeEvent]:
        self.replay_calls += 1
        if after is not None and self.invalidate_anchor:
            raise ValueError('cursor outside retained history')
        start = 0
        if after is not None:
            start = next(
                index + 1
                for index, event in enumerate(self.events)
                if event.event_id == after.event_id
            )
        return self.events[start : start + limit]

    def watch_realtime_events(self, stop: Event) -> Iterator[RealtimeEvent]:
        self.watch_started.set()
        if self.fail_watch:
            raise RuntimeError('source unavailable')
        stop.wait(1.0)
        return
        yield  # pragma: no cover


class _BlockedReplaySource(_DurableHintSource):
    def realtime_high_watermark(self) -> RealtimeEvent | None:
        Event().wait(0.05)
        return None


class _BlockingGapRecoverySource(_DurableHintSource):
    def __init__(self, events: list[RealtimeEvent]) -> None:
        super().__init__(events)
        self.trigger_gap = False
        self.recovery_started = Event()
        self.release_recovery = Event()

    def replay_realtime_events(
        self, after: RealtimeCursor | None, *, limit: int
    ) -> list[RealtimeEvent]:
        if after is not None and self.trigger_gap:
            self.trigger_gap = False
            raise ValueError('cursor outside retained history')
        if after is None and not self.release_recovery.is_set():
            self.recovery_started.set()
            self.release_recovery.wait(1.0)
        return super().replay_realtime_events(after, limit=limit)


def test_dispatcher_start_fails_when_durable_boundary_never_becomes_ready() -> None:
    dispatcher = RealtimeDispatcher(
        _BlockedReplaySource(),  # type: ignore[arg-type]
        startup_timeout_seconds=0.01,
    )

    with pytest.raises(RuntimeError, match='did not become ready'):
        dispatcher.start()


def test_dispatcher_start_anchors_at_tail_without_replaying_retained_history() -> None:
    source = _DurableHintSource([_event(index) for index in range(100)])
    dispatcher = RealtimeDispatcher(
        source,  # type: ignore[arg-type]
        durable_poll_seconds=1.0,
    )

    dispatcher.start()
    try:
        assert dispatcher.state is RealtimeDispatcherState.READY
        assert dispatcher._processed_cursor == cursor_for(source.events[-1])
        assert source.replay_calls <= 1
    finally:
        dispatcher.stop()


def test_dispatcher_closes_replay_to_watcher_start_gap() -> None:
    source = _DurableHintSource()
    dispatcher = RealtimeDispatcher(
        source,  # type: ignore[arg-type]
        durable_poll_seconds=0.01,
    )
    dispatcher.start()
    try:
        subscription = dispatcher.subscribe(RealtimeScope(RealtimeAudience.STAFF, 'stf_one'))
        assert source.watch_started.wait(1.0)
        assert dispatcher.replay(subscription.scope, None) == []
        source.events.append(_event(1))

        delivery = subscription.next(1.0)
        assert delivery is not None
        assert delivery.event == 'resources.changed'
        assert delivery.data['claim_revision'] == 2
    finally:
        dispatcher.stop()


def test_dispatcher_drains_commit_while_source_is_restarting() -> None:
    source = _DurableHintSource()
    source.fail_watch = True
    dispatcher = RealtimeDispatcher(
        source,  # type: ignore[arg-type]
        durable_poll_seconds=0.01,
        source_retry_seconds=0.01,
    )
    dispatcher.start()
    try:
        subscription = dispatcher.subscribe(RealtimeScope(RealtimeAudience.STAFF, 'stf_one'))
        assert source.watch_started.wait(1.0)
        source.events.append(_event(1))

        delivery = subscription.next(1.0)
        assert delivery is not None
        assert delivery.event == 'resources.changed'
        assert delivery.data['claim_revision'] == 2
    finally:
        dispatcher.stop()


def test_dispatcher_deduplicates_repeated_durable_observation() -> None:
    source = _DurableHintSource([_event(1)])
    dispatcher = RealtimeDispatcher(
        source,  # type: ignore[arg-type]
        durable_poll_seconds=0.01,
    )
    dispatcher.start()
    try:
        subscription = dispatcher.subscribe(RealtimeScope(RealtimeAudience.STAFF, 'stf_one'))
        source.events.append(_event(2))
        dispatcher._wake.set()
        assert subscription.next(1.0) is not None
        dispatcher._wake.set()
        assert subscription.next(0.05) is None
    finally:
        dispatcher.stop()


def test_dispatcher_requires_resync_when_durable_anchor_is_lost() -> None:
    source = _DurableHintSource([_event(1)])
    dispatcher = RealtimeDispatcher(
        source,  # type: ignore[arg-type]
        durable_poll_seconds=0.01,
    )
    dispatcher.start()
    try:
        subscription = dispatcher.subscribe(RealtimeScope(RealtimeAudience.STAFF, 'stf_one'))
        source.invalidate_anchor = True
        source.events.append(_event(2))

        delivery = subscription.next(1.0)
        assert delivery is not None
        assert delivery.event == 'resync_required'
        assert delivery.data == {'reason': 'durable_replay_gap'}
    finally:
        dispatcher.stop()


def test_subscriptions_before_during_and_after_gap_recovery_have_closed_semantics() -> None:
    source = _BlockingGapRecoverySource([_event(1)])
    dispatcher = RealtimeDispatcher(source, durable_poll_seconds=0.01)  # type: ignore[arg-type]
    dispatcher.start()
    try:
        existing = dispatcher.subscribe(RealtimeScope(RealtimeAudience.STAFF, 'stf_existing'))
        source.trigger_gap = True
        source.events.append(_event(2))
        dispatcher._wake.set()
        assert source.recovery_started.wait(1.0)
        assert dispatcher.state is RealtimeDispatcherState.GAP_RECOVERING

        arriving = dispatcher.subscribe(RealtimeScope(RealtimeAudience.STAFF, 'stf_new'))
        existing_delivery = existing.next(0.1)
        arriving_delivery = arriving.next(0.1)

        assert existing_delivery is not None
        assert existing_delivery.data == {'reason': 'durable_replay_gap'}
        assert arriving_delivery is not None
        assert arriving_delivery.data == {'reason': 'durable_replay_gap'}
        assert arriving not in dispatcher._subscriptions

        source.release_recovery.set()
        deadline = monotonic() + 1.0
        while dispatcher.state is not RealtimeDispatcherState.READY and monotonic() < deadline:
            sleep(0.01)
        assert dispatcher.state is RealtimeDispatcherState.READY

        after_recovery = dispatcher.subscribe(
            RealtimeScope(RealtimeAudience.STAFF, 'stf_after_recovery')
        )
        source.events.append(_event(3))
        dispatcher._wake.set()
        changed = after_recovery.next(1.0)
        assert changed is not None
        assert changed.event == 'resources.changed'
        assert changed.data['claim_revision'] == 4
    finally:
        dispatcher.stop()


def test_fixture_event_construction_failure_leaves_no_claim(
    client: TestClient,
    repository: FixtureRepository,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_event(*_: object, **__: object) -> RealtimeEvent:
        raise RuntimeError('event construction failed')

    with monkeypatch.context() as event_patch:
        event_patch.setattr(
            'backend.repositories.fixture.realtime_event_from_publication',
            fail_event,
        )
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
    for suffix in (0, 1, 2):
        repository.append_realtime_publication(_publication(suffix))
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
    anchor = repository.append_realtime_publication(_publication(0))
    repository.append_realtime_publication(_publication(1))
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
