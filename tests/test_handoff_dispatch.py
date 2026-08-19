from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.handoff_dispatch import (
    HandoffDispatchUnavailable,
    MockHandoffDispatchAdapter,
)
from backend.app import create_app
from backend.core.config import Settings
from backend.repositories.fixture import FixtureRepository

CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}

SUPPORT_PAYLOAD = {
    'reason': 'I want a person to continue this synthetic claim.',
    'support_need': 'human_requested',
    'preferred_channel': 'phone',
}


@pytest.fixture
def dispatch_adapter() -> MockHandoffDispatchAdapter:
    return MockHandoffDispatchAdapter()


@pytest.fixture
def dispatch_repository() -> FixtureRepository:
    return FixtureRepository()


@pytest.fixture
def dispatch_client(
    dispatch_repository: FixtureRepository,
    dispatch_adapter: MockHandoffDispatchAdapter,
) -> TestClient:
    app = create_app(
        Settings(),
        dispatch_repository,
        handoff_dispatch_adapter=dispatch_adapter,
    )
    return TestClient(app)


def create_claim(client: TestClient, key: str) -> str:
    response = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT_AUTH, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return str(cast(dict[str, Any], response.json()['claim'])['claim_id'])


def request_support(client: TestClient, claim_id: str, key: str, revision: int = 1) -> Any:
    return client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={**CLAIMANT_AUTH, 'Idempotency-Key': key, 'If-Match': str(revision)},
        json=SUPPORT_PAYLOAD,
    )


def staff_queue_entry(client: TestClient, claim_id: str) -> dict[str, Any] | None:
    listing = client.get('/api/v1/workbench/claims?view=all', headers=STAFF_AUTH)
    assert listing.status_code == 200
    return next(
        (item for item in listing.json()['items'] if item['claim_id'] == claim_id),
        None,
    )


def test_support_request_notifies_the_staff_queue_service(
    dispatch_client: TestClient,
) -> None:
    with dispatch_client as client:
        claim_id = create_claim(client, 'dispatch-ok-claim')
        response = request_support(client, claim_id, 'dispatch-ok-support')
        entry = staff_queue_entry(client, claim_id)

    assert response.status_code == 201
    assert response.json()['delivery'] == {'state': 'delivered', 'limitations': []}
    assert response.json()['revision'] == 2
    assert entry is not None


def test_notification_outage_keeps_the_request_its_state_and_the_staff_queue(
    dispatch_client: TestClient,
    dispatch_repository: FixtureRepository,
    dispatch_adapter: MockHandoffDispatchAdapter,
) -> None:
    dispatch_adapter.set_outage(
        HandoffDispatchUnavailable(
            code='DISPATCH_UNAVAILABLE',
            detail='The staff queue service refused the connection.',
        )
    )

    with dispatch_client as client:
        claim_id = create_claim(client, 'dispatch-outage-claim')
        response = request_support(client, claim_id, 'dispatch-outage-support')
        entry = staff_queue_entry(client, claim_id)
        readiness = client.get('/health/ready')

    # The claimant request still succeeds: dispatch runs after the handoff is
    # durable, so a notification outage degrades delivery, not the request.
    assert response.status_code == 201
    body = response.json()
    assert body['delivery']['state'] == 'queued_locally'
    assert body['delivery']['limitations'] == [
        'The staff notification service is unavailable. The request is saved and is '
        'already visible to the claims team.'
    ]
    assert body['revision'] == 2

    handoff_id = body['handoff']['handoff_id']
    stored = dispatch_repository.get_handoff(claim_id, handoff_id, 'cus_demo')
    claim = dispatch_repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    assert claim is not None
    assert claim.revision == 2

    # Nothing is lost: the Workbench queue is derived from persisted claim
    # state, so staff still see the handoff while dispatch is down.
    assert entry is not None
    assert entry['priority'] == stored.priority.value

    assert readiness.json()['checks']['handoff_dispatch'] == 'unavailable'


def test_retry_during_an_outage_does_not_duplicate_the_handoff_or_the_revision(
    dispatch_client: TestClient,
    dispatch_repository: FixtureRepository,
    dispatch_adapter: MockHandoffDispatchAdapter,
) -> None:
    dispatch_adapter.set_outage(
        HandoffDispatchUnavailable(code='DISPATCH_UNAVAILABLE', detail='Queue service is down.')
    )

    with dispatch_client as client:
        claim_id = create_claim(client, 'dispatch-retry-claim')
        first = request_support(client, claim_id, 'dispatch-retry-support')
        replay = request_support(client, claim_id, 'dispatch-retry-support')

        # The claimant asks again on a new key while the service is still down.
        repeat = request_support(client, claim_id, 'dispatch-retry-support-2', revision=2)

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert repeat.json()['handoff']['handoff_id'] == first.json()['handoff']['handoff_id']

    handoffs = dispatch_repository.list_handoffs(claim_id, 'cus_demo')
    claim = dispatch_repository.get_claim(claim_id, 'cus_demo')
    assert len(handoffs) == 1
    assert claim is not None
    assert claim.revision == 2


def test_recovered_service_delivers_without_notifying_the_same_handoff_twice(
    dispatch_client: TestClient,
    dispatch_adapter: MockHandoffDispatchAdapter,
) -> None:
    dispatch_adapter.set_outage(
        HandoffDispatchUnavailable(code='DISPATCH_UNAVAILABLE', detail='Queue service is down.')
    )

    with dispatch_client as client:
        claim_id = create_claim(client, 'dispatch-recovery-claim')
        degraded = request_support(client, claim_id, 'dispatch-recovery-support')
        dispatch_adapter.set_outage(None)
        recovered = request_support(client, claim_id, 'dispatch-recovery-support')
        second_claim_id = create_claim(client, 'dispatch-recovery-claim-2')
        fresh = request_support(client, second_claim_id, 'dispatch-recovery-support-2')

    assert degraded.json()['delivery']['state'] == 'queued_locally'
    assert recovered.json()['delivery']['state'] == 'delivered'
    assert fresh.json()['delivery']['state'] == 'delivered'


def test_demo_reset_clears_dispatch_state_and_restores_the_service(
    dispatch_client: TestClient,
    dispatch_adapter: MockHandoffDispatchAdapter,
) -> None:
    dispatch_adapter.set_outage(
        HandoffDispatchUnavailable(code='DISPATCH_UNAVAILABLE', detail='Queue service is down.')
    )

    with dispatch_client as client:
        claim_id = create_claim(client, 'dispatch-reset-claim')
        request_support(client, claim_id, 'dispatch-reset-support')
        reset = client.post('/api/v1/workbench/demo/reset', headers=STAFF_AUTH)
        readiness = client.get('/health/ready')

    assert reset.status_code == 200
    assert 'mock_handoff_dispatches' in reset.json()['cleared']
    assert readiness.json()['checks']['handoff_dispatch'] == 'using_fixture'
