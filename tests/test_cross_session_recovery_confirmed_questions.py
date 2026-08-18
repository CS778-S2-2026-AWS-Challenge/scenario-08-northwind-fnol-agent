from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
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


def test_resume_drops_confirmation_question_after_field_is_confirmed() -> None:
    loaded = load_scenario(SCENARIO_DIRECTORY / 'AT-08-resume.json')
    repository = FixtureRepository()
    seed_scenario(repository, loaded)

    claim_id = loaded.claim.claim_id
    session_id = loaded.claim.active_session_id or ''
    claim = repository.get_claim(claim_id, 'cus_demo')
    session = repository.get_session(claim_id, session_id, 'cus_demo')
    assert claim is not None
    assert session is not None
    assert claim.form['incident.location'].status.value == 'confirmed'
    assert claim.revision > session.context_revision

    stale_question = 'Please confirm where the incident happened.'
    unrelated_question = 'How should Northwind request the police report when it is ready?'
    repository.save_session(
        session.model_copy(
            update={
                'status': SessionStatus.PAUSED,
                'unresolved_questions': [stale_question, unrelated_question],
            }
        )
    )
    repository.save_agent_decision(
        AgentDecisionRecord(
            decision_id='dec_at08_stale_location_confirmation',
            claim_id=claim_id,
            session_id=session_id,
            trigger_message_id='msg_at08_claimant',
            action=AgentAction.CONFIRM,
            reason_codes=['MATERIAL_FACTS_PROPOSED'],
            customer_reason=stale_question,
            customer_response=stale_question,
            state_changes=[],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=['confirm:incident.location'],
            customer_next_step=claim.customer_next_step.model_copy(
                update={'summary': stale_question}
            ),
            authority=AgentAuthority(
                proposed_by='agent',
                validated_by='deterministic_rule_engine',
                outcome=AuthorityOutcome.AUTHORISED,
            ),
            form_changes={},
            resulting_revision=session.context_revision,
            created_at=session.last_active_at,
        ),
        'cus_demo',
    )
    repository.save_claim(
        claim.model_copy(
            update={
                'active_session_id': None,
                'revision': claim.revision + 1,
                'updated_at': claim.updated_at + timedelta(minutes=1),
            }
        ),
        expected_revision=claim.revision,
    )

    with TestClient(create_app(Settings(), repository)) as client:
        response = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**AUTH, 'Idempotency-Key': 'resume-at08-confirmed-location'},
            json={'intent': 'resume'},
        )

    assert response.status_code == 201
    questions = response.json()['resume']['unresolved_questions']
    assert stale_question not in questions
    assert unrelated_question in questions
