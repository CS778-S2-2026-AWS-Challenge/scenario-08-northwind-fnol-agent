from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.external_services import (
    ExternalTaskDelivery,
    ExternalTaskEvidenceLink,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
)
from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    IntegrationSource,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyConflict, PersistenceRepository

INTEGRATION_AUTH = {'Authorization': 'Bearer synthetic-integration'}


def _claim(*, claim_id: str = 'clm_external_tasks') -> WorkingClaim:
    timestamp = datetime(2026, 9, 2, 1, 0, tzinfo=UTC)
    return WorkingClaim(
        claim_id=claim_id,
        customer_id='cus_external_tasks',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id=f'ses_{claim_id}',
        customer_next_step=CustomerNextStep(
            status='collecting_details',
            summary='Continue the report.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def _session(claim: WorkingClaim) -> SessionRecord:
    return SessionRecord(
        session_id=claim.active_session_id or '',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=claim.revision,
        started_at=claim.created_at,
        last_active_at=claim.updated_at,
        status=SessionStatus.ACTIVE,
    )


def _task(
    claim: WorkingClaim,
    number: int,
    *,
    status: ExternalTaskOperationStatus = ExternalTaskOperationStatus.PREPARED,
) -> ExternalTaskRecord:
    timestamp = claim.created_at + timedelta(minutes=number)
    fields: dict[str, object] = {}
    if status is ExternalTaskOperationStatus.RETRYABLE_FAILURE:
        fields['failure_code'] = ExternalTaskFailureCode.TIMEOUT
    if status is ExternalTaskOperationStatus.ACCEPTED:
        fields.update(
            delivery=ExternalTaskDelivery.SUBMITTED,
            delivery_evidence='provider acknowledgement',
            provider_reference=f'provider-{number}',
        )
    return ExternalTaskRecord(
        task_id=f'tsk_{number}',
        claim_id=claim.claim_id,
        service_identity='vehicle_damage_assessment_routing',
        requested_action='vehicle_damage_assessment',
        integration_source=IntegrationSource.FIXTURE,
        status=status,
        created_at=timestamp,
        updated_at=timestamp,
        **fields,
    )


def _repositories() -> Iterator[PersistenceRepository]:
    yield FixtureRepository()
    mongo = MongoDBRepository(mongomock.MongoClient(), 'external_task_contract')
    mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    yield mongo


@pytest.mark.parametrize('repository', _repositories())
def test_external_task_persistence_keeps_claim_and_evidence_origins(
    repository: PersistenceRepository,
) -> None:
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    first = _task(claim, 1)
    second = _task(claim, 2)
    repository.save_external_task(second, claim.customer_id)
    repository.save_external_task(first, claim.customer_id)
    link = ExternalTaskEvidenceLink(
        task_id=first.task_id,
        evidence_id='evd_external_1',
        claim_id=claim.claim_id,
        linked_at=claim.created_at + timedelta(minutes=3),
    )
    repository.save_external_task_evidence_link(link, claim.customer_id)

    assert repository.list_external_tasks_internal(claim.claim_id) == [first, second]
    assert repository.list_external_task_evidence_links_internal(claim.claim_id) == [link]

    conflicting = link.model_copy(update={'task_id': second.task_id})
    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_evidence_link(conflicting, claim.customer_id)
    changed_identity = first.model_copy(update={'service_identity': 'another_service'})
    with pytest.raises(IdempotencyConflict):
        repository.save_external_task(changed_identity, claim.customer_id)
    with pytest.raises(KeyError):
        repository.save_external_task(first, 'cus_other')


def test_internal_external_task_api_maps_material_and_pages_from_launch() -> None:
    repository = FixtureRepository()
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    tasks = [
        _task(claim, 1),
        _task(claim, 2, status=ExternalTaskOperationStatus.RETRYABLE_FAILURE),
        _task(claim, 3, status=ExternalTaskOperationStatus.ACCEPTED),
    ]
    for task in tasks:
        repository.save_external_task(task, claim.customer_id)
    repository.save_external_task_evidence_link(
        ExternalTaskEvidenceLink(
            task_id=tasks[0].task_id,
            evidence_id='evd_external_1',
            claim_id=claim.claim_id,
            linked_at=claim.created_at + timedelta(minutes=4),
        ),
        claim.customer_id,
    )
    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)

    with TestClient(create_app(settings, repository)) as client:
        first = client.get(
            f'/internal/v1/claims/{claim.claim_id}/external-tasks',
            headers=INTEGRATION_AUTH,
            params={'limit': 2},
        )
        assert first.status_code == 200
        payload = first.json()
        assert payload['claim_id'] == claim.claim_id
        assert [item['task']['task_id'] for item in payload['items']] == ['tsk_1', 'tsk_2']
        assert payload['items'][0]['evidence_ids'] == ['evd_external_1']
        assert payload['items'][0]['task']['integration_source'] == 'fixture'
        assert payload['items'][1]['task']['status'] == 'retryable_failure'
        assert payload['items'][0]['task']['created_at'] is not None

        second = client.get(
            f'/internal/v1/claims/{claim.claim_id}/external-tasks',
            headers=INTEGRATION_AUTH,
            params={'cursor': payload['page']['next_cursor'], 'limit': 2},
        )
        assert second.status_code == 200
        assert [item['task']['task_id'] for item in second.json()['items']] == ['tsk_3']
        assert second.json()['page'] == {'next_cursor': None}


def test_internal_external_task_api_fails_closed_for_auth_claim_and_cursor(
    client: TestClient,
) -> None:
    path = '/internal/v1/claims/clm_missing/external-tasks'

    assert client.get(path).status_code == 401
    assert client.get(path, headers=INTEGRATION_AUTH).status_code == 404
    invalid = client.get(path, headers=INTEGRATION_AUTH, params={'cursor': 'not-a-cursor'})
    assert invalid.status_code == 404

    repository = FixtureRepository()
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    with TestClient(create_app(settings, repository)) as scoped_client:
        invalid = scoped_client.get(
            f'/internal/v1/claims/{claim.claim_id}/external-tasks',
            headers=INTEGRATION_AUTH,
            params={'cursor': 'not-a-cursor'},
        )
        assert invalid.status_code == 422
        assert invalid.json()['error']['code'] == 'VALIDATION_ERROR'
