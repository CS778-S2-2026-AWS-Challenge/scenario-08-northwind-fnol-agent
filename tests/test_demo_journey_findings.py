"""Demo capture findings: incident time, chat photos, papers the claimant sends later."""

import re
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.agent_v8 import V8DocumentRequest
from backend.domain.evidence import effective_evidence_kind
from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import InvariantGuardedAgent
from backend.services.turn_reducer import deferred_document_evidence
from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact

NZ_MOMENT = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\+1[23]:00$')


def test_relative_incident_time_is_stored_as_a_new_zealand_time(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    # The values the live model produced for "about 20 minutes ago" in the capture.
    provider = V8JourneyProvider(
        [
            envelope(
                fields=[
                    fact('claim.product_family', 'motor', 'rear-ended'),
                    fact('incident.occurred_at', 'PT20M', 'about 20 minutes ago'),
                ]
            ),
            envelope(fields=[fact('incident.occurred_at', 'current_approx', None)]),
        ]
    )
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'motor', 'relative-time')

    journey.send('Someone rear-ended me at the lights about 20 minutes ago.')

    claim = repository.get_claim(journey.claim_id, 'cus_demo')
    assert claim is not None
    stored = claim.form['incident.occurred_at']
    assert NZ_MOMENT.match(stored.value), stored.value
    assert stored.precision.value == 'approximate'
    assert 'reported_at_local' in (provider.gateway.requests[0].messages[-1].content or '')

    # An internal token with no claimant words is dropped, not stored over the time.
    journey.send('Thanks.')
    claim = repository.get_claim(journey.claim_id, 'cus_demo')
    assert claim is not None and claim.form['incident.occurred_at'].value == stored.value


def _evidence(kind: str, media_type: str | None, status: EvidenceStatus) -> EvidenceRecord:
    created = datetime(2026, 10, 1, 4, 40, tzinfo=UTC)
    return EvidenceRecord(
        evidence_id=f'evd_{kind}',
        claim_id='clm_photo',
        kind=kind,
        media_type=media_type,
        status=status,
        file_status=EvidenceFileStatus.READY,
        source=EvidenceSource.CLAIMANT,
        created_at=created,
        updated_at=created,
    )


def test_a_chat_photo_counts_as_the_incident_photo() -> None:
    assert (
        effective_evidence_kind(_evidence('other_document', 'image/jpeg', EvidenceStatus.RECEIVED))
        == 'incident_photo'
    )
    assert (
        effective_evidence_kind(
            _evidence('other_document', 'application/pdf', EvidenceStatus.RECEIVED)
        )
        == 'other_document'
    )
    assert (
        effective_evidence_kind(_evidence('repair_quote', 'image/png', EvidenceStatus.RECEIVED))
        == 'repair_quote'
    )


def test_a_paper_promised_for_later_is_recorded_once_as_expected() -> None:
    claim = SimpleNamespace(claim_id='clm_later')
    message = SimpleNamespace(
        message_id='msg_later', content={'text': "I'll get the quote this week."}
    )
    later = SimpleNamespace(
        document_requests=(
            V8DocumentRequest(document_kind='repair_quote', from_party='claimant', when='later'),
        )
    )
    now = datetime(2026, 10, 1, 4, 40, tzinfo=UTC)

    record = deferred_document_evidence(claim, later, message, now, [])  # type: ignore[arg-type]

    assert record is not None
    assert record.kind == 'repair_quote' and record.status is EvidenceStatus.PENDING
    assert record.related_fields == []
    assert deferred_document_evidence(claim, later, message, now, [record]) is None  # type: ignore[arg-type]
    asked_now = SimpleNamespace(
        document_requests=(V8DocumentRequest(document_kind='repair_quote', from_party='claimant'),)
    )
    assert deferred_document_evidence(claim, asked_now, message, now, []) is None  # type: ignore[arg-type]
