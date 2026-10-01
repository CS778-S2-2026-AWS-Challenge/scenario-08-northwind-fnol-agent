from datetime import UTC, datetime, timedelta

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.audit import AuditSubject, AuditSubjectType
from backend.domain.models import (
    AbandonClaimRequest,
    Channel,
    ClaimState,
    CustomerNextStep,
    FollowUpContactPermission,
    FollowUpReasonCode,
    FollowUpRecord,
    FollowUpStatus,
    PreferredChannel,
    ResponsibleParty,
    SessionRecord,
    SessionRecoveryContext,
    SessionStatus,
    StartSessionRequest,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
    WorkingClaim,
)
from backend.domain.recovery_policy_registry import (
    INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_ID,
    INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION,
    INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.claims import start_session
from backend.services.follow_up_recovery import process_expiring_follow_up
from backend.services.terminal_claims import abandon_incomplete_claim


def _repository(kind: str) -> PersistenceRepository:
    if kind == 'fixture':
        return FixtureRepository()

    repository = MongoDBRepository(
        mongomock.MongoClient(),
        f'p17_staff_abandonment_{kind}',
    )
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    return repository


def _checkpoint(
    repository: PersistenceRepository,
    *,
    claim_id: str = 'clm_p17_staff_abandon',
) -> tuple[WorkingClaim, FollowUpRecord, datetime]:
    # Staff abandonment reads the real clock, so anchor the interruption to it. A fixed
    # date would put every abandonment past the recovery deadline once it elapsed.
    timestamp = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)

    claim = WorkingClaim(
        claim_id=claim_id,
        customer_id=f'cus_{claim_id}',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        assignee_id='stf_demo',
        active_session_id=f'ses_{claim_id}',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Continue describing the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )

    session = SessionRecord(
        session_id=f'ses_{claim_id}',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.ACTIVE,
        context_revision=claim.revision,
        started_at=timestamp,
        last_active_at=timestamp,
    )

    repository.create_claim(claim, session)

    recovery = SessionRecoveryContext(
        interrupted_at=timestamp,
        last_meaningful_activity_at=timestamp,
        last_meaningful_activity_source_ref=(f'claim:{claim.claim_id}:revision:{claim.revision}'),
        resume_point='Continue describing the incident.',
    )

    paused_session = session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            'recovery_context': recovery,
        }
    )

    paused_claim = claim.model_copy(
        update={
            'revision': claim.revision + 1,
            'active_session_id': None,
            'updated_at': timestamp,
        }
    )

    follow_up = FollowUpRecord(
        follow_up_id=f'fup_{claim_id}',
        claim_id=claim.claim_id,
        source_session_id=session.session_id,
        purpose='resume_incomplete_claim',
        policy_id=INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_ID,
        policy_version=INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION,
        deadline_at=(timestamp + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE),
        responsible_party=ResponsibleParty.SYSTEM,
        source_refs=[
            f'claim:{claim.claim_id}:revision:{paused_claim.revision}',
            f'session:{session.session_id}',
        ],
        contact_permission=FollowUpContactPermission.AUTHORISED,
        attempt_count=0,
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=timestamp,
        created_at=timestamp,
        updated_at=timestamp,
    )

    repository.save_incomplete_checkpoint(
        paused_claim,
        expected_revision=claim.revision,
        session=paused_session,
        follow_up=follow_up,
        idempotency=IdempotencyRecord(
            actor_id=claim.customer_id,
            route=f'/claims/{claim.claim_id}/pause',
            key=f'pause-{claim_id}',
            request_fingerprint=f'pause-fingerprint-{claim_id}',
            claim_id=claim.claim_id,
            session_id=session.session_id,
            follow_up_id=follow_up.follow_up_id,
        ),
    )

    return paused_claim, follow_up, timestamp


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_staff_abandonment_is_atomic_terminal_and_audited(
    kind: str,
) -> None:
    repository = _repository(kind)
    claim, follow_up, _ = _checkpoint(
        repository,
        claim_id=f'clm_staff_abandon_{kind}',
    )

    principal = Principal(
        subject='stf_demo',
        actor_type='staff',
        auth_source='test:staff_session',
        scopes=frozenset({'workbench:read', 'workbench:write'}),
    )

    response = abandon_incomplete_claim(
        repository,
        principal,
        claim.claim_id,
        AbandonClaimRequest(reason='The authorised claims owner ended this incomplete intake.'),
        f'abandon-{kind}',
        str(claim.revision),
    )

    stored_claim = repository.get_claim_internal(claim.claim_id)
    assert stored_claim is not None
    assert stored_claim.revision == claim.revision + 1
    assert stored_claim.terminal_disposition is not None
    assert stored_claim.terminal_disposition.value is TerminalDispositionValue.ABANDONED
    assert (
        stored_claim.terminal_disposition.reason_code
        is TerminalDispositionReasonCode.AUTHORISED_STAFF_ABANDONMENT
    )

    stored_follow_up = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert stored_follow_up is not None
    assert stored_follow_up.status is FollowUpStatus.RESOLVED
    assert stored_follow_up.reason_code is FollowUpReasonCode.STAFF_ABANDONED
    assert stored_follow_up.outcome == 'staff_abandoned'
    assert stored_follow_up.due_at is None

    assert response.terminal_disposition is not None
    assert response.work_summary.incomplete_context is None
    assert any(action.action_code == 'claim.reopen' for action in response.allowed_actions)

    idempotency = repository.find_idempotency(
        principal.subject,
        f'/api/v1/workbench/claims/{claim.claim_id}/abandon',
        f'abandon-{kind}',
    )
    assert idempotency is not None
    assert idempotency.action_code == 'claim.abandon'
    assert idempotency.follow_up_id == follow_up.follow_up_id

    events = repository.list_audit_events_internal(
        AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim.claim_id,
            claim_id=claim.claim_id,
        )
    )

    abandonment_events = [event for event in events if event.idempotency_key == f'abandon-{kind}']

    assert len(abandonment_events) == 1
    assert abandonment_events[0].actor.actor_id == 'stf_demo'
    assert abandonment_events[0].claim_revision == stored_claim.revision


