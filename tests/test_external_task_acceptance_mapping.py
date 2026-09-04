import json
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.claims_service import AssessorFixtureFailure, MockAssessorServiceAdapter
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.external_services import ExternalTaskOperationStatus, ExternalTaskRecord
from backend.repositories.fixture import FixtureRepository

AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
DEVELOPER_SETTINGS = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
JOURNEY_PATH = Path(__file__).parent / 'fixtures' / 'journeys' / 'AT-01-clear-motor-creation.json'


def _journey() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(JOURNEY_PATH.read_text(encoding='utf-8')))


def _create_assessor_ready_claim(client: TestClient, *, key: str) -> tuple[str, int]:
    journey = _journey()
    created = client.post(
        '/api/v1/claims',
        headers={**AUTH, 'Idempotency-Key': f'{key}-claim'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    working = created.json()
    claim_id = str(working['claim']['claim_id'])
    session_id = str(working['session']['session_id'])

    turn = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={
            **AUTH,
            'Idempotency-Key': f'{key}-description',
            'If-Match': str(working['claim']['revision']),
        },
        json={
            'client_message_id': f'{key}-description',
            'content': {'type': 'text', 'text': journey['input']},
            'evidence_refs': [],
        },
    )
    assert turn.status_code == 200

    confirmation = client.post(
        f'/api/v1/claims/{claim_id}/form/confirmations',
        headers={
            **AUTH,
            'Idempotency-Key': f'{key}-confirmation',
            'If-Match': str(turn.json()['claim_revision']),
        },
        json={'field_codes': journey['expected_proposed_fields']},
    )
    assert confirmation.status_code == 200

    external = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **AUTH,
            'Idempotency-Key': f'{key}-creation',
            'If-Match': str(confirmation.json()['revision']),
        },
    )
    assert external.status_code == 201
    assert external.json()['external_service_action']['status'] == 'consent_required'
    return claim_id, int(external.json()['revision'])


def _grant_consent(client: TestClient, claim_id: str, revision: int, *, key: str) -> int:
    response = client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing/consent',
        headers={
            **AUTH,
            'Idempotency-Key': f'{key}-consent',
            'If-Match': str(revision),
        },
        json={'consent': True},
    )
    assert response.status_code == 201
    return int(response.json()['revision'])


@pytest.mark.parametrize(
    'failure',
    [AssessorFixtureFailure.UNAVAILABLE, AssessorFixtureFailure.TIMEOUT],
)
def test_successful_retry_clears_failure_state_from_task_and_workbench(
    failure: AssessorFixtureFailure,
) -> None:
    repository = FixtureRepository()
    adapter = MockAssessorServiceAdapter(failure_sequence=(failure,))
    key = f'acceptance-clears-{failure.value}'

    with TestClient(
        create_app(
            DEVELOPER_SETTINGS,
            repository=repository,
            assessor_service_adapter=adapter,
        )
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        headers = {
            **AUTH,
            'Idempotency-Key': f'{key}-route',
            'If-Match': str(consent_revision),
        }

        failed = client.post(f'/api/v1/claims/{claim_id}/assessor-routing', headers=headers)
        after_failure = repository.list_external_tasks_internal(claim_id)
        retry = client.post(f'/api/v1/claims/{claim_id}/assessor-routing', headers=headers)
        workbench = client.get(
            f'/api/v1/workbench/claims/{claim_id}/external-requests',
            headers=STAFF_AUTH,
        )

    assert failed.status_code == 503
    assert len(after_failure) == 1
    failed_task = after_failure[0]
    assert failed_task.status is ExternalTaskOperationStatus.RETRYABLE_FAILURE
    assert failed_task.failure_code is not None
    assert failed_task.failure_code.value == failure.value

    assert retry.status_code == 201
    tasks = repository.list_external_tasks_internal(claim_id)
    assert len(tasks) == 1
    accepted_task = tasks[0]
    assert accepted_task.task_id == failed_task.task_id
    assert accepted_task.status is ExternalTaskOperationStatus.ACCEPTED
    assert accepted_task.failure_code is None
    assert ExternalTaskRecord.model_validate(accepted_task.model_dump()) == accepted_task

    assert workbench.status_code == 200
    items = workbench.json()['items']
    assert len(items) == 1
    staff_task = items[0]['task']
    assert staff_task['task_id'] == accepted_task.task_id
    assert staff_task['status'] == 'accepted'
    assert staff_task['failure_code'] is None
