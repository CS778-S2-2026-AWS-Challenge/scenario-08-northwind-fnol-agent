import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.repositories.scenario_loader import (
    CANONICAL_SCENARIO_DIRECTORY,
    EvidenceBusinessPath,
    FixtureVisibility,
    claimant_evidence_for,
    load_evidence_path_fixtures,
    load_mvp_journey_scenarios,
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


def test_mvp_journey_catalogue_uses_one_canonical_scenario_per_path() -> None:
    scenarios = load_mvp_journey_scenarios()
    actual: list[tuple[str, str]] = []
    for scenario in scenarios:
        assert scenario.business_path is not None
        actual.append((scenario.business_path.value, scenario.scenario_id))

    assert actual == [
        ('clear', 'AT-01-clear-motor'),
        ('pending', 'AT-06-pending-evidence'),
        ('urgent', 'AT-04-urgent'),
        ('professional_review', 'AT-02-coverage-ambiguity'),
        ('handoff', 'AT-05-human-request'),
    ]


def test_visibility_entries_are_exact_projections_of_canonical_evidence() -> None:
    fixture_set = load_evidence_path_fixtures(FIXTURE_PATH)

    for entry in fixture_set.entries:
        scenario = load_scenario(CANONICAL_SCENARIO_DIRECTORY / f'{entry.scenario_id}.json')

        assert entry.claim_id == scenario.claim.claim_id
        assert entry.claim_state == scenario.claim.claim_state
        assert entry.evidence_summary == scenario.claim.evidence_summary
        assert entry.customer_next_step == scenario.claim.customer_next_step
        assert entry.handoffs == scenario.handoffs
        assert [fixture.evidence for fixture in entry.evidence] == scenario.evidence


def test_visibility_source_contains_only_canonical_references_and_classification() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))

    for entry in payload['entries']:
        assert {
            'claim_id',
            'business_path',
            'claim_state',
            'customer_next_step',
            'evidence_summary',
            'handoffs',
        }.isdisjoint(entry)
        assert set(entry['entry_baseline']) == {
            'workflow_state',
            'next_action',
            'evidence_state',
            'customer_next_step_status',
            'responsible_party',
            'handoff',
        }
        for fixture in entry['evidence']:
            assert set(fixture) == {'fixture_id', 'visibility', 'evidence_id'}
            assert fixture['evidence_id']


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


def test_clear_path_uses_the_canonical_received_evidence_state() -> None:
    scenario = load_scenario(CANONICAL_SCENARIO_DIRECTORY / 'AT-01-clear-motor.json')
    fixture_set = load_evidence_path_fixtures(FIXTURE_PATH)
    clear_entry = next(
        entry for entry in fixture_set.entries if entry.business_path is EvidenceBusinessPath.CLEAR
    )

    assert scenario.claim.claim_state.evidence.value == 'received'
    assert scenario.claim.evidence_summary.received == 1
    assert clear_entry.claim_state == scenario.claim.claim_state
    assert clear_entry.evidence_summary == scenario.claim.evidence_summary
    assert clear_entry.evidence[0].evidence == scenario.evidence[0]


def test_entry_baselines_cover_the_current_scenario_actions_and_handoffs() -> None:
    fixture_set = load_evidence_path_fixtures(FIXTURE_PATH)

    actual = {
        entry.business_path.value: (
            entry.scenario_id,
            entry.entry_baseline.workflow_state.value,
            entry.entry_baseline.next_action.value,
            entry.entry_baseline.evidence_state.value,
            entry.entry_baseline.customer_next_step_status,
            entry.entry_baseline.responsible_party.value,
            None
            if entry.entry_baseline.handoff is None
            else (
                entry.entry_baseline.handoff.type.value,
                entry.entry_baseline.handoff.status.value,
                entry.entry_baseline.handoff.priority.value,
                entry.entry_baseline.handoff.queue,
                entry.entry_baseline.handoff.trigger.value,
            ),
        )
        for entry in fixture_set.entries
    }

    assert actual == {
        'clear': (
            'AT-01-clear-motor',
            'ready_for_next',
            'CREATE_CLAIM',
            'received',
            'ready_to_create',
            'system',
            None,
        ),
        'pending': (
            'AT-06-pending-evidence',
            'ready_for_next',
            'PROCEED',
            'pending',
            'continue_current_report',
            'claimant',
            None,
        ),
        'urgent': (
            'AT-04-urgent',
            'professional_review',
            'URGENT_HANDOFF',
            'received',
            'urgent_support_queued',
            'claims_professional',
            ('urgent_support', 'queued', 'urgent', 'urgent_support', 'urgent_safety_risk'),
        ),
        'professional_review': (
            'AT-02-coverage-ambiguity',
            'professional_review',
            'HANDOFF',
            'in_conflict',
            'professional_review_queued',
            'claims_professional',
            (
                'professional_review',
                'queued',
                'high',
                'professional_review',
                'professional_review_required',
            ),
        ),
        'handoff': (
            'AT-05-human-request',
            'professional_review',
            'HANDOFF',
            'received',
            'human_support_queued',
            'claims_professional',
            (
                'human_support',
                'queued',
                'standard',
                'claimant_support',
                'claimant_support_request',
            ),
        ),
    }


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


