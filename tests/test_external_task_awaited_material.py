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
    ExternalTaskEvidenceLink,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
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

    return _drive(client, route=True)


def _consented_claim(client: TestClient) -> str:
    """Drive a motor claim to recorded consent, stopping before its first request."""

    return _drive(client, route=False)


def _drive(client: TestClient, *, route: bool) -> str:
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
    if not route:
        return claim_id
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


def test_a_refused_repeat_request_leaves_the_record_alone(
    client: TestClient, repository: FixtureRepository
) -> None:
    """A repeat request is refused before the recorder, and refusal writes nothing.

    Consent is spent by the request that uses it, so a second one is refused for want of
    permission rather than for being a duplicate. What is worth asserting is that the
    refusal is clean: no second assessment is owed, and no second link appears.

    This is not an idempotency test, and an earlier version of it claimed to be one. It
    asserted only that no second record existed, which holds for any refusal whatever its
    reason, so it read as evidence that a retry continues its task when in fact the
    request never reached the recorder. The status is asserted here so the test cannot
    quietly change meaning if the reason for refusal does.
    """

    claim_id = _routed_claim(client)
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None

    repeated = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'aw-r2',
            'If-Match': _revision(client, claim_id),
        },
        json={},
    )

    assert repeated.status_code == 409
    assert repeated.json()['error']['code'] == 'INVALID_STATE_TRANSITION'

    awaited = [
        item
        for item in repository.list_evidence(claim_id, claim.customer_id)
        if item.source is EvidenceSource.EXTERNAL_SYSTEM
    ]
    assert len(awaited) == 1
    assert len(repository.list_external_task_evidence_links_internal(claim_id)) == 1


def test_the_guard_itself_refuses_a_second_record(
    client: TestClient, repository: FixtureRepository
) -> None:
    """Reach the early return, rather than asserting an outcome something else produced.

    A repeat request through the API is refused before it reaches the recorder, so it
    says nothing about this guard; diff coverage caught that the guard's own line was
    never executed by anything. This calls the recorder twice.
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


def test_an_interrupted_first_request_leaves_an_orphan_that_a_retry_repairs(
    client: TestClient, repository: FixtureRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail between the two writes on the *first* request, then retry through the API.

    The evidence and the link are two repository calls. If the second fails, the claim
    holds external-system material naming no task — the exact state
    `external_task_for_evidence` rejects — while the task is already accepted.

    The earlier version of this test patched the link write *after* a completed routing
    had already written one, so it never created the orphan it described and never
    exercised the retry. That is how the reconciliation gap survived it: the retry took
    the recovery branch, found the task already accepted, skipped reconciliation, and
    returned success over a broken invariant.
    """

    claim_id = _consented_claim(client)
    original = repository.save_external_task_evidence_link
    calls = {'n': 0}

    def fail_once(link: ExternalTaskEvidenceLink, customer_id: str) -> None:
        calls['n'] += 1
        if calls['n'] == 1:
            raise KeyError('link store unavailable')
        original(link, customer_id)

    monkeypatch.setattr(repository, 'save_external_task_evidence_link', fail_once)

    interrupted = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'aw-r',
            'If-Match': _revision(client, claim_id),
        },
        json={},
    )
    assert interrupted.status_code == 409

    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    orphaned = [
        item
        for item in repository.list_evidence(claim_id, claim.customer_id)
        if item.source is EvidenceSource.EXTERNAL_SYSTEM
    ]
    assert len(orphaned) == 1
    assert repository.list_external_task_evidence_links_internal(claim_id) == []

    retried = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'aw-r',
            'If-Match': _revision(client, claim_id),
        },
        json={},
    )

    assert retried.status_code in {200, 201}, retried.text
    links = repository.list_external_task_evidence_links_internal(claim_id)
    records = [
        item
        for item in repository.list_evidence(claim_id, claim.customer_id)
        if item.source is EvidenceSource.EXTERNAL_SYSTEM
    ]
    assert len(records) == 1
    assert len(links) == 1
    # The invariant the whole change exists to hold.
    assert external_task_for_evidence(records[0], links) == links[0].task_id


def test_holding_the_evidence_is_not_proof_of_holding_the_link(
    client: TestClient, repository: FixtureRepository
) -> None:
    """The recorder returned early on the evidence alone, so a lost link stayed lost."""

    claim_id = _routed_claim(client)
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    task = repository.list_external_tasks_internal(claim_id)[0]
    repository._external_task_evidence_links.clear()

    _record_awaited_material(repository, task=task, claim=claim)

    assert len(repository.list_external_task_evidence_links_internal(claim_id)) == 1


