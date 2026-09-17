from datetime import UTC, datetime

import mongomock
import pytest

from backend.domain.models import (
    Channel,
    CustomerNextStep,
    CustomerUpdateRecord,
    ResponsibleParty,
    SessionRecord,
    SignalDecisionRecord,
    SignalDecisionValue,
    StaffActionRecord,
    StaffActionResult,
    StaffActionStatus,
    WorkingClaim,
)
from backend.domain.realtime import RealtimeResource
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyRecord

FIXED_TIME = datetime(2026, 8, 24, 1, 30, tzinfo=UTC)


def _repository() -> tuple[FixtureRepository, WorkingClaim]:
    repository = FixtureRepository()
    claim = WorkingClaim(
        claim_id='clm_staff_actor',
        customer_id='cus_staff_actor',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id='ses_staff_actor',
        customer_next_step=CustomerNextStep(
            status='staff_review',
            summary='Northwind staff are reviewing the claim.',
            responsible_party=ResponsibleParty.CLAIMS_PROFESSIONAL,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    session = SessionRecord(
        session_id='ses_staff_actor',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=FIXED_TIME,
        last_active_at=FIXED_TIME,
    )
    repository.create_claim(claim, session)
    return repository, claim


def _idempotency(key: str) -> IdempotencyRecord:
    return IdempotencyRecord(
        actor_id='stf_demo',
        route=f'/api/v1/workbench/claims/clm_staff_actor/{key}',
        key=key,
        request_fingerprint=f'fingerprint-{key}',
        claim_id='clm_staff_actor',
        session_id='',
    )


def _assert_no_staff_side_effect(
    repository: FixtureRepository,
    claim: WorkingClaim,
    idempotency: IdempotencyRecord,
) -> None:
    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_staff_actions(claim.claim_id) == []
    assert repository.list_customer_updates(claim.claim_id) == []
    assert repository.list_signal_decisions(claim.claim_id) == []
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )


def test_staff_mutation_rejects_completed_action_actor_mismatch_without_partial_write() -> None:
    repository, claim = _repository()
    idempotency = _idempotency('completed-action-actor')
    action = StaffActionRecord(
        action_id='act_actor_mismatch',
        claim_id=claim.claim_id,
        action_type='professional_review',
        status=StaffActionStatus.COMPLETED,
        assigned_to='stf_demo',
        requested_outcome='Review the supplied context.',
        result=StaffActionResult(
            outcome='reviewed',
            summary='Review completed.',
            reason_codes=['REVIEW_COMPLETE'],
        ),
        completed_by='stf_other',
        created_at=FIXED_TIME,
        completed_at=FIXED_TIME,
    )

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            claim.model_copy(update={'revision': 2}),
            expected_revision=1,
            idempotency=idempotency,
            staff_action=action,
        )

    _assert_no_staff_side_effect(repository, claim, idempotency)


def test_staff_mutation_rejects_customer_update_actor_mismatch_without_partial_write() -> None:
    repository, claim = _repository()
    idempotency = _idempotency('customer-update-actor')
    update = CustomerUpdateRecord(
        update_id='upd_actor_mismatch',
        claim_id=claim.claim_id,
        summary='The review has been completed.',
        responsible_party=ResponsibleParty.CLAIMANT,
        created_by='stf_other',
        created_at=FIXED_TIME,
    )

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            claim.model_copy(update={'revision': 2}),
            expected_revision=1,
            idempotency=idempotency,
            customer_update=update,
        )

    _assert_no_staff_side_effect(repository, claim, idempotency)


def test_staff_mutation_rejects_signal_decision_actor_mismatch_without_partial_write() -> None:
    repository, claim = _repository()
    idempotency = _idempotency('signal-decision-actor')
    decision = SignalDecisionRecord(
        signal_decision_id='sdec_actor_mismatch',
        claim_id=claim.claim_id,
        signal_id='sig_review',
        actor_id='stf_other',
        decision=SignalDecisionValue.DISMISSED,
        reason_codes=['NOT_SUPPORTED'],
        summary='The signal is not supported by the evidence.',
        created_at=FIXED_TIME,
    )

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            claim.model_copy(update={'revision': 2}),
            expected_revision=1,
            idempotency=idempotency,
            signal_decision=decision,
        )

    _assert_no_staff_side_effect(repository, claim, idempotency)


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
def test_staff_projection_changes_publish_independent_refresh_boundaries(adapter: str) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(mongomock.MongoClient(), f'staff_projection_{adapter}')
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo
    fixture_repository, claim = _repository()
    del fixture_repository
    repository.create_claim(
        claim,
        SessionRecord(
            session_id=claim.active_session_id or '',
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            started_at=FIXED_TIME,
            last_active_at=FIXED_TIME,
        ),
    )
    update = CustomerUpdateRecord(
        update_id='upd_projection_refresh',
        claim_id=claim.claim_id,
        summary='The review has been completed.',
        responsible_party=ResponsibleParty.CLAIMANT,
        created_by='stf_demo',
        created_at=FIXED_TIME,
    )
    decision = SignalDecisionRecord(
        signal_decision_id='sdec_projection_refresh',
        claim_id=claim.claim_id,
        signal_id='sig_review',
        actor_id='stf_demo',
        decision=SignalDecisionValue.DISMISSED,
        reason_codes=['NOT_SUPPORTED'],
        summary='The signal is not supported by the evidence.',
        created_at=FIXED_TIME,
    )

    assert repository.list_customer_updates(claim.claim_id) == []
    assert repository.list_signal_decisions(claim.claim_id) == []
    repository.save_staff_mutation(
        claim.model_copy(update={'revision': 2}),
        expected_revision=1,
        idempotency=_idempotency(f'projection-refresh-{adapter}'),
        customer_update=update,
        signal_decision=decision,
    )

    assert repository.list_customer_updates(claim.claim_id) == [update]
    assert repository.list_signal_decisions(claim.claim_id) == [decision]
    assert repository.replay_realtime_events(None, limit=10)[-1].resources == (
        RealtimeResource.CLAIM,
        RealtimeResource.CUSTOMER_UPDATES,
        RealtimeResource.SIGNALS,
        RealtimeResource.QUEUE,
    )
