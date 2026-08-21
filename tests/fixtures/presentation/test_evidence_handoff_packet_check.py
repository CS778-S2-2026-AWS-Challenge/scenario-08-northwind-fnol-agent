"""Issue #146, the `bdfa123` half: the evidence handoff packet.

@liyang6620 owns the handoff API, priority, retry, and fallback demonstration.
This is the independent check of the packet itself: does it carry the evidence
context staff need, does it survive an external failure, and does it keep an
urgent transfer moving while ordinary intake is still in progress.
"""

from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.handoff_dispatch import (
    HandoffDispatchUnavailable,
    MockHandoffDispatchAdapter,
)
from backend.app import create_app
from backend.core.config import Settings
from backend.domain.models import EvidenceSource, MessageVisibility
from backend.repositories.fixture import FixtureRepository
from backend.services.evidence_handoff import default_handoff_visibility

CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
CUSTOMER_ID = 'cus_demo'


@pytest.fixture
def dispatch() -> MockHandoffDispatchAdapter:
    return MockHandoffDispatchAdapter()


@pytest.fixture
def repository() -> FixtureRepository:
    return FixtureRepository()


@pytest.fixture
def client(
    repository: FixtureRepository,
    dispatch: MockHandoffDispatchAdapter,
) -> TestClient:
    return TestClient(create_app(Settings(), repository, handoff_dispatch_adapter=dispatch))


def create_claim(client: TestClient, key: str) -> str:
    response = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT_AUTH, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    return str(cast(dict[str, Any], response.json()['claim'])['claim_id'])


def register_pending_evidence(client: TestClient, claim_id: str, key: str, revision: int) -> str:
    response = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={**CLAIMANT_AUTH, 'Idempotency-Key': key, 'If-Match': str(revision)},
        json={
            'kind': 'police_report',
            'status': 'pending_generation',
            'related_fields': ['authorities.police_report_reference'],
            'needed_for': ['later_action'],
            'claimant_note': 'The report will be available next week.',
        },
    )
    assert response.status_code == 201
    return str(response.json()['evidence']['evidence_id'])


def request_support(
    client: TestClient,
    claim_id: str,
    key: str,
    revision: int,
    support_need: str = 'human_requested',
) -> Any:
    return client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={**CLAIMANT_AUTH, 'Idempotency-Key': key, 'If-Match': str(revision)},
        json={
            'reason': 'A person should continue this synthetic claim.',
            'support_need': support_need,
        },
    )


def stored_packet(repository: FixtureRepository, claim_id: str) -> Any:
    handoffs = repository.list_handoffs(claim_id, CUSTOMER_ID)
    assert len(handoffs) == 1
    return handoffs[0].packet


