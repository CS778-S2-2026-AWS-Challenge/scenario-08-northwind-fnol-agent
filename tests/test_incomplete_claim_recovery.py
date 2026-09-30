import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import mongomock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import MockEvidenceStorage
from backend.domain.audit import AuditSubject, AuditSubjectType
from backend.domain.models import (
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
    TerminalDispositionReasonCode,
    WorkingClaim,
)
from backend.domain.retention import (
    RetentionOperationStatus,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyRecord, RevisionConflict
from backend.services.follow_up_recovery import (
    process_due_follow_up,
    process_expiring_follow_up,
)
from backend.services.retention import (
    execute_retention_cleanup,
    freeze_retention_cleanup_targets,
    reserve_retention_from_terminal,
)
from scripts import run_recovery_worker as recovery_worker_cli


def _create_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    key: str,
) -> dict[str, object]:
    response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': key},
        json={
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': 'motor',
        },
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def test_pause_checkpoint_is_durable_visible_idempotent_and_resumable(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = _create_claim(client, auth_headers, 'p17-create')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    revision = int(claim['revision'])

    pause_headers = {
        **auth_headers,
        'Idempotency-Key': 'p17-pause',
        'If-Match': f'"{revision}"',
    }
    paused = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause',
        headers=pause_headers,
    )
    assert paused.status_code == 200
    body = paused.json()
    assert body['session']['status'] == 'paused'
    assert body['claim']['revision'] == revision + 1
    assert body['claim']['incomplete_context']['follow_up_status'] == 'pending'

    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    stored_session = repository.get_session(claim_id, session_id, 'cus_demo')
    follow_ups = repository.list_follow_ups(claim_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_session is not None
    assert stored_claim.active_session_id is None
    assert stored_session.status is SessionStatus.PAUSED
    assert stored_session.recovery_context is not None
    assert len(follow_ups) == 1
    assert follow_ups[0].source_session_id == session_id
    assert follow_ups[0].attempt_count == 0
    assert (
        repository.get_follow_up(
            claim_id,
            follow_ups[0].follow_up_id,
            'cus_demo',
        )
        == follow_ups[0]
    )
    assert repository.get_follow_up(claim_id, 'fup_missing', 'cus_demo') is None
    assert (
        repository.get_follow_up(
            claim_id,
            follow_ups[0].follow_up_id,
            'cus_other',
        )
        is None
    )
    assert repository.list_follow_ups(claim_id, 'cus_other') == []

    replay = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause',
        headers=pause_headers,
    )
    assert replay.status_code == 200
    assert replay.json() == body
    assert len(repository.list_follow_ups(claim_id, 'cus_demo')) == 1
    replayed_claim = repository.get_claim(claim_id, 'cus_demo')
    assert replayed_claim is not None
    assert replayed_claim.revision == revision + 1

    claimant_read = client.get(
        f'/api/v1/claims/{claim_id}',
        headers=auth_headers,
    )
    assert claimant_read.status_code == 200
    assert claimant_read.json()['incomplete_context']['resume_point']

    claimant_list = client.get('/api/v1/claims', headers=auth_headers)
    assert claimant_list.status_code == 200
    list_item = next(item for item in claimant_list.json()['items'] if item['claim_id'] == claim_id)
    assert list_item['incomplete_context']['follow_up_status'] == 'pending'

    staff_read = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers={'Authorization': 'Bearer synthetic-staff'},
    )
    assert staff_read.status_code == 200
    incomplete = staff_read.json()['work_summary']['incomplete_context']
    assert incomplete['follow_up_status'] == 'pending'
    assert incomplete['follow_up_attempts'] == 0
    assert incomplete['resume_point']

    resumed = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'p17-resume'},
        json={'intent': 'resume'},
    )
    assert resumed.status_code == 201
    assert resumed.json()['session_id'] != session_id
    assert repository.claim_count == 1
    final_claim = repository.get_claim(claim_id, 'cus_demo')
    assert final_claim is not None
    assert final_claim.active_session_id == resumed.json()['session_id']
    resumed_follow_ups = repository.list_follow_ups(claim_id, 'cus_demo')
    assert len(resumed_follow_ups) == 1
    assert resumed_follow_ups[0].status is FollowUpStatus.RESOLVED
    assert resumed_follow_ups[0].outcome == 'claimant_resumed'

    resume_events = repository.list_audit_events_internal(
        AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim_id,
            claim_id=claim_id,
        )
    )
    resume_events = [event for event in resume_events if event.idempotency_key == 'p17-resume']
    assert len(resume_events) == 1
    assert resume_events[0].actor.actor_id == 'cus_demo'
    assert resume_events[0].claim_revision == final_claim.revision


