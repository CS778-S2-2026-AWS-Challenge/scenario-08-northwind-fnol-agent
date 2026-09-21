from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.model_gateway import ModelGatewayError, ModelGatewayErrorCode
from backend.domain.models import (
    ActorType,
    AgentAction,
    AgentProposalSource,
    CustomerNextStep,
    ProposedFormChange,
    RuntimeTraceRecord,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentProposal, AgentTurnContext, ControlledAgent


class ObservingGatewayFailure:
    def __init__(self, repository: FixtureRepository, failure: ModelGatewayErrorCode) -> None:
        self.repository = repository
        self.failure = failure
        self.fail = True
        self.calls = 0

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        self.calls += 1
        current = self.repository.get_claim(context.claim.claim_id, 'cus_demo')
        assert current is not None
        assert len(self.repository.list_handoffs(current.claim_id, 'cus_demo')) == 1
        assert current.revision == context.claim.revision
        if self.fail:
            assert current.form == {}
            assert current.contents_items == []
            raise ModelGatewayError(self.failure, retryable=True)
        timestamp = datetime.now(UTC)
        return AgentProposal(
            action=AgentAction.UPDATE,
            action_code='conversation.answer',
            reason_codes=['CONTEXT_RECORDED'],
            customer_reason='The location was recorded.',
            customer_response='I have recorded Symonds Street.',
            customer_next_step=CustomerNextStep(
                status='more_information_needed', summary='Continue.', responsible_party='claimant'
            ),
            form_changes=[
                ProposedFormChange(
                    field_code='incident.location',
                    value='Symonds Street',
                    source='claimant',
                    status='confirmed',
                    reported_text='Symonds Street',
                )
            ],
            state_changes=[],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=[],
            proposal_source=AgentProposalSource.MODEL_GATEWAY,
            runtime_trace=RuntimeTraceRecord(
                trace_id=f'trc_success_{self.calls}',
                claim_id=current.claim_id,
                session_id=context.session_id,
                model_profile_id=context.model_profile_id,
                trigger_message_id=context.trigger_message_id,
                invocations=[{'ordinal': 1, 'latency_ms': 1}],
                action_code='conversation.answer',
                runtime_action_code='runtime.continue',
                reason_codes=['CONTEXT_RECORDED'],
                model_invocations=1,
                status='succeeded',
                created_at=timestamp,
                finished_at=timestamp,
            ),
        )


@pytest.mark.parametrize(
    'failure', [ModelGatewayErrorCode.TIMEOUT, ModelGatewayErrorCode.MALFORMED_RESPONSE]
)
@pytest.mark.parametrize('text', ['A passenger is injured.', 'I want to speak to a person.'])
def test_safety_handoff_commits_before_failed_provider_and_followup_continues(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    failure: ModelGatewayErrorCode,
    text: str,
) -> None:
    gateway = ObservingGatewayFailure(repository, failure)
    app.state.agent_turn_provider = gateway

    def reject_fallback(*_args: object, **_kwargs: object) -> AgentProposal:
        raise AssertionError('A model failure must never fall back to ControlledAgent.')

    monkeypatch.setattr(ControlledAgent, 'propose_turn', reject_fallback)
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'safety-start'},
        json={'incident_type': 'motor'},
    ).json()
    claim_id, session_id = created['claim']['claim_id'], created['session']['session_id']
    url = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
    payload = {'client_message_id': 'safety-input', 'content': {'type': 'text', 'text': text}}
    headers = {**auth_headers, 'Idempotency-Key': 'safety-turn', 'If-Match': '1'}
    response = client.post(url, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['claim_revision'] == 3
    assert body['agent_message'] is not None
    assert body['agent_message']['recovery']['rule_id'] == 'claimant_turn.model_dependency_failure'
    assert 'Northwind support has been notified' in body['agent_message']['content']['text']
    assert body['handoff'] is not None
    if 'injured' in text:
        assert 'Your safety comes first' in body['agent_message']['content']['text']
    assert gateway.calls == 1
    assert repository.list_agent_decisions(claim_id, 'cus_demo') == []
    assert client.post(url, headers=headers, json=payload).json() == body
    assert gateway.calls == 1
    history = client.get(url, headers=auth_headers).json()['items']
    saved_input = next(item for item in history if item['actor'] == 'claimant')
    assert saved_input['recovery'] is not None
    gateway.fail = False
    followup = client.post(
        url,
        headers={**auth_headers, 'Idempotency-Key': 'safety-followup', 'If-Match': '3'},
        json={
            'client_message_id': 'safety-followup',
            'content': {'type': 'text', 'text': 'The incident happened on Symonds Street.'},
        },
    )
    assert followup.status_code == 200, followup.text
    current = repository.get_claim(claim_id, 'cus_demo')
    assert current is not None and current.form['incident.location'].value == 'Symonds Street'
    assert len(repository.list_handoffs(claim_id, 'cus_demo')) == 1
    assert gateway.calls == 2
    assert all(
        item.actor in {ActorType.CLAIMANT, ActorType.AGENT}
        for item in repository.list_messages(claim_id, session_id, 'cus_demo')
    )


def test_safety_commit_failure_is_hard_error_and_provider_is_never_called(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = ObservingGatewayFailure(repository, ModelGatewayErrorCode.TIMEOUT)
    app.state.agent_turn_provider = gateway
    created = client.post(
        '/api/v1/claims', headers={**auth_headers, 'Idempotency-Key': 'safety-fail-start'}, json={}
    ).json()
    claim_id, session_id = created['claim']['claim_id'], created['session']['session_id']

    def fail_commit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError('Synthetic handoff persistence failure.')

    monkeypatch.setattr(repository, 'save_handoff_mutation', fail_commit)
    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={**auth_headers, 'Idempotency-Key': 'safety-fail-turn', 'If-Match': '1'},
        json={
            'client_message_id': 'safety-fail',
            'content': {'type': 'text', 'text': 'A passenger is injured.'},
        },
    )
    assert response.status_code == 500
    assert response.json()['error']['code'] == 'SAFETY_HANDOFF_PERSISTENCE_FAILED'
    assert gateway.calls == 0
    messages = repository.list_messages(claim_id, session_id, 'cus_demo')
    assert len(messages) == 1 and messages[0].recovery_rule_id is None
