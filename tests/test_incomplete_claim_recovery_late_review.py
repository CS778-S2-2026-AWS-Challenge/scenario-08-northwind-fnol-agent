import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from backend.domain.models import (
    FollowUpContactPermission,
    FollowUpRecord,
    FollowUpStatus,
    PreferredChannel,
    ResponsibleParty,
    SessionRecord,
    SessionRecoveryContext,
    SessionStatus,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    RevisionConflict,
)

CheckpointBundle = tuple[
    WorkingClaim,
    int,
    SessionRecord,
    FollowUpRecord,
    IdempotencyRecord,
]


def _create_claim(
    client: TestClient,
    headers: dict[str, str],
    key: str,
) -> tuple[str, str, int]:
    response = client.post(
        '/api/v1/claims',
        headers={
            **headers,
            'Idempotency-Key': key,
        },
        json={
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': 'motor',
        },
    )

    assert response.status_code == 201

    body = response.json()

    return (
        str(body['claim']['claim_id']),
        str(body['session']['session_id']),
        int(body['claim']['revision']),
    )


def _set_eligibility(
    repository: FixtureRepository,
    claim_id: str,
    *,
    workflow_state: WorkflowState,
    can_resume: bool,
) -> int:
    claim = repository.get_claim(
        claim_id,
        'cus_demo',
    )
    assert claim is not None

    updated = claim.model_copy(
        update={
            'claim_state': claim.claim_state.model_copy(
                update={
                    'workflow_state': workflow_state,
                }
            ),
            'customer_next_step': (
                claim.customer_next_step.model_copy(
                    update={
                        'can_resume': can_resume,
                    }
                )
            ),
            'revision': claim.revision + 1,
            'updated_at': datetime.now(UTC),
        }
    )

    repository.save_claim(
        updated,
        expected_revision=claim.revision,
    )

    return updated.revision


