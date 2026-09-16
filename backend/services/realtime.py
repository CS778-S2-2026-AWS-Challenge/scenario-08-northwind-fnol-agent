"""Process-level durable-event dispatch and role-safe replay."""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread

from backend.core.auth import Principal
from backend.domain.realtime import (
    RealtimeAudience,
    RealtimeCursor,
    RealtimeDelivery,
    RealtimeEvent,
    cursor_for,
    cursor_is_after,
)
from backend.repositories.protocols import PersistenceRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ResyncSignal:
    reason: str


@dataclass(frozen=True, slots=True)
class RealtimeScope:
    audience: RealtimeAudience
    subject: str
    claim_id: str | None = None

    def permits(self, event: RealtimeEvent) -> bool:
        if self.audience not in event.audiences:
            return False
        if self.audience is RealtimeAudience.CLAIMANT and event.customer_id != self.subject:
            return False
        return self.claim_id is None or event.claim_id == self.claim_id


class RealtimeSubscription:
    def __init__(self, scope: RealtimeScope, *, capacity: int) -> None:
        self.scope = scope
        self._queue: Queue[RealtimeEvent | _ResyncSignal] = Queue(maxsize=capacity)
        self._closed = Event()
        self._latest_cursor: str | None = None

    def offer(self, event: RealtimeEvent) -> None:
        if self._closed.is_set() or not self.scope.permits(event):
            return
        event_cursor = cursor_for(event)
        if not cursor_is_after(event_cursor, self._latest_cursor):
            return
        self._latest_cursor = event_cursor
        try:
            self._queue.put_nowait(event)
        except Full:
            while True:
                try:
                    self._queue.get_nowait()
                except Empty:
                    break
            self._queue.put_nowait(_ResyncSignal('subscriber_overflow'))

    def require_resync(self, reason: str) -> None:
        if self._closed.is_set():
            return
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                break
        with suppress(Full):
            self._queue.put_nowait(_ResyncSignal(reason))

    def next(self, timeout: float) -> RealtimeDelivery | None:
        if self._closed.is_set():
            return None
        try:
            item = self._queue.get(timeout=timeout)
        except Empty:
            return None
        if isinstance(item, _ResyncSignal):
            return RealtimeDelivery(event='resync_required', data={'reason': item.reason})
        assert isinstance(item, RealtimeEvent)
        return delivery_for(item, self.scope.audience)

    def close(self) -> None:
        self._closed.set()


def scope_for(principal: Principal, *, claim_id: str | None = None) -> RealtimeScope:
    if principal.actor_type == 'claimant':
        return RealtimeScope(RealtimeAudience.CLAIMANT, principal.subject, claim_id)
    if principal.actor_type == 'staff':
        return RealtimeScope(RealtimeAudience.STAFF, principal.subject, claim_id)
    raise ValueError('Realtime streams support claimant and staff principals only.')


def delivery_for(event: RealtimeEvent, audience: RealtimeAudience) -> RealtimeDelivery:
    resources = (
        event.claimant_resources if audience is RealtimeAudience.CLAIMANT else event.resources
    )
    data: dict[str, object] = {
        'event_id': event.event_id,
        'claim_id': event.claim_id,
        'claim_revision': event.claim_revision,
        'resources': [resource.value for resource in resources],
        'occurred_at': event.occurred_at.isoformat(),
    }
    if audience is RealtimeAudience.STAFF:
        data['operation_correlation'] = event.operation_correlation
    return RealtimeDelivery(event='resources.changed', cursor=cursor_for(event), data=data)


class RealtimeDispatcher:
    """Fan out one repository event source to bounded browser subscriptions."""

    def __init__(
        self,
        repository: PersistenceRepository,
        *,
        queue_capacity: int = 100,
        replay_limit: int = 500,
    ) -> None:
        self._repository = repository
        self._queue_capacity = queue_capacity
        self._replay_limit = replay_limit
        self._subscriptions: set[RealtimeSubscription] = set()
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(target=self._run, name='realtime-dispatcher', daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            subscriptions = tuple(self._subscriptions)
            self._subscriptions.clear()
            thread = self._thread
        for subscription in subscriptions:
            subscription.close()
        if thread is not None:
            thread.join(timeout=2)

    def subscribe(self, scope: RealtimeScope) -> RealtimeSubscription:
        subscription = RealtimeSubscription(scope, capacity=self._queue_capacity)
        with self._lock:
            self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: RealtimeSubscription) -> None:
        with self._lock:
            self._subscriptions.discard(subscription)
        subscription.close()

    def replay(
        self,
        scope: RealtimeScope,
        cursor: str | None,
    ) -> list[RealtimeDelivery]:
        if cursor is None:
            return []
        after = RealtimeCursor.decode(cursor) if cursor else None
        events = self._repository.replay_realtime_events(after, limit=self._replay_limit + 1)
        window_exceeded = len(events) > self._replay_limit
        deliveries = [
            delivery_for(event, scope.audience)
            for event in events[: self._replay_limit]
            if scope.permits(event)
        ]
        if window_exceeded:
            deliveries.append(
                RealtimeDelivery(
                    event='resync_required',
                    data={'reason': 'replay_window_exceeded'},
                )
            )
        return deliveries

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                for event in self._repository.watch_realtime_events(self._stop):
                    if self._stop.is_set():
                        return
                    with self._lock:
                        subscriptions = tuple(self._subscriptions)
                    for subscription in subscriptions:
                        subscription.offer(event)
                if self._stop.is_set():
                    return
                raise RuntimeError('Realtime repository subscription ended unexpectedly.')
            except Exception:
                logger.exception('Realtime repository subscription stopped unexpectedly.')
                with self._lock:
                    subscriptions = tuple(self._subscriptions)
                for subscription in subscriptions:
                    subscription.require_resync('event_source_unavailable')
                self._stop.wait(1.0)
