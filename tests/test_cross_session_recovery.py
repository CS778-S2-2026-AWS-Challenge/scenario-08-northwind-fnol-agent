from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.models import (
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AuthorityOutcome,
    SessionStatus,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import load_scenario, seed_scenario

SCENARIO_DIRECTORY = Path(__file__).parents[1] / 'backend' / 'demo_data' / 'scenarios'
AUTH = {'Authorization': 'Bearer synthetic-claimant'}
DEVELOPER_SETTINGS = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)


def seeded_scenario(name: str) -> tuple[FixtureRepository, str, str]:
    loaded = load_scenario(SCENARIO_DIRECTORY / f'{name}.json')
    repository = FixtureRepository()
    seed_scenario(repository, loaded)
    return repository, loaded.claim.claim_id, loaded.claim.active_session_id or ''


def pause_active_session(
    repository: FixtureRepository,
    claim_id: str,
    session_id: str,
    *,
    clear_context: bool = False,
) -> None:
    claim = repository.get_claim(claim_id, 'cus_demo')
    session = repository.get_session(claim_id, session_id, 'cus_demo')
    assert claim is not None
    assert session is not None

    paused = session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            **(
                {
                    'summary': None,
                    'unresolved_questions': [],
                    'pending_items': [],
                    'prior_commitments': [],
                }
                if clear_context
                else {}
            ),
        }
    )
    repository.save_session(paused)
    # Pausing clears WorkingClaim.active_session_id, and
    # docs/claim-state-transaction-boundary.md reserves pointer changes for the
    # resume/start session mutation, so save_claim() correctly rejects it. No
    # production path performs a pause, so this is fixture seeding rather than a
    # repository operation.
    repository._claims[claim.claim_id] = claim.model_copy(
        update={
            'active_session_id': None,
            'revision': claim.revision + 1,
            'updated_at': claim.updated_at + timedelta(minutes=1),
        }
    )


def test_resume_uses_latest_persisted_context_without_duplication() -> None:
    repository, claim_id, active_session_id = seeded_scenario('AT-08-resume')
    source = repository.get_session(claim_id, active_session_id, 'cus_demo')
    assert source is not None
    pause_active_session(repository, claim_id, active_session_id)

    with TestClient(create_app(DEVELOPER_SETTINGS, repository)) as client:
        response = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**AUTH, 'Idempotency-Key': 'resume-at08-again'},
            json={'intent': 'resume'},
        )

    assert response.status_code == 201
    body = response.json()
    assert body['claim_id'] == claim_id
    assert body['session_id'] != active_session_id
    assert body['resume']['summary'] == source.summary
    assert body['resume']['unresolved_questions'] == source.unresolved_questions
    assert source.pending_items[0] in body['resume']['pending_items']
    assert source.prior_commitments[0] in body['resume']['prior_commitments']
    assert repository.claim_count == 1
    assert len(repository.list_sessions_for_claim(claim_id, 'cus_demo')) == 3


def test_resume_revision_baseline_is_atomic_and_idempotent() -> None:
    repository, claim_id, active_session_id = seeded_scenario('AT-08-resume')
    pause_active_session(repository, claim_id, active_session_id)
    before = repository.get_claim(claim_id, 'cus_demo')
    assert before is not None
    assert before.active_session_id is None
    sessions_before = repository.list_sessions_for_claim(claim_id, 'cus_demo')
    headers = {**AUTH, 'Idempotency-Key': 'resume-revision-baseline'}

    with TestClient(create_app(DEVELOPER_SETTINGS, repository)) as client:
        first = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers=headers,
            json={'intent': 'resume'},
        )
        replay = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers=headers,
            json={'intent': 'resume'},
        )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    body = first.json()
    resumed_session_id = body['session_id']
    assert isinstance(resumed_session_id, str)

    after = repository.get_claim(claim_id, 'cus_demo')
    resumed = repository.get_session(claim_id, resumed_session_id, 'cus_demo')
    sessions_after = repository.list_sessions_for_claim(claim_id, 'cus_demo')
    assert after is not None
    assert resumed is not None
    assert after.revision == before.revision + 1
    assert after.active_session_id == resumed_session_id
    assert resumed.context_revision == before.revision
    assert len(sessions_after) == len(sessions_before) + 1
    assert repository.claim_count == 1


