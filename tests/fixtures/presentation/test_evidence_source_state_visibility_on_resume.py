"""Issue #144, the `bdfa123` half: evidence source, state, and visibility.

@jxu316-arch's half (PR #160) demonstrates session recovery and revision
behaviour against a single claimant-uploaded image. This is the independent
check and deliberately uses a different shape: the pending-evidence scenario,
which holds three records from three different sources.

A single-source claim cannot show whether resume preserves *which* source a
record came from, or whether the claimant/staff boundary survives the session
change. A mixed set can.
"""

from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.domain.evidence import evidence_state_for, evidence_summary_for
from backend.domain.models import EvidenceSource, SessionStatus
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import (
    CANONICAL_SCENARIO_DIRECTORY,
    load_scenarios,
    seed_scenario,
)

CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
SCENARIO_ID = 'AT-06-pending-evidence'
CUSTOMER_ID = 'cus_demo'


@pytest.fixture
def seeded() -> tuple[FixtureRepository, str]:
    scenario = next(
        item
        for item in load_scenarios(CANONICAL_SCENARIO_DIRECTORY)
        if item.scenario_id == SCENARIO_ID
    )
    repository = FixtureRepository()
    seed_scenario(repository, scenario)
    return repository, scenario.claim.claim_id


def pause_active_session(repository: FixtureRepository, claim_id: str) -> int:
    claim = repository.get_claim(claim_id, CUSTOMER_ID)
    assert claim is not None
    assert claim.active_session_id is not None
    session = repository.get_session(claim_id, claim.active_session_id, CUSTOMER_ID)
    assert session is not None

    repository.save_session(session.model_copy(update={'status': SessionStatus.PAUSED}))
    updated = claim.model_copy(
        update={
            'active_session_id': None,
            'revision': claim.revision + 1,
            'updated_at': claim.updated_at + timedelta(minutes=1),
        }
    )
    repository.save_claim(updated, expected_revision=claim.revision)
    return updated.revision


def evidence_snapshot(repository: FixtureRepository, claim_id: str) -> dict[str, dict[str, Any]]:
    return {
        record.evidence_id: record.model_dump(mode='json')
        for record in repository.list_evidence(claim_id, CUSTOMER_ID)
    }


def test_a_mixed_source_evidence_set_survives_resume_unchanged(
    seeded: tuple[FixtureRepository, str],
) -> None:
    """Source, state, and derived summary are identical either side of resume."""
    repository, claim_id = seeded
    records_before = repository.list_evidence(claim_id, CUSTOMER_ID)

    # The point of using this scenario: three records, three sources.
    assert {record.source for record in records_before} == {
        EvidenceSource.CLAIMANT,
        EvidenceSource.STAFF,
        EvidenceSource.EXTERNAL_SYSTEM,
    }

    before = evidence_snapshot(repository, claim_id)
    state_before = evidence_state_for(records_before)
    summary_before = evidence_summary_for(records_before)

    paused_revision = pause_active_session(repository, claim_id)
    app = create_app(Settings(), repository)
    with TestClient(app) as client:
        resumed = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**CLAIMANT_AUTH, 'Idempotency-Key': 'day5-mixed-source-resume'},
            json={'intent': 'resume'},
        )
    assert resumed.status_code == 201
    resumed_session_id = cast(dict[str, Any], resumed.json())['session_id']

    claim_after = repository.get_claim(claim_id, CUSTOMER_ID)
    records_after = repository.list_evidence(claim_id, CUSTOMER_ID)
    assert claim_after is not None
    assert claim_after.active_session_id == resumed_session_id
    assert claim_after.revision > paused_revision

    # Every record is byte-identical: resume neither rewrote nor recreated one.
    assert evidence_snapshot(repository, claim_id) == before
    assert {record.source for record in records_after} == {
        EvidenceSource.CLAIMANT,
        EvidenceSource.STAFF,
        EvidenceSource.EXTERNAL_SYSTEM,
    }

    # Derived state is recomputed from the records, so it must land identically.
    assert evidence_state_for(records_after) is state_before
    assert evidence_summary_for(records_after) == summary_before
    assert claim_after.claim_state.evidence is state_before
    assert claim_after.evidence_summary == summary_before


def test_internal_provenance_never_reaches_the_claimant_across_resume(
    seeded: tuple[FixtureRepository, str],
) -> None:
    """The field-level boundary holds before and after the session change.

    Each of the three records carries an `internal_note` in provenance. None of
    it may appear in a claimant response at either point.
    """
    repository, claim_id = seeded
    stored = repository.list_evidence(claim_id, CUSTOMER_ID)
    notes = [
        str(record.provenance['internal_note'])
        for record in stored
        if 'internal_note' in record.provenance
    ]
    assert len(notes) == 3

    app = create_app(Settings(), repository)
    with TestClient(app) as client:
        before = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH)
        pause_active_session(repository, claim_id)
        client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**CLAIMANT_AUTH, 'Idempotency-Key': 'day5-provenance-resume'},
            json={'intent': 'resume'},
        )
        after = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH)
        staff = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=STAFF_AUTH)

    assert before.status_code == 200
    assert after.status_code == 200
    for response in (before, after):
        assert 'provenance' not in response.json()['items'][0]
        for note in notes:
            assert note not in response.text

    # Staff keep the operational detail the claimant must not see.
    assert staff.status_code == 200
    staff_notes = [
        item['provenance'].get('internal_note')
        for item in staff.json()['evidence']
        if 'provenance' in item
    ]
    assert sorted(note for note in staff_notes if note) == sorted(notes)


def test_resume_does_not_widen_the_known_record_level_visibility_gap(
    seeded: tuple[FixtureRepository, str],
) -> None:
    """Records the claimant should not see are the same set before and after.

    `INTERNAL_EVIDENCE_VISIBLE_TO_CLAIMANT` in
    `docs/day4-evidence-visibility-defects.md` is open: `EvidenceRecord` has no
    visibility field, so the claimant list returns staff- and
    external-system-sourced records. That is a record-level gap owned by the
    evidence API and domain model.

    This asserts what Issue #144 is actually responsible for — that resume does
    not change the boundary — and pins the leak so a fix or a regression shows
    up here rather than passing quietly.
    """
    repository, claim_id = seeded
    internal_ids = {
        record.evidence_id
        for record in repository.list_evidence(claim_id, CUSTOMER_ID)
        if record.source is not EvidenceSource.CLAIMANT
    }
    assert internal_ids

    app = create_app(Settings(), repository)
    with TestClient(app) as client:
        before = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH)
        pause_active_session(repository, claim_id)
        client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**CLAIMANT_AUTH, 'Idempotency-Key': 'day5-visibility-resume'},
            json={'intent': 'resume'},
        )
        after = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH)

    visible_before = {item['evidence_id'] for item in before.json()['items']}
    visible_after = {item['evidence_id'] for item in after.json()['items']}

    assert visible_before == visible_after, 'resume changed which records the claimant sees'
    assert internal_ids <= visible_before, (
        'The recorded visibility gap no longer reproduces. Update '
        'docs/day4-evidence-visibility-defects.md and this test together.'
    )
