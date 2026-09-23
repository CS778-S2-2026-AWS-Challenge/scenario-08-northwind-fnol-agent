from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.domain.external_service_registry import ExternalLifecycleStatus
from backend.domain.models import ActorType, ExternalServiceConsent, MessageRecord, WorkingClaim
from backend.services import external_service_eligibility as eligibility


def test_cooldown_starts_at_consent_decision_and_handoff_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = 'vehicle_damage_assessment_routing'
    decided_at = datetime(2026, 9, 20, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id='clm_cooldown',
        customer_id='cus_demo',
        channel='web_agent',
        locale='en-NZ',
        created_at=decided_at,
        updated_at=decided_at,
        customer_next_step={
            'status': 'more_information_needed',
            'summary': 'Continue.',
            'responsible_party': 'claimant',
        },
        assessor_routing=None,
        external_service_consents=[
            ExternalServiceConsent(
                consent_ref='cns_declined',
                requested_action='submit_request',
                granted_by={'actor_type': 'claimant', 'actor_id': 'cus_demo'},
                service_identity=identity,
                status='declined',
                granted_at=decided_at,
                withdrawn_at=None,
            )
        ],
    )
    open_handoffs: list[SimpleNamespace] = []
    repository = SimpleNamespace(list_handoffs=lambda *_: open_handoffs)
    monkeypatch.setattr(
        eligibility,
        'build_agent_external_lifecycle_context',
        lambda *_: [
            SimpleNamespace(
                service_identity=identity, operation_status=ExternalLifecycleStatus.CONSENT_REQUIRED
            )
        ],
    )
    old_turns = tuple(
        MessageRecord(
            message_id=f'msg_old_{i}',
            claim_id=claim.claim_id,
            session_id='ses_cooldown',
            actor=ActorType.CLAIMANT,
            visibility='claimant_visible',
            content={'type': 'text', 'text': 'detail'},
            created_at=decided_at - timedelta(minutes=i + 1),
        )
        for i in range(20)
    )
    later_turns = tuple(
        MessageRecord(
            message_id=f'msg_new_{i}',
            claim_id=claim.claim_id,
            session_id='ses_cooldown',
            actor=ActorType.CLAIMANT,
            visibility='claimant_visible',
            content={'type': 'text', 'text': 'detail'},
            created_at=decided_at + timedelta(minutes=i + 1),
        )
        for i in range(3)
    )
    assert not eligibility.eligible_service_ids(repository, claim, 'motor', old_turns)
    assert not eligibility.eligible_service_ids(
        repository, claim, 'motor', old_turns + later_turns[:2]
    )
    assert eligibility.eligible_service_ids(
        repository, claim, 'motor', old_turns + later_turns
    ) == {identity}
    assert eligibility.eligible_service_ids(
        repository, claim, 'motor', old_turns, current_text='Please get me a damage assessment.'
    ) == {identity}
    open_handoffs.append(SimpleNamespace(status=SimpleNamespace(value='queued')))
    assert not eligibility.eligible_service_ids(
        repository,
        claim,
        'motor',
        old_turns + later_turns,
        current_text='Please get me a damage assessment.',
    )
