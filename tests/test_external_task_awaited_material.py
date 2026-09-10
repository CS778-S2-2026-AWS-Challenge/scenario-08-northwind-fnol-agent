"""An accepted external task records what it owes, and what it owes names the task.

`ExternalTaskEvidenceLink` is documented as tying an evidence record to the task that
*produced or owes* it, and `external_task_for_evidence` refuses external-system material
that names no task. Neither half had a producer: nothing in the application ever
constructed a link, and a claim that had requested an assessment looked exactly like one
that had not.

These cover the owed half. The produced half needs an `ExternalTaskResult`, and nothing
calls `save_external_task_result`, which is recorded on #402 as a dependency rather than
worked around here.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault('DATA_RUNTIME_PROFILE', 'fixture')

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.core.errors import ApiError
from backend.domain.external_services import (
    external_task_for_evidence,
)
from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceSource,
    EvidenceStatus,
    EvidenceWaitType,
    ResponsibleParty,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import ControlledAgent
from backend.services.integrations import _record_awaited_material

CLAIMANT = {'Authorization': 'Bearer synthetic-claimant'}
STAFF = {'Authorization': 'Bearer synthetic-staff'}

FIELD_VALUES: dict[str, Any] = {
    'incident.type': 'collision',
    'incident.occurred_at': '2026-09-01T09:30:00Z',
    'incident.location': 'Great North Road, Auckland',
    'incident.description': 'A demonstration incident recorded for this run.',
    'incident.injury_or_danger': False,
    'incident.cause': 'Another vehicle failed to stop.',
    'loss.description': 'Damage recorded for this run.',
    'parties.other_parties': False,
    'authorities.police_report_reference': 'SIMULATED-REF',
    'authorities.emergency_services_notified': False,
    'vehicle.registration': 'SIM123',
    'vehicle.damage_description': 'Rear bumper and tail light damage.',
    'vehicle.drivable': True,
    'claimant.contact_preference': 'in_app',
    'claimant.client_number': 'SIM-CLIENT-1',
    'claimant.role': 'policyholder',
    'policy.policy_number': 'SIM-POLICY-1',
}


@pytest.fixture
def repository() -> FixtureRepository:
    return FixtureRepository()


@pytest.fixture
def client(repository: FixtureRepository) -> Iterator[TestClient]:
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
        repository,
        ControlledAgent(),
    )
    with TestClient(app) as test_client:
        yield test_client


def _revision(client: TestClient, claim_id: str) -> str:
    return str(client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT).json()['revision'])


def _routed_claim(client: TestClient) -> str:
    """Drive a motor claim to an accepted assessor routing request."""

    created = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT, 'Idempotency-Key': 'aw-open'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    claim_id = str(created.json()['claim']['claim_id'])
    session_id = created.json()['claim'].get('active_session_id')
    if session_id is None:
        session_id = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**CLAIMANT, 'Idempotency-Key': 'aw-session'},
            json={},
        ).json()['session_id']
    client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={**CLAIMANT, 'Idempotency-Key': 'aw-msg', 'If-Match': _revision(client, claim_id)},
        json={'client_message_id': 'aw-cmid', 'content': {'text': 'My car was hit.'}},
    )
    for attempt in range(8):
        response = client.post(
            f'/api/v1/claims/{claim_id}/creation',
            headers={
                **CLAIMANT,
                'Idempotency-Key': f'aw-create-{attempt}',
                'If-Match': _revision(client, claim_id),
            },
            json={},
        )
        if response.status_code < 400:
            break
        details = (response.json().get('error') or {}).get('details') or []
        assert details, response.json()
        client.patch(
            f'/api/v1/claims/{claim_id}/form',
            headers={
                **CLAIMANT,
                'Idempotency-Key': f'aw-patch-{attempt}',
                'If-Match': _revision(client, claim_id),
            },
            json={
                'updates': [
                    {
                        'field_code': detail['field'],
                        'value': (
                            'motor'
                            if detail['field'] == 'claim.product_family'
                            else FIELD_VALUES.get(detail['field'], 'Recorded for this run.')
                        ),
                        'status': 'confirmed',
                    }
                    for detail in details
                ]
            },
        )
    client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing/consent',
        headers={**CLAIMANT, 'Idempotency-Key': 'aw-c', 'If-Match': _revision(client, claim_id)},
        json={'consent': True},
    )
    routed = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={**CLAIMANT, 'Idempotency-Key': 'aw-r', 'If-Match': _revision(client, claim_id)},
        json={},
    )
    assert routed.status_code == 201, routed.text
    return claim_id


def test_nothing_is_owed_before_a_request_is_accepted(
    client: TestClient, repository: FixtureRepository
) -> None:
    """A claim that has not requested an assessment records no awaited assessment."""

    created = client.post(
        '/api/v1/claims',
        headers={**CLAIMANT, 'Idempotency-Key': 'aw-bare'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    claim_id = str(created.json()['claim']['claim_id'])

    assert repository.list_evidence(claim_id, 'cus_demo') == []
    assert repository.list_external_task_evidence_links_internal(claim_id) == []


def test_an_accepted_request_records_what_it_owes(
    client: TestClient, repository: FixtureRepository
) -> None:
    """The claim can say it is waiting on the assessor, which it could not before.

    The material is `pending` with nothing to open, because an acknowledgement is not an
    assessment. Recording it as anything else would let a demonstration read "requested"
    as "arrived".
    """

    claim_id = _routed_claim(client)

    records = repository.list_evidence(claim_id, 'cus_demo')
    awaited = [item for item in records if item.source is EvidenceSource.EXTERNAL_SYSTEM]
    assert len(awaited) == 1
    record = awaited[0]

    assert record.status is EvidenceStatus.PENDING
    assert record.file_status is EvidenceFileStatus.NOT_AVAILABLE
    assert record.wait_type is EvidenceWaitType.EXTERNAL_AGENCY
    assert record.responsible_party is ResponsibleParty.EXTERNAL_PARTY
    assert record.size_bytes is None


def test_the_awaited_material_names_the_task_that_owes_it(
    client: TestClient, repository: FixtureRepository
) -> None:
    """This is the guard the change exists to satisfy, not to work around.

    `external_task_for_evidence` refuses external-system material that names no task, so
    recording the evidence without the link would produce exactly the state it rejects.
    """

    claim_id = _routed_claim(client)
    records = repository.list_evidence(claim_id, 'cus_demo')
    links = repository.list_external_task_evidence_links_internal(claim_id)
    tasks = repository.list_external_tasks_internal(claim_id)

    assert len(links) == 1
    record = next(item for item in records if item.source is EvidenceSource.EXTERNAL_SYSTEM)

    assert external_task_for_evidence(record, links) == tasks[0].task_id


def test_staff_are_told_who_is_being_waited_on(client: TestClient) -> None:
    """A gap with no owner is not a displayable state; this one names the external party."""

    claim_id = _routed_claim(client)

    detail = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=STAFF).json()
    gaps = {
        (gap['kind'], gap['code']): gap for gap in detail['work_summary']['missing_information']
    }
    awaited = gaps[('evidence', 'assessment_report')]

    assert awaited['status'] == 'pending'
    assert awaited['responsible_party'] == 'external_party'


def test_the_claimant_is_not_shown_the_internal_placeholder(client: TestClient) -> None:
    """What the claimant is owed is told by the service action, not by a stub record.

    The awaited material is external-system sourced, so the existing visibility rule keeps
    it out of the claimant projection. The claimant learns the request is in flight from
    `external_service_action`, which is the surface that speaks to them.
    """

    claim_id = _routed_claim(client)

    listed = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT).json()
    assert listed.get('items') == []

    claim = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT).json()
    action = claim.get('external_service_action') or {}
    assert action.get('status') in {'queued', 'assigned'}


def test_recording_what_is_owed_is_idempotent(
    client: TestClient, repository: FixtureRepository
) -> None:
    """A retried routing request continues its task rather than owing a second assessment."""

    claim_id = _routed_claim(client)
    client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'aw-r2',
            'If-Match': _revision(client, claim_id),
        },
        json={},
    )

    records = repository.list_evidence(claim_id, 'cus_demo')
    awaited = [item for item in records if item.source is EvidenceSource.EXTERNAL_SYSTEM]

    assert len(awaited) == 1
    assert len(repository.list_external_task_evidence_links_internal(claim_id)) == 1


def test_the_guard_itself_refuses_a_second_record(
    client: TestClient, repository: FixtureRepository
) -> None:
    """Reach the early return, rather than asserting an outcome something else produced.

    `test_recording_what_is_owed_is_idempotent` passes because a retried routing request
    is refused before it reaches the recorder, so it proves the endpoint is idempotent and
    says nothing about this guard. Diff coverage caught that the guard's own line was
    never executed. This calls it twice.
    """

    claim_id = _routed_claim(client)
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    task = repository.list_external_tasks_internal(claim_id)[0]

    _record_awaited_material(repository, task=task, claim=claim)

    awaited = [
        item
        for item in repository.list_evidence(claim_id, claim.customer_id)
        if item.source is EvidenceSource.EXTERNAL_SYSTEM
    ]
    assert len(awaited) == 1
    assert len(repository.list_external_task_evidence_links_internal(claim_id)) == 1


def test_a_failed_link_write_surfaces_rather_than_leaving_a_silent_orphan(
    client: TestClient, repository: FixtureRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the link cannot be written the caller is told, not left with untraceable material.

    The evidence and the link are two repository writes. A failure between them produces
    external-system material with no link, which `external_task_for_evidence` then
    rejects. That is the safe direction, but the caller still has to hear about it.
    """

    claim_id = _routed_claim(client)
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    task = repository.list_external_tasks_internal(claim_id)[0]

    def refuse(*args: object, **kwargs: object) -> None:
        raise KeyError('link store unavailable')

    monkeypatch.setattr(repository, 'save_external_task_evidence_link', refuse)
    monkeypatch.setattr(
        repository,
        'get_evidence',
        lambda *args, **kwargs: None,
    )

    with pytest.raises(ApiError) as refused:
        _record_awaited_material(repository, task=task, claim=claim)

    assert refused.value.status_code == 409
