"""Permanent API and adapter regressions for direct post-FNOL staff acceptance."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Any

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.core.auth import STAFF_SCOPES, Principal
from backend.core.errors import ApiError
from backend.domain.audit import AuditSubject, AuditSubjectType
from backend.domain.models import (
    HandoffPacket,
    HandoffPriority,
    HandoffRecord,
    HandoffStatus,
    HandoffTrigger,
    HandoffType,
    SessionStatus,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
    WorkflowState,
    WorkingClaim,
)
from backend.domain.staff_identity import StaffPresenceRecord
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services.claim_acceptance import accept_claim
from backend.services.workbench import get_workbench_claim_detail
from tests.test_claim_decisions import _created_claim


def _staff(staff_id: str = 'stf_demo') -> Principal:
    return Principal(
        subject=staff_id,
        actor_type='staff',
        scopes=STAFF_SCOPES,
        roles=frozenset({'claims_professional'}),
        auth_source='test:staff',
    )


def _presence(repository: PersistenceRepository, staff_id: str = 'stf_demo') -> None:
    now = datetime.now(UTC)
    current = repository.get_staff_presence(staff_id)
    repository.save_staff_presence(
        StaffPresenceRecord(
            staff_id=staff_id,
            online=True,
            available=True,
            last_seen_at=now,
            expires_at=now + timedelta(minutes=5),
            updated_at=now,
            revision=current.revision + 1 if current else 1,
        ),
        current.revision if current else None,
    )


def _claim(repository: PersistenceRepository, claim_id: str = 'clm_accept') -> WorkingClaim:
    claim, session = _created_claim(claim_id)
    claim = claim.model_copy(update={'assignee_id': None})
    repository.create_claim(claim, session)
    return claim


def _audits(repository: PersistenceRepository, claim_id: str) -> list[Any]:
    return repository.list_audit_events_internal(
        AuditSubject(subject_type=AuditSubjectType.CLAIM, subject_id=claim_id, claim_id=claim_id)
    )


@pytest.fixture(params=['fixture', 'mongo'])
def acceptance_repository(request: pytest.FixtureRequest) -> PersistenceRepository:
    if request.param == 'fixture':
        return FixtureRepository()
    repository = MongoDBRepository(mongomock.MongoClient(), 'claim_acceptance_parity')
    # Adapter parity only: mongomock cannot establish real Mongo transaction evidence.
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


def test_acceptance_persists_owner_replays_once_and_unlocks_decision_and_conversation(
    acceptance_repository: PersistenceRepository,
) -> None:
    repository = acceptance_repository
    claim = _claim(repository)
    _presence(repository)
    before = get_workbench_claim_detail(repository, _staff(), claim.claim_id)
    assert before.ownership.accept_claim is True
    assert any(action.action_code == 'ownership.accept_claim' for action in before.allowed_actions)

    result = accept_claim(repository, _staff(), claim.claim_id, 'take-once', '1')
    assert result.revision == 2
    assert result.ownership.primary_assignee is not None
    assert result.ownership.primary_assignee.staff_id == 'stf_demo'
    assert result.ownership.accept_claim is False
    assert any(action.action_code == 'claim.record_decision' for action in result.allowed_actions)
    message_action = next(
        action
        for action in result.allowed_actions
        if action.action_code == 'conversation.send_claimant_message'
    )
    assert message_action.target_ref == claim.active_session_id
    assert message_action.availability.value == 'confirmation_required'
    assert message_action.based_on_revision == 2
    assert all(action.action_code != 'ownership.accept_claim' for action in result.allowed_actions)
    stored = repository.get_claim_internal(claim.claim_id)
    assert stored is not None and stored.assignee_id == 'stf_demo'
    assert stored.terminal_disposition == claim.terminal_disposition
    assert stored.external_claim == claim.external_claim
    audits = _audits(repository, claim.claim_id)
    assert len(audits) == 1
    assert audits[0].actor.actor_id == 'stf_demo'
    assert audits[0].permission is not None
    assert audits[0].permission.required_permission == 'ownership.accept_claim'
    assert accept_claim(repository, _staff(), claim.claim_id, 'take-once', '1') == result
    assert repository.get_claim_internal(claim.claim_id) == stored
    assert len(_audits(repository, claim.claim_id)) == 1
    with pytest.raises(ApiError) as error:
        accept_claim(repository, _staff(), claim.claim_id, 'second-action', '2')
    assert error.value.code == 'CLAIM_ALREADY_ASSIGNED'


def test_acceptance_keeps_conversation_blocked_without_active_claimant_session(
    acceptance_repository: PersistenceRepository,
) -> None:
    repository = acceptance_repository
    claim = _claim(repository, 'clm_accept_closed_session')
    session = repository.get_session(
        claim.claim_id, claim.active_session_id or '', claim.customer_id
    )
    assert session is not None
    repository.save_session(
        session.model_copy(update={'status': SessionStatus.CLOSED, 'closed_at': datetime.now(UTC)})
    )
    _presence(repository)

    result = accept_claim(repository, _staff(), claim.claim_id, 'take-closed-session', '1')

    message_action = next(
        action
        for action in result.allowed_actions
        if action.action_code == 'conversation.send_claimant_message'
    )
    assert message_action.availability.value == 'blocked'
    assert message_action.blocked_reason == 'No active claimant session is available.'


@pytest.mark.parametrize('presence_state', ['missing', 'offline', 'unavailable', 'expired'])
def test_ineligible_presence_hides_action_and_prevents_mutation(
    repository: FixtureRepository,
    presence_state: str,
) -> None:
    claim = _claim(repository)
    repository._staff_presence.clear()
    if presence_state != 'missing':
        _presence(repository)
        current = repository.get_staff_presence('stf_demo')
        assert current is not None
        changes: dict[str, Any] = {'revision': current.revision + 1}
        if presence_state == 'expired':
            changes['expires_at'] = datetime.now(UTC) - timedelta(seconds=1)
        else:
            changes['online' if presence_state == 'offline' else 'available'] = False
        repository.save_staff_presence(current.model_copy(update=changes), current.revision)
    assert (
        get_workbench_claim_detail(repository, _staff(), claim.claim_id).ownership.accept_claim
        is False
    )
    with pytest.raises(ApiError) as error:
        accept_claim(repository, _staff(), claim.claim_id, 'unavailable', '1')
    assert error.value.code == 'STAFF_NOT_AVAILABLE'
    assert repository.get_claim_internal(claim.claim_id) == claim
    assert _audits(repository, claim.claim_id) == []


@pytest.mark.parametrize('denied', ['claimant', 'wrong-role', 'read-only', 'write-only'])
def test_authority_is_checked_before_claim_lookup(
    repository: FixtureRepository,
    denied: str,
) -> None:
    principal = _staff()
    if denied == 'claimant':
        principal = replace(principal, actor_type='claimant')
    elif denied == 'wrong-role':
        principal = replace(principal, roles=frozenset({'operations'}))
    else:
        scope = 'workbench:read' if denied == 'read-only' else 'workbench:write'
        principal = replace(principal, scopes=frozenset({scope}))
    with pytest.raises(ApiError) as error:
        accept_claim(repository, principal, 'clm_missing', 'denied', '1')
    assert error.value.code == 'ACCESS_DENIED'
    assert error.value.status_code == 403


def test_stale_revision_and_incomplete_fnol_are_rejected(repository: FixtureRepository) -> None:
    claim = _claim(repository)
    _presence(repository)
    with pytest.raises(ApiError) as stale:
        accept_claim(repository, _staff(), claim.claim_id, 'stale', '0')
    assert stale.value.code == 'REVISION_CONFLICT'
    incomplete = claim.model_copy(
        update={
            'claim_state': claim.claim_state.model_copy(
                update={'workflow_state': WorkflowState.PROFESSIONAL_REVIEW}
            ),
            'revision': 2,
        }
    )
    repository.save_claim(incomplete, expected_revision=1)
    with pytest.raises(ApiError) as ineligible:
        accept_claim(repository, _staff(), claim.claim_id, 'not-ready', '2')
    assert ineligible.value.code == 'CLAIM_NOT_READY_FOR_ACCEPTANCE'
    assert repository.get_claim_internal(claim.claim_id) == incomplete
    assert _audits(repository, claim.claim_id) == []


@pytest.mark.parametrize(
    'state', ['closed', 'abandoned', 'missing-external', 'already-decided', 'owned']
)
def test_completed_fnol_does_not_make_other_ineligible_claims_claimable(
    repository: FixtureRepository,
    state: str,
) -> None:
    claim, session = _created_claim('clm_eligibility')
    changes: dict[str, Any] = {'assignee_id': None}
    if state in {'closed', 'abandoned'}:
        assert claim.terminal_disposition is not None
        changes['terminal_disposition'] = claim.terminal_disposition.model_copy(
            update={
                'value': TerminalDispositionValue.CLOSED
                if state == 'closed'
                else TerminalDispositionValue.ABANDONED,
                'reason_code': TerminalDispositionReasonCode.AUTHORISED_CLOSURE
                if state == 'closed'
                else TerminalDispositionReasonCode.AUTHORISED_STAFF_ABANDONMENT,
            }
        )
    elif state == 'missing-external':
        changes['external_claim'] = None
    elif state == 'already-decided':
        changes['claim_decision_id'] = 'cdec_11111111111111111111'
    else:
        changes['assignee_id'] = 'stf_someone_else'
    claim = claim.model_copy(update=changes)
    repository.create_claim(claim.model_copy(update={'claim_decision_id': None}), session)
    # A restored decided record stays ineligible even if its owner was later cleared.
    repository._claims[claim.claim_id] = claim
    _presence(repository)
    with pytest.raises(ApiError) as error:
        accept_claim(repository, _staff(), claim.claim_id, 'ineligible', '1')
    expected = 'CLAIM_ALREADY_ASSIGNED' if state == 'owned' else 'CLAIM_NOT_READY_FOR_ACCEPTANCE'
    assert error.value.code == expected
    assert repository.get_claim_internal(claim.claim_id) == claim
    assert _audits(repository, claim.claim_id) == []


@pytest.mark.parametrize('assigned', [False, True])
def test_direct_acceptance_preserves_queued_handoff_and_respects_handoff_owner(
    repository: FixtureRepository,
    assigned: bool,
) -> None:
    claim = _claim(repository)
    _presence(repository)
    handoff = HandoffRecord(
        handoff_id='hof_acceptance',
        claim_id=claim.claim_id,
        type=HandoffType.PROFESSIONAL_REVIEW,
        status=HandoffStatus.ACCEPTED if assigned else HandoffStatus.QUEUED,
        priority=HandoffPriority.STANDARD,
        queue='professional_review',
        trigger=HandoffTrigger.PROFESSIONAL_REVIEW_REQUIRED,
        reason_codes=['PROFESSIONAL_REVIEW_REQUIRED'],
        reason='Review completed FNOL.',
        requested_action='Review the Claim.',
        applied_rule='professional_review',
        packet=HandoffPacket(form_revision=1, promised_next_step='Staff review.'),
        assigned_to='stf_someone_else' if assigned else None,
        created_at=claim.created_at,
    )
    repository.save_handoff(handoff, claim.customer_id)
    active = claim.model_copy(update={'active_handoff_id': handoff.handoff_id, 'revision': 2})
    repository.save_claim(active, expected_revision=1)
    if assigned:
        with pytest.raises(ApiError) as error:
            accept_claim(repository, _staff(), claim.claim_id, 'handoff-owned', '2')
        assert error.value.code == 'CLAIM_ALREADY_ASSIGNED'
    else:
        accept_claim(repository, _staff(), claim.claim_id, 'handoff-queued', '2')
    assert repository.get_handoff(claim.claim_id, handoff.handoff_id, claim.customer_id) == handoff


def test_competing_staff_acceptance_has_one_winner(
    acceptance_repository: PersistenceRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = acceptance_repository
    claim = _claim(repository)
    for staff_id in ('stf_first', 'stf_second'):
        _presence(repository, staff_id)
    original = repository.save_staff_mutation
    ready = Barrier(2)

    def synchronized_save(*args: Any, **kwargs: Any) -> None:
        ready.wait(timeout=10)
        original(*args, **kwargs)

    monkeypatch.setattr(repository, 'save_staff_mutation', synchronized_save)

    def take(staff_id: str) -> str:
        try:
            accept_claim(repository, _staff(staff_id), claim.claim_id, 'same-key', '1')
            return 'accepted'
        except ApiError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(take, ('stf_first', 'stf_second')))
    assert sorted(outcomes) == ['CLAIM_ALREADY_ASSIGNED', 'accepted']
    stored = repository.get_claim_internal(claim.claim_id)
    assert stored is not None and stored.revision == 2
    assert len(_audits(repository, claim.claim_id)) == 1


def test_presence_change_at_commit_cannot_assign_claim(
    acceptance_repository: PersistenceRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = acceptance_repository
    claim = _claim(repository)
    _presence(repository)
    original = repository.save_staff_mutation

    def invalidate_presence(*args: Any, **kwargs: Any) -> None:
        current = repository.get_staff_presence('stf_demo')
        assert current is not None
        repository.save_staff_presence(
            current.model_copy(update={'available': False, 'revision': current.revision + 1}),
            current.revision,
        )
        original(*args, **kwargs)

    monkeypatch.setattr(repository, 'save_staff_mutation', invalidate_presence)
    with pytest.raises(ApiError) as error:
        accept_claim(repository, _staff(), claim.claim_id, 'presence-race', '1')
    assert error.value.code == 'STAFF_NOT_AVAILABLE'
    assert repository.get_claim_internal(claim.claim_id) == claim
    assert _audits(repository, claim.claim_id) == []


def test_failed_publication_rolls_back_all_acceptance_writes(
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim(repository)
    _presence(repository)
    realtime_before = dict(repository._realtime_events)

    def fail_publication(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError('injected acceptance publication failure')

    monkeypatch.setattr(repository, '_commit_realtime_event', fail_publication)
    with pytest.raises(RuntimeError, match='injected acceptance publication failure'):
        accept_claim(repository, _staff(), claim.claim_id, 'failed-commit', '1')
    assert repository.get_claim_internal(claim.claim_id) == claim
    assert repository._idempotency == {}
    assert repository._audit_events == {}
    assert repository._realtime_events == realtime_before


def test_audit_preparation_failure_prevents_acceptance_in_both_adapters(
    acceptance_repository: PersistenceRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = acceptance_repository
    claim = _claim(repository)
    _presence(repository)

    def fail_audit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError('injected audit preparation failure')

    monkeypatch.setattr(repository, '_prepare_audit_events', fail_audit)
    with pytest.raises(RuntimeError, match='injected audit preparation failure'):
        accept_claim(repository, _staff(), claim.claim_id, 'audit-failure', '1')
    assert repository.get_claim_internal(claim.claim_id) == claim
    assert _audits(repository, claim.claim_id) == []
    assert (
        repository.find_idempotency(
            'stf_demo', f'/api/v1/workbench/claims/{claim.claim_id}/accept', 'audit-failure'
        )
        is None
    )


@pytest.mark.parametrize('tampering', ['missing-audit', 'wrong-actor', 'unrelated-change'])
def test_persistence_rejects_acceptance_without_its_bounded_authority(
    acceptance_repository: PersistenceRepository,
    monkeypatch: pytest.MonkeyPatch,
    tampering: str,
) -> None:
    repository = acceptance_repository
    claim = _claim(repository)
    _presence(repository)
    original = repository.save_staff_mutation

    def tampered_save(proposed: WorkingClaim, *args: Any, **kwargs: Any) -> None:
        if tampering == 'missing-audit':
            kwargs['audit_event'] = None
        elif tampering == 'wrong-actor':
            _presence(repository, 'stf_forged')
            kwargs['required_staff_id'] = 'stf_forged'
            kwargs['required_staff_revision'] = 1
        else:
            proposed = proposed.model_copy(update={'locale': 'en-AU'})
        original(proposed, *args, **kwargs)

    monkeypatch.setattr(repository, 'save_staff_mutation', tampered_save)
    with pytest.raises(KeyError):
        accept_claim(repository, _staff(), claim.claim_id, 'tampered', '1')
    assert repository.get_claim_internal(claim.claim_id) == claim
    assert _audits(repository, claim.claim_id) == []
    assert (
        repository.find_idempotency(
            'stf_demo', f'/api/v1/workbench/claims/{claim.claim_id}/accept', 'tampered'
        )
        is None
    )


def test_api_requires_empty_body_and_discovers_unassigned_completed_claims(
    client: TestClient,
    repository: FixtureRepository,
    staff_auth_headers: dict[str, str],
) -> None:
    claim = _claim(repository)
    other = _claim(repository, 'clm_other_accept')
    headers = {**staff_auth_headers, 'If-Match': '1', 'Idempotency-Key': 'api-accept'}
    route = f'/api/v1/workbench/claims/{claim.claim_id}/accept'
    # Staff presence affects the action, not discovery of completed unassigned FNOL.
    queue = client.get(
        '/api/v1/workbench/claims?ownership=unassigned&limit=1', headers=staff_auth_headers
    )
    assert queue.status_code == 200
    assert len(queue.json()['items']) == 1
    cursor = queue.json()['page']['next_cursor']
    assert cursor is not None
    second_page = client.get(
        '/api/v1/workbench/claims',
        headers=staff_auth_headers,
        params={'ownership': 'unassigned', 'limit': 1, 'cursor': cursor},
    )
    assert {queue.json()['items'][0]['claim_id'], second_page.json()['items'][0]['claim_id']} == {
        claim.claim_id,
        other.claim_id,
    }
    _presence(repository)
    assert client.post(route, headers=headers).status_code == 422
    assert (
        client.post(route, headers=headers, json={'assignee_id': 'stf_forged'}).status_code == 422
    )
    assert client.post(route, headers=staff_auth_headers, json={}).status_code == 400
    response = client.post(route, headers=headers, json={})
    assert response.status_code == 200
    assert response.json()['ownership']['primary_assignee']['staff_id'] == 'stf_demo'
    queue_after = client.get(
        '/api/v1/workbench/claims?ownership=unassigned', headers=staff_auth_headers
    )
    assert [item['claim_id'] for item in queue_after.json()['items']] == [other.claim_id]
    default_queue = client.get('/api/v1/workbench/claims', headers=staff_auth_headers)
    assert default_queue.json()['items'] == []  # Existing default excludes the completed queue.
