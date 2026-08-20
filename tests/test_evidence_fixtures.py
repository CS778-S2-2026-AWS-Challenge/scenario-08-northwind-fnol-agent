import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.domain.evidence import (
    EvidenceLifecycleStage,
    evidence_state_for,
    evidence_summary_for,
)
from backend.repositories.scenario_loader import load_evidence_lifecycle_fixtures

REPOSITORY_ROOT = Path(__file__).parents[1]
FIXTURE_PATH = REPOSITORY_ROOT / 'tests' / 'fixtures' / 'evidence' / 'evidence-lifecycle.json'


def test_evidence_lifecycle_catalogue_records_every_required_state() -> None:
    fixture_set = load_evidence_lifecycle_fixtures(FIXTURE_PATH)

    assert {fixture.lifecycle_stage for fixture in fixture_set.fixtures} == set(
        EvidenceLifecycleStage
    )
    assert all(fixture.evidence.source.value for fixture in fixture_set.fixtures)
    assert all(fixture.visibility.value for fixture in fixture_set.fixtures)
    assert all(fixture.next_requirement for fixture in fixture_set.fixtures)
    assert all(fixture.expected_state_change.trigger for fixture in fixture_set.fixtures)


def test_evidence_lifecycle_catalogue_loads_repeatably_without_edits() -> None:
    first = load_evidence_lifecycle_fixtures(FIXTURE_PATH)
    second = load_evidence_lifecycle_fixtures(FIXTURE_PATH)

    assert first == second
    assert [fixture.fixture_id for fixture in first.fixtures] == [
        'EV-01-pending-upload',
        'EV-02-unofficial-document',
        'EV-03-incomplete-document',
        'EV-04-not-yet-generated',
        'EV-05-received-image',
    ]


def test_evidence_lifecycle_loader_rejects_mismatched_contract_state(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    payload['fixtures'][0]['evidence']['file_status'] = 'ready'
    invalid = tmp_path / 'evidence-lifecycle.json'
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='pending fixture does not match'):
        load_evidence_lifecycle_fixtures(invalid)


def test_evidence_fixture_runner_is_directly_executable() -> None:
    completed = subprocess.run(
        [sys.executable, 'scripts/run_evidence_fixtures.py'],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count('PASS EV-') == 5
    assert 'PASS EV-04-not-yet-generated' in completed.stdout


def test_a_scenario_cannot_declare_evidence_state_its_records_contradict() -> None:
    """Guard against a scenario claiming evidence it does not hold.

    Path entries have been held to this since Issue #110. Canonical scenarios
    were not, and three of them declared a state or summary their own records
    could not produce: AT-02, AT-13, and AT-14 each claimed an evidence item
    while holding none.
    """
    from backend.repositories.scenario_loader import ScenarioFixture

    scenario = json.loads(
        (
            REPOSITORY_ROOT / 'backend' / 'demo_data' / 'scenarios' / 'AT-01-clear-motor.json'
        ).read_text(encoding='utf-8')
    )
    assert scenario['evidence'] == []

    overstated_summary = {
        **scenario,
        'claim': {
            **scenario['claim'],
            'evidence_summary': {'received': 1, 'pending': 0, 'needs_attention': 0},
        },
    }
    with pytest.raises(ValidationError, match='evidence_summary must derive'):
        ScenarioFixture.model_validate(overstated_summary)

    overstated_state = {
        **scenario,
        'claim': {
            **scenario['claim'],
            'claim_state': {**scenario['claim']['claim_state'], 'evidence': 'received'},
        },
    }
    with pytest.raises(ValidationError, match='claim_state.evidence must derive'):
        ScenarioFixture.model_validate(overstated_state)


def test_every_canonical_scenario_agrees_with_its_own_records() -> None:
    """Every scenario on disk passes the derivation guard."""
    from backend.repositories.scenario_loader import CANONICAL_SCENARIO_DIRECTORY, load_scenarios

    scenarios = load_scenarios(CANONICAL_SCENARIO_DIRECTORY)

    assert scenarios
    for scenario in scenarios:
        assert scenario.claim.claim_state.evidence is evidence_state_for(scenario.evidence)
        assert scenario.claim.evidence_summary == evidence_summary_for(scenario.evidence)
