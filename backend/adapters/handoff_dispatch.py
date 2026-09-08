from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from backend.domain.models import HandoffDeliveryState, HandoffRecord, IntegrationSource


class HandoffDispatchUnavailable(Exception):
    """The staff notification service could not accept the handoff.

    This is a delivery failure, not a claim failure. The handoff is already
    durable when dispatch runs, so this never invalidates the request.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class HandoffDispatchReceipt:
    state: HandoffDeliveryState
    dispatch_reference: str | None
    limitations: tuple[str, ...]


class HandoffDispatchAdapter(Protocol):
    """Stable notification boundary implemented by a fixture now and a queue later."""

    integration_source: IntegrationSource

    def dispatch(self, handoff: HandoffRecord) -> HandoffDispatchReceipt:
        raise NotImplementedError

    def connection_status(self) -> str:
        raise NotImplementedError


LOCAL_QUEUE_LIMITATION = (
    'The staff notification service is unavailable. The request is saved and is '
    'already visible to the claims team.'
)


class MockHandoffDispatchAdapter(HandoffDispatchAdapter):
    """Deterministic fixture dispatch with a controllable outage.

    Dispatch is keyed by handoff so a retried support request cannot notify the
    staff queue twice for the same handoff.
    """

    integration_source = IntegrationSource.FIXTURE

    def __init__(self, outage: HandoffDispatchUnavailable | None = None) -> None:
        self._outage = outage
        self._dispatched: dict[str, HandoffDispatchReceipt] = {}

    def reset_demo_state(self) -> dict[str, int]:
        cleared = {'mock_handoff_dispatches': len(self._dispatched)}
        self._dispatched.clear()
        self._outage = None
        return cleared

    def set_outage(self, outage: HandoffDispatchUnavailable | None) -> None:
        self._outage = outage

    def connection_status(self) -> str:
        return 'unavailable' if self._outage is not None else 'using_fixture'

    def dispatch(self, handoff: HandoffRecord) -> HandoffDispatchReceipt:
        existing = self._dispatched.get(handoff.handoff_id)
        if existing is not None:
            return existing
        if self._outage is not None:
            raise self._outage

        digest = sha256(handoff.handoff_id.encode('utf-8')).hexdigest()[:8]
        receipt = HandoffDispatchReceipt(
            state=HandoffDeliveryState.DELIVERED,
            dispatch_reference=f'dsp_fixture_{digest}',
            limitations=(),
        )
        self._dispatched[handoff.handoff_id] = receipt
        return receipt


def local_queue_receipt() -> HandoffDispatchReceipt:
    """Fallback used when dispatch fails; the workbench queue is the source of truth."""

    return HandoffDispatchReceipt(
        state=HandoffDeliveryState.QUEUED_LOCALLY,
        dispatch_reference=None,
        limitations=(LOCAL_QUEUE_LIMITATION,),
    )
