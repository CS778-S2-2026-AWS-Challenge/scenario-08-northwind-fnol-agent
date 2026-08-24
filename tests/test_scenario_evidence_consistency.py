import json
from pathlib import Path

import pytest

from backend.repositories.scenario_loader import (
    CANONICAL_SCENARIO_DIRECTORY,
    load_scenario,
)

REPOSITORY_ROOT = Path(__file__).parents[1]
PROFESSIONAL_REVIEW_DIRECTORY = REPOSITORY_ROOT / 'tests' / 'fixtures' / 'professional_review'


def test_every_canonical_scenario_derives_evidence_state_and_summary() -> None:
    scenarios = [
        load_scenario(path) for path in sorted(CANONICAL_SCENARIO_DIRECTORY.glob('AT-*.json'))
    ]

    assert scenarios
    assert all(scenario.claim.claim_id for scenario in scenarios)


def test_professional_review_fixtures_obey_the_same_evidence_contract() -> None:
    scenarios = [
        load_scenario(path) for path in sorted(PROFESSIONAL_REVIEW_DIRECTORY.glob('AT-*.json'))
    ]

    assert scenarios
    for scenario in scenarios:
        if not scenario.evidence:
            assert scenario.claim.claim_state.evidence.value == 'not_started'
            assert scenario.claim.evidence_summary.model_dump() == {
                'received': 0,
                'pending': 0,
                'needs_attention': 0,
            }


def test_scenario_rejects_evidence_state_that_its_records_cannot_produce(
    tmp_path: Path,
) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-01-clear-motor.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['claim']['claim_state']['evidence'] = 'not_started'
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='claim_state.evidence must derive'):
        load_scenario(invalid)


def test_scenario_rejects_evidence_summary_that_its_records_cannot_produce(
    tmp_path: Path,
) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-01-clear-motor.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['claim']['evidence_summary']['received'] = 99
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='evidence_summary must derive'):
        load_scenario(invalid)
