from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from typing import Any

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.core.auth import STAFF_SCOPES, Principal
from backend.core.errors import ApiError
from backend.domain.audit import AuditSubject, AuditSubjectType
from backend.domain.models import (
    ActorReference,
    ActorType,
    Channel,
    ClaimCreationStatus,
    ClaimDecisionRequest,
    ClaimDecisionValue,
    ClaimState,
    ClaimTerminalDisposition,
    CustomerNextStep,
    ExternalClaimResult,
    IntegrationSource,
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
from backend.services.staff_actions import decide_claim


def _created_claim(
    claim_id: str = 'clm_decision',
    *,
    customer_id: str = 'cus_demo',
    owner_id: str = 'stf_demo',
    workflow_state: WorkflowState = WorkflowState.CREATED,
) -> tuple[WorkingClaim, SessionRecord]:
    timestamp = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    external_claim = ExternalClaimResult(
        external_claim_id=f'ext_{claim_id}',
        claim_number=f'NW-{claim_id}',
        creation_status=ClaimCreationStatus.CREATED,
        route='standard_motor_intake',
        next_step='A claims professional will review the created Claim.',
        source=IntegrationSource.FIXTURE,
        created_at=timestamp,
    )
    claim = WorkingClaim(
        claim_id=claim_id,
        customer_id=customer_id,
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='motor',
        claim_state=ClaimState(workflow_state=workflow_state),
        assignee_id=owner_id,
        active_session_id=f'ses_{claim_id}',
        external_claim=external_claim,
        terminal_disposition=ClaimTerminalDisposition(
            value=TerminalDispositionValue.COMPLETED,
            reason_code=TerminalDispositionReasonCode.CLAIM_CREATED,
            source_refs=['dec_claim_created', external_claim.external_claim_id],
            recorded_by=ActorReference(
                actor_type=ActorType.SYSTEM,
                actor_id='claim_creation_service',
            ),
            recorded_at=timestamp,
            recorded_revision=1,
        ),
        customer_next_step=CustomerNextStep(
            status='claim_created',
            summary='Your Claim was created and is ready for staff review.',
            responsible_party=ResponsibleParty.CLAIMS_PROFESSIONAL,
            can_resume=False,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id=claim.active_session_id or '',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=claim.revision,
        status=SessionStatus.ACTIVE,
        started_at=timestamp,
        last_active_at=timestamp,
    )
    return claim, session


def _store_created_claim(
    repository: PersistenceRepository,
    claim_id: str = 'clm_decision',
    *,
    customer_id: str = 'cus_demo',
    owner_id: str = 'stf_demo',
    workflow_state: WorkflowState = WorkflowState.CREATED,
) -> WorkingClaim:
    claim, session = _created_claim(
        claim_id,
        customer_id=customer_id,
        owner_id=owner_id,
        workflow_state=workflow_state,
    )
    repository.create_claim(claim, session)
    return claim


def _decision_headers(
    staff_auth_headers: dict[str, str],
    *,
    key: str = 'claim-decision-1',
    revision: int = 1,
) -> dict[str, str]:
    return {
        **staff_auth_headers,
        'Idempotency-Key': key,
        'If-Match': str(revision),
    }


def test_approval_is_atomic_idempotent_and_role_safe(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim, session = _created_claim()
    # Older created Claims may retain the pre-fix resumable flag. Claimant reads must still
    # agree with the terminal Session boundary without rewriting the durable record.
    claim = claim.model_copy(
        update={
            'customer_next_step': claim.customer_next_step.model_copy(update={'can_resume': True})
        }
    )
    repository.create_claim(claim, session)
    route = f'/api/v1/workbench/claims/{claim.claim_id}/decisions'
    workbench_before = client.get(
        f'/api/v1/workbench/claims/{claim.claim_id}', headers=staff_auth_headers
    )
    assert workbench_before.status_code == 200
    action = next(
        item
        for item in workbench_before.json()['allowed_actions']
        if item['action_code'] == 'claim.record_decision'
    )
    assert action['availability'] == 'confirmation_required'
    assert action['confirmation']['level'] == 'high_impact'

    realtime_before = len(repository._realtime_events)
    response = client.post(
        route,
        headers=_decision_headers(staff_auth_headers),
        json={'decision': 'approved', 'internal_note': 'Reviewed against the policy.'},
    )

    assert response.status_code == 201
    decision = response.json()
    assert decision['decision'] == 'approved'
    assert decision['decided_by'] == 'stf_demo'
    assert decision['claimant_explanation'] == 'Your claim has been approved.'
    assert decision['source_claim_revision'] == 1
    stored = repository.get_claim_internal(claim.claim_id)
    assert stored is not None
    assert stored.revision == 2
    assert stored.claim_decision_id == decision['decision_id']
    assert len(repository._claim_decisions) == 1
    assert len(repository._realtime_events) == realtime_before + 1
    audits = repository.list_audit_events_internal(
        AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim.claim_id,
            claim_id=claim.claim_id,
        )
    )
    assert len(audits) == 1
    assert audits[0].actor.actor_id == 'stf_demo'
    assert audits[0].permission is not None
    assert audits[0].permission.required_permission == 'claim.record_decision'

    claimant = client.get(f'/api/v1/claims/{claim.claim_id}', headers=auth_headers)
    assert claimant.status_code == 200
    assert claimant.json()['claim_decision'] == {
        'decision': 'approved',
        'decided_at': decision['decided_at'],
        'claimant_explanation': 'Your claim has been approved.',
    }
    assert claimant.json()['customer_next_step']['can_resume'] is False
    assert 'internal_note' not in claimant.text
    assert 'decided_by' not in claimant.text
    claimant_list = client.get('/api/v1/claims', headers=auth_headers)
    assert claimant_list.status_code == 200
    assert claimant_list.json()['items'][0]['claim_decision'] == claimant.json()['claim_decision']
    assert claimant_list.json()['items'][0]['can_resume'] is False
    assert claimant_list.json()['items'][0]['customer_next_step']['can_resume'] is False

    workbench = client.get(f'/api/v1/workbench/claims/{claim.claim_id}', headers=staff_auth_headers)
    assert workbench.status_code == 200
    assert workbench.json()['claim_decision'] == decision
    assert all(
        item['action_code'] != 'claim.record_decision'
        for item in workbench.json()['allowed_actions']
    )

    replay = client.post(
        route,
        headers=_decision_headers(staff_auth_headers),
        json={'decision': 'approved', 'internal_note': 'Reviewed against the policy.'},
    )
    assert replay.status_code == 201
    assert replay.json() == decision
    assert repository.get_claim_internal(claim.claim_id) == stored
    assert len(repository._claim_decisions) == 1
    assert len(repository._realtime_events) == realtime_before + 1
    assert len(repository.list_audit_events_internal(audits[0].subject)) == 1


def test_rejection_validation_rejects_client_authority_and_requires_safe_copy(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim = _store_created_claim(repository, 'clm_rejection_validation')
    route = f'/api/v1/workbench/claims/{claim.claim_id}/decisions'
    headers = _decision_headers(staff_auth_headers)

    missing = client.post(route, headers=headers, json={'decision': 'rejected'})
    blank = client.post(
        route,
        headers={**headers, 'Idempotency-Key': 'claim-decision-blank'},
        json={'decision': 'rejected', 'claimant_explanation': '   '},
    )
    forged = client.post(
        route,
        headers={**headers, 'Idempotency-Key': 'claim-decision-forged'},
        json={
            'decision': 'approved',
            'decided_by': 'stf_forged',
            'decided_at': '2026-01-01T00:00:00Z',
        },
    )
    claimant_denied = client.post(
        route,
        headers={
            **auth_headers,
            'Idempotency-Key': 'claimant-denied',
            'If-Match': '1',
        },
        json={'decision': 'approved'},
    )

    assert missing.status_code == 422
    assert blank.status_code == 422
    assert forged.status_code == 422
    assert claimant_denied.status_code == 403
    assert repository.get_claim_internal(claim.claim_id) == claim
    assert repository._claim_decisions == {}


def test_claim_decision_enforces_owner_eligibility_conflicts_and_idempotency(
    client: TestClient,
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    other_owner = _store_created_claim(repository, 'clm_other_owner', owner_id='stf_someone_else')
    denied = client.post(
        f'/api/v1/workbench/claims/{other_owner.claim_id}/decisions',
        headers=_decision_headers(staff_auth_headers),
        json={'decision': 'approved'},
    )
    assert denied.status_code == 403
    assert denied.json()['error']['code'] == 'ACCESS_DENIED'

    not_ready = _store_created_claim(
        repository,
        'clm_not_ready',
        workflow_state=WorkflowState.PROFESSIONAL_REVIEW,
    )
    not_ready_response = client.post(
        f'/api/v1/workbench/claims/{not_ready.claim_id}/decisions',
        headers=_decision_headers(staff_auth_headers, key='not-ready'),
        json={'decision': 'approved'},
    )
    assert not_ready_response.status_code == 409
    assert not_ready_response.json()['error']['code'] == 'CLAIM_NOT_READY_FOR_DECISION'

    claim = _store_created_claim(repository, 'clm_decision_conflicts')
    route = f'/api/v1/workbench/claims/{claim.claim_id}/decisions'
    accepted = client.post(
        route,
        headers=_decision_headers(staff_auth_headers, key='accepted'),
        json={'decision': 'approved'},
    )
    assert accepted.status_code == 201

    changed_payload = client.post(
        route,
        headers=_decision_headers(staff_auth_headers, key='accepted'),
        json={'decision': 'rejected', 'claimant_explanation': 'Coverage does not apply.'},
    )
    assert changed_payload.status_code == 409
    assert changed_payload.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'

    stale = client.post(
        route,
        headers=_decision_headers(staff_auth_headers, key='stale', revision=1),
        json={'decision': 'approved'},
    )
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'REVISION_CONFLICT'

    second = client.post(
        route,
        headers=_decision_headers(staff_auth_headers, key='second', revision=2),
        json={'decision': 'rejected', 'claimant_explanation': 'Coverage does not apply.'},
    )
    assert second.status_code == 409
    assert second.json()['error']['code'] == 'CLAIM_ALREADY_DECIDED'
    assert len(repository._claim_decisions) == 1


def test_failed_commit_rolls_back_claim_decision_audit_idempotency_and_realtime(
    client: TestClient,
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _store_created_claim(repository, 'clm_decision_rollback')
    realtime_before = dict(repository._realtime_events)

    def fail_publication(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError('injected realtime failure')

    monkeypatch.setattr(repository, '_commit_realtime_event', fail_publication)
    with pytest.raises(RuntimeError, match='injected realtime failure'):
        client.post(
            f'/api/v1/workbench/claims/{claim.claim_id}/decisions',
            headers=_decision_headers(staff_auth_headers),
            json={'decision': 'approved'},
        )
    assert repository.get_claim_internal(claim.claim_id) == claim
    assert repository._claim_decisions == {}
    assert repository._audit_events == {}
    assert repository._idempotency == {}
    assert repository._realtime_events == realtime_before


def test_ordinary_claim_write_cannot_clear_or_forge_decision_reference(
    repository: FixtureRepository,
) -> None:
    claim = _store_created_claim(repository, 'clm_decision_immutable')
    decided = decide_claim(
        repository,
        _claims_professional(),
        claim.claim_id,
        ClaimDecisionRequest(decision=ClaimDecisionValue.APPROVED),
        'immutable-decision',
        '1',
    )
    stored = repository.get_claim_internal(claim.claim_id)
    assert stored is not None

    with pytest.raises(KeyError):
        repository.save_claim(
            stored.model_copy(
                update={
                    'claim_decision_id': None,
                    'revision': stored.revision + 1,
                }
            ),
            expected_revision=stored.revision,
        )
    with pytest.raises(KeyError):
        repository.save_claim(
            stored.model_copy(
                update={
                    'claim_decision_id': 'cdec_11111111111111111111',
                    'revision': stored.revision + 1,
                }
            ),
            expected_revision=stored.revision,
        )
    assert repository.get_claim_decision(claim.claim_id, decided.decision_id) == decided
    assert repository.get_claim_internal(claim.claim_id) == stored


def test_concurrent_claim_decisions_commit_exactly_one_result(
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _store_created_claim(repository, 'clm_decision_race')
    original_save = repository.save_staff_mutation
    ready = Barrier(2)

    def synchronized_save(*args: Any, **kwargs: Any) -> None:
        ready.wait(timeout=5)
        original_save(*args, **kwargs)

    monkeypatch.setattr(repository, 'save_staff_mutation', synchronized_save)

    def decide(value: ClaimDecisionValue, key: str) -> str:
        try:
            result = decide_claim(
                repository,
                _claims_professional(),
                claim.claim_id,
                ClaimDecisionRequest(
                    decision=value,
                    claimant_explanation=(
                        'The policy does not cover this loss.'
                        if value is ClaimDecisionValue.REJECTED
                        else None
                    ),
                ),
                key,
                '1',
            )
            return result.decision.value
        except ApiError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        approved = pool.submit(decide, ClaimDecisionValue.APPROVED, 'race-approved')
        rejected = pool.submit(decide, ClaimDecisionValue.REJECTED, 'race-rejected')
        outcomes = {approved.result(), rejected.result()}

    assert outcomes in [
        {'approved', 'REVISION_CONFLICT'},
        {'rejected', 'REVISION_CONFLICT'},
    ]
    assert len(repository._claim_decisions) == 1
    stored = repository.get_claim_internal(claim.claim_id)
    assert stored is not None
    assert stored.revision == 2
    assert len(repository._audit_events) == 1


def _claims_professional() -> Principal:
    return Principal(
        subject='stf_demo',
        actor_type='staff',
        scopes=STAFF_SCOPES,
        roles=frozenset({'claims_professional'}),
        auth_source='test:staff',
    )


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongo'])
def test_fixture_and_mongodb_persist_the_same_claim_decision_contract(
    repository_kind: str,
) -> None:
    repository: PersistenceRepository
    if repository_kind == 'fixture':
        repository = FixtureRepository()
    else:
        mongo_repository = MongoDBRepository(mongomock.MongoClient(), 'claim_decision_parity')
        mongo_repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo_repository
    claim = _store_created_claim(repository, f'clm_{repository_kind}_decision')

    decision = decide_claim(
        repository,
        _claims_professional(),
        claim.claim_id,
        ClaimDecisionRequest(
            decision=ClaimDecisionValue.REJECTED,
            claimant_explanation='The policy does not cover this loss.',
            internal_note='Coverage exclusion verified.',
        ),
        f'{repository_kind}-decision',
        '1',
    )

    stored = repository.get_claim_internal(claim.claim_id)
    assert stored is not None
    assert stored.claim_decision_id == decision.decision_id
    assert stored.revision == 2
    assert repository.get_claim_decision(claim.claim_id, decision.decision_id) == decision
    replay = decide_claim(
        repository,
        _claims_professional(),
        claim.claim_id,
        ClaimDecisionRequest(
            decision=ClaimDecisionValue.REJECTED,
            claimant_explanation='The policy does not cover this loss.',
            internal_note='Coverage exclusion verified.',
        ),
        f'{repository_kind}-decision',
        '1',
    )
    assert replay == decision


def test_non_claims_professional_is_denied_before_claim_lookup(
    repository: FixtureRepository,
) -> None:
    principal = Principal(
        subject='stf_operations',
        actor_type='staff',
        scopes=STAFF_SCOPES,
        roles=frozenset({'operations'}),
        auth_source='test:staff',
    )

    with pytest.raises(ApiError) as error:
        decide_claim(
            repository,
            principal,
            'clm_does_not_exist',
            ClaimDecisionRequest(decision=ClaimDecisionValue.APPROVED),
            'role-denied',
            '1',
        )

    assert error.value.status_code == 403
    assert error.value.code == 'ACCESS_DENIED'
