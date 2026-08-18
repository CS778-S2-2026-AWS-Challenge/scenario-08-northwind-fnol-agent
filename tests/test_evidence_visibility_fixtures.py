import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.domain.evidence import evidence_state_for, evidence_summary_for
from backend.domain.models import EvidenceState
from backend.repositories.scenario_loader import (
    CANONICAL_SCENARIO_DIRECTORY,
    EvidenceBusinessPath,
    FixtureVisibility,
    claimant_evidence_for,
    load_evidence_path_fixtures,
    load_scenario,
)

REPOSITORY_ROOT = Path(__file__).parents[1]
FIXTURE_PATH = REPOSITORY_ROOT / 'tests' / 'fixtures' / 'evidence' / 'path-entry-visibility.json'


def test_visibility_catalogue_loads_all_five_path_entries() -> None:
    fixture_set = load_evidence_path_fixtures(FIXTURE_PATH)

    assert {entry.business_path for entry in fixture_set.entries} == set(EvidenceBusinessPath)
    assert [entry.scenario_id for entry in fixture_set.entries] == [
        'AT-01-clear-motor',
        'AT-02-coverage-ambiguity',
        'AT-04-urgent',
        'AT-05-human-request',
        'AT-06-pending-evidence',
    ]


def test_visibility_entries_derive_canonical_and_effective_evidence_state() -> None:
    fixture_set = load_evidence_path_fixtures(FIXTURE_PATH)

    for entry in fixture_set.entries:
        scenario = load_scenario(CANONICAL_SCENARIO_DIRECTORY / f'{entry.scenario_id}.json')

        assert entry.claim_id == scenario.claim.claim_id
        records = [fixture.evidence for fixture in entry.evidence]
        assert entry.claim_state == scenario.claim.claim_state.model_copy(
            update={'evidence': evidence_state_for(records)}
        )
        assert entry.evidence_summary == evidence_summary_for(records)
        assert entry.customer_next_step == scenario.claim.customer_next_step
        assert {fixture.evidence.claim_id for fixture in entry.evidence} == {
            scenario.claim.claim_id
        }


def test_visibility_source_does_not_duplicate_canonical_scenario_state() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))

    for entry in payload['entries']:
        assert {'claim_id', 'claim_state', 'customer_next_step', 'evidence_summary'}.isdisjoint(
            entry
        )
        assert all('claim_id' not in fixture['evidence'] for fixture in entry['evidence'])


def test_claimant_fixtures_exclude_internal_evidence_and_provenance() -> None:
    fixture_set = load_evidence_path_fixtures(FIXTURE_PATH)

    for entry in fixture_set.entries:
        internal_ids = {
            fixture.evidence.evidence_id
            for fixture in entry.evidence
            if fixture.visibility is FixtureVisibility.INTERNAL_ONLY
        }
        expected_claimant_ids = {
            fixture.evidence.evidence_id
            for fixture in entry.evidence
            if fixture.visibility is not FixtureVisibility.INTERNAL_ONLY
        }
        claimant_payload = [item.model_dump(mode='json') for item in claimant_evidence_for(entry)]
        claimant_ids = {item['evidence_id'] for item in claimant_payload}

        assert claimant_ids == expected_claimant_ids
        assert claimant_ids.isdisjoint(internal_ids)
        assert 'provenance' not in json.dumps(claimant_payload)


def test_visibility_catalogue_loads_repeatably_without_manual_edits() -> None:
    first = load_evidence_path_fixtures(FIXTURE_PATH)
    second = load_evidence_path_fixtures(FIXTURE_PATH)

    assert first == second
    assert all(entry.evidence for entry in first.entries)


def test_visibility_loader_corrects_canonical_not_started_state_from_evidence() -> None:
    scenario = load_scenario(CANONICAL_SCENARIO_DIRECTORY / 'AT-01-clear-motor.json')
    fixture_set = load_evidence_path_fixtures(FIXTURE_PATH)
    fast_entry = next(
        entry for entry in fixture_set.entries if entry.business_path is EvidenceBusinessPath.FAST
    )

    assert scenario.claim.claim_state.evidence is EvidenceState.NOT_STARTED
    assert fast_entry.claim_state.evidence is EvidenceState.RECEIVED
    assert fast_entry.evidence_summary.received == 1
    assert fast_entry.evidence_summary.pending == 0
    assert fast_entry.evidence_summary.needs_attention == 0


def test_visibility_loader_rejects_internal_only_catalogue(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    for entry in payload['entries']:
        for fixture in entry['evidence']:
            fixture['visibility'] = 'internal_only'
    invalid = tmp_path / 'path-entry-visibility.json'
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='every evidence visibility class'):
        load_evidence_path_fixtures(invalid)


def test_visibility_loader_rejects_duplicate_scenario_state(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    payload['entries'][0]['claim_id'] = 'clm_duplicate_source'
    invalid = tmp_path / 'path-entry-visibility.json'
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='derive canonical scenario fields: claim_id'):
        load_evidence_path_fixtures(invalid)


def test_visibility_loader_rejects_unknown_canonical_scenario(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    payload['entries'][0]['scenario_id'] = 'AT-99-unknown'
    invalid = tmp_path / 'path-entry-visibility.json'
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='Unknown canonical scenario: AT-99-unknown'):
        load_evidence_path_fixtures(invalid)


def test_evidence_visibility_runner_is_directly_executable() -> None:
    completed = subprocess.run(
        [sys.executable, 'scripts/run_evidence_visibility_fixtures.py'],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count('PASS AT-') == 5
    assert 'PASS AT-04-urgent' in completed.stdout
