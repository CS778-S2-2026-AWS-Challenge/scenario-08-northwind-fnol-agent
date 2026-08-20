import json
from pathlib import Path
from typing import Any, cast

FIXTURE_PATH = Path(__file__).parent / 'fixtures' / 'journeys' / 'AT-01-clear-motor-creation.json'
EXPECTED_STATES = ('describe', 'confirm', 'correct', 'proceed')
REQUIRED_FACT_KEYS = {'field_code', 'value', 'status', 'source'}


def _fixture() -> dict[str, Any]:
    loaded: object = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    assert isinstance(loaded, dict)
    return cast(dict[str, Any], loaded)


def test_clear_claim_baseline_fixture_is_repeatable_without_backend() -> None:
    first = _fixture()
    second = _fixture()

    assert first == second
    states = first['baseline_states']
    assert [state['name'] for state in states] == list(EXPECTED_STATES)

    for state in states:
        assert state['action']
        assert state['next_step']['status']
        assert state['next_step']['responsible_party']
        assert state['facts']
        for fact in state['facts']:
            assert fact.keys() >= REQUIRED_FACT_KEYS
            assert fact['field_code']
            assert fact['value']
            assert fact['status'] in {'proposed', 'confirmed'}
            assert fact['source'] in {'claimant', 'inference', 'image', 'document'}

    describe = states[0]['facts'][0]
    confirm = states[1]['facts'][0]
    correction = states[2]['facts'][0]
    assert describe['status'] == 'proposed'
    assert confirm['status'] == 'confirmed'
    assert correction['status'] == 'confirmed'
    assert correction['value'] != confirm['value']
    assert states[3]['next_step']['status'] == 'ready_to_create'
    assert all(fact['status'] == 'confirmed' for fact in states[3]['facts'])
