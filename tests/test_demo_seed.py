from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import CANONICAL_SCENARIO_DIRECTORY, load_scenario
from backend.services.professional_reviews import (
    PROFESSIONAL_REVIEW_NEXT_STEP_STATUS,
    PROFESSIONAL_REVIEW_RESPONSIBLE_PARTY,
)

STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
DEVELOPER_SETTINGS = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)


def test_seed_scenarios_populates_handoff_review_and_created_routed_queues() -> None:
    scenario = load_scenario(CANONICAL_SCENARIO_DIRECTORY / 'AT-02-coverage-ambiguity.json')
    linked = scenario.linked_records
    assert linked is not None

    with TestClient(create_app(DEVELOPER_SETTINGS, FixtureRepository())) as client:
        seeded = client.post('/api/v1/workbench/demo/seed-scenarios', headers=STAFF_AUTH)
        assert seeded.status_code == 200
        body = seeded.json()
        assert body['status'] == 'seeded'
        assert set(body['scenario_ids']) == {
            'AT-02-coverage-ambiguity',
            'AT-04-urgent',
            'AT-05-human-request',
            'AT-06-pending-evidence',
            'AT-10-controlled-assessor',
        }
        assert len(body['claim_ids']) == 5

        pending = client.get('/api/v1/workbench/claims?view=awaiting_evidence', headers=STAFF_AUTH)
        assert pending.status_code == 200
        pending_items = pending.json()['items']
        assert [item['claim_id'] for item in pending_items] == ['clm_fixture_at06']
        assert pending_items[0]['pending_wait_types'] == [
            'claimant',
            'external_agency',
            'internal',
        ]

        listing = client.get('/api/v1/workbench/claims', headers=STAFF_AUTH)
        assert listing.status_code == 200
        items = {item['claim_id']: item for item in listing.json()['items']}
        assert set(body['claim_ids']) <= set(items)
        priorities = {items[claim_id]['priority'] for claim_id in body['claim_ids']}
        assert priorities == {'urgent', 'high', 'standard'}

        review_detail = client.get('/api/v1/workbench/claims/clm_fixture_at02', headers=STAFF_AUTH)
        assert review_detail.status_code == 200
        detail = review_detail.json()
        evidence = detail['evidence']
        assert [item['original_filename'] for item in evidence] == [
            'synthetic-ground-floor-water-damage.jpg',
            'synthetic-plumber-site-note.pdf',
            'synthetic-weather-history-capture.png',
        ]
        assert [item['status'] for item in evidence] == [
            'received',
            'received',
            'inconsistent',
        ]
        retrievals = {item['retrieval_id']: item for item in detail['retrievals']}
        assert set(retrievals) == {
            linked.policy_retrieval_id,
            linked.claim_history_retrieval_id,
        }
        assert retrievals[linked.policy_retrieval_id]['kind'] == 'policy'
        assert retrievals[linked.claim_history_retrieval_id]['kind'] == 'claim_history'
        assert detail['customer_reference'] == linked.customer_id
        assert detail['claim_id'] == linked.claim_id
        assert {item['evidence_id'] for item in evidence} == set(linked.evidence_ids)
        assert {item['message_id'] for item in detail['messages']} == set(linked.message_ids)
        assert [item['handoff_id'] for item in detail['handoffs']] == [linked.handoff_id]
        packet = detail['handoffs'][0]['packet']
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
        staff_policy_field = detail['form']['policy.policy_number']
        assert staff_policy_field['source'] == 'policy'
        assert staff_policy_field['source_refs'] == [linked.policy_retrieval_id]
        claimant_policy_field = claimant_claim.json()['form']['policy.policy_number']
        assert claimant_policy_field['source'] == 'policy'
        assert claimant_policy_field['value'] == staff_policy_field['value']
        assert claimant_policy_field['source_refs'] == []

        signals = detail['signals']
        assert [item['signal_id'] for item in signals] == [
            'sig_at02_policy_cause',
            'sig_at02_weather_date',
        ]
        assert all(item['status'] == 'review_required' for item in signals)


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