def test_pause_checkpoint_rejects_stale_revision_without_partial_write(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = _create_claim(client, auth_headers, 'p17-stale-create')
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)
    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    revision = int(claim['revision'])

    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p17-stale-pause',
            'If-Match': f'"{revision + 1}"',
        },
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'
    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    stored_session = repository.get_session(claim_id, session_id, 'cus_demo')
    assert stored_claim is not None
    assert stored_session is not None
    assert stored_claim.revision == revision
    assert stored_claim.active_session_id == session_id
    assert stored_session.status is SessionStatus.ACTIVE
    assert repository.list_follow_ups(claim_id, 'cus_demo') == []


def _mongo_bundle() -> tuple[
    MongoDBRepository,
    WorkingClaim,
    SessionRecord,
    WorkingClaim,
    SessionRecord,
    FollowUpRecord,
    IdempotencyRecord,
]:
    repository = MongoDBRepository(mongomock.MongoClient(), 'p17_test')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    timestamp = datetime(2026, 9, 9, 1, 0, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id='clm_p17_mongo',
        customer_id='cus_p17_mongo',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id='ses_p17_mongo',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Continue describing the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id='ses_p17_mongo',
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
        last_meaningful_activity_source_ref=(f'claim:{claim.claim_id}:revision:1'),
        resume_point='Continue describing the incident.',
    )
    paused_session = session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            'recovery_context': recovery,
        }
    )
    updated_claim = claim.model_copy(
        update={
            'revision': 2,
            'active_session_id': None,
            'updated_at': timestamp,
        }
    )
    follow_up = FollowUpRecord(
        follow_up_id='fup_p17_mongo',
        claim_id=claim.claim_id,
        source_session_id=session.session_id,
        purpose='resume_incomplete_claim',
        responsible_party=ResponsibleParty.SYSTEM,
        source_refs=[f'session:{session.session_id}'],
        contact_permission=FollowUpContactPermission.AUTHORISED,
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=timestamp,
        created_at=timestamp,
        updated_at=timestamp,
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/sessions/{session.session_id}/pause',
        key='p17-mongo-pause',
        request_fingerprint='p17-mongo-fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        follow_up_id=follow_up.follow_up_id,
    )
    return (
        repository,
        claim,
        session,
        updated_claim,
        paused_session,
        follow_up,
        idempotency,
    )


def test_mongodb_persists_incomplete_checkpoint_with_fixture_equivalent_shape() -> None:
    (
        repository,
        claim,
        _,
        updated_claim,
        paused_session,
        follow_up,
        idempotency,
    ) = _mongo_bundle()

    repository.save_incomplete_checkpoint(
        updated_claim,
        expected_revision=claim.revision,
        session=paused_session,
        follow_up=follow_up,
        idempotency=idempotency,
    )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == updated_claim
    assert (
        repository.get_session(
            claim.claim_id,
            paused_session.session_id,
            claim.customer_id,
        )
        == paused_session
    )
    assert repository.list_follow_ups(claim.claim_id, claim.customer_id) == [follow_up]
    assert (
        repository.get_follow_up(
            claim.claim_id,
            follow_up.follow_up_id,
            claim.customer_id,
        )
        == follow_up
    )
    assert (
        repository.get_follow_up(
            claim.claim_id,
            'fup_missing',
            claim.customer_id,
        )
        is None
    )
    assert (
        repository.get_follow_up(
            claim.claim_id,
            follow_up.follow_up_id,
            'cus_other',
        )
        is None
    )
    assert repository.list_follow_ups(claim.claim_id, 'cus_other') == []
    assert (
        repository.find_idempotency(
            claim.customer_id,
            idempotency.route,
            idempotency.key,
        )
        == idempotency
    )


