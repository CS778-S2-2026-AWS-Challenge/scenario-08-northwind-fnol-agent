from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.domain.external_service_registry import ExternalLifecycleStatus
from backend.domain.models import (
    ActorReference,
    ActorType,
    ExternalServiceConsent,
    FormSource,
    FormStatus,
    MessageRecord,
    NeededFor,
    StructuredFormField,
    WorkingClaim,
)
from backend.services import external_service_eligibility as eligibility

ASSESSMENT = 'vehicle_damage_assessment_routing'
RECOVERY = 'vehicle_recovery_request'


def _described(status: FormStatus) -> dict[str, StructuredFormField]:
    return {
        'incident.description': StructuredFormField(
            value='I reversed into a bollard in the car park.',
            source=FormSource.CLAIMANT,
            status=status,
            needed_for=NeededFor.CURRENT_ACTION,
            updated_at=datetime(2026, 9, 20, tzinfo=UTC),
            updated_by=ActorReference(
                actor_type=ActorType.CLAIMANT, actor_id='cus_8f41a2c90d7e463b'
            ),
        )
    }


def _claim(form: dict[str, StructuredFormField]) -> WorkingClaim:
    decided_at = datetime(2026, 9, 20, tzinfo=UTC)
    return WorkingClaim(
        claim_id='clm_narrative',
        customer_id='cus_8f41a2c90d7e463b',
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
        form=form,
    )


def _consent_required(*identities: str) -> object:
    return lambda *_: [
        SimpleNamespace(
            service_identity=identity, operation_status=ExternalLifecycleStatus.CONSENT_REQUIRED
        )
        for identity in identities
    ]


@pytest.mark.parametrize('status', [None, FormStatus.PROPOSED])
def test_services_wait_for_a_confirmed_incident_description(
    monkeypatch: pytest.MonkeyPatch, status: FormStatus | None
) -> None:
    monkeypatch.setattr(
        eligibility,
        'build_agent_external_lifecycle_context',
        _consent_required(ASSESSMENT, RECOVERY),
    )
    repository = SimpleNamespace(list_handoffs=lambda *_: [])
    claim = _claim({} if status is None else _described(status))

    assert eligibility.eligible_service_ids(repository, claim, 'motor', ()) == frozenset()
    assert eligibility.eligible_service_ids(
        repository, claim, 'motor', (), current_text='My car is stuck. Can you arrange a tow?'
    ) == {RECOVERY}
    assert eligibility.eligible_service_ids(
        repository, _claim(_described(FormStatus.CONFIRMED)), 'motor', ()
    ) == {ASSESSMENT, RECOVERY}


def test_cooldown_starts_at_consent_decision_and_handoff_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = 'vehicle_damage_assessment_routing'
    decided_at = datetime(2026, 9, 20, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id='clm_cooldown',
        customer_id='cus_8f41a2c90d7e463b',
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
        form=_described(FormStatus.CONFIRMED),
        external_service_consents=[
            ExternalServiceConsent(
                consent_ref='cns_declined',
                requested_action='submit_request',
                granted_by={'actor_type': 'claimant', 'actor_id': 'cus_8f41a2c90d7e463b'},
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


def test_verified_requests_replace_pattern_recognition_on_the_model_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        eligibility,
        'build_agent_external_lifecycle_context',
        _consent_required(ASSESSMENT, RECOVERY),
    )
    repository = SimpleNamespace(list_handoffs=lambda *_: [])
    claim = _claim({})

    # The request patterns match "tow", but the model path verified no request.
    assert (
        eligibility.eligible_service_ids(
            repository,
            claim,
            'motor',
            (),
            current_text='I do not want a tow.',
            explicit_requests=frozenset(),
        )
        == frozenset()
    )
    assert eligibility.eligible_service_ids(
        repository, claim, 'motor', (), explicit_requests=frozenset({RECOVERY})
    ) == {RECOVERY}
