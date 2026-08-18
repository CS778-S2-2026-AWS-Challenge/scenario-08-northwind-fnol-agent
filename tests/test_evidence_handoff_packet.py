from pathlib import Path

import pytest

from backend.domain.models import EvidenceFileStatus, HandoffPacket, MessageVisibility
from backend.repositories.scenario_loader import (
    CANONICAL_SCENARIO_DIRECTORY,
    EvidencePathEntry,
    claimant_evidence_for,
    load_evidence_path_fixtures,
    load_scenario,
)
from backend.services.evidence_handoff import assemble_evidence_handoff_packet

FIXTURE_PATH = Path(__file__).parent / 'fixtures' / 'evidence' / 'path-entry-visibility.json'


def _assembled_packet(scenario_id: str) -> tuple[EvidencePathEntry, HandoffPacket]:
    fixture_set = load_evidence_path_fixtures(FIXTURE_PATH)
    entry = next(item for item in fixture_set.entries if item.scenario_id == scenario_id)
    scenario = load_scenario(CANONICAL_SCENARIO_DIRECTORY / f'{scenario_id}.json')
    assert len(scenario.handoffs) == 1
    packet = assemble_evidence_handoff_packet(
        scenario.handoffs[0].packet,
        scenario.claim.claim_id,
        (
            (fixture.evidence, MessageVisibility(fixture.visibility.value))
            for fixture in entry.evidence
        ),
    )
    return entry, packet


def test_human_and_urgent_handoff_packets_carry_evidence_state_and_visibility() -> None:
    for scenario_id in ('AT-04-urgent', 'AT-05-human-request'):
        entry, packet = _assembled_packet(scenario_id)

        assert packet.evidence_refs == [fixture.evidence.evidence_id for fixture in entry.evidence]
        assert [item.source.value for item in packet.evidence] == ['claimant']
        assert [item.status.value for item in packet.evidence] == ['received']
        assert [item.visibility.value for item in packet.evidence] == ['shared']
        assert packet.missing_items


def test_professional_review_packet_keeps_internal_evidence_for_staff_only() -> None:
    entry, packet = _assembled_packet('AT-02-coverage-ambiguity')

    staff_ids = {item.evidence_id for item in packet.evidence}
    internal_ids = {
        fixture.evidence.evidence_id
        for fixture in entry.evidence
        if fixture.visibility.value == 'internal_only'
    }
    claimant_ids = {item.evidence_id for item in claimant_evidence_for(entry)}

    assert staff_ids == {fixture.evidence.evidence_id for fixture in entry.evidence}
    assert internal_ids
    assert internal_ids.issubset(staff_ids)
    assert claimant_ids.isdisjoint(internal_ids)
    assert {item.visibility.value for item in packet.evidence} == {'shared', 'internal_only'}
    assert all('provenance' not in item.model_dump() for item in packet.evidence)


def test_pending_evidence_is_preserved_as_a_handoff_gap() -> None:
    fixture_set = load_evidence_path_fixtures(FIXTURE_PATH)
    entry = next(
        item for item in fixture_set.entries if item.scenario_id == 'AT-06-pending-evidence'
    )
    packet = assemble_evidence_handoff_packet(
        HandoffPacket(
            form_revision=1,
            promised_next_step='Wait for the pending evidence without restarting the report.',
        ),
        entry.claim_id,
        (
            (fixture.evidence, MessageVisibility(fixture.visibility.value))
            for fixture in entry.evidence
        ),
    )

    evidence_id = entry.evidence[0].evidence.evidence_id
    assert evidence_id in packet.evidence_refs
    assert evidence_id in packet.pending_items


def test_handoff_packet_rejects_evidence_from_another_claim() -> None:
    entry, packet = _assembled_packet('AT-05-human-request')
    evidence = entry.evidence[0].evidence.model_copy(update={'claim_id': 'clm_other'})

    with pytest.raises(
        ValueError,
        match='Every handoff evidence item must belong to the handoff claim',
    ):
        assemble_evidence_handoff_packet(
            packet,
            entry.claim_id,
            [(evidence, MessageVisibility.SHARED)],
        )


def test_processing_upload_remains_visible_as_pending_handoff_work() -> None:
    entry, packet = _assembled_packet('AT-05-human-request')
    evidence = entry.evidence[0].evidence.model_copy(
        update={'file_status': EvidenceFileStatus.PROCESSING}
    )

    assembled = assemble_evidence_handoff_packet(
        packet,
        entry.claim_id,
        [(evidence, MessageVisibility.SHARED)],
    )

    assert evidence.evidence_id in assembled.pending_items
