"""What one failed assessor attempt maps to on the task, the operation, and the staff view.

The later tests cover the outcome that had no producer until #612: an attempt the adapter
reports as having reached the assessor before it failed. `SPEC/08-acceptance-scenarios.md`
MVP-AT-10 requires that such a request "remains `unknown_outcome`; status is checked with
the existing identity before any retry, and no duplicate external action is created". They
drive the wired adapter rather than constructing a submitted task, as #612 requires of its
evidence.
"""

import json
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.claims_service import (
    AssessorAdapterFailure,
    AssessorFixtureFailure,
    AssessorRoutingOutcome,
    MockAssessorServiceAdapter,
    ScriptedAssessorFailure,
)
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.core.errors import ApiError
from backend.domain.external_services import (
    ExternalTaskDelivery,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
)
from backend.domain.models import AssessorRoutingOperationStatus, RouteAssessorRequest
from backend.repositories.fixture import FixtureRepository
from backend.services.integrations import route_assessor

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


UNRESOLVED_MESSAGE = 'may already have reached the assessor'
SENT_THEN_LOST = ScriptedAssessorFailure(
    code=AssessorFixtureFailure.TIMEOUT,
    delivery=ExternalTaskDelivery.SUBMITTED,
    delivery_evidence='fixture send acknowledged; no routing answer returned',
)


