import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.adapters.claims_service import (
    AssessorFixtureFailure,
    AssessorRoutingOutcome,
    MockAssessorServiceAdapter,
)
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.external_services import (
    ExternalTaskOperationStatus,
)
from backend.domain.models import IntegrationSource, RouteAssessorRequest
from backend.repositories.fixture import FixtureRepository
from backend.services.external_service_entry import MismatchedServiceAdapterError

AUTH = {'Authorization': 'Bearer synthetic-claimant'}
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
    assert confirmation.json()['customer_next_step']['status'] == 'ready_to_create'

    external = client.post(
        f'/api/v1/claims/{claim_id}/creation',
        headers={
            **AUTH,
            'Idempotency-Key': f'{key}-creation',
            'If-Match': str(confirmation.json()['revision']),
        },
    )
    assert external.status_code == 201
    body = external.json()
    assert body['external_claim']['creation_status'] == 'created'
    assert body['external_service_action']['status'] == 'consent_required'
    assert body['external_service_action']['can_request'] is True
    return claim_id, int(body['revision'])


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
    assert response.json()['action']['status'] == 'ready_to_request'
    return int(response.json()['revision'])


class NeverCalledAssessorAdapter:
    """A double that must never answer, so it declares the source class of a double."""

    integration_source = IntegrationSource.FIXTURE

    def route_assessor(
        self,
        command: RouteAssessorRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome:
        del command, request_fingerprint
        raise AssertionError('The assessor adapter must not be called without claimant consent.')


def test_declined_consent_preserves_the_claim_and_never_calls_the_adapter() -> None:
    repository = FixtureRepository()
    with TestClient(
        create_app(
            DEVELOPER_SETTINGS,
            repository=repository,
            assessor_service_adapter=NeverCalledAssessorAdapter(),
        )
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key='declined-consent')
        before = repository.get_claim_internal(claim_id)
        assert before is not None

        declined = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing/consent',
            headers={
                **AUTH,
                'Idempotency-Key': 'declined-consent-choice',
                'If-Match': str(revision),
            },
            json={'consent': False},
        )
        route_without_consent = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers={
                **AUTH,
                'Idempotency-Key': 'declined-consent-route',
                'If-Match': str(revision),
            },
        )
        claimant = client.get(f'/api/v1/claims/{claim_id}', headers=AUTH)

    assert declined.status_code == 422
    assert declined.json()['error']['code'] == 'VALIDATION_ERROR'
    assert route_without_consent.status_code == 409
    assert route_without_consent.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    assert claimant.status_code == 200
    assert claimant.json()['workflow_state'] == 'created'
    assert claimant.json()['external_service_action']['status'] == 'consent_required'
    after = repository.get_claim_internal(claim_id)
    assert after is not None
    assert after.model_dump(mode='json') == before.model_dump(mode='json')
    assert after.external_service_consents == []
    assert after.assessor_routing is None


def test_success_is_claimant_safe_and_replays_without_a_second_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FixtureRepository()
    with TestClient(create_app(DEVELOPER_SETTINGS, repository=repository)) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key='validation-success')
        consent_revision = _grant_consent(
            client,
            claim_id,
            revision,
            key='validation-success',
        )
        headers = {
            **AUTH,
            'Idempotency-Key': 'validation-success-route',
            'If-Match': str(consent_revision),
        }
        same_instant = datetime(2026, 9, 3, tzinfo=UTC)
        monkeypatch.setattr(
            'backend.services.integrations.now_utc',
            lambda: same_instant,
        )

        routed = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers=headers,
        )
        replay = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers=headers,
        )

    assert routed.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == routed.json()
    projection = routed.json()
    assert projection['action']['status'] == 'assigned'
    assert projection['action']['routing']['routing_status'] == 'assigned'
    assert 'consent_ref' not in str(projection)
    assert 'decision_id' not in str(projection)
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.revision == consent_revision + 1
    assert stored.assessor_routing is not None
    tasks = repository.list_external_tasks_internal(claim_id)
    assert len(tasks) == 1
    assert tasks[0].updated_at == same_instant + timedelta(microseconds=1)
    decisions = [
        decision
        for decision in repository.list_agent_decisions(claim_id, 'cus_demo')
        if decision.reason_codes == ['ASSESSOR_RULE_AUTHORISED']
    ]
    assert len(decisions) == 1


