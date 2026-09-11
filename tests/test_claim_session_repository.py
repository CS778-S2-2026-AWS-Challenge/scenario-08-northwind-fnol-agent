from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.domain.models import (
    Channel,
    CustomerNextStep,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    RevisionConflict,
)

FIXED_TIME = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)


def make_paused_claim() -> tuple[WorkingClaim, SessionRecord]:
    claim = WorkingClaim(
        claim_id='clm_resume_fixture',
        customer_id='cus_demo',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id=None,
        customer_next_step=CustomerNextStep(
            status='resume_claim',
            summary='Continue the saved claim.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    session = SessionRecord(
        session_id='ses_original',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.PAUSED,
        summary='Saved incident context.',
        unresolved_questions=['Is the police report ready?'],
        pending_items=['Police report pending.'],
        prior_commitments=['The claimant can return without restarting.'],
        context_revision=claim.revision,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
    )
    return claim, session


def make_resume_mutation(
    claim: WorkingClaim,
) -> tuple[WorkingClaim, SessionRecord, IdempotencyRecord]:
    resumed_at = FIXED_TIME + timedelta(days=1)
    session = SessionRecord(
        session_id='ses_resumed',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        summary='Saved incident context.',
        unresolved_questions=['Is the police report ready?'],
        pending_items=['Police report pending.'],
        prior_commitments=['The claimant can return without restarting.'],
        context_revision=claim.revision,
        started_at=resumed_at,
        last_active_at=resumed_at,
    )
    updated_claim = claim.model_copy(
        update={
            'active_session_id': session.session_id,
            'revision': claim.revision + 1,
            'updated_at': resumed_at,
        }
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/sessions',
        key='resume-key',
        request_fingerprint='resume-fingerprint',
        claim_id=claim.claim_id,
        session_id=session.session_id,
    )
    return updated_claim, session, idempotency


def pause_created_claim(
    repository: FixtureRepository,
    claim_id: str,
    session_id: str,
) -> tuple[WorkingClaim, SessionRecord]:
    claim = repository.get_claim(claim_id, 'cus_demo')
    session = repository.get_session(claim_id, session_id, 'cus_demo')
    assert claim is not None
    assert session is not None

    timestamp = claim.updated_at + timedelta(minutes=1)
    paused_session = session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            'summary': 'Saved API resume context.',
            'pending_items': ['Police report pending.'],
            'last_active_at': timestamp,
        }
    )
    paused_claim = claim.model_copy(
        update={
            'active_session_id': None,
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    repository.save_session(paused_session)
    # Pausing clears WorkingClaim.active_session_id, and
    # docs/claim-state-transaction-boundary.md reserves pointer changes for the
    # resume/start session mutation, so save_claim() correctly rejects it. No
    # production path performs a pause, so this is fixture seeding rather than a
    # repository operation.
    repository._claims[claim.claim_id] = paused_claim
    return paused_claim, paused_session


def test_session_mutation_persists_claim_session_and_retry_metadata_together() -> None:
    repository = FixtureRepository()
    claim, paused_session = make_paused_claim()
    repository.create_claim(claim, paused_session)
    updated_claim, resumed_session, idempotency = make_resume_mutation(claim)

    repository.save_session_mutation(
        updated_claim,
        expected_revision=claim.revision,
        session=resumed_session,
        idempotency=idempotency,
    )

    assert repository.claim_count == 1
    assert repository.get_claim(claim.claim_id, claim.customer_id) == updated_claim
    assert repository.get_active_session(claim.claim_id, claim.customer_id) == resumed_session
    assert repository.list_sessions_for_claim(claim.claim_id, claim.customer_id) == [
        paused_session,
        resumed_session,
    ]
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        == idempotency
    )


def test_session_mutation_rejects_stale_revision_without_partial_writes() -> None:
    repository = FixtureRepository()
    claim, paused_session = make_paused_claim()
    repository.create_claim(claim, paused_session)
    updated_claim, resumed_session, idempotency = make_resume_mutation(claim)

    with pytest.raises(RevisionConflict) as error:
        repository.save_session_mutation(
            updated_claim,
            expected_revision=claim.revision - 1,
            session=resumed_session,
            idempotency=idempotency,
        )

    assert error.value.current_revision == claim.revision
    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert (
        repository.get_session(
            claim.claim_id,
            resumed_session.session_id,
            claim.customer_id,
        )
        is None
    )
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )


