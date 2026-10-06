from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.adapters.identity import FixtureIdentityRepository
from backend.app import create_app as _create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import (
    CANONICAL_SCENARIO_DIRECTORY,
    FixtureVisibility,
    load_evidence_path_fixtures,
    load_mvp_journey_scenarios,
    load_scenario,
    seed_scenario,
)
from backend.services.business_seed import load_business_seed
from backend.services.professional_reviews import (
    PROFESSIONAL_REVIEW_NEXT_STEP_STATUS,
    PROFESSIONAL_REVIEW_RESPONSIBLE_PARTY,
)

STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
PATH_FIXTURE = (
    CANONICAL_SCENARIO_DIRECTORY.parents[2]
    / 'tests'
    / 'fixtures'
    / 'evidence'
    / 'path-entry-visibility.json'
)
DEVELOPER_SETTINGS = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)


def create_app(*args: Any, **kwargs: Any) -> FastAPI:
    kwargs.setdefault(
        'identity_repository',
        FixtureIdentityRepository(load_business_seed(Path('config/business-seed.json'))),
    )
    app = _create_app(*args, **kwargs)
    if app.state.business_seed is None:
        app.state.business_seed = load_business_seed(Path('config/business-seed.json'))
    return app


@pytest.mark.parametrize('endpoint', ['seed-scenarios', 'seed-validation'])
def test_demo_routes_use_only_the_configured_business_seed(tmp_path: Path, endpoint: str) -> None:
    seed = load_business_seed(Path('config/business-seed.json'))
    seed.prior_submitted_claims = []
    seed.demo_cases = seed.demo_cases[:1]
    case = seed.demo_cases[0]
    case.case_id = 'case_a934dc28'
    case.fields['incident.description'].value = 'The side mirror was damaged in a car park.'
    selected_path = tmp_path / 'business.json'
    selected_path.write_text(seed.model_dump_json(), encoding='utf-8')
    settings = replace(DEVELOPER_SETTINGS, business_seed_path=str(selected_path))
    repository = FixtureRepository()
    with TestClient(create_app(settings, repository)) as client:
        response = client.post(
            f'/api/v1/workbench/demo/{endpoint}',
            headers={**STAFF_AUTH, 'Idempotency-Key': 'selected-manifest'},
        )
    assert response.status_code == 200, response.text
    assert response.json()['scenario_ids'] == [case.case_id]
    claims = repository.list_claims_internal()
    assert len(claims) == 1
    assert claims[0].customer_id == case.customer_id
    assert claims[0].form['incident.description'].value == case.fields['incident.description'].value
    assert claims[0].claim_id.startswith('clm_')
    assert 'fixture' not in claims[0].claim_id


@pytest.mark.parametrize('endpoint', ['seed-scenarios', 'seed-validation'])
@pytest.mark.parametrize('configured', [False, True])
def test_demo_seed_requires_an_explicit_business_seed(endpoint: str, configured: bool) -> None:
    repository = FixtureRepository()
    app = _create_app(DEVELOPER_SETTINGS, repository)
    if configured:
        seed = load_business_seed(Path('config/business-seed.json'))
        seed.demo_cases = []
        app.state.business_seed = seed
    with TestClient(app) as client:
        response = client.post(
            f'/api/v1/workbench/demo/{endpoint}',
            headers={**STAFF_AUTH, 'Idempotency-Key': 'missing-cases'},
        )
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'DEMO_CLAIMANT_UNAVAILABLE'
    assert ('no demo cases' if configured else 'business_seed_path') in response.json()['error'][
        'message'
    ]
    assert repository.list_claims_internal() == []


