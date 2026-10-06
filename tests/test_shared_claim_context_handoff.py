from collections.abc import Iterator
from typing import Any, cast

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import PersistenceRepository


@pytest.fixture(params=['fixture', 'mongodb'])
def shared_context_repository(
    request: pytest.FixtureRequest,
) -> FixtureRepository | MongoDBRepository:
    if request.param == 'fixture':
        return FixtureRepository()
    repository = MongoDBRepository(mongomock.MongoClient(), 'shared_claim_context_handoff')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


@pytest.fixture
def shared_context_client(
    shared_context_repository: FixtureRepository | MongoDBRepository,
) -> Iterator[TestClient]:
    app = create_app(
        Settings(
            business_seed_path='config/business-seed.json',
            environment='test',
            identity_mode=IdentityMode.DEVELOPER,
        ),
        shared_context_repository,
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ('support_need', 'expected_action'),
    [
        ('human_requested', 'HANDOFF'),
        ('urgent', 'URGENT_HANDOFF'),
    ],
)
def test_evidence_handoff_and_next_action_share_one_claim_context(
    shared_context_client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    shared_context_repository: PersistenceRepository,
    support_need: str,
    expected_action: str,
) -> None:
    client = shared_context_client
    repository = shared_context_repository
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'shared-context-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    created_body = cast(dict[str, Any], created.json())
    claim_id = created_body['claim']['claim_id']
    assert isinstance(claim_id, str)

    registered = client.post(
        f'/api/v1/claims/{claim_id}/evidence',
        headers={
            **auth_headers,
            'Idempotency-Key': 'shared-context-evidence',
            'If-Match': '1',
        },
        json={
            'kind': 'police_report',
            'status': 'pending',
            'related_fields': ['authorities.police_report_reference'],
            'needed_for': ['later_action'],
            'claimant_note': 'The synthetic police report is not available yet.',
        },
    )
    assert registered.status_code == 201
    evidence_body = cast(dict[str, Any], registered.json())
    evidence = evidence_body['evidence']
    evidence_id = evidence['evidence_id']
    evidence_revision = evidence_body['revision']
    assert isinstance(evidence, dict)
    assert isinstance(evidence_id, str)
    assert isinstance(evidence_revision, int)

    support = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'shared-context-support',
            'If-Match': str(evidence_revision),
        },
        json={
            'reason': 'I want a person to continue with this report.',
            'support_need': support_need,
            'preferred_channel': 'phone',
        },
    )
    assert support.status_code == 201
    support_body = cast(dict[str, Any], support.json())
    handoff_id = support_body['handoff']['handoff_id']
    next_step = support_body['customer_next_step']
    assert isinstance(handoff_id, str)
    assert isinstance(next_step, dict)

    stored_claim = repository.get_claim(claim_id, 'cus_8f41a2c90d7e463b')
    handoffs = repository.list_handoffs(claim_id, 'cus_8f41a2c90d7e463b')
    assert stored_claim is not None
    assert len(handoffs) == 1
    handoff = handoffs[0]

    assert stored_claim.revision == support_body['revision']
    assert stored_claim.claim_state.next_action.value == expected_action
    assert stored_claim.customer_next_step.status == next_step['status']
    assert stored_claim.customer_next_step.summary == next_step['summary']
    assert handoff.handoff_id == handoff_id
    assert handoff.packet.evidence_refs == [evidence_id]
    assert [item.evidence_id for item in handoff.packet.evidence] == [evidence_id]
    assert evidence_id in handoff.packet.pending_items
    assert handoff.packet.promised_next_step == next_step['summary']
    assert support_body['handoff']['summary'] == next_step['summary']

    replay = client.post(
        f'/api/v1/claims/{claim_id}/support-requests',
        headers={
            **auth_headers,
            'Idempotency-Key': 'shared-context-support',
            'If-Match': str(evidence_revision),
        },
        json={
            'reason': 'I want a person to continue with this report.',
            'support_need': support_need,
            'preferred_channel': 'phone',
        },
    )
    assert replay.status_code == 201
    replay_body = cast(dict[str, Any], replay.json())
    assert replay_body['revision'] == support_body['revision']
    assert replay_body['handoff'] == support_body['handoff']
    assert replay_body['customer_next_step'] == next_step
    assert len(repository.list_handoffs(claim_id, 'cus_8f41a2c90d7e463b')) == 1

    claimant_detail = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert claimant_detail.status_code == 200
    claimant_detail_body = cast(dict[str, Any], claimant_detail.json())
    assert claimant_detail_body['customer_next_step'] == next_step

    workbench = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )
    assert workbench.status_code == 200
    detail = cast(dict[str, Any], workbench.json())
    assert detail['claim_id'] == claim_id
    assert detail['revision'] == stored_claim.revision
    assert detail['claim_state']['next_action'] == expected_action
    assert detail['customer_next_step']['status'] == next_step['status']
    assert detail['customer_next_step']['summary'] == next_step['summary']
    evidence_items = client.get(
        f'/api/v1/workbench/claims/{claim_id}/evidence', headers=staff_auth_headers
    ).json()['items']
    assert [item['evidence_id'] for item in evidence_items] == [evidence_id]
    handoff_items = client.get(
        f'/api/v1/workbench/claims/{claim_id}/handoffs', headers=staff_auth_headers
    ).json()['items']
    assert [item['handoff_id'] for item in handoff_items] == [handoff_id]
    packet = handoff_items[0]['packet']
    assert packet['evidence_refs'] == [evidence_id]
    assert [item['evidence_id'] for item in packet['evidence']] == [evidence_id]
    assert evidence_id in packet['pending_items']
    assert packet['promised_next_step'] == next_step['summary']

    claimant_evidence = client.get(
        f'/api/v1/claims/{claim_id}/evidence',
        headers=auth_headers,
    )
    assert claimant_evidence.status_code == 200
    claimant_evidence_body = cast(dict[str, Any], claimant_evidence.json())
    assert [item['evidence_id'] for item in claimant_evidence_body['items']] == [evidence_id]
    assert 'provenance' not in claimant_evidence_body['items'][0]
    assert 'packet' not in support_body['handoff']
