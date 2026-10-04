"""Virtual-time transport acceptance, not a wall-clock performance measurement."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.adapters.model_gateway import OpenAICompatibleModelGateway
from backend.core.config import Settings
from backend.core.model_gateway import _model_gateway_config_from_runtime
from backend.domain.configuration import ModelRuntimeBinding, ModelRuntimeConfiguration
from backend.repositories.fixture import FixtureRepository
from backend.services import model_agent
from backend.services.agent import InvariantGuardedAgent
from backend.services.initial_runtime_release import repository_release_values
from backend.services.model_agent import GatewayAgent
from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact


@pytest.mark.parametrize('timeout_source', ['bootstrap', 'published'])
def test_legitimate_generation_near_configured_timeout_commits_facts(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    timeout_source: str,
) -> None:
    bindings = [
        ModelRuntimeBinding.model_validate(value)
        for value in json.loads(
            Path('config/model-runtime-bindings.json').read_text(encoding='utf-8')
        )
    ]
    configuration = ModelRuntimeConfiguration.model_validate(
        repository_release_values(bindings)['model:openrouter-gpt4o-mini']
    )
    timeout = (
        Settings().model_timeout_seconds
        if timeout_source == 'bootstrap'
        else configuration.timeout_seconds
    )
    configuration = configuration.model_copy(
        update={'timeout_seconds': timeout, 'credential_environment_variable': None}
    )
    elapsed = [0.0]
    calls: list[httpx.Request] = []
    output = envelope(fields=[fact('incident.location', 'Wellington', 'Wellington')])

    def delayed_response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        read_timeout = request.extensions['timeout']['read']
        assert read_timeout == timeout
        simulated_generation = timeout - 5.0
        assert simulated_generation > 30
        if simulated_generation > read_timeout:
            raise httpx.ReadTimeout('Virtual provider timeout', request=request)
        elapsed[0] += simulated_generation
        return httpx.Response(
            200,
            json={
                'model': 'openai/gpt-4o-mini',
                'choices': [
                    {
                        'finish_reason': 'stop',
                        'message': {'role': 'assistant', 'content': json.dumps(output)},
                    }
                ],
                'usage': {'prompt_tokens': 1000, 'completion_tokens': 100, 'total_tokens': 1100},
            },
        )

    gateway = OpenAICompatibleModelGateway(
        _model_gateway_config_from_runtime(configuration),
        transport=httpx.MockTransport(delayed_response),
    )
    provider = V8JourneyProvider([])
    provider.agent = GatewayAgent(gateway)
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    monkeypatch.setattr(model_agent, 'perf_counter', lambda: elapsed[0])
    journey = Journey(client, 'motor', f'slow-generation-{timeout_source}')
    turn = journey.send('The accident happened in Wellington.')
    assert len(calls) == 1
    claim = repository.get_claim(journey.claim_id, 'cus_demo')
    assert claim is not None and claim.form['incident.location'].value == 'Wellington'
    assert turn['recovery'] is None
    trace = repository.find_runtime_trace_for_trigger(
        journey.claim_id, turn['claimant_message']['message_id'], 'cus_demo'
    )
    assert trace is not None and trace.status == 'succeeded'
    assert trace.total_latency_ms == pytest.approx((timeout - 5) * 1000)
