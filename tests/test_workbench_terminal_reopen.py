from datetime import UTC, datetime
from typing import Any

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.core.auth import Principal
from backend.domain.audit import AuditSubject, AuditSubjectType
from backend.domain.models import (
    ActorReference,
    ActorType,
    Channel,
    ClaimCreationStatus,
    ClaimState,
    ClaimTerminalDisposition,
    CustomerNextStep,
    ExternalClaimResult,
    IntegrationSource,
    ReopenClaimRequest,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services.terminal_claims import reopen_claim


def _terminal_reason(value: TerminalDispositionValue) -> TerminalDispositionReasonCode:
    return {
        TerminalDispositionValue.COMPLETED: TerminalDispositionReasonCode.CLAIM_CREATED,
        TerminalDispositionValue.ABANDONED: (
            TerminalDispositionReasonCode.ABANDONMENT_POLICY_APPLIED
        ),
        TerminalDispositionValue.CLOSED: TerminalDispositionReasonCode.AUTHORISED_CLOSURE,
    }[value]


def _terminal_claim(
    claim_id: str,
    value: TerminalDispositionValue,
    *,
    owner_id: str = 'stf_demo',
) -> tuple[WorkingClaim, SessionRecord]:
    timestamp = datetime(2026, 9, 11, 6, 0, tzinfo=UTC)
    completed = value is TerminalDispositionValue.COMPLETED
    external_claim_id = f'ext_{claim_id}'
    external_claim = (
        ExternalClaimResult(
            external_claim_id=external_claim_id,
            claim_number=f'NW-{claim_id}',
            creation_status=ClaimCreationStatus.CREATED,
            route='standard_motor_intake',
            next_step='A claims professional will review the created Claim.',
            source=IntegrationSource.FIXTURE,
            created_at=timestamp,
        )
        if completed
        else None
    )
    source_refs = (
        ['dec_claim_created', external_claim_id]
        if external_claim is not None
        else [f'act_{value.value}']
    )
    claim = WorkingClaim(
        claim_id=claim_id,
        customer_id=f'cus_{claim_id}',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='motor',
        claim_state=ClaimState(
            workflow_state=(WorkflowState.CREATED if completed else WorkflowState.COLLECTING)
        ),
        assignee_id=owner_id,
        active_session_id=f'ses_{claim_id}',
        external_claim=external_claim,
        terminal_disposition=ClaimTerminalDisposition(
            value=value,
            reason_code=_terminal_reason(value),
            source_refs=source_refs,
            recorded_by=ActorReference(
                actor_type=ActorType.SYSTEM,
                actor_id='terminal_contract_test',
            ),
            recorded_at=timestamp,
            recorded_revision=1,
        ),
        customer_next_step=CustomerNextStep(
            status=value.value,
            summary=f'The Claim is {value.value}.',
            responsible_party=ResponsibleParty.SYSTEM,
            can_resume=not completed,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id=claim.active_session_id or '',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=claim.revision,
        started_at=timestamp,
        last_active_at=timestamp,
        status=SessionStatus.ACTIVE,
    )
    return claim, session


def _store_terminal_claim(
    repository: PersistenceRepository,
    claim_id: str,
    value: TerminalDispositionValue,
    *,
    owner_id: str = 'stf_demo',
) -> WorkingClaim:
    claim, session = _terminal_claim(claim_id, value, owner_id=owner_id)
    repository.create_claim(claim, session)
    return claim


def test_terminal_views_are_server_owned_and_excluded_from_all_active(
    client: TestClient,
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claims = {
        value: _store_terminal_claim(repository, f'clm_{value.value}', value)
        for value in TerminalDispositionValue
    }

    metadata = client.get(
        '/api/v1/workbench/claims/filter-metadata',
        headers=staff_auth_headers,
    )
    assert metadata.status_code == 200
    terminal_views = [item for item in metadata.json()['views'] if item['group'] == 'terminal']
    assert [item['value'] for item in terminal_views] == ['completed', 'abandoned', 'closed']

    active = client.get('/api/v1/workbench/claims?view=all', headers=staff_auth_headers)
    assert active.status_code == 200
    assert active.json()['items'] == []
    counts = {item['view']: item['count'] for item in active.json()['view_counts']['items']}
    assert counts['all'] == 0

    for value, claim in claims.items():
        response = client.get(
            f'/api/v1/workbench/claims?view={value.value}',
            headers=staff_auth_headers,
        )
        assert response.status_code == 200
        item = response.json()['items'][0]
        assert item['claim_id'] == claim.claim_id
        assert item['work_summary']['queue_key'] == value.value
        assert item['terminal_disposition']['value'] == value.value
        assert counts[value.value] == 1

    created_routed = client.get(
        '/api/v1/workbench/claims?view=created_routed',
        headers=staff_auth_headers,
    )
    assert [item['claim_id'] for item in created_routed.json()['items']] == [
        claims[TerminalDispositionValue.COMPLETED].claim_id
    ]


def test_primary_owner_reopens_closed_claim_with_atomic_audit_and_replay(
    client: TestClient,
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim = _store_terminal_claim(repository, 'clm_reopen_api', TerminalDispositionValue.CLOSED)
    terminal = claim.terminal_disposition
    assert terminal is not None
    before = client.get(
        f'/api/v1/workbench/claims/{claim.claim_id}',
        headers=staff_auth_headers,
    )
    assert before.status_code == 200
    action = before.json()['allowed_actions'][0]
    assert action['action_code'] == 'claim.reopen'
    assert action['target_ref'] == claim.claim_id
    assert action['based_on_revision'] == claim.revision
    assert action['availability'] == 'confirmation_required'
    assert action['source_refs'] == terminal.source_refs

    headers = {
        **staff_auth_headers,
        'Idempotency-Key': 'reopen-closed-claim',
        'If-Match': str(claim.revision),
    }
    response = client.post(
        f'/api/v1/workbench/claims/{claim.claim_id}/reopen',
        headers=headers,
        json={'reason': 'The claimant supplied the information needed to continue.'},
    )
    assert response.status_code == 200
    reopened = response.json()
    assert reopened['revision'] == claim.revision + 1
    assert reopened['terminal_disposition'] is None
    assert reopened['work_summary']['queue_key'] == 'processing'
    assert reopened['active_session_id'] == claim.active_session_id

    replay = client.post(
        f'/api/v1/workbench/claims/{claim.claim_id}/reopen',
        headers=headers,
        json={'reason': 'The claimant supplied the information needed to continue.'},
    )
    assert replay.status_code == 200
    assert replay.json() == reopened

    conflict = client.post(
        f'/api/v1/workbench/claims/{claim.claim_id}/reopen',
        headers=headers,
        json={'reason': 'A changed reason must not reuse the same operation key.'},
    )
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'

    revision_conflict = client.post(
        f'/api/v1/workbench/claims/{claim.claim_id}/reopen',
        headers={**headers, 'If-Match': str(claim.revision + 1)},
        json={'reason': 'The claimant supplied the information needed to continue.'},
    )
    assert revision_conflict.status_code == 409
    assert revision_conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'

    already_reopened = client.post(
        f'/api/v1/workbench/claims/{claim.claim_id}/reopen',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'reopen-closed-again',
            'If-Match': str(claim.revision + 1),
        },
        json={'reason': 'A cleared terminal record cannot be reopened twice.'},
    )
    assert already_reopened.status_code == 403
    assert already_reopened.json()['error']['code'] == 'ACCESS_DENIED'

    subject = AuditSubject(
        subject_type=AuditSubjectType.CLAIM,
        subject_id=claim.claim_id,
        claim_id=claim.claim_id,
    )
    events = repository.list_audit_events_internal(subject)
    assert len(events) == 1
    assert events[0].actor.actor_id == 'stf_demo'
    assert events[0].source_refs == terminal.source_refs
    assert events[0].claim_revision == reopened['revision']
    assert events[0].idempotency_key == 'reopen-closed-claim'

    active = client.get('/api/v1/workbench/claims?view=all', headers=staff_auth_headers)
    assert [item['claim_id'] for item in active.json()['items']] == [claim.claim_id]
    closed = client.get('/api/v1/workbench/claims?view=closed', headers=staff_auth_headers)
    assert closed.json()['items'] == []


def test_reopen_rejects_non_owner_completed_stale_missing_and_unknown_input(
    client: TestClient,
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    non_owner = _store_terminal_claim(
        repository,
        'clm_non_owner',
        TerminalDispositionValue.ABANDONED,
        owner_id='stf_other',
    )
    detail = client.get(
        f'/api/v1/workbench/claims/{non_owner.claim_id}', headers=staff_auth_headers
    ).json()
    assert detail['allowed_actions'][0]['availability'] == 'blocked'
    denied = client.post(
        f'/api/v1/workbench/claims/{non_owner.claim_id}/reopen',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'reopen-non-owner',
            'If-Match': '1',
        },
        json={'reason': 'This staff member is not the primary owner.'},
    )
    assert denied.status_code == 403
    assert denied.json()['error']['code'] == 'ACCESS_DENIED'

    completed = _store_terminal_claim(
        repository, 'clm_completed_no_reopen', TerminalDispositionValue.COMPLETED
    )
    completed_detail = client.get(
        f'/api/v1/workbench/claims/{completed.claim_id}', headers=staff_auth_headers
    ).json()
    assert all(
        action['action_code'] != 'claim.reopen' for action in completed_detail['allowed_actions']
    )
    completed_denied = client.post(
        f'/api/v1/workbench/claims/{completed.claim_id}/reopen',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'reopen-completed',
            'If-Match': '1',
        },
        json={'reason': 'Completed Claims cannot return to FNOL intake.'},
    )
    assert completed_denied.status_code == 403

    owner = _store_terminal_claim(
        repository, 'clm_reopen_failures', TerminalDispositionValue.ABANDONED
    )
    stale = client.post(
        f'/api/v1/workbench/claims/{owner.claim_id}/reopen',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'reopen-stale',
            'If-Match': '2',
        },
        json={'reason': 'This page is stale.'},
    )
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'
    assert stale.json()['error']['current_revision'] == 1

    unknown = client.post(
        f'/api/v1/workbench/claims/{owner.claim_id}/reopen',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'reopen-unknown-field',
            'If-Match': '1',
        },
        json={'reason': 'Valid reason.', 'terminal_state': 'processing'},
    )
    assert unknown.status_code == 422
    assert unknown.json()['error']['code'] == 'VALIDATION_ERROR'

    missing = client.post(
        '/api/v1/workbench/claims/clm_missing/reopen',
        headers={
            **staff_auth_headers,
            'Idempotency-Key': 'reopen-missing',
            'If-Match': '1',
        },
        json={'reason': 'The target does not exist.'},
    )
    assert missing.status_code == 404
    assert missing.json()['error']['code'] == 'RESOURCE_NOT_FOUND'


