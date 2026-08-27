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


def test_scenario_rejects_a_message_link_to_unknown_evidence(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['messages'][0]['evidence_refs'].append('evd_missing')
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='message evidence_ref'):
        load_scenario(invalid)


def test_scenario_rejects_a_handoff_link_to_unknown_policy_data(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['handoffs'][0]['packet']['source_refs'] = ['msg_at02_claimant_1']
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='sources must reference the policy retrieval'):
        load_scenario(invalid)


def test_scenario_rejects_a_policy_citation_for_another_policy(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['handoffs'][0]['packet']['policy_citation_refs'] = [
        'POL-OTHER: gradual damage exclusion'
    ]
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='policy citation must identify'):
        load_scenario(invalid)


def test_scenario_rejects_a_linked_graph_for_another_customer(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['linked_records']['customer_id'] = 'cus_other'
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='customer and claim identifiers'):
        load_scenario(invalid)


def test_scenario_rejects_duplicate_linked_record_identifiers(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['linked_records']['message_ids'].append(payload['linked_records']['message_ids'][0])
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='message identifiers must be unique'):
        load_scenario(invalid)


def test_scenario_rejects_duplicate_evidence_records(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['evidence'].append(payload['evidence'][0])
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='Scenario evidence identifiers must be unique'):
        load_scenario(invalid)


def test_scenario_rejects_duplicate_message_records(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['messages'].append(payload['messages'][0])
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='Scenario message identifiers must be unique'):
        load_scenario(invalid)


def test_scenario_rejects_a_reply_to_an_unknown_message(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['messages'][0]['in_reply_to'] = 'msg_missing'
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='in_reply_to'):
        load_scenario(invalid)


def test_scenario_rejects_a_handoff_from_an_unknown_message(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['handoffs'][0]['source_message_id'] = 'msg_missing'
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='source_message_id'):
        load_scenario(invalid)


def test_scenario_rejects_a_handoff_link_to_unknown_evidence(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['handoffs'][0]['packet']['evidence_refs'] = ['evd_missing']
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='handoff evidence_ref'):
        load_scenario(invalid)


def test_scenario_rejects_a_handoff_link_to_unknown_history_data(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['handoffs'][0]['packet']['history_evidence_refs'] = ['ret_missing']
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='history_evidence_ref'):
        load_scenario(invalid)


@pytest.mark.parametrize(
    ('field', 'value', 'message'),
    [
        (
            'evidence_ids',
            ['evd_fixture_at02_damage_photos'],
            'evidence identifiers must be complete',
        ),
        ('handoff_id', 'hnd_missing', 'handoff identifier must select'),
        ('message_ids', ['msg_at02_claimant_1'], 'message identifiers must be complete'),
    ],
)
def test_scenario_rejects_an_incomplete_linked_record_baseline(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['linked_records'][field] = value
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match=message):
        load_scenario(invalid)


def test_scenario_rejects_a_policy_fact_that_does_not_match_retrieval(
    tmp_path: Path,
) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['claim']['form']['policy.policy_number']['value'] = 'POL-MISMATCH'
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='policy fact must reference'):
        load_scenario(invalid)


def test_scenario_rejects_policy_provenance_without_a_source_ref(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['claim']['form']['policy.policy_number']['source_refs'] = []
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='declares policy provenance without a source_ref'):
        load_scenario(invalid)


def test_scenario_rejects_policy_provenance_that_cites_a_non_policy_retrieval(
    tmp_path: Path,
) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    payload['claim']['form']['policy.policy_number']['source_refs'] = ['ret_fixture_at02_history']
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='must reference a scenario policy retrieval record'):
        load_scenario(invalid)


def test_canonical_policy_fields_cite_a_policy_retrieval_record() -> None:
    scenario = load_scenario(CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json')
    policy_retrieval_ids = {
        record.retrieval_id for record in scenario.retrievals if record.kind.value == 'policy'
    }

    policy_fields = {
        code: fact for code, fact in scenario.claim.form.items() if fact.source.value == 'policy'
    }
    assert policy_fields
    for fact in policy_fields.values():
        assert fact.source_refs
        assert set(fact.source_refs) <= policy_retrieval_ids


def test_scenario_rejects_a_reply_that_crosses_the_interaction_session(tmp_path: Path) -> None:
    source = CANONICAL_SCENARIO_DIRECTORY / 'AT-08-resume.json'
    payload = json.loads(source.read_text(encoding='utf-8'))
    replying = next(
        message for message in payload['messages'] if message['message_id'] == 'msg_at08_agent'
    )
    assert replying['in_reply_to'] == 'msg_at08_claimant'
    replying['session_id'] = 'ses_fixture_at08_resume'
    invalid = tmp_path / source.name
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(
        ValueError,
        match='in_reply_to must reference a message in the same claim and session',
    ):
        load_scenario(invalid)
