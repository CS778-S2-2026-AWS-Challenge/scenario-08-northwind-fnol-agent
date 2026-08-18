import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.repositories.scenario_loader import (
    EvidenceLifecycleStage,
    load_evidence_lifecycle_fixtures,
)

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
