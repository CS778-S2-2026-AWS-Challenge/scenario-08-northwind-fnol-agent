import logging
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
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
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


def _evidence(claim: WorkingClaim, evidence_id: str = 'evd_external_1') -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        claim_id=claim.claim_id,
        kind='external_assessment',
        status=EvidenceStatus.PENDING_GENERATION,
        file_status=EvidenceFileStatus.NOT_AVAILABLE,
        source=EvidenceSource.EXTERNAL_SYSTEM,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
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
    repository.save_evidence(_evidence(claim), claim.customer_id)
    link = ExternalTaskEvidenceLink(
        task_id=first.task_id,
        evidence_id='evd_external_1',
        claim_id=claim.claim_id,
        linked_at=claim.created_at + timedelta(minutes=3),
    )
    repository.save_external_task_evidence_link(link, claim.customer_id)
    repository.save_external_task_evidence_link(link, claim.customer_id)

    assert repository.list_external_tasks_internal(claim.claim_id) == [first, second]
    assert repository.list_external_task_evidence_links_internal(claim.claim_id) == [link]

    progressed = first.model_copy(
        update={
            'status': ExternalTaskOperationStatus.RETRYABLE_FAILURE,
            'failure_code': ExternalTaskFailureCode.TIMEOUT,
            'updated_at': first.updated_at + timedelta(minutes=1),
        }
    )
    repository.save_external_task(progressed, claim.customer_id)
    assert repository.list_external_tasks_internal(claim.claim_id)[0] == progressed

    missing_evidence = link.model_copy(update={'evidence_id': 'evd_missing'})
    with pytest.raises(KeyError):
        repository.save_external_task_evidence_link(missing_evidence, claim.customer_id)

    other_claim = _claim(claim_id='clm_external_tasks_other')
    repository.create_claim(other_claim, _session(other_claim))
    repository.save_evidence(_evidence(other_claim, 'evd_other_claim'), other_claim.customer_id)
    cross_claim = link.model_copy(update={'evidence_id': 'evd_other_claim'})
    with pytest.raises(KeyError):
        repository.save_external_task_evidence_link(cross_claim, claim.customer_id)

    conflicting = link.model_copy(update={'task_id': second.task_id})
    with pytest.raises(IdempotencyConflict):
        repository.save_external_task_evidence_link(conflicting, claim.customer_id)
    changed_identity = first.model_copy(update={'service_identity': 'another_service'})
    with pytest.raises(IdempotencyConflict):
        repository.save_external_task(changed_identity, claim.customer_id)
    with pytest.raises(KeyError):
        repository.save_external_task(first, 'cus_other')


def test_internal_external_task_api_maps_material_pages_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
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
    repository.save_evidence(_evidence(claim), claim.customer_id)
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
        with caplog.at_level(logging.INFO, logger='backend.api.integrations'):
            first = client.get(
                f'/internal/v1/claims/{claim.claim_id}/external-tasks',
                headers={**INTEGRATION_AUTH, 'X-Request-ID': 'external-task-list-test'},
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
        event = next(record for record in caplog.records if record.msg == 'external_tasks.list')
        assert event.__dict__['request_id'] == 'external-task-list-test'
        assert event.__dict__['claim_id'] == claim.claim_id
        assert event.__dict__['limit'] == 2

        second = client.get(
            f'/internal/v1/claims/{claim.claim_id}/external-tasks',
            headers=INTEGRATION_AUTH,
            params={'cursor': payload['page']['next_cursor'], 'limit': 2},
        )
        assert second.status_code == 200
        assert [item['task']['task_id'] for item in second.json()['items']] == ['tsk_3']
        assert second.json()['page'] == {'next_cursor': None}


def test_internal_external_task_api_truncates_limit_above_cap() -> None:
    repository = FixtureRepository()
    claim = _claim()
    repository.create_claim(claim, _session(claim))
    for number in range(1, 102):
        repository.save_external_task(_task(claim, number), claim.customer_id)
    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)

    with TestClient(create_app(settings, repository)) as client:
        response = client.get(
            f'/internal/v1/claims/{claim.claim_id}/external-tasks',
            headers=INTEGRATION_AUTH,
            params={'limit': 101},
        )

    assert response.status_code == 200
    assert len(response.json()['items']) == 100
    assert response.json()['page']['next_cursor'] is not None


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
        invalid_limit = scoped_client.get(
            f'/internal/v1/claims/{claim.claim_id}/external-tasks',
            headers=INTEGRATION_AUTH,
            params={'limit': 0},
        )
        assert invalid_limit.status_code == 422
        invalid = scoped_client.get(
            f'/internal/v1/claims/{claim.claim_id}/external-tasks',
            headers=INTEGRATION_AUTH,
            params={'cursor': 'not-a-cursor'},
        )
        assert invalid.status_code == 422
        assert invalid.json()['error']['code'] == 'VALIDATION_ERROR'
