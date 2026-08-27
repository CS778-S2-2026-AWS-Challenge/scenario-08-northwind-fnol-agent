from datetime import timedelta

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.domain.models import SessionStatus
from backend.repositories.fixture import FixtureRepository

AUTH = {'Authorization': 'Bearer synthetic-claimant'}


def test_resume_drops_confirmation_question_after_fields_are_confirmed() -> None:
    repository = FixtureRepository()

    with TestClient(create_app(Settings(), repository)) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**AUTH, 'Idempotency-Key': 'resume-confirm-question-claim'},
            json={
                'channel': 'web_agent',
                'locale': 'en-NZ',
                'incident_type': 'motor',
            },
        )
        assert created.status_code == 201
        claim_id = created.json()['claim']['claim_id']
        session_id = created.json()['session']['session_id']

        turn = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **AUTH,
                'Idempotency-Key': 'resume-confirm-question-turn',
                'If-Match': '1',
            },
            json={
                'client_message_id': 'resume-confirm-question-message',
                'content': {
                    'type': 'text',
                    'text': 'A synthetic rear-end incident with no injuries.',
                },
                'evidence_refs': [],
            },
        )
        assert turn.status_code == 200
        assert turn.json()['claim_revision'] == 2

        decision = repository.list_agent_decisions(claim_id, 'cus_demo')[-1]
        requirements = decision.next_action_requirements
        assert requirements
        assert all(requirement.startswith('confirm:') for requirement in requirements)
        field_codes = [requirement.removeprefix('confirm:') for requirement in requirements]
        assert 'incident.description' in field_codes
        stale_question = decision.customer_next_step.summary
        unrelated_question = 'Please keep the remaining claim notes available.'

        source = repository.get_session(claim_id, session_id, 'cus_demo')
        assert source is not None
        assert source.context_revision == 2
        repository.save_session(
            source.model_copy(
                update={
                    'unresolved_questions': [stale_question, unrelated_question],
                }
            )
        )

        confirmed = client.post(
            f'/api/v1/claims/{claim_id}/form/confirmations',
            headers={
                **AUTH,
                'Idempotency-Key': 'resume-confirm-question-confirmation',
                'If-Match': '2',
            },
            json={'field_codes': field_codes},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()['revision'] == 3

        claim = repository.get_claim(claim_id, 'cus_demo')
        source = repository.get_session(claim_id, session_id, 'cus_demo')
        assert claim is not None
        assert source is not None
        assert all(claim.form[field_code].status.value == 'confirmed' for field_code in field_codes)
        assert claim.revision > source.context_revision

        paused_at = claim.updated_at + timedelta(minutes=1)
        repository.save_session(
            source.model_copy(
                update={
                    'status': SessionStatus.PAUSED,
                    'last_active_at': paused_at,
                }
            )
        )
        # Fixture seeding: pausing clears the active-session pointer, which
        # save_claim() correctly rejects under the transaction boundary.
        repository._claims[claim.claim_id] = claim.model_copy(
            update={
                'active_session_id': None,
                'revision': claim.revision + 1,
                'updated_at': paused_at,
            }
        )

        resumed = client.post(
            f'/api/v1/claims/{claim_id}/sessions',
            headers={**AUTH, 'Idempotency-Key': 'resume-confirm-question-resume'},
            json={'intent': 'resume'},
        )

    assert resumed.status_code == 201
    questions = resumed.json()['resume']['unresolved_questions']
    assert stale_question not in questions
    assert unrelated_question in questions
