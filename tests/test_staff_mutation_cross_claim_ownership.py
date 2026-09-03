from datetime import UTC, datetime

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
    StaffActionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyRecord

FIXED_TIME = datetime(2026, 8, 24, 1, 45, tzinfo=UTC)


def _claim(repository: FixtureRepository, suffix: str) -> WorkingClaim:
    claim = WorkingClaim(
        claim_id=f'clm_{suffix}',
        customer_id=f'cus_{suffix}',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id=f'ses_{suffix}',
        customer_next_step=CustomerNextStep(
            status='staff_review',
            summary='Northwind staff are reviewing the claim.',
            responsible_party=ResponsibleParty.CLAIMS_PROFESSIONAL,
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    repository.create_claim(
        claim,
        SessionRecord(
            session_id=f'ses_{suffix}',
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            started_at=FIXED_TIME,
            last_active_at=FIXED_TIME,
        ),
    )
    return claim


def _idempotency(claim: WorkingClaim, key: str) -> IdempotencyRecord:
    return IdempotencyRecord(
        actor_id='stf_demo',
        route=f'/api/v1/workbench/claims/{claim.claim_id}/{key}',
        key=key,
        request_fingerprint=f'fingerprint-{key}',
        claim_id=claim.claim_id,
        session_id='',
    )


def test_staff_action_id_cannot_be_reowned_by_another_claim() -> None:
    repository = FixtureRepository()
    first = _claim(repository, 'first_action')
    second = _claim(repository, 'second_action')
    original = StaffActionRecord(
        action_id='act_shared_identity',
        claim_id=first.claim_id,
        action_type='review',
        status=StaffActionStatus.OPEN,
        assigned_to='stf_demo',
        requested_outcome='Review the claim.',
        created_at=FIXED_TIME,
    )
    repository.save_staff_mutation(
        first.model_copy(update={'revision': 2}),
        1,
        _idempotency(first, 'seed-action'),
        staff_action=original,
    )

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            second.model_copy(update={'revision': 2}),
            1,
            _idempotency(second, 'steal-action'),
            staff_action=original.model_copy(update={'claim_id': second.claim_id}),
        )

    assert repository.get_staff_action(first.claim_id, original.action_id) == original
    assert repository.get_staff_action(second.claim_id, original.action_id) is None
    assert repository.get_claim(second.claim_id, second.customer_id) == second


def test_customer_update_id_cannot_be_reowned_by_another_claim() -> None:
    repository = FixtureRepository()
    first = _claim(repository, 'first_update')
    second = _claim(repository, 'second_update')
    original = CustomerUpdateRecord(
        update_id='upd_shared_identity',
        claim_id=first.claim_id,
        summary='First claim update.',
        responsible_party=ResponsibleParty.CLAIMANT,
        created_by='stf_demo',
        created_at=FIXED_TIME,
    )
    repository.save_staff_mutation(
        first.model_copy(update={'revision': 2}),
        1,
        _idempotency(first, 'seed-update'),
        customer_update=original,
    )

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            second.model_copy(update={'revision': 2}),
            1,
            _idempotency(second, 'steal-update'),
            customer_update=original.model_copy(update={'claim_id': second.claim_id}),
        )

    assert repository.list_customer_updates(first.claim_id) == [original]
    assert repository.list_customer_updates(second.claim_id) == []
    assert repository.get_claim(second.claim_id, second.customer_id) == second


def test_signal_decision_id_cannot_be_reowned_by_another_claim() -> None:
    repository = FixtureRepository()
    first = _claim(repository, 'first_signal')
    second = _claim(repository, 'second_signal')
    original = SignalDecisionRecord(
        signal_decision_id='sdec_shared_identity',
        claim_id=first.claim_id,
        signal_id='sig_review',
        actor_id='stf_demo',
        decision=SignalDecisionValue.DISMISSED,
        reason_codes=['NOT_SUPPORTED'],
        summary='The signal is not supported by the evidence.',
        created_at=FIXED_TIME,
    )
    repository.save_staff_mutation(
        first.model_copy(update={'revision': 2}),
        1,
        _idempotency(first, 'seed-signal'),
        signal_decision=original,
    )

    with pytest.raises(KeyError):
        repository.save_staff_mutation(
            second.model_copy(update={'revision': 2}),
            1,
            _idempotency(second, 'steal-signal'),
            signal_decision=original.model_copy(update={'claim_id': second.claim_id}),
        )

    assert repository.list_signal_decisions(first.claim_id) == [original]
    assert repository.list_signal_decisions(second.claim_id) == []
    assert repository.get_claim(second.claim_id, second.customer_id) == second