@pytest.mark.parametrize(
    ('case', 'expected_error'),
    [
        ('missing_claim', KeyError),
        ('mismatched_link', KeyError),
        ('duplicate_session', IdempotencyConflict),
        ('existing_active_session', KeyError),
        ('duplicate_key', IdempotencyConflict),
    ],
)
def test_session_mutation_rejects_invalid_guards_without_partial_writes(
    case: str,
    expected_error: type[Exception],
) -> None:
    repository = FixtureRepository()
    claim, paused_session = make_paused_claim()
    updated_claim, resumed_session, idempotency = make_resume_mutation(claim)

    if case != 'missing_claim':
        repository.create_claim(claim, paused_session)

    if case == 'mismatched_link':
        resumed_session = resumed_session.model_copy(update={'customer_id': 'cus_other'})
    elif case == 'duplicate_session':
        repository.save_session(resumed_session)
    elif case == 'existing_active_session':
        already_active = paused_session.model_copy(
            update={
                'session_id': 'ses_already_active',
                'status': SessionStatus.ACTIVE,
            }
        )
        repository.save_session(already_active)
    elif case == 'duplicate_key':
        repository.save_idempotency(idempotency)

    before_claim = repository.get_claim(claim.claim_id, claim.customer_id)
    before_sessions = repository.list_sessions_for_claim(claim.claim_id, claim.customer_id)
    before_idempotency = repository.find_idempotency(
        idempotency.actor_id,
        idempotency.route,
        idempotency.key,
    )

    with pytest.raises(expected_error):
        repository.save_session_mutation(
            updated_claim,
            expected_revision=claim.revision,
            session=resumed_session,
            idempotency=idempotency,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == before_claim
    assert repository.list_sessions_for_claim(claim.claim_id, claim.customer_id) == before_sessions
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        == before_idempotency
    )


def test_start_session_reads_saved_claim_in_new_session(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'claim-for-resume'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']
    original_session_id = created.json()['session']['session_id']
    paused_claim, _ = pause_created_claim(repository, claim_id, original_session_id)

    resumed = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'resume-saved-claim'},
        json={'intent': 'resume'},
    )

    assert resumed.status_code == 201
    resumed_session_id = resumed.json()['session_id']
    assert resumed_session_id != original_session_id
    assert resumed.json()['resume']['summary'] == 'Saved API resume context.'
    assert resumed.json()['resume']['pending_items'] == ['Police report pending.']

    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    assert stored_claim is not None
    assert repository.claim_count == 1
    assert stored_claim.revision == paused_claim.revision + 1
    assert stored_claim.active_session_id == resumed_session_id
    evaluation = repository.list_branch_evaluations(claim_id, 'cus_demo')[-1]
    assert evaluation.recomputation_reason == 'session_resumed'
    assert evaluation.resulting_claim_revision == stored_claim.revision
    assert evaluation.session_id == resumed_session_id

    read_session = client.get(
        f'/api/v1/claims/{claim_id}/sessions/{resumed_session_id}',
        headers=auth_headers,
    )
    assert read_session.status_code == 200
    assert read_session.json()['session_id'] == resumed_session_id
    assert (
        repository.find_idempotency(
            'cus_demo',
            f'/api/v1/claims/{claim_id}/sessions',
            'resume-saved-claim',
        )
        is not None
    )


def test_start_new_session_replaces_active_session_inside_atomic_mutation(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={
            **auth_headers,
            'Idempotency-Key': 'claim-for-atomic-new-session',
        },
        json={
            'channel': 'web_agent',
            'locale': 'en-NZ',
            'incident_type': 'motor',
        },
    )
    assert created.status_code == 201

    claim_id = created.json()['claim']['claim_id']
    original_session_id = created.json()['session']['session_id']

    def reject_standalone_session_write(session: SessionRecord) -> None:
        del session
        raise AssertionError('start_session(intent="new") must not pre-write the old Session')

    monkeypatch.setattr(
        repository,
        'save_session',
        reject_standalone_session_write,
    )

    started = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={
            **auth_headers,
            'Idempotency-Key': 'atomic-new-session',
        },
        json={'intent': 'new'},
    )

    assert started.status_code == 201

    new_session_id = started.json()['session_id']
    assert new_session_id != original_session_id

    stored_claim = repository.get_claim(claim_id, 'cus_demo')
    old_session = repository.get_session(
        claim_id,
        original_session_id,
        'cus_demo',
    )
    new_session = repository.get_session(
        claim_id,
        new_session_id,
        'cus_demo',
    )

    assert stored_claim is not None
    assert old_session is not None
    assert new_session is not None

    assert stored_claim.active_session_id == new_session_id
    assert old_session.status is SessionStatus.CLOSED
    assert old_session.closed_at is not None
    assert old_session.recovery_context is None
    assert new_session.status is SessionStatus.ACTIVE


