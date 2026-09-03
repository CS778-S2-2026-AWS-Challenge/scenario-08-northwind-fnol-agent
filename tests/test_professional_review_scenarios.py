from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
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
        assert scenario.expected['visibility']['claimant_message_count'] == 1
        assert scenario.expected['visibility']['internal_reason_hidden'] is True


def test_professional_review_scenarios_load_and_seed_repeatably_without_edits() -> None:
    first = run_scenarios(FIXTURE_DIRECTORY)
    second = run_scenarios(FIXTURE_DIRECTORY)

    assert first == second
    assert all(result.sessions == 1 for result in first)
    assert {result.scenario_id: result.evidence for result in first} == {
        'AT-13-coverage-ambiguity': 0,
        'AT-14-history-signal': 0,
        'AT-15-conflicting-evidence': 2,
        'AT-16-retrieval-unavailable': 0,
    }
    assert {result.scenario_id: result.retrievals for result in first} == {
        'AT-13-coverage-ambiguity': 1,
        'AT-14-history-signal': 1,
        'AT-15-conflicting-evidence': 0,
        # An unavailable provider returns no facts, so there is no retrieval
        # record and no signal derived from one. The review reason travels on
        # the handoff instead.
        'AT-16-retrieval-unavailable': 0,
    }
    assert {result.scenario_id: result.review_signals for result in first} == {
        'AT-13-coverage-ambiguity': 1,
        'AT-14-history-signal': 1,
        'AT-15-conflicting-evidence': 0,
        'AT-16-retrieval-unavailable': 0,
    }


def test_review_reasons_are_visible_to_staff_but_not_claimants() -> None:
    for scenario in load_scenarios(FIXTURE_DIRECTORY):
        repository = FixtureRepository()
        seed_scenario(repository, scenario)
        app = create_app(
            Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
            repository,
        )
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
            staff_messages = client.get(
                f'/api/v1/workbench/claims/{scenario.claim.claim_id}/sessions/{session_id}/messages',
                headers={'Authorization': 'Bearer synthetic-staff'},
            )

        visibility = scenario.expected['visibility']
        review_reason = str(scenario.expected['review_reason'])
        review_signals = repository.list_review_signals(
            scenario.claim.claim_id,
            scenario.claim.customer_id,
        )
        assert claimant_messages.status_code == 200
        assert staff_detail.status_code == 200
        assert len(claimant_messages.json()['items']) == visibility['claimant_message_count']
        assert staff_messages.status_code == 200
        assert len(staff_messages.json()['items']) == visibility['staff_message_count']
        assert len(review_signals) == visibility['staff_review_signal_count']
        assert review_reason not in claimant_messages.text
        staff_signals = client.get(
            f'/api/v1/workbench/claims/{scenario.claim.claim_id}/signals',
            headers={'Authorization': 'Bearer synthetic-staff'},
        )
        staff_handoffs = client.get(
            f'/api/v1/workbench/claims/{scenario.claim.claim_id}/handoffs',
            headers={'Authorization': 'Bearer synthetic-staff'},
        )
        assert (
            review_reason in staff_messages.text
            or review_reason in staff_signals.text
            or review_reason in staff_handoffs.text
            or any(review_reason in signal.reason_codes for signal in review_signals)
        )
        for retrieval in scenario.retrievals:
            assert retrieval.retrieval_id not in claimant_messages.text
            assert retrieval.source.reference not in claimant_messages.text


def test_an_unavailable_provider_persists_no_retrieval_evidence() -> None:
    """An outage must not be recorded as a sourced retrieval finding.

    The runtime contract for `POST /internal/v1/policy/search` returns
    `unavailable` with limitations only: no source, no facts, nothing
    persisted. A fixture that stored a placeholder record with a synthetic
    source would validate behaviour the API forbids, and would teach the
    Workbench to read an outage as evidence.
    """
    unavailable = [
        scenario
        for scenario in load_scenarios(FIXTURE_DIRECTORY)
        if scenario.expected.get('unavailable_provider') is True
    ]
    assert [scenario.scenario_id for scenario in unavailable] == ['AT-16-retrieval-unavailable']

    for scenario in unavailable:
        assert scenario.retrievals == []

        repository = FixtureRepository()
        seed_scenario(repository, scenario)
        claim_id = scenario.claim.claim_id
        customer_id = scenario.claim.customer_id

        assert repository.list_retrieval_records(claim_id, customer_id) == []
        assert repository.list_review_signals(claim_id, customer_id) == []

        # The review reason still reaches staff, carried by the handoff that
        # routed the claim, rather than by invented evidence.
        handoffs = repository.list_handoffs(claim_id, customer_id)
        assert len(handoffs) == 1
        assert scenario.expected['review_reason'] in handoffs[0].reason_codes
        assert handoffs[0].trigger.value == 'professional_review_required'