class CountingAssessorAdapter(MockAssessorServiceAdapter):
    """The fixture adapter, counting how often the assessor side was actually called."""

    def __init__(self, *, failure_sequence: tuple[ScriptedAssessorFailure, ...]) -> None:
        super().__init__(failure_sequence=failure_sequence)
        self.calls = 0

    def route_assessor(
        self,
        command: RouteAssessorRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome:
        self.calls += 1
        return super().route_assessor(command, request_fingerprint)


def _operation_statuses(
    repository: FixtureRepository,
    claim_id: str,
) -> list[AssessorRoutingOperationStatus]:
    return [
        operation.status
        for request in repository.list_external_task_requests_internal(claim_id)
        if request.operation_id is not None
        for operation in [repository.get_assessor_routing_operation(request.operation_id)]
        if operation is not None
    ]


def _route(client: TestClient, claim_id: str, *, key: str, revision: int) -> Any:
    return client.post(
        f'/api/v1/claims/{claim_id}/assessor-routing',
        headers={**AUTH, 'Idempotency-Key': key, 'If-Match': str(revision)},
    )


def test_an_attempt_that_may_have_arrived_is_unresolved_rather_than_retryable() -> None:
    """The delivery the adapter reports decides the outcome, not the failure code.

    The same `timeout` describes an attempt that never left and one whose
    acknowledgement was lost. The claimant is not told this one "can be retried
    safely", which is what the code alone produced, because that is the one thing an
    unresolved outcome cannot promise.
    """

    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(failure_sequence=(SENT_THEN_LOST,))
    key = 'unresolved-outcome'

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        response = _route(client, claim_id, key=f'{key}-route', revision=consent_revision)
        claimant = client.get(f'/api/v1/claims/{claim_id}', headers=AUTH).json()
        staff = client.get(
            f'/api/v1/workbench/claims/{claim_id}/external-requests',
            headers=STAFF_AUTH,
        ).json()

    error = response.json()['error']
    assert response.status_code == 409
    assert error['code'] == 'INVALID_STATE_TRANSITION'
    assert error['retryable'] is False
    assert UNRESOLVED_MESSAGE in error['message']
    assert [detail['reason'] for detail in error['details']] == ['unknown_outcome']
    assert adapter.calls == 1

    task = repository.list_external_tasks_internal(claim_id)[0]
    assert task.status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME
    assert task.delivery is ExternalTaskDelivery.SUBMITTED
    assert task.delivery_evidence == SENT_THEN_LOST.delivery_evidence
    assert _operation_statuses(repository, claim_id) == [
        AssessorRoutingOperationStatus.UNKNOWN_OUTCOME
    ]

    # An unresolved outcome must not read as a claim that never made a request.
    action = claimant['external_service_action']
    assert action['status'] == 'awaiting_reconciliation'
    assert action['can_request'] is False
    assert action['failure_code'] == 'timeout'
    assert action['routing'] is None

    # Staff already had the wording for this state; until now nothing reached it.
    lifecycle = staff['items'][0]['lifecycle']
    assert lifecycle['status_label'] == 'Outcome not confirmed'
    assert lifecycle['verification_state'] == 'reconciliation_required'
    assert lifecycle['delivery_state'] == 'submitted'
    assert lifecycle['needs_attention'] is True
    assert 'Reconcile' in lifecycle['next_action']


def test_the_same_timeout_that_never_left_stays_retryable() -> None:
    """The pre-submission timeout confirmed by the #425 review is unchanged."""

    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(
        failure_sequence=(ScriptedAssessorFailure(code=AssessorFixtureFailure.TIMEOUT),)
    )
    key = 'unsent-timeout'

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        response = _route(client, claim_id, key=f'{key}-route', revision=consent_revision)
        claimant = client.get(f'/api/v1/claims/{claim_id}', headers=AUTH).json()

    assert response.status_code == 503
    assert response.json()['error']['retryable'] is True
    task = repository.list_external_tasks_internal(claim_id)[0]
    assert task.status is ExternalTaskOperationStatus.RETRYABLE_FAILURE
    assert task.delivery is ExternalTaskDelivery.NOT_SUBMITTED
    assert task.delivery_evidence is None
    assert claimant['external_service_action']['status'] == 'retryable_failure'
    assert claimant['external_service_action']['can_request'] is True


@pytest.mark.parametrize('reuses_key', [True, False])
def test_a_further_request_reaches_no_assessor_whatever_key_it_carries(
    reuses_key: bool,
) -> None:
    """The refusal is keyed on the claim's task, not on the operation identity.

    The operation identity is derived from the caller's idempotency key, so a client
    presenting a new key would otherwise build a fresh authority, operation, and task,
    and send the request a second time.
    """

    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(failure_sequence=(SENT_THEN_LOST,))
    key = f'unresolved-repeat-{reuses_key}'

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        first = _route(client, claim_id, key=f'{key}-route', revision=consent_revision)
        assert first.status_code == 409, first.text
        current = int(client.get(f'/api/v1/claims/{claim_id}', headers=AUTH).json()['revision'])
        again = _route(
            client,
            claim_id,
            key=f'{key}-route' if reuses_key else f'{key}-another',
            revision=current,
        )

    error = again.json()['error']
    assert again.status_code == 409
    assert error['code'] == 'INVALID_STATE_TRANSITION'
    assert error['retryable'] is False
    # A claim with no permission left to spend is refused with the same status and
    # code, so the message is what separates them and is asserted rather than the
    # status alone.
    assert UNRESOLVED_MESSAGE in error['message']
    assert len(repository.list_external_tasks_internal(claim_id)) == 1
    assert _operation_statuses(repository, claim_id) == [
        AssessorRoutingOperationStatus.UNKNOWN_OUTCOME
    ]
    # The assessor was contacted once, by the attempt that produced the outcome.
    assert adapter.calls == 1


def test_what_reached_the_assessor_is_recorded_once_and_not_rewritten() -> None:
    """A second attempt describes what happened next, not what happened first.

    `unavailable` keeps the assessor contract's retryability even when the failed
    invocation reached the provider, so it is the one case where a second attempt runs
    over a task already marked submitted. The first attempt's delivery evidence is what
    reached the provider, and a later attempt does not restate it.
    """

    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(
        failure_sequence=(
            ScriptedAssessorFailure(
                code=AssessorFixtureFailure.UNAVAILABLE,
                delivery=ExternalTaskDelivery.SUBMITTED,
                delivery_evidence='first acknowledgement',
            ),
            ScriptedAssessorFailure(
                code=AssessorFixtureFailure.UNAVAILABLE,
                delivery=ExternalTaskDelivery.SUBMITTED,
                delivery_evidence='second acknowledgement',
            ),
        )
    )
    key = 'submitted-unavailable'

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        assert (
            _route(client, claim_id, key=f'{key}-route', revision=consent_revision).status_code
            == 503
        )
        assert (
            _route(client, claim_id, key=f'{key}-route', revision=consent_revision).status_code
            == 503
        )

    tasks = repository.list_external_tasks_internal(claim_id)
    assert len(tasks) == 1
    assert tasks[0].status is ExternalTaskOperationStatus.RETRYABLE_FAILURE
    assert tasks[0].delivery is ExternalTaskDelivery.SUBMITTED
    assert tasks[0].delivery_evidence == 'first acknowledgement'
    assert adapter.calls == 2


def test_the_routing_service_refuses_an_unresolved_outcome_on_its_own() -> None:
    """The refusal also stands at the boundary that performs the side effect.

    The claimant route refuses earlier, so that its message names reconciliation
    instead of a missing permission. This is the other half: `route_assessor` is the
    function that prepares an operation and calls the adapter, and a caller reaching it
    another way must not get past it either. The unresolved task is produced by driving
    the real path; only the second call is made at the service boundary.
    """

    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(failure_sequence=(SENT_THEN_LOST,))
    key = 'unresolved-service-boundary'

    app = create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    with TestClient(app) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        assert (
            _route(client, claim_id, key=f'{key}-route', revision=consent_revision).status_code
            == 409
        )
        stored_request = repository.list_external_task_requests_internal(claim_id)[0]
        claim = repository.get_claim_internal(claim_id)
        assert claim is not None and claim.external_claim is not None
        assert claim.external_claim.external_claim_id is not None
        # The same request the service built, so the operation identity and its
        # fingerprint match and the call reaches the guard rather than stopping at the
        # idempotency check.
        payload = RouteAssessorRequest(
            claim_id=claim_id,
            external_claim_id=claim.external_claim.external_claim_id,
            authorisation_ref=stored_request.authorisation.northwind_authority_ref,
            claimant_consent_ref=stored_request.authorisation.claimant_consent_ref,
            requested_action=stored_request.requested_action,
            location={'region': str(claim.form['incident.location'].value)},
        )

        with pytest.raises(ApiError) as refused:
            route_assessor(
                repository,
                adapter,
                app.state.assessor_service_entry,
                payload,
            )

    assert refused.value.status_code == 409
    assert refused.value.code == 'INVALID_STATE_TRANSITION'
    assert refused.value.retryable is False
    assert UNRESOLVED_MESSAGE in refused.value.message
    assert adapter.calls == 1


def test_a_failure_cannot_misdescribe_what_reached_the_provider() -> None:
    """The adapter boundary refuses a delivery claim that contradicts its evidence."""

    with pytest.raises(ValueError, match='must name what reached the provider'):
        AssessorAdapterFailure(
            AssessorFixtureFailure.TIMEOUT,
            delivery=ExternalTaskDelivery.SUBMITTED,
        )
    with pytest.raises(ValueError, match='cannot carry delivery evidence'):
        AssessorAdapterFailure(
            AssessorFixtureFailure.TIMEOUT,
            delivery=ExternalTaskDelivery.NOT_SUBMITTED,
            delivery_evidence='nothing was sent',
        )