def test_the_packet_carries_the_evidence_context_staff_need(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    """Evidence still outstanding must reach the packet as a named gap."""
    with client as active:
        claim_id = create_claim(active, 'packet-context-claim')
        evidence_id = register_pending_evidence(active, claim_id, 'packet-context-evidence', 1)
        response = request_support(active, claim_id, 'packet-context-support', 2)

    assert response.status_code == 201
    packet = stored_packet(repository, claim_id)

    assert evidence_id in packet.evidence_refs
    # Evidence the claim is still waiting on is a gap, not just a reference.
    assert evidence_id in packet.pending_items

    item = next(entry for entry in packet.evidence if entry.evidence_id == evidence_id)
    assert item.kind == 'police_report'
    assert item.status.value == 'pending_generation'
    assert item.file_status.value == 'not_available'
    assert item.source is EvidenceSource.CLAIMANT
    assert item.related_fields == ['authorities.police_report_reference']
    assert item.claimant_note == 'The report will be available next week.'


def test_the_packet_classifies_visibility_by_source(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    """The packet and claimant projection consume the shared visibility rule."""
    with client as active:
        claim_id = create_claim(active, 'packet-visibility-claim')
        evidence_id = register_pending_evidence(active, claim_id, 'packet-visibility-evidence', 1)

        record = repository.get_evidence(claim_id, evidence_id, CUSTOMER_ID)
        assert record is not None
        staff_record = record.model_copy(
            update={
                'evidence_id': 'evd_staff_probe',
                'source': EvidenceSource.STAFF,
                'claimant_note': None,
            }
        )
        repository.save_evidence(staff_record, CUSTOMER_ID)

        request_support(active, claim_id, 'packet-visibility-support', 2)
        claimant_evidence = active.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH)

    packet = stored_packet(repository, claim_id)
    item = next(entry for entry in packet.evidence if entry.evidence_id == evidence_id)
    assert item.visibility is MessageVisibility.SHARED

    assert default_handoff_visibility(record) is MessageVisibility.SHARED

    staff_item = next(
        entry for entry in packet.evidence if entry.evidence_id == staff_record.evidence_id
    )
    assert default_handoff_visibility(staff_record) is MessageVisibility.INTERNAL_ONLY
    assert staff_item.visibility is MessageVisibility.INTERNAL_ONLY

    # No storage provenance is copied into the staff packet.
    assert not hasattr(item, 'provenance')
    assert not hasattr(staff_item, 'provenance')

    # The claimant projection uses the same source boundary below the route.
    assert claimant_evidence.status_code == 200
    assert {entry['evidence_id'] for entry in claimant_evidence.json()['items']} == {evidence_id}


def test_a_dispatch_outage_does_not_lose_the_packet_or_its_context(
    client: TestClient,
    repository: FixtureRepository,
    dispatch: MockHandoffDispatchAdapter,
) -> None:
    """Issue #146: external failure must not lose the request or its context."""
    dispatch.set_outage(
        HandoffDispatchUnavailable(
            code='DISPATCH_UNAVAILABLE',
            detail='The staff queue service refused the connection.',
        )
    )

    with client as active:
        claim_id = create_claim(active, 'packet-outage-claim')
        evidence_id = register_pending_evidence(active, claim_id, 'packet-outage-evidence', 1)
        response = request_support(active, claim_id, 'packet-outage-support', 2)
        replay = request_support(active, claim_id, 'packet-outage-support', 2)
        repeated_request = request_support(active, claim_id, 'packet-outage-support-repeat', 3)
        detail = active.get(f'/api/v1/workbench/claims/{claim_id}', headers=STAFF_AUTH)

    assert response.status_code == 201
    assert response.json()['delivery']['state'] == 'queued_locally'
    assert replay.status_code == 201
    assert replay.json() == response.json()
    assert repeated_request.status_code == 201
    assert (
        repeated_request.json()['handoff']['handoff_id'] == response.json()['handoff']['handoff_id']
    )

    # The structured context is intact despite the notification failing.
    packet = stored_packet(repository, claim_id)
    assert evidence_id in packet.evidence_refs
    assert evidence_id in packet.pending_items
    assert packet.promised_next_step
    assert [entry.evidence_id for entry in packet.evidence] == [evidence_id]

    # And staff can still reach it, because the queue reads persisted state.
    assert detail.status_code == 200
    assert detail.json()['handoffs']
    assert len(repository.list_handoffs(claim_id, CUSTOMER_ID)) == 1
    claim = repository.get_claim(claim_id, CUSTOMER_ID)
    assert claim is not None
    assert claim.revision == 3


def test_an_urgent_transfer_is_not_blocked_by_outstanding_intake(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    """Issue #146: urgent handling is not blocked by ordinary intake.

    The claim still has evidence outstanding, which is exactly the state that
    must not hold an urgent transfer. The packet carries the gap rather than
    waiting for it to close.
    """
    with client as active:
        claim_id = create_claim(active, 'packet-urgent-claim')
        evidence_id = register_pending_evidence(active, claim_id, 'packet-urgent-evidence', 1)
        response = request_support(active, claim_id, 'packet-urgent-support', 2, 'urgent')
        listing = active.get('/api/v1/workbench/claims?view=all', headers=STAFF_AUTH)

    assert response.status_code == 201
    handoff = response.json()['handoff']
    assert handoff['support_need'] == 'urgent'
    assert handoff['priority'] in {'urgent', 'immediate'}

    # The outstanding item travels with the transfer instead of blocking it.
    packet = stored_packet(repository, claim_id)
    assert evidence_id in packet.pending_items

    entry = next(item for item in listing.json()['items'] if item['claim_id'] == claim_id)
    assert entry['priority'] == handoff['priority']