def _repository(repository_kind: str) -> PersistenceRepository:
    if repository_kind == 'fixture':
        return FixtureRepository()
    client: Any = mongomock.MongoClient()
    repository = MongoDBRepository(client, 'northwind_terminal_reopen_test')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb'])
def test_reopen_persists_terminal_clear_staff_idempotency_and_audit(
    repository_kind: str,
) -> None:
    repository = _repository(repository_kind)
    claim = _store_terminal_claim(
        repository,
        f'clm_reopen_{repository_kind}',
        TerminalDispositionValue.ABANDONED,
    )
    terminal = claim.terminal_disposition
    assert terminal is not None
    principal = Principal(
        subject='stf_demo',
        actor_type='staff',
        auth_source='test:staff_session',
    )

    response = reopen_claim(
        repository,
        principal,
        claim.claim_id,
        ReopenClaimRequest(reason='The recovery path is ready to continue.'),
        f'reopen-{repository_kind}',
        '1',
    )

    stored = repository.get_claim_internal(claim.claim_id)
    assert stored is not None
    assert stored.terminal_disposition is None
    assert stored.revision == response.revision == 2
    assert stored.active_session_id == claim.active_session_id
    idempotency = repository.find_idempotency(
        principal.subject,
        f'/api/v1/workbench/claims/{claim.claim_id}/reopen',
        f'reopen-{repository_kind}',
    )
    assert idempotency is not None
    assert idempotency.action_code == 'claim.reopen'
    assert idempotency.target_ref == claim.claim_id
    events = repository.list_audit_events_internal(
        AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim.claim_id,
            claim_id=claim.claim_id,
        )
    )
    assert len(events) == 1
    assert events[0].source_refs == terminal.source_refs
