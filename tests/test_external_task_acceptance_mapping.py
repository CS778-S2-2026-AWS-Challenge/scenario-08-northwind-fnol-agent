"""What one failed assessor attempt maps to on the task, the operation, and the staff view.

The later tests cover the outcome that had no producer until #612: an attempt the adapter
reports as having reached the assessor before it failed. `SPEC/08-acceptance-scenarios.md`
MVP-AT-10 requires that such a request "remains `unknown_outcome`; status is checked with
the existing identity before any retry, and no duplicate external action is created". They
drive the wired adapter rather than constructing a submitted task, as #612 requires of its
evidence.
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.claims_service import (
    AdapterIdempotencyConflict,
    AssessorAdapterFailure,
    AssessorFixtureFailure,
    AssessorReconciliationRequest,
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
from backend.domain.models import (
    AssessorRoutingOperationStatus,
    AssessorRoutingResult,
    AssessorRoutingStatus,
    IntegrationSource,
    RouteAssessorRequest,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.integrations import reconcile_assessor_routing, route_assessor

AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
INTEGRATION_AUTH = {'Authorization': 'Bearer synthetic-integration'}
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
        self.reconciliation_calls = 0

    def route_assessor(
        self,
        command: RouteAssessorRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome:
        self.calls += 1
        return super().route_assessor(command, request_fingerprint)

    def reconcile_assessor(
        self,
        command: AssessorReconciliationRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome | None:
        """Count status checks while preserving the fixture's reconciliation result.

        Args:
            command: Persisted external-operation identity being checked.
            request_fingerprint: Stable fingerprint of that persisted identity.

        Returns:
            The deterministic fixture status result.

        Raises:
            AdapterIdempotencyConflict: The persisted identity changed between checks.
        """

        self.reconciliation_calls += 1
        return super().reconcile_assessor(command, request_fingerprint)


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


def test_a_permitted_retry_keeps_the_original_operation_whatever_key_it_carries() -> None:
    """#612: "Any permitted retry preserves the original task, request fingerprint, and
    operation identity."

    The operation identity used to be derived from the caller's idempotency key, so a
    retry presenting a new key minted a new Northwind decision, a new operation, a new
    task, and a second provider call. Three timeouts on one claim left three of each.
    The claimant client happens to hold one key per claim, so the contract held only for
    as long as the client cooperated and was lost on a page reload.
    """

    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(
        failure_sequence=(ScriptedAssessorFailure(code=AssessorFixtureFailure.TIMEOUT),)
    )
    key = 'retry-identity'

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        first = _route(client, claim_id, key=f'{key}-first', revision=consent_revision)
        after_first = repository.list_external_tasks_internal(claim_id)
        # A new key is what a claimant who reloaded the page presents.
        second = _route(client, claim_id, key=f'{key}-second', revision=consent_revision)

    assert first.status_code == 503
    assert second.status_code == 201, second.text
    assert adapter.calls == 2

    tasks = repository.list_external_tasks_internal(claim_id)
    assert len(after_first) == 1
    assert len(tasks) == 1
    assert tasks[0].task_id == after_first[0].task_id
    assert tasks[0].status is ExternalTaskOperationStatus.ACCEPTED
    requests = repository.list_external_task_requests_internal(claim_id)
    assert len(requests) == 1
    assert _operation_statuses(repository, claim_id) == [AssessorRoutingOperationStatus.ACCEPTED]
    routing_decisions = [
        decision
        for decision in repository.list_agent_decisions(claim_id, 'cus_demo')
        if 'ASSESSOR_RULE_AUTHORISED' in decision.reason_codes
    ]
    assert len(routing_decisions) == 1
    assert routing_decisions[0].decision_id == requests[0].authorisation.northwind_authority_ref


def _reconcile(
    client: TestClient,
    claim_id: str,
    task_id: str,
    *,
    key: str,
    revision: int,
) -> Any:
    return client.post(
        f'/internal/v1/claims/{claim_id}/external-tasks/{task_id}/reconcile',
        headers={
            **INTEGRATION_AUTH,
            'Idempotency-Key': key,
            'If-Match': str(revision),
        },
    )


def test_reconciliation_settles_the_existing_identity_without_another_route() -> None:
    """A provider status check accepts the one task that produced the unknown outcome."""

    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(failure_sequence=(SENT_THEN_LOST,))
    key = 'accepted-reconciliation'

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        failed = _route(client, claim_id, key=f'{key}-route', revision=consent_revision)
        assert failed.status_code == 409
        task_before = repository.list_external_tasks_internal(claim_id)[0]
        request_before = repository.list_external_task_requests_internal(claim_id)[0]
        claim_before = repository.get_claim_internal(claim_id)
        assert claim_before is not None

        settled = _reconcile(
            client,
            claim_id,
            task_before.task_id,
            key=f'{key}-check',
            revision=claim_before.revision,
        )
        replay = _reconcile(
            client,
            claim_id,
            task_before.task_id,
            key=f'{key}-check',
            revision=claim_before.revision,
        )
        claimant = client.get(f'/api/v1/claims/{claim_id}', headers=AUTH)
        staff = client.get(
            f'/api/v1/workbench/claims/{claim_id}/external-requests',
            headers=STAFF_AUTH,
        )

    assert settled.status_code == 200, settled.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == settled.json()
    assert adapter.calls == 1
    assert adapter.reconciliation_calls == 1
    assert len(repository.list_external_tasks_internal(claim_id)) == 1
    assert repository.list_external_task_requests_internal(claim_id) == [request_before]

    task_after = repository.list_external_tasks_internal(claim_id)[0]
    assert task_after.task_id == task_before.task_id
    assert task_after.status is ExternalTaskOperationStatus.ACCEPTED
    assert task_after.provider_reference is not None
    operation = repository.get_assessor_routing_operation(str(request_before.operation_id))
    assert operation is not None
    assert operation.status is AssessorRoutingOperationStatus.ACCEPTED
    assert operation.result is not None
    assert operation.result.model_dump(mode='json') == settled.json()

    claim_after = repository.get_claim_internal(claim_id)
    assert claim_after is not None
    assert claim_after.revision == claim_before.revision + 1
    assert claim_after.assessor_routing == operation.result
    evidence = repository.list_evidence(claim_id, claim_after.customer_id)
    links = repository.list_external_task_evidence_links_internal(claim_id)
    assert len(evidence) == 1
    assert evidence[0].status.value == 'pending'
    assert evidence[0].provenance['external_task_id'] == task_after.task_id
    assert len(links) == 1
    assert links[0].task_id == task_after.task_id
    assert links[0].evidence_id == evidence[0].evidence_id

    assert claimant.status_code == 200
    assert claimant.json()['external_service_action']['status'] == 'assigned'
    assert staff.status_code == 200
    assert staff.json()['items'][0]['task']['status'] == 'accepted'


class InconclusiveAssessorAdapter(CountingAssessorAdapter):
    """Status-check fixture that cannot yet establish the original request outcome."""

    def reconcile_assessor(
        self,
        command: AssessorReconciliationRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome | None:
        """Return an inconclusive provider status without mutating fixture state.

        Args:
            command: Persisted external-operation identity being checked.
            request_fingerprint: Stable fingerprint of that persisted identity.

        Returns:
            `None`, meaning the provider outcome remains unknown.

        Raises:
            ValueError: This controlled fixture does not raise.
        """

        del command, request_fingerprint
        self.reconciliation_calls += 1
        return None


def test_inconclusive_reconciliation_preserves_unknown_and_resend_refusal() -> None:
    """A status check that proves nothing cannot weaken the no-duplicate boundary."""

    repository = FixtureRepository()
    adapter = InconclusiveAssessorAdapter(failure_sequence=(SENT_THEN_LOST,))
    key = 'inconclusive-reconciliation'

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        assert (
            _route(client, claim_id, key=f'{key}-route', revision=consent_revision).status_code
            == 409
        )
        claim_before = repository.get_claim_internal(claim_id)
        assert claim_before is not None
        task = repository.list_external_tasks_internal(claim_id)[0]

        unresolved = _reconcile(
            client,
            claim_id,
            task.task_id,
            key=f'{key}-check',
            revision=claim_before.revision,
        )
        resend = _route(
            client,
            claim_id,
            key=f'{key}-another-route',
            revision=claim_before.revision,
        )

    assert unresolved.status_code == 409
    error = unresolved.json()['error']
    assert error['code'] == 'INVALID_STATE_TRANSITION'
    assert error['retryable'] is True
    assert [detail['reason'] for detail in error['details']] == ['unknown_outcome']
    assert resend.status_code == 409
    assert UNRESOLVED_MESSAGE in resend.json()['error']['message']
    assert adapter.calls == 1
    assert adapter.reconciliation_calls == 1
    assert repository.get_claim_internal(claim_id) == claim_before
    assert repository.list_evidence(claim_id, claim_before.customer_id) == []
    assert repository.list_external_task_evidence_links_internal(claim_id) == []
    assert (
        repository.list_external_tasks_internal(claim_id)[0].status
        is ExternalTaskOperationStatus.UNKNOWN_OUTCOME
    )
    assert _operation_statuses(repository, claim_id) == [
        AssessorRoutingOperationStatus.UNKNOWN_OUTCOME
    ]


def test_reconciliation_requires_integration_identity_key_and_current_revision() -> None:
    """Transport authority is checked before a provider status check can run."""

    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(failure_sequence=(SENT_THEN_LOST,))
    key = 'reconciliation-boundary'

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        assert (
            _route(client, claim_id, key=f'{key}-route', revision=consent_revision).status_code
            == 409
        )
        task = repository.list_external_tasks_internal(claim_id)[0]
        claim = repository.get_claim_internal(claim_id)
        assert claim is not None
        route = f'/internal/v1/claims/{claim_id}/external-tasks/{task.task_id}/reconcile'

        unauthenticated = client.post(
            route,
            headers={'Idempotency-Key': f'{key}-check', 'If-Match': str(claim.revision)},
        )
        claimant = client.post(
            route,
            headers={
                **AUTH,
                'Idempotency-Key': f'{key}-check',
                'If-Match': str(claim.revision),
            },
        )
        missing_key = client.post(
            route,
            headers={**INTEGRATION_AUTH, 'If-Match': str(claim.revision)},
        )
        stale = client.post(
            route,
            headers={
                **INTEGRATION_AUTH,
                'Idempotency-Key': f'{key}-check',
                'If-Match': str(claim.revision - 1),
            },
        )

    assert unauthenticated.status_code == 401
    assert claimant.status_code == 403
    assert missing_key.status_code == 400
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert stale.json()['error']['current_revision'] == claim.revision
    assert adapter.reconciliation_calls == 0
    assert repository.get_claim_internal(claim_id) == claim
    assert repository.list_external_tasks_internal(claim_id)[0] == task


class MalformedReconciliationAdapter(CountingAssessorAdapter):
    """Status-check fixture that returns a state outside accepted routing."""

    def reconcile_assessor(
        self,
        command: AssessorReconciliationRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome | None:
        """Return a non-accepted status to exercise fail-closed validation.

        Args:
            command: Persisted external-operation identity being checked.
            request_fingerprint: Stable fingerprint of that persisted identity.

        Returns:
            A provider-neutral result that cannot settle the unknown request.

        Raises:
            ValueError: This controlled fixture does not raise.
        """

        del command, request_fingerprint
        self.reconciliation_calls += 1
        return AssessorRoutingOutcome(
            result=AssessorRoutingResult(
                routing_status=AssessorRoutingStatus.NOT_REQUIRED,
                next_step='No accepted request was found.',
            ),
            replayed=False,
        )


class MissingReferenceReconciliationAdapter(CountingAssessorAdapter):
    """Status-check fixture that claims acceptance without an acknowledgement."""

    def reconcile_assessor(
        self,
        command: AssessorReconciliationRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome | None:
        """Return an accepted status without its required provider reference.

        Args:
            command: Persisted external-operation identity being checked.
            request_fingerprint: Stable fingerprint of that persisted identity.

        Returns:
            An incomplete accepted answer used to verify fail-closed handling.

        Raises:
            ValueError: This controlled fixture does not raise.
        """

        del command, request_fingerprint
        self.reconciliation_calls += 1
        return AssessorRoutingOutcome(
            result=AssessorRoutingResult(
                routing_status=AssessorRoutingStatus.ASSIGNED,
                next_step='The provider omitted its acknowledgement reference.',
            ),
            replayed=False,
        )


def test_malformed_reconciliation_result_leaves_all_persisted_state_unknown() -> None:
    """A status answer that does not prove acceptance produces no partial settlement."""

    repository = FixtureRepository()
    adapter = MalformedReconciliationAdapter(failure_sequence=(SENT_THEN_LOST,))
    key = 'malformed-reconciliation'

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        assert (
            _route(client, claim_id, key=f'{key}-route', revision=consent_revision).status_code
            == 409
        )
        claim_before = repository.get_claim_internal(claim_id)
        task_before = repository.list_external_tasks_internal(claim_id)[0]
        assert claim_before is not None

        response = _reconcile(
            client,
            claim_id,
            task_before.task_id,
            key=f'{key}-check',
            revision=claim_before.revision,
        )

    assert response.status_code == 502
    assert response.json()['error']['code'] == 'DEPENDENCY_FAILED'
    assert adapter.calls == 1
    assert adapter.reconciliation_calls == 1
    assert repository.get_claim_internal(claim_id) == claim_before
    assert repository.list_external_tasks_internal(claim_id)[0] == task_before
    assert repository.list_evidence(claim_id, claim_before.customer_id) == []
    assert _operation_statuses(repository, claim_id) == [
        AssessorRoutingOperationStatus.UNKNOWN_OUTCOME
    ]


def test_accepted_reconciliation_without_reference_leaves_state_unknown() -> None:
    """An accepted-looking status is unusable without a new provider reference."""

    repository = FixtureRepository()
    adapter = MissingReferenceReconciliationAdapter(failure_sequence=(SENT_THEN_LOST,))
    key = 'reference-less-reconciliation'

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        assert (
            _route(client, claim_id, key=f'{key}-route', revision=consent_revision).status_code
            == 409
        )
        claim_before = repository.get_claim_internal(claim_id)
        task_before = repository.list_external_tasks_internal(claim_id)[0]
        assert claim_before is not None

        response = _reconcile(
            client,
            claim_id,
            task_before.task_id,
            key=f'{key}-check',
            revision=claim_before.revision,
        )

    assert response.status_code == 502
    assert response.json()['error']['code'] == 'DEPENDENCY_FAILED'
    assert adapter.reconciliation_calls == 1
    assert repository.get_claim_internal(claim_id) == claim_before
    assert repository.list_external_tasks_internal(claim_id)[0] == task_before
    assert _operation_statuses(repository, claim_id) == [
        AssessorRoutingOperationStatus.UNKNOWN_OUTCOME
    ]


def test_fixture_status_check_rejects_incomplete_or_reused_identity() -> None:
    """The fixture status path is keyed by the persisted operation, not caller input."""

    adapter = MockAssessorServiceAdapter()
    command = AssessorReconciliationRequest(
        task_id='tsk_reconciliation_guard',
        request_id='erq_reconciliation_guard',
        operation_id='asr_op_reconciliation_guard',
        claim_id='clm_reconciliation_guard',
        external_claim_id='ext_reconciliation_guard',
        authorisation_ref='dec_reconciliation_guard',
        claimant_consent_ref='consent_reconciliation_guard',
        requested_action='vehicle_damage_assessment_routing',
        request_fingerprint='request-fingerprint',
    )

    with pytest.raises(ValueError, match='complete persisted identity'):
        adapter.reconcile_assessor(
            replace(command, task_id=''),
            'status-fingerprint',
        )

    first = adapter.reconcile_assessor(command, 'status-fingerprint')
    assert first is not None and first.replayed is False
    replay = adapter.reconcile_assessor(command, 'status-fingerprint')
    assert replay is not None and replay.replayed is True
    with pytest.raises(AdapterIdempotencyConflict):
        adapter.reconcile_assessor(command, 'changed-status-fingerprint')
    assert adapter.reset_demo_state()['mock_assessor_reconciliations'] == 1


class FailedStatusCheckAdapter(CountingAssessorAdapter):
    """Status-check fixture that raises one bounded adapter error."""

    def __init__(self, failure: Exception) -> None:
        super().__init__(failure_sequence=(SENT_THEN_LOST,))
        self.failure = failure

    def reconcile_assessor(
        self,
        command: AssessorReconciliationRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome | None:
        """Raise the configured status-check failure.

        Args:
            command: Persisted external-operation identity being checked.
            request_fingerprint: Stable fingerprint of that persisted identity.

        Returns:
            No result because the configured failure is always raised.

        Raises:
            Exception: The bounded failure configured by the test.
        """

        del command, request_fingerprint
        self.reconciliation_calls += 1
        raise self.failure


@pytest.mark.parametrize(
    ('failure', 'status_code', 'error_code', 'retryable'),
    [
        (
            AssessorAdapterFailure(AssessorFixtureFailure.UNAVAILABLE),
            503,
            'DEPENDENCY_UNAVAILABLE',
            True,
        ),
        (
            AssessorAdapterFailure(AssessorFixtureFailure.ACCESS_DENIED),
            502,
            'DEPENDENCY_FAILED',
            False,
        ),
        (ValueError('malformed status'), 502, 'DEPENDENCY_FAILED', False),
        (AdapterIdempotencyConflict('changed identity'), 409, 'IDEMPOTENCY_CONFLICT', False),
    ],
)
def test_status_check_failures_preserve_the_unresolved_operation(
    failure: Exception,
    status_code: int,
    error_code: str,
    retryable: bool,
) -> None:
    """Status dependency failures cannot partially settle or release a resend."""

    repository = FixtureRepository()
    adapter = FailedStatusCheckAdapter(failure)
    key = f'status-check-failure-{status_code}-{error_code}'

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        assert (
            _route(client, claim_id, key=f'{key}-route', revision=consent_revision).status_code
            == 409
        )
        task_before = repository.list_external_tasks_internal(claim_id)[0]
        claim_before = repository.get_claim_internal(claim_id)
        assert claim_before is not None

        response = _reconcile(
            client,
            claim_id,
            task_before.task_id,
            key=f'{key}-check',
            revision=claim_before.revision,
        )

    assert response.status_code == status_code
    error = response.json()['error']
    assert error['code'] == error_code
    assert error['retryable'] is retryable
    assert adapter.reconciliation_calls == 1
    assert repository.get_claim_internal(claim_id) == claim_before
    assert repository.list_external_tasks_internal(claim_id)[0] == task_before
    assert _operation_statuses(repository, claim_id) == [
        AssessorRoutingOperationStatus.UNKNOWN_OUTCOME
    ]


def test_reconciliation_service_refuses_missing_claim_and_task() -> None:
    """Service lookup failures are explicit and never reach the assessor adapter."""

    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(failure_sequence=())
    with pytest.raises(ApiError) as missing_claim:
        reconcile_assessor_routing(
            repository,
            adapter,
            'clm_missing',
            'tsk_missing',
            'missing-claim-check',
            1,
        )
    assert missing_claim.value.status_code == 404

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, _revision = _create_assessor_ready_claim(client, key='missing-task-check')
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None
    with pytest.raises(ApiError) as missing_task:
        reconcile_assessor_routing(
            repository,
            adapter,
            claim_id,
            'tsk_missing',
            'missing-task-check',
            claim.revision,
        )
    assert missing_task.value.status_code == 404
    assert adapter.reconciliation_calls == 0


@pytest.mark.parametrize(
    ('missing_record', 'error_code'),
    [
        ('request', 'IDEMPOTENCY_CONFLICT'),
        ('operation', 'IDEMPOTENCY_CONFLICT'),
        ('authority', 'INVALID_STATE_TRANSITION'),
    ],
)
def test_reconciliation_refuses_an_incomplete_persisted_identity_graph(
    monkeypatch: pytest.MonkeyPatch,
    missing_record: str,
    error_code: str,
) -> None:
    """Missing durable identity records fail closed before the provider status check."""

    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(failure_sequence=(SENT_THEN_LOST,))
    key = f'missing-reconciliation-{missing_record}'
    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        assert (
            _route(client, claim_id, key=f'{key}-route', revision=consent_revision).status_code
            == 409
        )
    task = repository.list_external_tasks_internal(claim_id)[0]
    claim = repository.get_claim_internal(claim_id)
    assert claim is not None

    if missing_record == 'request':
        monkeypatch.setattr(repository, 'list_external_task_requests_internal', lambda _claim: [])
    elif missing_record == 'operation':
        monkeypatch.setattr(repository, 'get_assessor_routing_operation', lambda _operation: None)
    else:
        monkeypatch.setattr(
            repository,
            'get_agent_decision_internal',
            lambda _claim, _decision: None,
        )

    with pytest.raises(ApiError) as refused:
        reconcile_assessor_routing(
            repository,
            adapter,
            claim_id,
            task.task_id,
            f'{key}-check',
            claim.revision,
        )

    assert refused.value.status_code == 409
    assert refused.value.code == error_code
    assert adapter.reconciliation_calls == 0
    assert repository.get_claim_internal(claim_id) == claim
    assert repository.list_external_tasks_internal(claim_id)[0] == task


def test_reconciliation_refuses_a_status_source_different_from_the_original() -> None:
    """A replacement adapter cannot settle an operation issued through another source."""

    repository = FixtureRepository()
    adapter = CountingAssessorAdapter(failure_sequence=(SENT_THEN_LOST,))
    key = 'mismatched-status-source'

    with TestClient(
        create_app(DEVELOPER_SETTINGS, repository=repository, assessor_service_adapter=adapter)
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        assert (
            _route(client, claim_id, key=f'{key}-route', revision=consent_revision).status_code
            == 409
        )
        task = repository.list_external_tasks_internal(claim_id)[0]
        claim = repository.get_claim_internal(claim_id)
        assert claim is not None

        # The request was persisted as fixture-sourced. Presenting this adapter as a
        # configured service only for the status check must fail before it is called.
        adapter.integration_source = IntegrationSource.CONFIGURED_SERVICE
        response = _reconcile(
            client,
            claim_id,
            task.task_id,
            key=f'{key}-check',
            revision=claim.revision,
        )

    assert response.status_code == 502
    assert response.json()['error']['code'] == 'DEPENDENCY_FAILED'
    assert adapter.reconciliation_calls == 0
    assert repository.get_claim_internal(claim_id) == claim
    assert repository.list_external_tasks_internal(claim_id)[0] == task