def test_regression_graphs_project_all_mvp_paths_and_created_routed_queue() -> None:
    scenario = load_scenario(CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json')
    linked = scenario.linked_records
    assert linked is not None

    repository = FixtureRepository()
    scenarios = [
        *load_mvp_journey_scenarios(),
        load_scenario(CANONICAL_SCENARIO_DIRECTORY / 'AT-10-controlled-assessor.json'),
    ]
    for graph in scenarios:
        seed_scenario(repository, graph)
    with TestClient(create_app(DEVELOPER_SETTINGS, repository)) as client:
        pending = client.get('/api/v1/workbench/claims?view=awaiting_evidence', headers=STAFF_AUTH)
        assert pending.status_code == 200
        pending_items = pending.json()['items']
        assert [item['claim_id'] for item in pending_items] == ['clm_fixture_at06']
        missing = pending_items[0]['work_summary']['missing_information']
        assert {item['responsible_party'] for item in missing} == {
            'claimant',
            'external_party',
            'claims_professional',
        }

        listing = client.get('/api/v1/workbench/claims', headers=STAFF_AUTH)
        assert listing.status_code == 200
        items = {item['claim_id']: item for item in listing.json()['items']}
        active_claim_ids = {graph.claim.claim_id for graph in scenarios} - {'clm_fixture_at10'}
        assert active_claim_ids <= set(items)
        assert 'clm_fixture_at10' not in items
        priorities = {
            items[claim_id]['priority_projection']['level'] for claim_id in active_claim_ids
        }
        assert priorities == {'urgent', 'high', 'standard'}

        completed = client.get('/api/v1/workbench/claims?view=completed', headers=STAFF_AUTH)
        assert [item['claim_id'] for item in completed.json()['items']] == ['clm_fixture_at10']
        completed_item = completed.json()['items'][0]
        assert completed_item['work_summary']['queue_key'] == 'completed'
        assert completed_item['terminal_disposition']['reason_code'] == 'CLAIM_CREATED'

        review_detail = client.get('/api/v1/workbench/claims/clm_fixture_at02', headers=STAFF_AUTH)
        assert review_detail.status_code == 200
        detail = review_detail.json()
        evidence = client.get(
            '/api/v1/workbench/claims/clm_fixture_at02/evidence', headers=STAFF_AUTH
        ).json()['items']
        assert [item['original_filename'] for item in evidence] == [
            'synthetic-ground-floor-water-damage.jpg',
            'synthetic-plumber-site-note.pdf',
            'synthetic-weather-history-capture.png',
        ]
        # The third record is contested, but a conflict is a reference now rather
        # than a status, and the claimant projection does not carry the other side.
        assert [item['status'] for item in evidence] == [
            'received',
            'received',
            'received',
        ]
        retrievals = {
            item['retrieval_id']: item
            for item in client.get(
                '/api/v1/workbench/claims/clm_fixture_at02/retrievals', headers=STAFF_AUTH
            ).json()['items']
        }
        assert set(retrievals) == {
            linked.policy_retrieval_id,
            linked.claim_history_retrieval_id,
        }
        assert retrievals[linked.policy_retrieval_id]['kind'] == 'policy'
        assert retrievals[linked.claim_history_retrieval_id]['kind'] == 'claim_history'
        assert detail['claimant']['customer_id'] == linked.customer_id
        assert detail['claim_id'] == linked.claim_id
        assert {item['evidence_id'] for item in evidence} == set(linked.evidence_ids)
        messages = client.get(
            f'/api/v1/workbench/claims/{linked.claim_id}/sessions/{scenario.claim.active_session_id}/messages',
            headers=STAFF_AUTH,
        ).json()['items']
        assert {item['message_id'] for item in messages} == set(linked.message_ids)
        handoffs = client.get(
            f'/api/v1/workbench/claims/{linked.claim_id}/handoffs', headers=STAFF_AUTH
        ).json()['items']
        assert [item['handoff_id'] for item in handoffs] == [linked.handoff_id]
        packet = handoffs[0]['packet']
        assert linked.policy_retrieval_id in packet['source_refs']
        assert packet['policy_citation_refs'] == [linked.policy_retrieval_id]
        assert packet['history_evidence_refs'] == [linked.claim_history_retrieval_id]
        assert set(packet['evidence_refs']) == set(linked.evidence_ids)

        claimant_claim = client.get(f'/api/v1/claims/{linked.claim_id}', headers=CLAIMANT_AUTH)
        claimant_messages = client.get(
            f'/api/v1/claims/{linked.claim_id}/sessions/{scenario.claim.active_session_id}/messages',
            headers=CLAIMANT_AUTH,
        )
        assert claimant_claim.status_code == 200
        assert claimant_messages.status_code == 200
        claimant_text = claimant_claim.text + claimant_messages.text
        assert linked.policy_retrieval_id not in claimant_text
        assert linked.claim_history_retrieval_id not in claimant_text
        assert retrievals[linked.claim_history_retrieval_id]['facts']['history_reference'] not in (
            claimant_text
        )

        # The policy fact keeps staff-side provenance without leaking the retrieval identifier
        # into the claimant projection.
        fields = client.get(
            f'/api/v1/workbench/claims/{linked.claim_id}/fields', headers=STAFF_AUTH
        ).json()['items']
        staff_policy_field = next(
            item['field'] for item in fields if item['code'] == 'policy.policy_number'
        )
        assert staff_policy_field['source'] == 'policy'
        assert staff_policy_field['source_refs'] == [linked.policy_retrieval_id]
        claimant_policy_field = claimant_claim.json()['form']['policy.policy_number']
        assert claimant_policy_field['source'] == 'policy'
        assert claimant_policy_field['value'] == staff_policy_field['value']
        assert claimant_policy_field['source_refs'] == []

        signals = client.get(
            f'/api/v1/workbench/claims/{linked.claim_id}/signals', headers=STAFF_AUTH
        ).json()['items']
        assert [item['signal_id'] for item in signals] == [
            'sig_at02_policy_cause',
            'sig_at02_weather_date',
        ]
        assert all(item['status'] == 'open' for item in signals)


def test_seeded_mvp_paths_use_canonical_records_and_role_safe_evidence() -> None:
    scenarios = load_mvp_journey_scenarios()
    visibility_entries = {
        entry.scenario_id: entry for entry in load_evidence_path_fixtures(PATH_FIXTURE).entries
    }

    repository = FixtureRepository()
    for scenario in scenarios:
        seed_scenario(repository, scenario)
    with TestClient(create_app(DEVELOPER_SETTINGS, repository)) as client:
        for scenario in scenarios:
            claim_id = scenario.claim.claim_id
            staff = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=STAFF_AUTH)
            claimant_claim = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT_AUTH)
            claimant_evidence = client.get(
                f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH
            )

            assert staff.status_code == 200
            assert claimant_claim.status_code == 200
            assert claimant_evidence.status_code == 200
            assert staff.json()['claim_state'] == scenario.claim.claim_state.model_dump(mode='json')
            assert claimant_claim.json()['workflow_state'] == (
                scenario.claim.claim_state.workflow_state.value
            )
            staff_evidence = client.get(
                f'/api/v1/workbench/claims/{claim_id}/evidence', headers=STAFF_AUTH
            ).json()['items']
            assert {item['evidence_id'] for item in staff_evidence} == {
                item.evidence_id for item in scenario.evidence
            }
            expected_claimant_ids = {
                fixture.evidence.evidence_id
                for fixture in visibility_entries[scenario.scenario_id].evidence
                if fixture.visibility is not FixtureVisibility.INTERNAL_ONLY
            }
            assert {
                item['evidence_id'] for item in claimant_evidence.json()['items']
            } == expected_claimant_ids