def test_mongodb_stale_incomplete_checkpoint_has_no_partial_children() -> None:
    (
        repository,
        claim,
        session,
        updated_claim,
        paused_session,
        follow_up,
        idempotency,
    ) = _mongo_bundle()

    try:
        repository.save_incomplete_checkpoint(
            updated_claim,
            expected_revision=claim.revision + 1,
            session=paused_session,
            follow_up=follow_up,
            idempotency=idempotency,
        )
    except RevisionConflict:
        pass
    else:
        raise AssertionError('Expected a stale revision conflict.')

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert (
        repository.get_session(
            claim.claim_id,
            session.session_id,
            claim.customer_id,
        )
        == session
    )
    assert repository.list_follow_ups(claim.claim_id, claim.customer_id) == []
    assert (
        repository.find_idempotency(
            claim.customer_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )


def test_supported_recovery_worker_entrypoint_advances_real_pause_to_retention(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    created = _create_claim(
        client,
        auth_headers,
        'p17-worker-entrypoint-create',
    )
    claim = created['claim']
    session = created['session']
    assert isinstance(claim, dict)
    assert isinstance(session, dict)

    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    revision = int(claim['revision'])

    paused = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p17-worker-entrypoint-pause',
            'If-Match': f'"{revision}"',
        },
    )
    assert paused.status_code == 200

    follow_up = repository.list_follow_ups(claim_id, 'cus_demo')[0]
    storage = MockEvidenceStorage()
    bundle = SimpleNamespace(
        repository=repository,
        evidence_storage=storage,
        close=lambda: None,
    )
    monkeypatch.setattr(
        recovery_worker_cli,
        '_configured_bundle',
        lambda: bundle,
    )

    def run_at(when: datetime) -> dict[str, int]:
        monkeypatch.setattr(
            recovery_worker_cli,
            '_utc_now',
            lambda: when,
        )
        assert recovery_worker_cli.main(['--once', '--limit', '10']) == 0
        output = capsys.readouterr().out.strip().splitlines()
        assert output
        return cast(dict[str, int], json.loads(output[-1]))

    assert follow_up.due_at is not None
    first_cycle = run_at(follow_up.due_at)
    assert first_cycle['due_candidates'] == 1
    assert first_cycle['contacted'] == 1

    messages = repository.list_messages(
        claim_id,
        session_id,
        'cus_demo',
    )
    assert len(messages) == 1
    assert messages[0].recovery_rule_id == 'incomplete_claim_follow_up.v1'

    for _ in range(2):
        current = repository.get_follow_up(
            claim_id,
            follow_up.follow_up_id,
            'cus_demo',
        )
        assert current is not None
        assert current.due_at is not None
        cycle = run_at(current.due_at)
        assert cycle['contacted'] == 1

    exhausted = repository.get_follow_up(
        claim_id,
        follow_up.follow_up_id,
        'cus_demo',
    )
    assert exhausted is not None
    assert exhausted.status is FollowUpStatus.BLOCKED
    assert exhausted.reason_code is FollowUpReasonCode.ATTEMPT_LIMIT_REACHED
    assert exhausted.deadline_at is not None

    expiry_cycle = run_at(exhausted.deadline_at)
    assert expiry_cycle['expired'] == 1
    assert expiry_cycle['retention_progressed'] == 1

    retention = repository.get_retention_operation_for_claim(claim_id)
    assert retention is not None
    assert retention.targets_frozen_at is not None
    assert retention.revision > 1
    assert retention.status is RetentionOperationStatus.COMPLETED