def test_visibility_loader_rejects_a_stale_entry_baseline(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    payload['entries'][0]['entry_baseline']['customer_next_step_status'] = 'stale_status'
    invalid = tmp_path / 'path-entry-visibility.json'
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='does not match its customer-status baseline'):
        load_evidence_path_fixtures(invalid)


def test_visibility_loader_rejects_a_misclassified_professional_review_handoff(
    tmp_path: Path,
) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    review = next(
        entry for entry in payload['entries'] if entry['scenario_id'] == 'AT-02-coverage-ambiguity'
    )
    review['entry_baseline']['handoff']['type'] = 'human_support'
    invalid = tmp_path / 'path-entry-visibility.json'
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='does not match its handoff baseline'):
        load_evidence_path_fixtures(invalid)


def test_mvp_journey_loader_rejects_a_duplicate_business_path(tmp_path: Path) -> None:
    for source in CANONICAL_SCENARIO_DIRECTORY.glob('AT-*.json'):
        payload = json.loads(source.read_text(encoding='utf-8'))
        if source.name == 'AT-06-pending-evidence.json':
            payload['business_path'] = 'clear'
        (tmp_path / source.name).write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='clear must identify exactly one'):
        load_mvp_journey_scenarios(tmp_path)


def test_mvp_journey_loader_rejects_a_missing_business_path(tmp_path: Path) -> None:
    for source in CANONICAL_SCENARIO_DIRECTORY.glob('AT-*.json'):
        payload = json.loads(source.read_text(encoding='utf-8'))
        if source.name == 'AT-06-pending-evidence.json':
            payload.pop('business_path')
        (tmp_path / source.name).write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match=r"missing: \['pending'\]"):
        load_mvp_journey_scenarios(tmp_path)


def test_visibility_loader_rejects_unknown_canonical_scenario(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    payload['entries'][0]['scenario_id'] = 'AT-99-unknown'
    invalid = tmp_path / 'path-entry-visibility.json'
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='Unknown canonical scenario: AT-99-unknown'):
        load_evidence_path_fixtures(invalid)


def test_visibility_loader_rejects_embedded_evidence_payload(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    payload['entries'][0]['evidence'][0]['evidence'] = {'kind': 'parallel-copy'}
    invalid = tmp_path / 'path-entry-visibility.json'
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='must derive from the canonical scenario'):
        load_evidence_path_fixtures(invalid)


def test_visibility_loader_rejects_unknown_evidence_reference(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    payload['entries'][0]['evidence'][0]['evidence_id'] = 'evd_not_in_scenario'
    invalid = tmp_path / 'path-entry-visibility.json'
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='is not present in the canonical scenario'):
        load_evidence_path_fixtures(invalid)


def test_visibility_loader_requires_complete_canonical_classification(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))
    review = next(
        entry for entry in payload['entries'] if entry['scenario_id'] == 'AT-02-coverage-ambiguity'
    )
    review['evidence'].pop()
    invalid = tmp_path / 'path-entry-visibility.json'
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match='classify the complete canonical evidence set'):
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
    assert 'PASS AT-01-clear-motor: path=clear' in completed.stdout
    assert 'action=CREATE_CLAIM' in completed.stdout
    assert 'handoff=professional_review:high:professional_review' in completed.stdout
