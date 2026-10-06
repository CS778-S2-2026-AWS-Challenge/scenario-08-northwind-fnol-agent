"""Demo capture findings: incident time and chat photos, judged by the model."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.evidence import evidence_kind
from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import InvariantGuardedAgent
from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact


def test_incident_time_is_the_models_reading_checked_not_rewritten(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    worked_out = (
        (datetime.now(UTC) - timedelta(minutes=20))
        .astimezone(ZoneInfo('Pacific/Auckland'))
        .strftime('%Y-%m-%dT%H:%M%z')
    )
    worked_out = f'{worked_out[:-2]}:{worked_out[-2:]}'
    provider = V8JourneyProvider(
        [
            envelope(
                fields=[
                    fact('claim.product_family', 'motor', 'rear-ended'),
                    fact(
                        'incident.occurred_at',
                        worked_out,
                        'about 20 minutes ago',
                        precision='approximate',
                    ),
                ]
            ),
            # The model's own token is not stored; the claimant's words are.
            envelope(fields=[fact('incident.occurred_at', 'PT20M', 'just after lunch')]),
            envelope(fields=[fact('incident.occurred_at', 'current_approx', None)]),
        ]
    )
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'motor', 'relative-time')

    journey.send('Someone rear-ended me at the lights about 20 minutes ago.')
    claim = repository.get_claim(journey.claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None
    assert claim.form['incident.occurred_at'].value == worked_out
    assert 'reported_at_local' in (provider.gateway.requests[0].messages[-1].content or '')

    journey.send('Actually it was just after lunch.')
    claim = repository.get_claim(journey.claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None
    stored = claim.form['incident.occurred_at']
    assert stored.value == 'just after lunch'
    assert stored.precision.value == 'approximate'

    journey.send('Thanks.')
    claim = repository.get_claim(journey.claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None and claim.form['incident.occurred_at'].value == 'just after lunch'


def _evidence(kind: str, media_type: str | None) -> EvidenceRecord:
    created = datetime(2026, 10, 1, 4, 40, tzinfo=UTC)
    return EvidenceRecord(
        evidence_id=f'evd_{kind}',
        claim_id='clm_photo',
        kind=kind,
        media_type=media_type,
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        source=EvidenceSource.CLAIMANT,
        created_at=created,
        updated_at=created,
    )


def test_a_chat_file_counts_as_what_the_model_read_it_to_be() -> None:
    chat_photo = _evidence('other_document', 'image/jpeg')
    # Not yet read: Runtime does not guess from the media type.
    assert evidence_kind(chat_photo) == 'other_document'
    assert evidence_kind(chat_photo, {chat_photo.evidence_id: 'incident_photo'}) == (
        'incident_photo'
    )
    # A kind the claimant chose stands; an unregistered reading is ignored.
    quote = _evidence('repair_quote', 'image/png')
    assert evidence_kind(quote, {quote.evidence_id: 'incident_photo'}) == 'repair_quote'
    assert evidence_kind(chat_photo, {chat_photo.evidence_id: 'selfie'}) == 'other_document'