def test_resume_rebuilds_pending_work_and_commitment_from_durable_records() -> None:
    repository, claim_id, active_session_id = seeded_scenario('AT-06-pending-evidence')
    pause_active_session(repository, claim_id, active_session_id, clear_context=True)
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None

    commitment = (
        'That is okay. I have recorded that the police report is expected later. '
        'It will not block the parts of your report that can safely continue now.'
    )
    repository.save_agent_decision(
        AgentDecisionRecord(
            decision_id='dec_at06_resume_source',
            claim_id=claim_id,
            session_id=active_session_id,
            trigger_message_id='msg_at06_pending',
            action=AgentAction.UPDATE,
            reason_codes=['EVIDENCE_PENDING_GENERATION'],
            customer_reason='The police report does not exist yet and is needed only later.',
            customer_response=commitment,
            state_changes=[],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=[],
            customer_next_step=claim.customer_next_step,
            authority=AgentAuthority(
                proposed_by='agent',
                validated_by='deterministic_rule_engine',
                outcome=AuthorityOutcome.AUTHORISED,
            ),
            form_changes={},
            resulting_revision=claim.revision,
            created_at=claim.updated_at,
        ),
        'cus_demo',
    )

    with TestClient(create_app(DEVELOPER_SETTINGS, repository)) as client:
        response = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**AUTH, 'Idempotency-Key': 'resume-at06-durable'},
            json={'intent': 'resume'},
        )

    assert response.status_code == 201
    body = response.json()
    assert body['claim_id'] == claim_id
    assert body['resume']['summary'] == claim.customer_next_step.summary
    assert 'Police said the report will be available next week.' in body['resume']['pending_items']
    assert commitment in body['resume']['prior_commitments']
    assert repository.claim_count == 1

    stored = repository.get_claim(claim_id, 'cus_demo')
    assert stored is not None
    assert stored.active_session_id == body['session_id']
    assert stored.revision == claim.revision + 1


def test_resume_uses_confirmed_description_when_session_summary_is_empty() -> None:
    repository, claim_id, active_session_id = seeded_scenario('AT-08-resume')
    pause_active_session(repository, claim_id, active_session_id, clear_context=True)
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    description = claim.form['incident.description'].value
    assert isinstance(description, str)

    with TestClient(create_app(DEVELOPER_SETTINGS, repository)) as client:
        response = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**AUTH, 'Idempotency-Key': 'resume-at08-description'},
            json={'intent': 'resume'},
        )

    assert response.status_code == 201
    assert response.json()['resume']['summary'] == description


def test_resume_rebuilds_question_and_generic_pending_item() -> None:
    repository, claim_id, active_session_id = seeded_scenario('AT-06-pending-evidence')
    pause_active_session(repository, claim_id, active_session_id, clear_context=True)
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None

    evidence = repository.list_evidence(claim_id, 'cus_demo')[0]
    evidence_without_note = evidence.model_copy(update={'claimant_note': None})
    repository.save_evidence(evidence_without_note, 'cus_demo')

    question = 'Please confirm the remaining claim detail before we continue.'
    repository.save_agent_decision(
        AgentDecisionRecord(
            decision_id='dec_at06_question_source',
            claim_id=claim_id,
            session_id=active_session_id,
            trigger_message_id='msg_at06_question',
            action=AgentAction.CLARIFY,
            reason_codes=['MISSING_REQUIRED_FIELD'],
            customer_reason=question,
            customer_response=question,
            state_changes=[],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=['remaining_claim_detail'],
            customer_next_step=claim.customer_next_step.model_copy(update={'summary': question}),
            authority=AgentAuthority(
                proposed_by='agent',
                validated_by='deterministic_rule_engine',
                outcome=AuthorityOutcome.AUTHORISED,
            ),
            form_changes={},
            resulting_revision=claim.revision,
            created_at=claim.updated_at,
        ),
        'cus_demo',
    )

    with TestClient(create_app(DEVELOPER_SETTINGS, repository)) as client:
        response = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**AUTH, 'Idempotency-Key': 'resume-at06-question'},
            json={'intent': 'resume'},
        )

    assert response.status_code == 201
    body = response.json()
    expected_pending = (
        f'{evidence.kind.replace("_", " ")}: {evidence.status.value.replace("_", " ")}.'
    )
    assert question in body['resume']['unresolved_questions']
    assert expected_pending in body['resume']['pending_items']
    assert body['resume']['prior_commitments'] == []