def test_p17_full_journey_pause_resume_stops_future_recovery(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = _create_claim(
        client,
        auth_headers,
        'p17-full-resume-create',
    )

    claim = created['claim']
    session = created['session']

    assert isinstance(claim, dict)
    assert isinstance(session, dict)

    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    revision = int(claim['revision'])

    paused = client.post(
        (f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause'),
        headers={
            **auth_headers,
            'Idempotency-Key': ('p17-full-resume-pause'),
            'If-Match': f'"{revision}"',
        },
    )

    assert paused.status_code == 200

    follow_ups = repository.list_follow_ups(
        claim_id,
        'cus_demo',
    )

    assert len(follow_ups) == 1

    obligation = follow_ups[0]

    assert obligation.status is FollowUpStatus.PENDING
    assert obligation.due_at is not None
    assert obligation.deadline_at is not None

    due_candidates, _ = repository.list_due_follow_ups(
        obligation.due_at,
        limit=10,
        cursor=None,
    )

    assert obligation.follow_up_id in {item.follow_up_id for item in due_candidates}

    resumed = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={
            **auth_headers,
            'Idempotency-Key': ('p17-full-resume-return'),
        },
        json={
            'intent': 'resume',
        },
    )

    assert resumed.status_code == 201

    final_claim = repository.get_claim(
        claim_id,
        'cus_demo',
    )

    assert final_claim is not None
    assert final_claim.terminal_disposition is None
    assert final_claim.active_session_id == resumed.json()['session_id']

    resolved = repository.list_follow_ups(
        claim_id,
        'cus_demo',
    )

    assert len(resolved) == 1
    assert resolved[0].status is FollowUpStatus.RESOLVED
    assert resolved[0].reason_code is FollowUpReasonCode.CLAIMANT_RESUMED

    future_due, _ = repository.list_due_follow_ups(
        obligation.deadline_at - timedelta(microseconds=1),
        limit=10,
        cursor=None,
    )

    assert obligation.follow_up_id not in {item.follow_up_id for item in future_due}


def test_p17_full_journey_attempt_exhaustion_expiry_retention_denies_old_session(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = _create_claim(
        client,
        auth_headers,
        'p17-full-expiry-create',
    )

    claim = created['claim']
    session = created['session']

    assert isinstance(claim, dict)
    assert isinstance(session, dict)

    claim_id = str(claim['claim_id'])
    session_id = str(session['session_id'])
    revision = int(claim['revision'])

    paused = client.post(
        (f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause'),
        headers={
            **auth_headers,
            'Idempotency-Key': ('p17-full-expiry-pause'),
            'If-Match': f'"{revision}"',
        },
    )

    assert paused.status_code == 200

    current = repository.list_follow_ups(
        claim_id,
        'cus_demo',
    )[0]

    assert current.deadline_at is not None

    # Three immutable v1 in-app attempts. Each later due execution
    # reconciles the previous no-response before committing the next.
    for _ in range(3):
        assert current.due_at is not None

        transition = process_due_follow_up(
            repository,
            current,
            current.due_at,
        )

        assert transition is not None

        reloaded = repository.get_follow_up(
            claim_id,
            current.follow_up_id,
            'cus_demo',
        )

        assert reloaded is not None
        current = reloaded

    assert current.attempt_count == 3
    assert current.status is FollowUpStatus.BLOCKED
    assert current.reason_code is FollowUpReasonCode.ATTEMPT_LIMIT_REACHED
    assert current.due_at is None

    deadline = current.deadline_at
    assert deadline is not None

    expired = process_expiring_follow_up(
        repository,
        current,
        deadline,
    )

    assert expired is not None

    terminal = repository.get_claim_internal(claim_id)

    assert terminal is not None
    assert terminal.terminal_disposition is not None
    assert (
        terminal.terminal_disposition.reason_code is TerminalDispositionReasonCode.RECOVERY_EXPIRED
    )

    terminal_follow_up = repository.get_follow_up(
        claim_id,
        current.follow_up_id,
        'cus_demo',
    )

    assert terminal_follow_up is not None
    assert terminal_follow_up.status is FollowUpStatus.RESOLVED
    assert terminal_follow_up.reason_code is FollowUpReasonCode.RECOVERY_EXPIRED

    retention = reserve_retention_from_terminal(
        repository,
        claim_id,
        now=deadline + timedelta(minutes=1),
    )

    frozen = freeze_retention_cleanup_targets(
        repository,
        retention.operation_id,
        now=deadline + timedelta(minutes=2),
    )

    completed = execute_retention_cleanup(
        repository,
        cast(FastAPI, client.app).state.evidence_storage,
        frozen.operation_id,
        now=deadline + timedelta(minutes=3),
    )

    assert completed.status is RetentionOperationStatus.COMPLETED

    assert repository.get_claim_internal(claim_id) is None

    old_session = client.get(
        (f'/api/v1/claims/{claim_id}/sessions/{session_id}'),
        headers=auth_headers,
    )

    assert old_session.status_code == 404

    old_claim = client.get(
        f'/api/v1/claims/{claim_id}',
        headers=auth_headers,
    )

    assert old_claim.status_code == 404

    staff_retention = client.get(
        (f'/api/v1/workbench/claims/{claim_id}/retention'),
        headers={'Authorization': ('Bearer synthetic-staff')},
    )

    assert staff_retention.status_code == 200
    assert staff_retention.json()['operation_status'] == 'completed'
