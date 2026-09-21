from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.model_gateway import ModelGatewayError, ModelGatewayErrorCode
from backend.domain.models import ActorType, AgentAction, CustomerNextStep
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentProposal, AgentTurnContext


class CheckpointAgent:
    def __init__(self, repository: FixtureRepository) -> None:
        self.repository = repository
        self.calls = 0
        self.fail = True
        self.before_reply: Callable[[AgentTurnContext], None] | None = None
        self.confirms_batch = False

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        self.calls += 1
        messages = self.repository.list_messages(
            context.claim.claim_id, context.session_id, 'cus_demo'
        )
        assert any(item.message_id == context.trigger_message_id for item in messages)
        if self.fail:
            raise ModelGatewayError(ModelGatewayErrorCode.TIMEOUT, retryable=True)
        if self.before_reply:
            self.before_reply(context)
        return AgentProposal(
            action=AgentAction.UPDATE,
            reason_codes=['CONTEXT_RECORDED'],
            customer_reason='Your message was saved.',
            customer_response='Thanks. Your message is saved.',
            customer_next_step=CustomerNextStep(
                status='more_information_needed',
                summary='Continue describing the incident.',
                responsible_party='claimant',
            ),
            form_changes=[],
            state_changes=[],
            proposed_signals=[],
            required_tools=[],
            next_action_requirements=[],
            confirms_batch=self.confirms_batch,
        )


