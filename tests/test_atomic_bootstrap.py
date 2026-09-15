from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.config import AgentRuntimeProfile
from backend.core.errors import ApiError
from backend.domain.models import ActorType
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentProposal, AgentTurnContext, ControlledAgent


def test_initial_bootstrap_persists_claim_and_turn_once(
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    payload: dict[str, object] = {
        'channel': 'web_agent',
        'locale': 'en-NZ',
        'incident_type': 'motor',
        'initial_message': {
            'client_message_id': 'bootstrap-message-1',
            'content': {'type': 'text', 'text': 'A parked car was damaged overnight.'},
        },
    }
    headers = {**auth_headers, 'Idempotency-Key': 'bootstrap-operation-1'}

    first = client.post('/api/v1/claims', headers=headers, json=payload)
    replay = client.post('/api/v1/claims', headers=headers, json=payload)

    assert first.status_code == 201, first.text
    assert replay.status_code == 201, replay.text
    assert replay.json() == first.json()
    body = first.json()
    claim_id = body['claim_id']
    session_id = body['session_id']
    assert body['claim']['claim_id'] == claim_id
    assert body['session']['session_id'] == session_id
    assert repository.get_claim(claim_id, 'cus_demo') is not None
    assert repository.get_session(claim_id, session_id, 'cus_demo') is not None
    messages = repository.list_messages(claim_id, session_id, 'cus_demo')
    assert len(messages) == 2
    claimant_message = next(message for message in messages if message.actor is ActorType.CLAIMANT)
    assert claimant_message.client_message_id == 'bootstrap-message-1'

    changed_payload = {
        **payload,
        'initial_message': {
            'client_message_id': 'bootstrap-message-2',
            'content': {'type': 'text', 'text': 'This is a different report.'},
        },
    }
    conflict = client.post('/api/v1/claims', headers=headers, json=changed_payload)
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert len(repository.list_claims_internal()) == 1


class _UnavailableAgent:
    def propose_turn(self, _context: object) -> object:
        raise ApiError(
            status_code=503,
            code='AGENT_RUNTIME_UNAVAILABLE',
            message='The Agent Runtime is unavailable.',
            retryable=True,
        )


class _BarrierAgent:
    def __init__(self) -> None:
        self._barrier = Barrier(2)
        self._delegate = ControlledAgent()

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        self._barrier.wait(timeout=5)
        return self._delegate.propose_turn(context)


def test_initial_bootstrap_failure_leaves_no_visible_claim(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    app.state.agent_turn_provider = _UnavailableAgent()
    response = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'failed-bootstrap-operation'},
        json={
            'incident_type': 'home',
            'initial_message': {
                'client_message_id': 'failed-bootstrap-message',
                'content': {'type': 'text', 'text': 'A pipe burst in my kitchen.'},
            },
        },
    )

    assert response.status_code == 503
    assert response.json()['error']['code'] == 'AGENT_RUNTIME_UNAVAILABLE'
    assert repository.list_claims_internal() == []


def test_concurrent_initial_bootstrap_replays_one_committed_claim(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    app.state.agent_turn_provider = _BarrierAgent()
    headers = {**auth_headers, 'Idempotency-Key': 'concurrent-bootstrap-operation'}
    payload = {
        'incident_type': 'contents',
        'initial_message': {
            'client_message_id': 'concurrent-bootstrap-message',
            'content': {'type': 'text', 'text': 'Water damaged my laptop.'},
        },
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _index: client.post('/api/v1/claims', headers=headers, json=payload),
                range(2),
            )
        )

    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    assert len(repository.list_claims_internal()) == 1


def test_initial_bootstrap_resolves_explicit_and_gateway_default_profiles(
    app: FastAPI,
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected: list[str | None] = []

    def select_profile(_request: object, profile_id: str | None) -> str:
        selected.append(profile_id)
        return profile_id or 'qwen-local'

    monkeypatch.setattr('backend.api.claims.select_model_profile', select_profile)
    explicit = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'profile-explicit'},
        json={
            'model_profile_id': 'qwen-local',
            'initial_message': {
                'client_message_id': 'profile-explicit-message',
                'content': {'type': 'text', 'text': 'A parked car was damaged.'},
            },
        },
    )
    assert explicit.status_code == 201, explicit.text

    app.state.settings = replace(
        app.state.settings,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_base_url='https://model.example.test/v1',
        model_identifier='test-model',
    )
    defaulted = client.post(
        '/api/v1/claims',
        headers={**auth_headers, 'Idempotency-Key': 'profile-default'},
        json={
            'initial_message': {
                'client_message_id': 'profile-default-message',
                'content': {'type': 'text', 'text': 'A pipe burst in my kitchen.'},
            },
        },
    )
    assert defaulted.status_code == 201, defaulted.text
    assert selected == ['qwen-local', 'qwen-local', None, 'qwen-local']