def test_resume_keeps_persisted_model_profile_for_a_fresh_client(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'claim-for-gpt-resume'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']
    original_session_id = created.json()['session']['session_id']
    _, paused_session = pause_created_claim(repository, claim_id, original_session_id)
    repository.save_session(
        paused_session.model_copy(update={'model_profile_id': 'nowcoding-gpt54mini'})
    )

    resumed = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'resume-gpt-from-fresh-client'},
        json={'intent': 'resume'},
    )

    assert resumed.status_code == 201
    assert resumed.json()['model_profile_id'] == 'nowcoding-gpt54mini'
    resumed_session = repository.get_session(
        claim_id,
        resumed.json()['session_id'],
        'cus_demo',
    )
    assert resumed_session is not None
    assert resumed_session.model_profile_id == 'nowcoding-gpt54mini'


def test_resume_rejects_explicit_model_profile_conflict(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'claim-for-profile-conflict'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']
    original_session_id = created.json()['session']['session_id']
    _, paused_session = pause_created_claim(repository, claim_id, original_session_id)
    repository.save_session(
        paused_session.model_copy(update={'model_profile_id': 'nowcoding-gpt54mini'})
    )

    resumed = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'resume-conflicting-profile'},
        json={'intent': 'resume', 'model_profile_id': 'qwen-local'},
    )

    assert resumed.status_code == 409
    assert resumed.json()['error']['code'] == 'MODEL_PROFILE_CONFLICT'
    assert len(repository.list_sessions_for_claim(claim_id, 'cus_demo')) == 1


def test_start_session_surfaces_repository_revision_conflict(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'claim-for-conflict'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']
    original_session_id = created.json()['session']['session_id']
    paused_claim, _ = pause_created_claim(repository, claim_id, original_session_id)

    def reject_session_mutation(
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: object | None = None,
        resolved_follow_up: object | None = None,
        replaced_active_session: SessionRecord | None = None,
    ) -> None:
        del (
            claim,
            session,
            idempotency,
            branch_evaluation,
            resolved_follow_up,
            replaced_active_session,
        )
        raise RevisionConflict(expected_revision + 7)

    monkeypatch.setattr(repository, 'save_session_mutation', reject_session_mutation)

    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'resume-conflict'},
        json={'intent': 'resume'},
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'
    assert response.json()['error']['current_revision'] == paused_claim.revision + 7
    assert repository.get_claim(claim_id, 'cus_demo') == paused_claim
    assert len(repository.list_sessions_for_claim(claim_id, 'cus_demo')) == 1
    assert (
        repository.find_idempotency(
            'cus_demo',
            f'/api/v1/claims/{claim_id}/sessions',
            'resume-conflict',
        )
        is None
    )


def test_start_session_surfaces_repository_idempotency_conflict_without_partial_writes(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'claim-for-idempotency-conflict'},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert created.status_code == 201
    claim_id = created.json()['claim']['claim_id']
    original_session_id = created.json()['session']['session_id']
    paused_claim, paused_session = pause_created_claim(repository, claim_id, original_session_id)

    def reject_session_mutation(
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: object | None = None,
        resolved_follow_up: object | None = None,
        replaced_active_session: SessionRecord | None = None,
    ) -> None:
        del (
            claim,
            expected_revision,
            session,
            branch_evaluation,
            resolved_follow_up,
            replaced_active_session,
        )
        raise IdempotencyConflict(idempotency.key)

    monkeypatch.setattr(repository, 'save_session_mutation', reject_session_mutation)

    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'resume-idempotency-conflict'},
        json={'intent': 'resume'},
    )

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert repository.get_claim(claim_id, 'cus_demo') == paused_claim
    assert repository.list_sessions_for_claim(claim_id, 'cus_demo') == [paused_session]
    assert (
        repository.find_idempotency(
            'cus_demo',
            f'/api/v1/claims/{claim_id}/sessions',
            'resume-idempotency-conflict',
        )
        is None
    )
