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
    EvidenceFileStatus,
    EvidenceStatus,
    SessionStatus,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import load_scenario, seed_scenario

SCENARIO_DIRECTORY = Path(__file__).parents[1] / 'backend' / 'demo_data' / 'scenarios'
AUTH = {'Authorization': 'Bearer synthetic-claimant'}


def test_resume_drops_resolved_evidence_pending_context() -> None:
    loaded = load_scenario(SCENARIO_DIRECTORY / 'AT-06-pending-evidence.json')
    repository = FixtureRepository()
    seed_scenario(repository, loaded)

    claim_id = loaded.claim.claim_id
    session_id = loaded.claim.active_session_id or ''
    claim = repository.get_claim(claim_id, 'cus_demo')
    session = repository.get_session(claim_id, session_id, 'cus_demo')
    evidence = repository.list_evidence(claim_id, 'cus_demo')[0]
    assert claim is not None
    assert session is not None

    commitment = (
        'That is okay. I have recorded that the police report is expected later. '
        'It will not block the parts of your report that can safely continue now.'
    )
    repository.save_agent_decision(
        AgentDecisionRecord(
            decision_id='dec_at06_resolved_resume_source',
            claim_id=claim_id,
            session_id=session_id,
            trigger_message_id='msg_at06_pending',
            action=AgentAction.UPDATE,
            reason_codes=['EVIDENCE_PENDING_GENERATION'],
            customer_reason='The police report is expected later.',
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

    paused_at = claim.updated_at + timedelta(minutes=1)
    repository.save_session(
        session.model_copy(update={'status': SessionStatus.PAUSED, 'last_active_at': paused_at})
    )
    repository.save_claim(
        claim.model_copy(
            update={
                'active_session_id': None,
                'revision': claim.revision + 1,
                'updated_at': paused_at,
            }
        ),
        expected_revision=claim.revision,
    )
    repository.save_evidence(
        evidence.model_copy(
            update={
                'status': EvidenceStatus.RECEIVED,
                'file_status': EvidenceFileStatus.READY,
                'updated_at': paused_at + timedelta(minutes=1),
            }
        ),
        'cus_demo',
    )

    with TestClient(create_app(Settings(), repository)) as client:
        response = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**AUTH, 'Idempotency-Key': 'resume-at06-after-ready'},
            json={'intent': 'resume'},
        )

    assert response.status_code == 201
    resume = response.json()['resume']
    assert resume['pending_items'] == []
    assert resume['prior_commitments'] == []
    assert commitment not in resume['prior_commitments']
    assert session.pending_items[0] not in resume['pending_items']
    assert session.prior_commitments[0] not in resume['prior_commitments']