def test_a_write_that_returns_quietly_is_not_taken_as_proof(
    client: TestClient, repository: FixtureRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A silently dropped link write must fail the request, not pass as success.

    The two writes are not one transaction, so a store that accepts the link and keeps
    nothing raises nothing for the recorder to catch. Reporting 201 there would tell the
    caller the assessment request is recorded while the material it produced still names
    no task. The record is read back through `external_task_for_evidence` instead, and
    the answer that guard gives is the only one taken as success.
    """

    claim_id = _consented_claim(client)

    def drop(link: ExternalTaskEvidenceLink, customer_id: str) -> None:
        return None

    monkeypatch.setattr(repository, 'save_external_task_evidence_link', drop)

    response = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'aw-r',
            'If-Match': _revision(client, claim_id),
        },
        json={},
    )

    assert response.status_code == 409, response.text


def test_a_task_left_behind_by_an_interrupted_acceptance_is_carried_forward(
    client: TestClient, repository: FixtureRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other partial-write shape: the operation advanced, the task did not.

    Acceptance is three writes — the routing operation, the task transition, then the
    owed material. An interruption at the second leaves the operation `accepted` while
    its task is still `prepared`, which is the state the recovery branch exists for.
    Nothing exercised it, so this states what recovery owes: finish the transition it
    finds unfinished, and record what the task then owes, rather than reporting a
    request whose task never left `prepared`.
    """

    claim_id = _consented_claim(client)
    original = repository.save_external_task
    calls = {'n': 0}

    def fail_the_transition(task: ExternalTaskRecord, customer_id: str) -> None:
        calls['n'] += 1
        if task.status is ExternalTaskOperationStatus.ACCEPTED and calls['n'] > 1:
            raise KeyError('task store unavailable')
        original(task, customer_id)

    monkeypatch.setattr(repository, 'save_external_task', fail_the_transition)

    interrupted = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'aw-r',
            'If-Match': _revision(client, claim_id),
        },
        json={},
    )
    assert interrupted.status_code == 409

    stranded = repository.list_external_tasks_internal(claim_id)[0]
    assert stranded.status is ExternalTaskOperationStatus.PREPARED

    monkeypatch.setattr(repository, 'save_external_task', original)
    retried = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'aw-r',
            'If-Match': _revision(client, claim_id),
        },
        json={},
    )

    assert retried.status_code in {200, 201}, retried.text
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    task = repository.list_external_tasks_internal(claim_id)[0]
    assert task.status is ExternalTaskOperationStatus.ACCEPTED
    links = repository.list_external_task_evidence_links_internal(claim_id)
    records = [
        item
        for item in repository.list_evidence(claim_id, claim.customer_id)
        if item.source is EvidenceSource.EXTERNAL_SYSTEM
    ]
    assert len(records) == 1
    assert len(links) == 1
    assert external_task_for_evidence(records[0], links) == task.task_id


def test_a_lost_record_under_a_surviving_link_fails_rather_than_reports_success(
    client: TestClient, repository: FixtureRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read-back covers the record too, on the one path nothing else guards.

    `save_external_task_evidence_link` refuses a link whose evidence is missing, so a
    lost record is normally caught by that write. It is not caught when the link is the
    half that survived: the recorder then has no link to write, and a store that accepts
    the record and keeps nothing raises nothing. Without the read-back the recorder
    would return quietly, having reconciled nothing.
    """

    claim_id = _routed_claim(client)
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    task = repository.list_external_tasks_internal(claim_id)[0]
    evidence_id = f'evd_{task.task_id.removeprefix("tsk_")}'
    repository._evidence.pop(evidence_id, None)
    assert repository.list_external_task_evidence_links_internal(claim_id) != []

    def drop(record: object, customer_id: str) -> None:
        return None

    monkeypatch.setattr(repository, 'save_evidence', drop)

    with pytest.raises(ApiError) as raised:
        _record_awaited_material(repository, task=task, claim=claim)

    assert raised.value.status_code == 409


def test_a_task_that_came_to_a_failure_is_owed_nothing(
    client: TestClient, repository: FixtureRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reconciliation acts on two statuses, and states them rather than assuming them.

    A failed attempt records the failure on the task and on the operation together, so
    an accepted operation should never hold a failed task. Recovery no longer leans on
    that pairing. The previous guard skipped every status but `prepared`, and widening
    it to reconcile an accepted task must not also widen it to owe an assessment against
    a task that failed, because nobody is waiting for that assessment.

    The interrupted first request is what leaves the operation accepted with the claim's
    routing unsaved, which is the only way into the recovery branch.
    """

    claim_id = _consented_claim(client)
    original = repository.save_external_task_evidence_link
    calls = {'n': 0}

    def fail_once(link: ExternalTaskEvidenceLink, customer_id: str) -> None:
        calls['n'] += 1
        if calls['n'] == 1:
            raise KeyError('link store unavailable')
        original(link, customer_id)

    monkeypatch.setattr(repository, 'save_external_task_evidence_link', fail_once)

    interrupted = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'aw-r',
            'If-Match': _revision(client, claim_id),
        },
        json={},
    )
    assert interrupted.status_code == 409

    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    task = repository.list_external_tasks_internal(claim_id)[0]
    evidence_id = f'evd_{task.task_id.removeprefix("tsk_")}'

    # An accepted operation holding a failed task is not reachable through the API. It is
    # constructed here because this guard is part of what keeps it unreachable.
    repository._external_tasks[task.task_id] = task.model_copy(
        update={'status': ExternalTaskOperationStatus.TERMINAL_FAILURE}
    )
    repository._evidence.pop(evidence_id, None)

    retried = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'aw-r',
            'If-Match': _revision(client, claim_id),
        },
        json={},
    )

    assert retried.status_code in {200, 201}, retried.text
    assert repository.get_evidence(claim_id, evidence_id, claim.customer_id) is None
    assert repository.list_external_task_evidence_links_internal(claim_id) == []
