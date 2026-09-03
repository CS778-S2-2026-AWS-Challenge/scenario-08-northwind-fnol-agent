from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditPermission,
    AuditPermissionOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)


def _claim_event(**updates: object) -> AuditEventEnvelope:
    payload: dict[str, object] = {
        'event_id': 'aud_contract_001',
        'event_type': AuditEventType.ACTION_COMPLETED,
        'outcome': AuditOutcome.SUCCEEDED,
        'subject': AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id='clm_contract_001',
            claim_id='clm_contract_001',
        ),
        'actor': AuditActor(
            actor_type='staff',
            actor_id='staff_001',
            auth_source='authenticated_session',
        ),
        'reason': 'Completed the bounded review action.',
        'source_refs': ['action_001'],
        'visibility': AuditVisibility.INTERNAL_ONLY,
        'claim_revision': 4,
        'created_at': datetime(2026, 9, 3, 0, 0, tzinfo=UTC),
    }
    payload.update(updates)
    return AuditEventEnvelope.model_validate(payload)


def test_claim_event_requires_resulting_revision() -> None:
    with pytest.raises(ValidationError, match='resulting claim revision'):
        _claim_event(claim_revision=None)


def test_permission_event_requires_permission_decision() -> None:
    with pytest.raises(ValidationError, match='permission decision'):
        _claim_event(
            event_type=AuditEventType.PERMISSION_REJECTED,
            outcome=AuditOutcome.REJECTED,
        )

    event = _claim_event(
        event_type=AuditEventType.PERMISSION_REJECTED,
        outcome=AuditOutcome.REJECTED,
        permission=AuditPermission(
            required_permission='share_claim_with_assessor',
            outcome=AuditPermissionOutcome.REJECTED,
        ),
    )
    assert event.permission is not None


def test_consent_event_requires_reference_and_state() -> None:
    with pytest.raises(ValidationError, match='consent reference and state'):
        _claim_event(event_type=AuditEventType.CONSENT_GRANTED)

    event = _claim_event(
        event_type=AuditEventType.CONSENT_GRANTED,
        consent_ref='cns_contract_001',
        consent_state='granted',
    )
    assert event.consent_ref == 'cns_contract_001'


def test_non_claim_subject_does_not_require_claim_revision() -> None:
    event = AuditEventEnvelope(
        event_id='aud_access_001',
        event_type=AuditEventType.ACCESS_DENIED,
        outcome=AuditOutcome.REJECTED,
        subject=AuditSubject(subject_type=AuditSubjectType.ACCESS, subject_id='access_001'),
        actor=AuditActor(
            actor_type='system',
            actor_id='policy-engine',
            auth_source='service_identity',
        ),
        reason='The requested scope was not authorised.',
        visibility=AuditVisibility.AUDIT_ONLY,
        created_at=datetime(2026, 9, 3, 0, 0, tzinfo=UTC),
    )
    assert event.claim_revision is None


def test_generated_snapshot_matches_domain_model() -> None:
    from scripts.export_audit_contract import current_schema

    snapshot = Path('docs/contracts/audit-event.schema.json')
    assert current_schema() == snapshot.read_text(encoding='utf-8')
