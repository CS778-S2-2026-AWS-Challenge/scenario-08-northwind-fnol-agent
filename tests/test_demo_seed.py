from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import (
    CANONICAL_SCENARIO_DIRECTORY,
    FixtureVisibility,
    load_evidence_path_fixtures,
    load_mvp_journey_scenarios,
    load_scenario,
)
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


def test_seed_scenarios_populates_all_mvp_paths_and_created_routed_queue() -> None:
    scenario = load_scenario(CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json')
    linked = scenario.linked_records
    assert linked is not None

    with TestClient(create_app(DEVELOPER_SETTINGS, FixtureRepository())) as client:
        seeded = client.post('/api/v1/workbench/demo/seed-scenarios', headers=STAFF_AUTH)
        assert seeded.status_code == 200
        body = seeded.json()
        assert body['status'] == 'seeded'
        assert body['scenario_ids'] == [
            'AT-01-clear-motor',
            'AT-06-pending-evidence',
            'AT-04-urgent',
            'AT-02-coverage-ambiguity',
            'AT-05-human-request',
            'AT-10-controlled-assessor',
        ]
        assert len(body['claim_ids']) == 6

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
        assert set(body['claim_ids']) <= set(items)
        priorities = {
            items[claim_id]['priority_projection']['level'] for claim_id in body['claim_ids']
        }
        assert priorities == {'urgent', 'high', 'standard'}

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
        assert (
            retrievals[linked.policy_retrieval_id]['facts']['policy_reference']
            in (packet['policy_citation_refs'][0])
        )
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

    with TestClient(create_app(DEVELOPER_SETTINGS, FixtureRepository())) as client:
        seeded = client.post('/api/v1/workbench/demo/seed-scenarios', headers=STAFF_AUTH)
        assert seeded.status_code == 200

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
    with TestClient(create_app(DEVELOPER_SETTINGS, FixtureRepository())) as client:
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
    with TestClient(create_app(DEVELOPER_SETTINGS, FixtureRepository())) as client:
        seeded = client.post('/api/v1/workbench/demo/seed-scenarios', headers=STAFF_AUTH)
        assert seeded.status_code == 200

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