def test_workbench_abandon_endpoint_requires_confirmation_and_replays(
    client: TestClient,
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim, follow_up, _ = _checkpoint(
        repository,
        claim_id='clm_staff_abandon_api',
    )

    detail = client.get(
        f'/api/v1/workbench/claims/{claim.claim_id}',
        headers=staff_auth_headers,
    )
    assert detail.status_code == 200

    abandon_actions = [
        action
        for action in detail.json()['allowed_actions']
        if action['action_code'] == 'claim.abandon'
    ]
    assert len(abandon_actions) == 1
    assert abandon_actions[0]['availability'] == 'confirmation_required'
    assert abandon_actions[0]['target_ref'] == claim.claim_id

    headers = {
        **staff_auth_headers,
        'Idempotency-Key': 'staff-abandon-api',
        'If-Match': str(claim.revision),
    }

    response = client.post(
        f'/api/v1/workbench/claims/{claim.claim_id}/abandon',
        headers=headers,
        json={'reason': 'Staff confirmed this incomplete intake should end.'},
    )

    assert response.status_code == 200
    body = response.json()

    assert body['terminal_disposition']['value'] == 'abandoned'
    assert body['terminal_disposition']['reason_code'] == 'AUTHORISED_STAFF_ABANDONMENT'
    assert body['work_summary']['incomplete_context'] is None

    replay = client.post(
        f'/api/v1/workbench/claims/{claim.claim_id}/abandon',
        headers=headers,
        json={'reason': 'Staff confirmed this incomplete intake should end.'},
    )

    assert replay.status_code == 200
    assert replay.json() == body

    stored_follow_up = repository.get_follow_up(
        claim.claim_id,
        follow_up.follow_up_id,
        claim.customer_id,
    )
    assert stored_follow_up is not None
    assert stored_follow_up.status is FollowUpStatus.RESOLVED


def test_terminal_claim_cannot_start_session_without_reopen(
    repository: FixtureRepository,
) -> None:
    claim, _, _ = _checkpoint(
        repository,
        claim_id='clm_terminal_session_guard',
    )

    staff_principal = Principal(
        subject='stf_demo',
        actor_type='staff',
        auth_source='test:staff_session',
        scopes=frozenset({'workbench:read', 'workbench:write'}),
    )

    abandon_incomplete_claim(
        repository,
        staff_principal,
        claim.claim_id,
        AbandonClaimRequest(reason='Authorised staff abandonment for guard test.'),
        'guard-abandon',
        str(claim.revision),
    )

    claimant_principal = Principal(
        subject=claim.customer_id,
        actor_type='claimant',
        auth_source='test:claimant_session',
    )

    with pytest.raises(ApiError) as caught:
        start_session(
            repository,
            claimant_principal,
            claim.claim_id,
            StartSessionRequest(intent='resume'),
            'illegal-terminal-resume',
        )

    assert caught.value.status_code == 409
    assert caught.value.code == 'INVALID_STATE_TRANSITION'

    stored = repository.get_claim(
        claim.claim_id,
        claim.customer_id,
    )
    assert stored is not None
    assert stored.terminal_disposition is not None
    assert stored.active_session_id is None


def test_read_only_staff_cannot_abandon_incomplete_claim() -> None:
    repository = _repository('fixture')
    claim, follow_up, _ = _checkpoint(repository, claim_id='clm_read_only_abandon')
    read_only = Principal(
        subject='stf_read_only',
        actor_type='staff',
        auth_source='test:staff_session',
        scopes=frozenset({'workbench:read'}),
    )

    with pytest.raises(ApiError) as denied:
        abandon_incomplete_claim(
            repository,
            read_only,
            claim.claim_id,
            AbandonClaimRequest(reason='Read-only staff must not end this intake.'),
            'abandon-read-only',
            str(claim.revision),
        )

    assert denied.value.status_code == 403
    stored = repository.get_claim_internal(claim.claim_id)
    assert stored is not None and stored.terminal_disposition is None
    assert stored.revision == claim.revision


def _staff() -> Principal:
    return Principal(
        subject='stf_demo',
        actor_type='staff',
        auth_source='test:staff_session',
        scopes=frozenset({'workbench:read', 'workbench:write'}),
    )


@pytest.mark.parametrize('kind', ['fixture', 'mongo'])
def test_expiry_and_staff_abandonment_race_has_one_typed_winner(kind: str) -> None:
    expired_first = _repository(kind)
    claim, follow_up, interrupted_at = _checkpoint(
        expired_first, claim_id=f'clm_expiry_wins_{kind}'
    )
    deadline = interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE

    assert process_expiring_follow_up(expired_first, follow_up, deadline) is not None
    with pytest.raises(ApiError) as refused:
        abandon_incomplete_claim(
            expired_first,
            _staff(),
            claim.claim_id,
            AbandonClaimRequest(reason='Staff abandonment that arrives after expiry.'),
            f'abandon-after-expiry-{kind}',
            str(claim.revision + 1),
        )
    # A terminal Claim no longer offers claim.abandon, so the action is refused
    # before any write.
    assert (refused.value.status_code, refused.value.code) == (403, 'ACCESS_DENIED')
    expired = expired_first.get_claim_internal(claim.claim_id)
    assert expired is not None and expired.terminal_disposition is not None
    assert (
        expired.terminal_disposition.reason_code is TerminalDispositionReasonCode.RECOVERY_EXPIRED
    )

    abandoned_first = _repository(kind)
    claim, follow_up, interrupted_at = _checkpoint(
        abandoned_first, claim_id=f'clm_abandon_wins_{kind}'
    )
    abandon_incomplete_claim(
        abandoned_first,
        _staff(),
        claim.claim_id,
        AbandonClaimRequest(reason='Staff abandonment that commits before expiry.'),
        f'abandon-before-expiry-{kind}',
        str(claim.revision),
    )
    late_expiry = process_expiring_follow_up(
        abandoned_first, follow_up, interrupted_at + INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE
    )
    assert late_expiry is None
    abandoned = abandoned_first.get_claim_internal(claim.claim_id)
    assert abandoned is not None and abandoned.terminal_disposition is not None
    assert abandoned.revision == claim.revision + 1
    assert (
        abandoned.terminal_disposition.reason_code
        is TerminalDispositionReasonCode.AUTHORISED_STAFF_ABANDONMENT
    )


def test_claimant_resume_before_staff_abandonment_wins_without_partial_write() -> None:
    repository = _repository('fixture')
    claim, follow_up, _ = _checkpoint(repository, claim_id='clm_resume_wins')

    start_session(
        repository,
        Principal(subject=claim.customer_id, actor_type='claimant', auth_source='test:claimant'),
        claim.claim_id,
        StartSessionRequest(intent='resume'),
        'resume-before-abandon',
    )
    resumed = repository.get_claim_internal(claim.claim_id)
    assert resumed is not None and resumed.revision > claim.revision

    with pytest.raises(ApiError) as refused:
        abandon_incomplete_claim(
            repository,
            _staff(),
            claim.claim_id,
            AbandonClaimRequest(reason='Staff abandonment loaded before the resume.'),
            'abandon-after-resume',
            str(claim.revision),
        )

    assert refused.value.status_code == 409
    assert repository.get_claim_internal(claim.claim_id) == resumed
    stored_follow_up = repository.get_follow_up(
        claim.claim_id, follow_up.follow_up_id, claim.customer_id
    )
    assert stored_follow_up is not None
    assert stored_follow_up.status is FollowUpStatus.RESOLVED
    assert stored_follow_up.reason_code is not FollowUpReasonCode.STAFF_ABANDONED


def test_blank_abandonment_reason_is_refused_before_any_write() -> None:
    repository = _repository('fixture')
    claim, _, _ = _checkpoint(repository, claim_id='clm_blank_abandon')

    with pytest.raises(ApiError) as refused:
        abandon_incomplete_claim(
            repository,
            _staff(),
            claim.claim_id,
            AbandonClaimRequest(reason='   '),
            'abandon-blank',
            str(claim.revision),
        )

    assert refused.value.status_code == 422
    stored = repository.get_claim_internal(claim.claim_id)
    assert stored is not None and stored.terminal_disposition is None


@pytest.mark.parametrize(
    ('conflict', 'status_code', 'code'),
    [
        (RevisionConflict(99), 409, 'REVISION_CONFLICT'),
        (IdempotencyConflict('abandon-race'), 409, 'IDEMPOTENCY_CONFLICT'),
        (KeyError('fup_removed'), 404, 'RESOURCE_NOT_FOUND'),
    ],
    ids=['stale-revision', 'idempotency', 'obligation-removed'],
)
def test_abandonment_commit_race_maps_to_a_safe_api_error(
    monkeypatch: pytest.MonkeyPatch,
    conflict: Exception,
    status_code: int,
    code: str,
) -> None:
    repository = _repository('fixture')
    claim, _, _ = _checkpoint(repository, claim_id=f'clm_abandon_race_{code.lower()}')

    def lose_race(*_args: object, **_kwargs: object) -> None:
        raise conflict

    monkeypatch.setattr(repository, 'commit_recovery_staff_abandonment', lose_race)

    with pytest.raises(ApiError) as refused:
        abandon_incomplete_claim(
            repository,
            _staff(),
            claim.claim_id,
            AbandonClaimRequest(reason='Authorised staff abandonment that loses a race.'),
            f'abandon-race-{code.lower()}',
            str(claim.revision),
        )

    assert refused.value.status_code == status_code
    assert refused.value.code == code
    stored = repository.get_claim_internal(claim.claim_id)
    assert stored is not None and stored.terminal_disposition is None