@pytest.mark.parametrize(
    'workflow_state',
    [
        WorkflowState.COLLECTING,
        WorkflowState.READY_FOR_NEXT,
        WorkflowState.AWAITING_EVIDENCE,
        WorkflowState.PROFESSIONAL_REVIEW,
    ],
)
def test_all_resumable_non_terminal_states_share_incomplete_projection(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
    workflow_state: WorkflowState,
) -> None:
    claim_id, session_id, revision = _create_claim(
        client,
        auth_headers,
        f'late-{workflow_state.value}',
    )

    if workflow_state is not WorkflowState.COLLECTING:
        revision = _set_eligibility(
            repository,
            claim_id,
            workflow_state=workflow_state,
            can_resume=True,
        )

    paused = client.post(
        (f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause'),
        headers={
            **auth_headers,
            'Idempotency-Key': (f'late-pause-{workflow_state.value}'),
            'If-Match': f'"{revision}"',
        },
    )

    assert paused.status_code == 200

    claimant = client.get(
        f'/api/v1/claims/{claim_id}',
        headers=auth_headers,
    )

    assert claimant.status_code == 200
    assert claimant.json()['incomplete_context'] is not None

    workbench = client.get(
        f'/api/v1/workbench/claims/{claim_id}',
        headers=staff_auth_headers,
    )

    assert workbench.status_code == 200

    summary = workbench.json()['work_summary']

    assert summary['incomplete_context'] is not None

    incomplete_view = client.get(
        '/api/v1/workbench/claims',
        params={'view': 'incomplete_claims'},
        headers=staff_auth_headers,
    )

    assert incomplete_view.status_code == 200
    assert claim_id in {item['claim_id'] for item in incomplete_view.json()['items']}


@pytest.mark.parametrize(
    ('workflow_state', 'can_resume'),
    [
        (
            WorkflowState.CREATED,
            True,
        ),
        (
            WorkflowState.COLLECTING,
            False,
        ),
    ],
)
def test_pause_rejects_terminal_or_non_resumable_claim(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    workflow_state: WorkflowState,
    can_resume: bool,
) -> None:
    claim_id, session_id, _ = _create_claim(
        client,
        auth_headers,
        f'late-reject-{workflow_state.value}',
    )

    revision = _set_eligibility(
        repository,
        claim_id,
        workflow_state=workflow_state,
        can_resume=can_resume,
    )

    response = client.post(
        (f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause'),
        headers={
            **auth_headers,
            'Idempotency-Key': (f'late-reject-{workflow_state.value}'),
            'If-Match': f'"{revision}"',
        },
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'INVALID_STATE_TRANSITION'

    stored_claim = repository.get_claim(
        claim_id,
        'cus_demo',
    )

    stored_session = repository.get_session(
        claim_id,
        session_id,
        'cus_demo',
    )

    assert stored_claim is not None
    assert stored_session is not None

    assert stored_claim.active_session_id == session_id
    assert stored_session.status is SessionStatus.ACTIVE

    assert (
        repository.list_follow_ups(
            claim_id,
            'cus_demo',
        )
        == []
    )


def test_pause_response_revision_provenance_and_logging(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    claim_id, session_id, revision = _create_claim(
        client,
        auth_headers,
        'late-business-create',
    )

    patched = client.patch(
        f'/api/v1/claims/{claim_id}/form',
        headers={
            **auth_headers,
            'If-Match': f'"{revision}"',
        },
        json={
            'updates': [
                {
                    'field_code': 'incident.description',
                    'value': ('Rear-ended while stopped at traffic lights.'),
                    'status': 'confirmed',
                }
            ]
        },
    )

    assert patched.status_code == 200

    patched_revision = int(patched.json()['revision'])

    before_pause = repository.get_claim(
        claim_id,
        'cus_demo',
    )

    assert before_pause is not None

    field = before_pause.form['incident.description']

    assert field.source_refs

    source_ref = field.source_refs[-1]

    caplog.clear()

    with caplog.at_level(
        logging.INFO,
        logger='backend.api.claims',
    ):
        paused = client.post(
            (f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause'),
            headers={
                **auth_headers,
                'Idempotency-Key': 'late-business-pause',
                'If-Match': f'"{patched_revision}"',
            },
        )

    assert paused.status_code == 200

    body = paused.json()

    returned_revision = int(body['claim']['revision'])

    assert returned_revision == patched_revision + 1

    assert body['claim']['dynamic_form'] is not None

    assert body['claim']['dynamic_form']['claim_revision'] == returned_revision

    stored_session = repository.get_session(
        claim_id,
        session_id,
        'cus_demo',
    )

    assert stored_session is not None
    assert stored_session.recovery_context is not None

    recovery = stored_session.recovery_context

    assert recovery.last_meaningful_activity_at == field.updated_at

    assert recovery.last_meaningful_activity_source_ref == source_ref

    follow_ups = repository.list_follow_ups(
        claim_id,
        'cus_demo',
    )

    assert len(follow_ups) == 1
    assert source_ref in follow_ups[0].source_refs

    records = [
        record
        for record in caplog.records
        if record.name == 'backend.api.claims' and record.getMessage() == 'claim_session.pause'
    ]

    assert records

    record = records[-1]

    assert getattr(record, 'request_id', None)
    assert getattr(record, 'claim_id', None) == claim_id
    assert getattr(record, 'session_id', None) == session_id
    assert getattr(record, 'outcome', None) == 'paused'
    assert getattr(record, 'claim_revision', None) == returned_revision


def _checkpoint_bundle(
    repository: FixtureRepository,
    claim_id: str,
    session_id: str,
    suffix: str,
) -> CheckpointBundle:
    claim = repository.get_claim(
        claim_id,
        'cus_demo',
    )

    session = repository.get_session(
        claim_id,
        session_id,
        'cus_demo',
    )

    assert claim is not None
    assert session is not None

    timestamp = datetime.now(UTC)

    source_ref = f'claim:{claim_id}:revision:1'

    recovery = SessionRecoveryContext(
        interrupted_at=timestamp,
        last_meaningful_activity_at=claim.created_at,
        last_meaningful_activity_source_ref=source_ref,
        resume_point=claim.customer_next_step.summary,
    )

    paused_session = session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            'context_revision': claim.revision,
            'recovery_context': recovery,
        }
    )

    updated_claim = claim.model_copy(
        update={
            'revision': claim.revision + 1,
            'active_session_id': None,
            'updated_at': timestamp,
        }
    )

    follow_up = FollowUpRecord(
        follow_up_id=f'fup_late_{suffix}',
        claim_id=claim_id,
        source_session_id=session_id,
        purpose='resume_incomplete_claim',
        responsible_party=ResponsibleParty.SYSTEM,
        source_refs=[
            (f'claim:{claim_id}:revision:{updated_claim.revision}'),
            f'session:{session_id}',
            source_ref,
        ],
        contact_permission=(FollowUpContactPermission.AUTHORISED),
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=timestamp,
        created_at=timestamp,
        updated_at=timestamp,
    )

    idempotency = IdempotencyRecord(
        actor_id='cus_demo',
        route=(f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause'),
        key=f'late-race-{suffix}',
        request_fingerprint=f'late-race-{suffix}',
        claim_id=claim_id,
        session_id=session_id,
        follow_up_id=follow_up.follow_up_id,
    )

    return (
        updated_claim,
        claim.revision,
        paused_session,
        follow_up,
        idempotency,
    )


def test_fixture_checkpoint_race_commits_exactly_one_bundle(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_id, session_id, _ = _create_claim(
        client,
        auth_headers,
        'late-race-create',
    )

    first = _checkpoint_bundle(
        repository,
        claim_id,
        session_id,
        'a',
    )

    second = _checkpoint_bundle(
        repository,
        claim_id,
        session_id,
        'b',
    )

    original_validate = repository._validate_claim_mutation
    barrier = Barrier(2)

    def synchronized_validate(
        claim: WorkingClaim,
        expected_revision: int,
        *,
        allow_active_session_change: bool = False,
    ) -> WorkingClaim:
        result = original_validate(
            claim,
            expected_revision,
            allow_active_session_change=allow_active_session_change,
        )
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(
        repository,
        '_validate_claim_mutation',
        synchronized_validate,
    )

    def commit(bundle: CheckpointBundle) -> str:
        (
            updated_claim,
            expected_revision,
            paused_session,
            follow_up,
            idempotency,
        ) = bundle

        try:
            repository.save_incomplete_checkpoint(
                updated_claim,
                expected_revision=expected_revision,
                session=paused_session,
                follow_up=follow_up,
                idempotency=idempotency,
            )
        except (
            RevisionConflict,
            IdempotencyConflict,
        ):
            return 'conflict'

        return 'success'

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                commit,
                (
                    first,
                    second,
                ),
            )
        )

    assert sorted(results) == [
        'conflict',
        'success',
    ]

    open_follow_ups = [
        record
        for record in repository.list_follow_ups(
            claim_id,
            'cus_demo',
        )
        if record.purpose == 'resume_incomplete_claim'
        and record.status
        in {
            FollowUpStatus.PENDING,
            FollowUpStatus.BLOCKED,
        }
    ]

    assert len(open_follow_ups) == 1
