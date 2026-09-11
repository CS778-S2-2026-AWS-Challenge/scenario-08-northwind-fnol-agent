from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest

from backend.domain.models import (
    Channel,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    FollowUpContactPermission,
    FollowUpRecord,
    FollowUpStatus,
    PreferredChannel,
    ResponsibleParty,
    SessionRecord,
    SessionRecoveryContext,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    RevisionConflict,
)


def test_fixture_pause_and_evidence_from_same_revision_commit_exactly_one_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FixtureRepository()
    now = datetime.now(UTC)
    claim = WorkingClaim(
        claim_id='clm_pause_evidence_race',
        customer_id='cus_pause_evidence_race',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id='ses_pause_evidence_race',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=now,
        updated_at=now,
    )
    session = SessionRecord(
        session_id='ses_pause_evidence_race',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        status=SessionStatus.ACTIVE,
        context_revision=claim.revision,
        started_at=now,
        last_active_at=now,
    )
    repository.create_claim(claim, session)

    source_ref = f'claim:{claim.claim_id}:revision:{claim.revision}'
    recovery = SessionRecoveryContext(
        interrupted_at=now,
        last_meaningful_activity_at=now,
        last_meaningful_activity_source_ref=source_ref,
        resume_point=claim.customer_next_step.summary,
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
            'updated_at': now,
        }
    )
    follow_up = FollowUpRecord(
        follow_up_id='fup_pause_evidence_race',
        claim_id=claim.claim_id,
        source_session_id=session.session_id,
        purpose='resume_incomplete_claim',
        responsible_party=ResponsibleParty.SYSTEM,
        source_refs=[source_ref, f'session:{session.session_id}'],
        contact_permission=FollowUpContactPermission.AUTHORISED,
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=now,
        created_at=now,
        updated_at=now,
    )
    pause_idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/sessions/{session.session_id}/pause',
        key='pause-race',
        request_fingerprint='pause-race-revision-1',
        claim_id=claim.claim_id,
        session_id=session.session_id,
        follow_up_id=follow_up.follow_up_id,
    )

    evidence_claim = claim.model_copy(
        update={
            'revision': claim.revision + 1,
            'updated_at': now,
        }
    )
    evidence = EvidenceRecord(
        evidence_id='evd_pause_evidence_race',
        claim_id=claim.claim_id,
        kind='incident_image',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        source=EvidenceSource.CLAIMANT,
        created_at=now,
        updated_at=now,
    )
    evidence_idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/evidence/uploads',
        key='evidence-race',
        request_fingerprint='evidence-race-revision-1',
        claim_id=claim.claim_id,
        session_id=session.session_id,
    )

    original_validate = repository._validate_claim_mutation
    barrier = Barrier(2)

    def synchronized_validate(
        incoming_claim: WorkingClaim,
        expected_revision: int,
        *,
        allow_active_session_change: bool = False,
    ) -> WorkingClaim:
        stored = original_validate(
            incoming_claim,
            expected_revision,
            allow_active_session_change=allow_active_session_change,
        )
        barrier.wait(timeout=5)
        return stored

    monkeypatch.setattr(repository, '_validate_claim_mutation', synchronized_validate)

    def pause() -> str:
        try:
            repository.save_incomplete_checkpoint(
                paused_claim,
                expected_revision=claim.revision,
                session=paused_session,
                follow_up=follow_up,
                idempotency=pause_idempotency,
            )
        except (RevisionConflict, IdempotencyConflict, KeyError):
            return 'conflict'
        return 'pause'

    def save_evidence() -> str:
        try:
            repository.save_evidence_mutation(
                evidence_claim,
                expected_revision=claim.revision,
                evidence=evidence,
                idempotency=evidence_idempotency,
            )
        except (RevisionConflict, IdempotencyConflict, KeyError):
            return 'conflict'
        return 'evidence'

    with ThreadPoolExecutor(max_workers=2) as pool:
        pause_future = pool.submit(pause)
        evidence_future = pool.submit(save_evidence)
        results = [pause_future.result(), evidence_future.result()]

    assert sorted(results) == ['conflict', 'evidence']

    stored_claim = repository.get_claim(claim.claim_id, claim.customer_id)
    stored_session = repository.get_session(
        claim.claim_id,
        session.session_id,
        claim.customer_id,
    )
    assert stored_claim == evidence_claim
    assert stored_session == session
    assert (
        repository.get_evidence(
            claim.claim_id,
            evidence.evidence_id,
            claim.customer_id,
        )
        == evidence
    )
    assert repository.list_follow_ups(claim.claim_id, claim.customer_id) == []
