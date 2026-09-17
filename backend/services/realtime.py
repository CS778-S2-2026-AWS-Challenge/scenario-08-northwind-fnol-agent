"""Process-level durable-event dispatch and role-safe replay."""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread
from time import monotonic

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


class RealtimeDispatcherState(str, Enum):
    STARTING = 'starting'
    READY = 'ready'
    SOURCE_DEGRADED = 'source_degraded'
    GAP_RECOVERING = 'gap_recovering'
    STOPPING = 'stopping'
    STOPPED = 'stopped'


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
        durable_poll_seconds: float = 1.0,
        source_retry_seconds: float = 1.0,
        startup_timeout_seconds: float = 5.0,
    ) -> None:
        self._repository = repository
        self._queue_capacity = queue_capacity
        self._replay_limit = replay_limit
        self._durable_poll_seconds = durable_poll_seconds
        self._source_retry_seconds = source_retry_seconds
        self._startup_timeout_seconds = startup_timeout_seconds
        self._subscriptions: set[RealtimeSubscription] = set()
        self._lock = RLock()
        self._stop = Event()
        self._wake = Event()
        self._ready = Event()
        self._thread: Thread | None = None
        self._source_thread: Thread | None = None
        self._processed_cursor: str | None = None
        self._state = RealtimeDispatcherState.STOPPED
        self._recovery_reason: str | None = None

    @property
    def state(self) -> RealtimeDispatcherState:
        with self._lock:
            return self._state

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._wake.clear()
            self._ready.clear()
            self._state = RealtimeDispatcherState.STARTING
            self._recovery_reason = None
            self._thread = Thread(target=self._run, name='realtime-dispatcher', daemon=True)
            self._thread.start()
        if not self._ready.wait(self._startup_timeout_seconds):
            self.stop()
            raise RuntimeError('Realtime durable replay did not become ready before startup.')

    def stop(self) -> None:
        with self._lock:
            self._state = RealtimeDispatcherState.STOPPING
            subscriptions = tuple(self._subscriptions)
            self._subscriptions.clear()
            thread = self._thread
            source_thread = self._source_thread
        self._stop.set()
        self._wake.set()
        for subscription in subscriptions:
            subscription.close()
        if thread is not None:
            thread.join(timeout=2)
        if source_thread is not None:
            source_thread.join(timeout=2)
        with self._lock:
            self._state = RealtimeDispatcherState.STOPPED

    def subscribe(self, scope: RealtimeScope) -> RealtimeSubscription:
        subscription = RealtimeSubscription(scope, capacity=self._queue_capacity)
        with self._lock:
            if self._state in {
                RealtimeDispatcherState.READY,
                RealtimeDispatcherState.SOURCE_DEGRADED,
            }:
                self._subscriptions.add(subscription)
                return subscription
            reason = (
                self._recovery_reason
                or {
                    RealtimeDispatcherState.STARTING: 'dispatcher_starting',
                    RealtimeDispatcherState.GAP_RECOVERING: 'durable_replay_gap',
                    RealtimeDispatcherState.STOPPING: 'dispatcher_stopping',
                    RealtimeDispatcherState.STOPPED: 'dispatcher_unavailable',
                }[self._state]
            )
        subscription.require_resync(reason)
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
        try:
            high_watermark = self._repository.realtime_high_watermark()
            self._processed_cursor = (
                cursor_for(high_watermark) if high_watermark is not None else None
            )
            self._transition(RealtimeDispatcherState.READY)
            self._ready.set()
        except Exception:
            logger.exception('Realtime durable high watermark is unavailable at startup.')
            return

        next_source_start = 0.0
        while not self._stop.is_set():
            source_thread = self._source_thread
            if (
                source_thread is None or not source_thread.is_alive()
            ) and monotonic() >= next_source_start:
                source_thread = Thread(
                    target=self._watch_source,
                    name='realtime-event-source',
                    daemon=True,
                )
                with self._lock:
                    self._source_thread = source_thread
                source_thread.start()
                next_source_start = monotonic() + self._source_retry_seconds
            try:
                recovering = self.state is RealtimeDispatcherState.GAP_RECOVERING
                self._drain_durable_events(publish=not recovering)
                if recovering:
                    self._transition(RealtimeDispatcherState.READY)
            except ValueError:
                logger.exception('Realtime durable cursor cannot be resumed.')
                self._begin_recovery('durable_replay_gap')
                self._processed_cursor = None
                try:
                    self._drain_durable_events(publish=False)
                    self._transition(RealtimeDispatcherState.READY)
                except Exception:
                    logger.exception('Realtime durable cursor recovery failed.')
            except Exception:
                logger.exception('Realtime durable replay stopped unexpectedly.')
                self._begin_recovery('durable_event_store_unavailable')
            self._wake.wait(self._durable_poll_seconds)
            self._wake.clear()

    def _watch_source(self) -> None:
        """Use the provider stream only as a low-latency durable-drain wake-up hint."""

        try:
            for _event in self._repository.watch_realtime_events(self._stop):
                if self._stop.is_set():
                    return
                self._mark_source_ready()
                self._wake.set()
            if not self._stop.is_set():
                logger.warning('Realtime repository subscription ended unexpectedly.')
                self._transition(RealtimeDispatcherState.SOURCE_DEGRADED)
        except Exception:
            if not self._stop.is_set():
                logger.exception('Realtime repository subscription stopped unexpectedly.')
                self._transition(RealtimeDispatcherState.SOURCE_DEGRADED)

    def _drain_durable_events(self, *, publish: bool = True) -> None:
        while not self._stop.is_set():
            after = (
                RealtimeCursor.decode(self._processed_cursor)
                if self._processed_cursor is not None
                else None
            )
            events = self._repository.replay_realtime_events(after, limit=self._replay_limit)
            if not events:
                return
            for event in events:
                event_cursor = cursor_for(event)
                if not cursor_is_after(event_cursor, self._processed_cursor):
                    continue
                if publish:
                    self._publish(event)
                self._processed_cursor = event_cursor
            if len(events) < self._replay_limit:
                return

    def _publish(self, event: RealtimeEvent) -> None:
        with self._lock:
            subscriptions = tuple(self._subscriptions)
        for subscription in subscriptions:
            subscription.offer(event)

    def _require_resync(self, reason: str) -> None:
        with self._lock:
            subscriptions = tuple(self._subscriptions)
        for subscription in subscriptions:
            subscription.require_resync(reason)

    def _begin_recovery(self, reason: str) -> None:
        with self._lock:
            self._state = RealtimeDispatcherState.GAP_RECOVERING
            self._recovery_reason = reason
            subscriptions = tuple(self._subscriptions)
        for subscription in subscriptions:
            subscription.require_resync(reason)

    def _transition(self, state: RealtimeDispatcherState) -> None:
        with self._lock:
            if self._state in {
                RealtimeDispatcherState.STOPPING,
                RealtimeDispatcherState.STOPPED,
            }:
                return
            if (
                self._state is RealtimeDispatcherState.GAP_RECOVERING
                and state is RealtimeDispatcherState.SOURCE_DEGRADED
            ):
                return
            self._state = state
            if state is not RealtimeDispatcherState.GAP_RECOVERING:
                self._recovery_reason = None

    def _mark_source_ready(self) -> None:
        with self._lock:
            if self._state is RealtimeDispatcherState.SOURCE_DEGRADED:
                self._state = RealtimeDispatcherState.READY