@pytest.mark.parametrize(
    'failure',
    [AssessorFixtureFailure.UNAVAILABLE, AssessorFixtureFailure.TIMEOUT],
)
def test_transient_failure_preserves_progress_then_retries_with_the_same_operation(
    failure: AssessorFixtureFailure,
) -> None:
    repository = FixtureRepository()
    adapter = MockAssessorServiceAdapter(failure_sequence=(failure,))
    with TestClient(
        create_app(
            DEVELOPER_SETTINGS,
            repository=repository,
            assessor_service_adapter=adapter,
        )
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(
            client,
            key=f'validation-{failure.value}',
        )
        consent_revision = _grant_consent(
            client,
            claim_id,
            revision,
            key=f'validation-{failure.value}',
        )
        before_attempt = repository.get_claim_internal(claim_id)
        assert before_attempt is not None
        headers = {
            **AUTH,
            'Idempotency-Key': f'validation-{failure.value}-route',
            'If-Match': str(consent_revision),
        }

        failed = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers=headers,
        )
        after_failure = repository.get_claim_internal(claim_id)
        claimant_after_failure = client.get(f'/api/v1/claims/{claim_id}', headers=AUTH)
        retry = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers=headers,
        )
        replay = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers=headers,
        )

    assert failed.status_code == 503
    error = failed.json()['error']
    assert error['code'] == 'DEPENDENCY_UNAVAILABLE'
    assert error['retryable'] is True
    assert error['details'] == [{'field': 'assessor_service', 'reason': failure.value}]
    assert after_failure is not None
    assert after_failure.model_dump(mode='json') == before_attempt.model_dump(mode='json')
    assert after_failure.revision == consent_revision
    assert after_failure.assessor_routing is None
    assert after_failure.customer_next_step.status == 'assessor_request_ready'
    assert claimant_after_failure.status_code == 200
    # AT-10 requires the claimant to receive an honest state and next step. This
    # projection previously returned to `ready_to_request`, offering the service
    # again without saying that the last attempt had failed.
    action_after_failure = claimant_after_failure.json()['external_service_action']
    assert action_after_failure['status'] == 'retryable_failure'
    assert action_after_failure['failure_code'] == failure.value
    assert action_after_failure['can_request'] is True
    assert retry.status_code == 201
    assert retry.json()['action']['status'] == 'assigned'
    assert replay.status_code == 200
    assert replay.json() == retry.json()
    stored = repository.get_claim_internal(claim_id)
    assert stored is not None
    assert stored.revision == consent_revision + 1
    decisions = [
        decision
        for decision in repository.list_agent_decisions(claim_id, 'cus_demo')
        if decision.reason_codes == ['ASSESSOR_RULE_AUTHORISED']
    ]
    assert len(decisions) == 1


class ConfiguredServiceAssessorAdapter(NeverCalledAssessorAdapter):
    """A double that claims to be a configured service, which the fixture runtime is not."""

    integration_source = IntegrationSource.CONFIGURED_SERVICE


def test_a_runtime_will_not_assemble_an_adapter_its_entry_cannot_provide() -> None:
    """The separation is enforced at composition, not left to whoever wires the app.

    Under the fixture profile the entry resolves to `test_fixture`, so an adapter
    declaring `configured_service` would answer through one source class while the
    runtime recorded another. The application refuses to start rather than run in
    that state, because a runtime that mislabels its own answers is worse than one
    that will not boot.
    """

    with pytest.raises(MismatchedServiceAdapterError):
        create_app(
            DEVELOPER_SETTINGS,
            repository=FixtureRepository(),
            assessor_service_adapter=ConfiguredServiceAssessorAdapter(),
        )


def test_the_fixture_runtime_assembles_with_the_adapter_it_declares() -> None:
    """The refusal above is a real bound, not one that refuses everything."""

    app = create_app(DEVELOPER_SETTINGS, repository=FixtureRepository())

    assert app.state.assessor_service_adapter.integration_source is IntegrationSource.FIXTURE
    assert app.state.assessor_service_entry.integration_source is IntegrationSource.FIXTURE


