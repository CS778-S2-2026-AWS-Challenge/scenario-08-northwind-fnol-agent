import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.domain.models import (
    AgentAction,
    CustomerNextStep,
    ResponsibleParty,
    WorkflowState,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import RevisionConflict
from backend.repositories.scenario_loader import load_scenario, load_scenarios, seed_scenario
from scripts.run_scenarios import run_scenarios

SCENARIO_DIRECTORY = Path(__file__).parent / 'fixtures' / 'scenarios'
REPOSITORY_ROOT = Path(__file__).parents[1]


def scenario(name: str) -> tuple[FixtureRepository, str, str]:
    loaded = load_scenario(SCENARIO_DIRECTORY / f'{name}.json')
    repository = FixtureRepository()
    seed_scenario(repository, loaded)
    return repository, loaded.claim.claim_id, loaded.claim.active_session_id or ''


def client_for(repository: FixtureRepository) -> TestClient:
    return TestClient(create_app(Settings(), repository))


@pytest.mark.parametrize(
    'scenario_id',
    [
        'AT-01-clear-motor',
        'AT-02-coverage-ambiguity',
        'AT-04-urgent',
        'AT-05-human-request',
        'AT-06-pending-evidence',
        'AT-08-resume',
        'AT-12-signal-writeback',
    ],
)
def test_scenario_files_validate_and_seed(scenario_id: str) -> None:
    repository, claim_id, _ = scenario(scenario_id)

    claim = repository.get_claim(claim_id, 'cus_demo')

    assert claim is not None
    assert claim.claim_id == claim_id
    assert repository.get_active_session(claim_id, 'cus_demo') is not None


def test_scenario_runner_reports_repeatable_fixture_counts() -> None:
    results = run_scenarios(SCENARIO_DIRECTORY)

    assert [result.scenario_id for result in results] == [
        'AT-01-clear-motor',
        'AT-02-coverage-ambiguity',
        'AT-04-urgent',
        'AT-05-human-request',
        'AT-06-pending-evidence',
        'AT-08-resume',
        'AT-12-signal-writeback',
    ]
    assert {result.scenario_id: result.sessions for result in results} == {
        'AT-01-clear-motor': 1,
        'AT-02-coverage-ambiguity': 1,
        'AT-04-urgent': 1,
        'AT-05-human-request': 1,
        'AT-06-pending-evidence': 1,
        'AT-08-resume': 2,
        'AT-12-signal-writeback': 1,
    }
    assert next(result for result in results if result.scenario_id == 'AT-08-resume').evidence == 1
    assert {
        result.scenario_id: result.handoffs
        for result in results
        if result.scenario_id in {'AT-02-coverage-ambiguity', 'AT-04-urgent', 'AT-05-human-request'}
    } == {
        'AT-02-coverage-ambiguity': 1,
        'AT-04-urgent': 1,
        'AT-05-human-request': 1,
    }


def test_scenario_runner_is_directly_executable_from_repository_root() -> None:
    completed = subprocess.run(
        [sys.executable, 'scripts/run_scenarios.py'],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count('PASS AT-') == 7
    assert 'PASS AT-06-pending-evidence' in completed.stdout
    assert 'PASS AT-08-resume' in completed.stdout


def test_fast_and_pending_evidence_scenarios_use_claimant_safe_shared_state() -> None:
    fast_repository, fast_claim_id, _ = scenario('AT-01-clear-motor')
    pending_repository, pending_claim_id, _ = scenario('AT-06-pending-evidence')

    with client_for(fast_repository) as fast_client:
        fast = fast_client.get(
            f'/api/v1/claims/{fast_claim_id}',
            headers={'Authorization': 'Bearer synthetic-claimant'},
        )
    with client_for(pending_repository) as pending_client:
        pending = pending_client.get(
            f'/api/v1/claims/{pending_claim_id}',
            headers={'Authorization': 'Bearer synthetic-claimant'},
        )
        evidence = pending_client.get(
            f'/api/v1/claims/{pending_claim_id}/evidence',
            headers={'Authorization': 'Bearer synthetic-claimant'},
        )

    assert fast.status_code == 200
    assert fast.json()['workflow_state'] == 'ready_for_next'
    assert fast.json()['customer_next_step']['status'] == 'ready_to_create'
    assert pending.status_code == 200
    assert pending.json()['workflow_state'] == 'ready_for_next'
    assert pending.json()['evidence_summary']['pending'] == 1
    assert evidence.json()['items'][0]['status'] == 'pending_generation'
    assert 'provenance' not in evidence.json()['items'][0]


def test_ten_day_resume_restores_bounded_context_without_internal_notes() -> None:
    loaded = load_scenario(SCENARIO_DIRECTORY / 'AT-08-resume.json')
    repository = FixtureRepository()
    seed_scenario(repository, loaded)

    claim = repository.get_claim(loaded.claim.claim_id, 'cus_demo')
    sessions = repository.list_sessions_for_claim(loaded.claim.claim_id, 'cus_demo')
    active = next(item for item in sessions if item.status.value == 'active')
    historical = next(item for item in sessions if item.session_id != active.session_id)

    assert claim is not None
    assert repository.claim_count == 1
    assert len(sessions) == 2
    assert historical.status.value == 'paused'
    assert active.session_id == claim.active_session_id
    assert active.claim_id == historical.claim_id == claim.claim_id
    assert active.started_at - historical.last_active_at == timedelta(days=10)
    assert active.context_revision <= claim.revision
    assert historical.context_revision <= claim.revision
    assert active.summary == historical.summary
    assert active.unresolved_questions == historical.unresolved_questions
    assert active.pending_items == historical.pending_items
    assert active.prior_commitments == historical.prior_commitments

    with client_for(repository) as client:
        resumed = client.get(
            f'/api/v1/claims/{claim.claim_id}/sessions/{active.session_id}',
            headers={'Authorization': 'Bearer synthetic-claimant'},
        )
        messages = client.get(
            f'/api/v1/claims/{claim.claim_id}/sessions/{historical.session_id}/messages',
            headers={'Authorization': 'Bearer synthetic-claimant'},
        )

    assert resumed.status_code == 200
    body = resumed.json()
    assert body['session_id'] == active.session_id
    assert body['resume']['summary'].startswith('Rear-end collision')
    assert body['resume']['unresolved_questions'] == [
        'How should Northwind request the police report when it is ready?'
    ]
    assert body['resume']['pending_items'] == ['Police report expected after the original session.']
    assert body['resume']['prior_commitments'] == [
        'The police report can be added later without restarting the claim.'
    ]
    assert claim.form['incident.description'].status.value == 'confirmed'
    assert claim.form['incident.location'].status.value == 'confirmed'
    assert messages.status_code == 200
    assert len(messages.json()['items']) == 2
    assert all(item['actor'] != 'system' for item in messages.json()['items'])


def test_older_revision_cannot_overwrite_newer_claim_state() -> None:
    loaded = load_scenario(SCENARIO_DIRECTORY / 'AT-08-resume.json')
    repository = FixtureRepository()
    seed_scenario(repository, loaded)
    claim = repository.get_claim(loaded.claim.claim_id, 'cus_demo')
    assert claim is not None

    newer = claim.model_copy(update={'revision': claim.revision + 1, 'route': 'newer_state'})
    repository.save_claim(newer, expected_revision=claim.revision)

    stale = claim.model_copy(update={'revision': claim.revision + 1, 'route': 'stale_state'})
    with pytest.raises(RevisionConflict) as conflict:
        repository.save_claim(stale, expected_revision=claim.revision)

    assert conflict.value.current_revision == newer.revision
    stored = repository.get_claim(claim.claim_id, 'cus_demo')
    assert stored is not None
    assert stored.revision == newer.revision
    assert stored.route == 'newer_state'


def test_fixture_public_api_never_exposes_logical_storage_keys() -> None:
    repository, claim_id, session_id = scenario('AT-08-resume')
    auth = {'Authorization': 'Bearer synthetic-claimant'}

    with client_for(repository) as client:
        responses = [
            client.get(f'/api/v1/claims/{claim_id}', headers=auth),
            client.get(f'/api/v1/claims/{claim_id}/sessions/{session_id}', headers=auth),
            client.get(f'/api/v1/claims/{claim_id}/evidence', headers=auth),
            client.get(
                f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
                headers=auth,
            ),
        ]

    assert all(response.status_code == 200 for response in responses)
    public_payload = json.dumps([response.json() for response in responses])
    for private_token in (
        'CLAIM#',
        'SESSION#',
        'MESSAGE#',
        'EVIDENCE#',
        'internal_storage_state',
        'partition',
        'sort',
    ):
        assert private_token not in public_payload
    assert 'Storage object must not be requested' not in public_payload


def test_claimant_and_staff_projections_share_state_without_leaking_internal_signal() -> None:
    repository, claim_id, session_id = scenario('AT-12-signal-writeback')
    auth = {'Authorization': 'Bearer synthetic-claimant'}

    with client_for(repository) as client:
        claimant_change = client.patch(
            f'/api/v1/claims/{claim_id}/form',
            headers={**auth, 'If-Match': '6'},
            json={
                'updates': [
                    {
                        'field_code': 'incident.location',
                        'value': 'Synthetic Street, Auckland',
                        'status': 'confirmed',
                    }
                ]
            },
        )
        workbench_state = repository.get_claim(claim_id, 'cus_demo')
        assert workbench_state is not None
        assert workbench_state.form['incident.location'].value == 'Synthetic Street, Auckland'

        staff_next_step = CustomerNextStep(
            status='review_completed',
            summary='The professional review is complete and your claim can continue.',
            responsible_party=ResponsibleParty.NORTHWIND,
        )
        staff_state = workbench_state.model_copy(
            update={
                'revision': workbench_state.revision + 1,
                'updated_at': datetime(2026, 8, 12, 3, 30, tzinfo=UTC),
                'claim_state': workbench_state.claim_state.model_copy(
                    update={
                        'workflow_state': WorkflowState.READY_FOR_NEXT,
                        'next_action': AgentAction.PROCEED,
                    }
                ),
                'customer_next_step': staff_next_step,
            }
        )
        repository.save_claim(staff_state, expected_revision=workbench_state.revision)

        claimant_view = client.get(f'/api/v1/claims/{claim_id}', headers=auth)
        claimant_messages = client.get(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers=auth,
        )

    assert claimant_change.status_code == 200
    assert claimant_view.status_code == 200
    assert claimant_view.json()['revision'] == 8
    assert claimant_view.json()['workflow_state'] == 'ready_for_next'
    assert claimant_view.json()['customer_next_step']['status'] == 'review_completed'
    assert 'fraud_signal' not in claimant_view.json()
    assert len(claimant_messages.json()['items']) == 1
    assert 'HISTORY-REVIEW-01' not in claimant_messages.text


def test_loader_rejects_missing_active_session(tmp_path: Path) -> None:
    source = SCENARIO_DIRECTORY / 'AT-01-clear-motor.json'
    payload = source.read_text(encoding='utf-8').replace(
        '"active_session_id": "ses_fixture_at01"',
        '"active_session_id": "ses_missing"',
    )
    invalid = tmp_path / 'AT-99-invalid.json'
    invalid.write_text(payload.replace('AT-01-clear-motor', 'AT-99-invalid'), encoding='utf-8')

    with pytest.raises(ValueError, match='active session'):
        load_scenario(invalid)


@pytest.mark.parametrize(
    ('mutation', 'message'),
    [
        ('duplicate_session', 'identifiers must be unique'),
        ('wrong_customer', 'scenario claim and customer'),
        ('wrong_evidence_claim', 'evidence item'),
        ('wrong_message_session', 'message must belong'),
        ('multiple_active', 'exactly one active session'),
        ('active_session_mismatch', 'must identify the active session'),
        ('future_context_revision', 'context_revision cannot exceed'),
    ],
)
def test_loader_rejects_broken_record_links(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    payload = json.loads((SCENARIO_DIRECTORY / 'AT-08-resume.json').read_text(encoding='utf-8'))
    payload['scenario_id'] = 'AT-99-invalid'
    if mutation == 'duplicate_session':
        payload['sessions'].append(payload['sessions'][0])
    elif mutation == 'wrong_customer':
        payload['sessions'][0]['customer_id'] = 'cus_other'
    elif mutation == 'wrong_evidence_claim':
        payload['evidence'][0]['claim_id'] = 'clm_other'
    elif mutation == 'wrong_message_session':
        payload['messages'][0]['session_id'] = 'ses_other'
    elif mutation == 'multiple_active':
        payload['sessions'][0]['status'] = 'active'
    elif mutation == 'active_session_mismatch':
        payload['claim']['active_session_id'] = payload['sessions'][0]['session_id']
    else:
        payload['sessions'][0]['context_revision'] = payload['claim']['revision'] + 1
    invalid = tmp_path / 'AT-99-invalid.json'
    invalid.write_text(json.dumps(payload), encoding='utf-8')

    with pytest.raises(ValueError, match=message):
        load_scenario(invalid)


def test_fixture_directory_contains_only_valid_synthetic_scenarios() -> None:
    loaded = load_scenarios(SCENARIO_DIRECTORY)

    assert loaded
    assert all(item.claim.customer_id == 'cus_demo' for item in loaded)
    assert all('fixture' in item.claim.claim_id for item in loaded)
