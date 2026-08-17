from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import load_scenarios, seed_scenario
from scripts.run_scenarios import run_scenarios

FIXTURE_DIRECTORY = Path(__file__).parent / 'fixtures' / 'professional_review'


def test_professional_review_catalogue_covers_every_required_condition() -> None:
    scenarios = load_scenarios(FIXTURE_DIRECTORY)

    assert [scenario.scenario_id for scenario in scenarios] == [
        'AT-13-coverage-ambiguity',
        'AT-14-history-signal',
        'AT-15-conflicting-evidence',
        'AT-16-retrieval-unavailable',
    ]
    assert {scenario.expected['review_reason'] for scenario in scenarios} == {
        'COVERAGE_AMBIGUOUS',
        'RELEVANT_HISTORY_REVIEW',
        'EVIDENCE_CONFLICT',
        'RETRIEVAL_UNAVAILABLE',
    }
    for scenario in scenarios:
        assert scenario.expected['action'] == scenario.claim.claim_state.next_action.value
        assert scenario.expected['evidence_state'] == scenario.claim.claim_state.evidence.value
        assert scenario.expected['visibility'] == {
            'claimant_message_count': 1,
            'staff_message_count': 2,
            'internal_reason_hidden': True,
        }


def test_professional_review_scenarios_load_and_seed_repeatably_without_edits() -> None:
    first = run_scenarios(FIXTURE_DIRECTORY)
    second = run_scenarios(FIXTURE_DIRECTORY)

    assert first == second
    assert all(result.sessions == 1 for result in first)
    assert {result.scenario_id: result.evidence for result in first} == {
        'AT-13-coverage-ambiguity': 1,
        'AT-14-history-signal': 1,
        'AT-15-conflicting-evidence': 2,
        'AT-16-retrieval-unavailable': 0,
    }


def test_review_reasons_are_visible_to_staff_but_not_claimants() -> None:
    for scenario in load_scenarios(FIXTURE_DIRECTORY):
        repository = FixtureRepository()
        seed_scenario(repository, scenario)
        app = create_app(Settings(), repository)
        session_id = scenario.claim.active_session_id
        assert session_id is not None

        with TestClient(app) as client:
            claimant_messages = client.get(
                f'/api/v1/claims/{scenario.claim.claim_id}/sessions/{session_id}/messages',
                headers={'Authorization': 'Bearer synthetic-claimant'},
            )
            staff_detail = client.get(
                f'/api/v1/workbench/claims/{scenario.claim.claim_id}',
                headers={'Authorization': 'Bearer synthetic-staff'},
            )

        visibility = scenario.expected['visibility']
        review_reason = str(scenario.expected['review_reason'])
        assert claimant_messages.status_code == 200
        assert staff_detail.status_code == 200
        assert len(claimant_messages.json()['items']) == visibility['claimant_message_count']
        assert len(staff_detail.json()['messages']) == visibility['staff_message_count']
        assert review_reason not in claimant_messages.text
        assert review_reason in staff_detail.text