@pytest.mark.parametrize(
    ('failure', 'expected'),
    [
        (AssessorFixtureFailure.UNAVAILABLE, ExternalTaskOperationStatus.RETRYABLE_FAILURE),
        (AssessorFixtureFailure.TIMEOUT, ExternalTaskOperationStatus.RETRYABLE_FAILURE),
        (AssessorFixtureFailure.ACCESS_DENIED, ExternalTaskOperationStatus.TERMINAL_FAILURE),
        (AssessorFixtureFailure.MALFORMED, ExternalTaskOperationStatus.TERMINAL_FAILURE),
    ],
)
def test_a_failed_attempt_is_recorded_on_the_task_rather_than_left_prepared(
    failure: AssessorFixtureFailure,
    expected: ExternalTaskOperationStatus,
) -> None:
    """A failed task must not still claim the request had not been sent.

    The routing operation already carried the failure. The task did not, so it
    stayed `prepared` and nothing reading the task could tell a finished failure
    from a request still in flight. The recovery matrix decides which failure this
    is; the task records it.
    """

    repository = FixtureRepository()
    adapter = MockAssessorServiceAdapter(failure_sequence=(failure,))
    key = f'recorded-{failure.value}'
    with TestClient(
        create_app(
            DEVELOPER_SETTINGS,
            repository=repository,
            assessor_service_adapter=adapter,
        )
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers={
                **AUTH,
                'Idempotency-Key': f'{key}-route',
                'If-Match': str(consent_revision),
            },
        )

    tasks = repository.list_external_tasks_internal(claim_id)
    assert len(tasks) == 1
    assert tasks[0].status is expected
    assert tasks[0].failure_code is not None
    assert tasks[0].failure_code.value == failure.value
    assert tasks[0].updated_at > tasks[0].created_at


def test_a_retry_continues_the_failed_task_instead_of_opening_a_second_one() -> None:
    """The retry advances the task it already has, and does not reset it.

    Returning the record to `prepared` would assert the first attempt had never
    been sent, which the transition guard refuses. One operation keeps one task
    across the failure and the retry that succeeds.
    """

    repository = FixtureRepository()
    adapter = MockAssessorServiceAdapter(failure_sequence=(AssessorFixtureFailure.UNAVAILABLE,))
    key = 'retry-continues'
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

    assert failed.status_code == 503
    assert len(after_failure) == 1
    assert after_failure[0].status is ExternalTaskOperationStatus.RETRYABLE_FAILURE
    assert retry.status_code == 201
    tasks = repository.list_external_tasks_internal(claim_id)
    assert len(tasks) == 1
    assert tasks[0].task_id == after_failure[0].task_id
    assert tasks[0].status is ExternalTaskOperationStatus.ACCEPTED
    assert tasks[0].updated_at > after_failure[0].updated_at


@pytest.mark.parametrize(
    'failure',
    [AssessorFixtureFailure.ACCESS_DENIED, AssessorFixtureFailure.MALFORMED],
)
def test_a_terminal_failure_is_shown_to_the_claimant_and_withdraws_the_request(
    failure: AssessorFixtureFailure,
) -> None:
    """A terminal failure is honest about itself and stops offering another attempt.

    AT-10 gives these two codes the `terminal_failure` lifecycle status and says
    Northwind must review the request before trying again, so the claimant keeps
    the state but loses the affordance. The claim itself is untouched, which is
    what that scenario's empty `failure_may_change` requires.
    """

    repository = FixtureRepository()
    adapter = MockAssessorServiceAdapter(failure_sequence=(failure,))
    key = f'terminal-{failure.value}'
    with TestClient(
        create_app(
            DEVELOPER_SETTINGS,
            repository=repository,
            assessor_service_adapter=adapter,
        )
    ) as client:
        claim_id, revision = _create_assessor_ready_claim(client, key=key)
        consent_revision = _grant_consent(client, claim_id, revision, key=key)
        before = repository.get_claim_internal(claim_id)
        headers = {
            **AUTH,
            'Idempotency-Key': f'{key}-route',
            'If-Match': str(consent_revision),
        }

        failed = client.post(f'/api/v1/claims/{claim_id}/assessor-routing', headers=headers)
        claimant = client.get(f'/api/v1/claims/{claim_id}', headers=AUTH)
        another = client.post(
            f'/api/v1/claims/{claim_id}/assessor-routing',
            headers={
                **AUTH,
                'Idempotency-Key': f'{key}-again',
                'If-Match': str(consent_revision),
            },
        )

    assert failed.status_code == 502
    action = claimant.json()['external_service_action']
    assert action['status'] == 'terminal_failure'
    assert action['failure_code'] == failure.value
    assert action['can_request'] is False
    assert action['routing'] is None
    assert another.status_code == 409
    assert another.json()['error']['code'] == 'INVALID_STATE_TRANSITION'
    after = repository.get_claim_internal(claim_id)
    assert before is not None and after is not None
    assert after.model_dump(mode='json') == before.model_dump(mode='json')