def test_provider_failure_is_saved_before_call_and_explicit_retry_reuses_inbound(
    app: FastAPI, client: TestClient, repository: FixtureRepository, auth_headers: dict[str, str]
) -> None:
    agent = CheckpointAgent(repository)
    app.state.agent_turn_provider = agent
    created = client.post(
        '/api/v1/claims', headers={**auth_headers, 'Idempotency-Key': 'checkpoint-create'}, json={}
    ).json()
    claim_id, session_id = created['claim']['claim_id'], created['session']['session_id']
    url = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
    payload = {
        'client_message_id': 'saved-input',
        'content': {'type': 'text', 'text': 'My rear bumper was damaged.'},
        'evidence_refs': [],
    }
    first = client.post(
        url, headers={**auth_headers, 'Idempotency-Key': 'attempt-1', 'If-Match': '1'}, json=payload
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body['agent_message'] is None
    assert body['claim_revision'] == 2
    assert body['recovery']['resume_entrypoint'] == 'submit_message'
    replay = client.post(
        url, headers={**auth_headers, 'Idempotency-Key': 'attempt-1', 'If-Match': '1'}, json=payload
    )
    assert replay.json() == body
    assert agent.calls == 1
    agent.fail = False
    retry = client.post(
        url, headers={**auth_headers, 'Idempotency-Key': 'attempt-2', 'If-Match': '2'}, json=payload
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()['agent_message'] is not None
    assert retry.json()['claim_revision'] == 3
    inbound = [
        item
        for item in repository.list_messages(claim_id, session_id, 'cus_demo')
        if item.actor is ActorType.CLAIMANT
    ]
    assert len(inbound) == 1
    assert inbound[0].message_id == body['claimant_message']['message_id']
    checkpoint = repository.find_message_checkpoint(claim_id, inbound[0].message_id, 'cus_demo')
    assert checkpoint is not None
    assert checkpoint.revision_before_message == 1
    assert agent.calls == 2


def test_provider_result_cannot_overwrite_concurrent_mutation(
    app: FastAPI, client: TestClient, repository: FixtureRepository, auth_headers: dict[str, str]
) -> None:
    agent = CheckpointAgent(repository)
    agent.fail = False
    app.state.agent_turn_provider = agent
    created = client.post(
        '/api/v1/claims', headers={**auth_headers, 'Idempotency-Key': 'concurrent-create'}, json={}
    ).json()
    claim_id, session_id = created['claim']['claim_id'], created['session']['session_id']

    def concurrent_update(context: AgentTurnContext) -> None:
        current = repository.get_claim(claim_id, 'cus_demo')
        assert current is not None
        repository.save_claim(
            current.model_copy(update={'revision': current.revision + 1}),
            expected_revision=current.revision,
        )

    agent.before_reply = concurrent_update
    response = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={**auth_headers, 'Idempotency-Key': 'concurrent-turn', 'If-Match': '1'},
        json={
            'client_message_id': 'concurrent-input',
            'content': {'type': 'text', 'text': 'My car is damaged.'},
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'REVISION_CONFLICT'
    assert len(repository.list_messages(claim_id, session_id, 'cus_demo')) == 1
    replay = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={**auth_headers, 'Idempotency-Key': 'concurrent-turn', 'If-Match': '1'},
        json={
            'client_message_id': 'concurrent-input',
            'content': {'type': 'text', 'text': 'My car is damaged.'},
        },
    )
    assert replay.status_code == 409
    assert replay.json()['error']['code'] == 'REVISION_CONFLICT'
    assert agent.calls == 1
    agent.before_reply = None
    resumed = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
        headers={**auth_headers, 'Idempotency-Key': 'concurrent-retry', 'If-Match': '3'},
        json={
            'client_message_id': 'concurrent-input',
            'content': {'type': 'text', 'text': 'My car is damaged.'},
        },
    )
    assert resumed.status_code == 200, resumed.text
    assert (
        len(
            [
                item
                for item in repository.list_messages(claim_id, session_id, 'cus_demo')
                if item.actor is ActorType.CLAIMANT
            ]
        )
        == 1
    )


def test_retry_does_not_revive_confirmation_after_an_intervening_mutation(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from backend.domain.models import ConfirmationRequestRecord, FormStatus, StructuredFormField
    from backend.domain.runtime import RuntimeWorkItemRecord
    from backend.services.turn_reducer import shown_values_fingerprint

    agent = CheckpointAgent(repository)
    agent.confirms_batch = True
    app.state.agent_turn_provider = agent
    created = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'stale-confirm-create'},
        json={},
    ).json()
    claim_id, session_id = created['claim']['claim_id'], created['session']['session_id']
    claim = repository.get_claim(claim_id, 'cus_demo')
    assert claim is not None
    timestamp = datetime.now(UTC)
    fields = {
        'incident.location': StructuredFormField(
            value='Symonds Street',
            source='inference',
            status='proposed',
            needed_for='current_action',
            updated_at=timestamp,
            updated_by={'actor_type': 'agent', 'actor_id': 'test-model'},
        )
    }
    claim = claim.model_copy(
        update={
            'revision': 2,
            'form': fields,
            'customer_next_step': CustomerNextStep(
                status='confirmation_requested',
                summary='Confirm Symonds Street.',
                responsible_party='claimant',
            ),
        }
    )
    repository.save_claim(claim, expected_revision=1)
    shown = ConfirmationRequestRecord(
        confirmation_id='cnf_retry',
        claim_id=claim_id,
        claim_revision=2,
        field_codes=list(fields),
        created_at=timestamp,
        shown_values_fingerprint=shown_values_fingerprint(fields, list(fields)),
    )
    item = RuntimeWorkItemRecord(
        work_item_id='wki_confirmation',
        claim_id=claim_id,
        turn_id='turn_shown',
        kind='confirmation',
        subject_ref=shown.confirmation_id,
        owner='claimant',
        status='open',
        created_at=timestamp,
        updated_at=timestamp,
        confirmation_request=shown,
    )
    original = repository.list_runtime_work_items
    monkeypatch.setattr(
        repository, 'list_runtime_work_items', lambda *args: [*original(*args), item]
    )
    url = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
    payload = {
        'client_message_id': 'confirm-retry-input',
        'content': {'type': 'text', 'text': 'Yes, that is right.'},
    }
    first = client.post(
        url,
        headers={**auth_headers, 'Idempotency-Key': 'confirm-attempt-1', 'If-Match': '2'},
        json=payload,
    )
    assert first.status_code == 200, first.text
    current = repository.get_claim(claim_id, 'cus_demo')
    assert current is not None
    repository.save_claim(current.model_copy(update={'revision': 4}), expected_revision=3)
    agent.fail = False
    retry = client.post(
        url,
        headers={**auth_headers, 'Idempotency-Key': 'confirm-attempt-2', 'If-Match': '4'},
        json=payload,
    )
    assert retry.status_code == 200, retry.text
    resumed = repository.get_claim(claim_id, 'cus_demo')
    assert resumed is not None
    assert resumed.form['incident.location'].status is FormStatus.PROPOSED