def test_seed_scenarios_rejects_non_staff_credentials() -> None:
    with TestClient(create_app(DEVELOPER_SETTINGS, FixtureRepository())) as client:
        response = client.post('/api/v1/workbench/demo/seed-scenarios', headers=CLAIMANT_AUTH)

    assert response.status_code == 403


def test_seed_scenarios_does_not_change_a_nonempty_queue() -> None:
    app = create_app(DEVELOPER_SETTINGS, FixtureRepository())
    app.state.business_seed = load_business_seed(Path('config/business-seed.json'))
    with TestClient(app) as client:
        assert (
            client.post('/api/v1/workbench/demo/seed-scenarios', headers=STAFF_AUTH).status_code
            == 200
        )
        response = client.post('/api/v1/workbench/demo/seed-scenarios', headers=STAFF_AUTH)

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'DEMO_SEED_REQUIRES_EMPTY_QUEUE'


def test_at02_next_step_matches_the_runtime_professional_review_contract() -> None:
    scenario = load_scenario(CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json')

    assert scenario.claim.customer_next_step.status == PROFESSIONAL_REVIEW_NEXT_STEP_STATUS
    assert (
        scenario.claim.customer_next_step.responsible_party is PROFESSIONAL_REVIEW_RESPONSIBLE_PARTY
    )
    assert scenario.expected['customer_status'] == PROFESSIONAL_REVIEW_NEXT_STEP_STATUS


def test_claimant_reads_seeded_professional_review_without_an_internal_handoff() -> None:
    repository = FixtureRepository()
    seed_scenario(
        repository, load_scenario(CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json')
    )
    with TestClient(create_app(DEVELOPER_SETTINGS, repository)) as client:
        response = client.get('/api/v1/claims/clm_fixture_at02', headers=CLAIMANT_AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body['handoff'] is None
    next_step = body['customer_next_step']
    assert next_step['status'] == PROFESSIONAL_REVIEW_NEXT_STEP_STATUS
    assert next_step['summary'] == (
        'A claims professional is reviewing the relevant information and policy wording before '
        'the claim can proceed.'
    )
    assert next_step['responsible_party'] == PROFESSIONAL_REVIEW_RESPONSIBLE_PARTY.value
    assert next_step['can_resume'] is True
    assert next_step['required_items'] == []
