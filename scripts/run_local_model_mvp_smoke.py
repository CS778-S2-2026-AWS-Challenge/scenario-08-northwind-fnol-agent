import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.adapters.model_gateway import (
    ModelGatewayConfig,
    ModelGatewayRegistry,
    OpenAICompatibleModelGateway,
)
from backend.app import create_app
from scripts.check_runtime_profile import isolated_environment, load_environment_example

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENVIRONMENT = ROOT / 'deploy' / 'runtime' / 'local-mvp.env.example'
CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
PROTOCOL = 'local_mvp_smoke_openai'
MODEL_ID = 'synthetic-openai-compatible-model'


def _proposal(*, unsafe_metadata: bool = False) -> dict[str, object]:
    form_change: dict[str, object] = {
        'field_code': 'incident.description',
        'value': 'A synthetic rear-end incident occurred in Auckland.',
        'needed_for': 'current_action',
        'confidence': 0.95,
    }
    if unsafe_metadata:
        form_change.update({'source': 'claimant', 'status': 'confirmed'})
    return {
        'action': 'UPDATE',
        'reason_codes': ['MODEL_UPDATE'],
        'customer_reason': 'The claimant supplied incident details.',
        'customer_response': 'The incident details were recorded for review.',
        'customer_next_step': {
            'status': 'continue',
            'summary': 'Continue the report.',
            'responsible_party': 'claimant',
            'required_items': [],
        },
        'form_changes': [form_change],
        'state_changes': [{'path': 'claim_state.next_action', 'to': 'UPDATE'}],
        'proposed_signals': [],
        'required_tools': [],
        'next_action_requirements': [],
        'handoff_priority': None,
    }


class SyntheticProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    @staticmethod
    def _message_text(request: httpx.Request) -> str:
        payload = json.loads(request.content)
        messages = cast(list[dict[str, object]], payload['messages'])
        content = str(messages[-1]['content'])
        model_context = json.loads(content)
        return str(model_context.get('message_text') or '')

    def handle(self, request: httpx.Request) -> httpx.Response:
        message_text = self._message_text(request)
        self.calls.append(message_text)
        if '[timeout]' in message_text:
            raise httpx.ReadTimeout('Synthetic provider timeout.', request=request)
        if '[malformed]' in message_text:
            content = '{not-json'
            finish_reason = 'stop'
        elif '[incomplete]' in message_text:
            content = json.dumps(_proposal())
            finish_reason = 'length'
        else:
            content = json.dumps(_proposal(unsafe_metadata='[unauthorised]' in message_text))
            finish_reason = 'stop'
        return httpx.Response(
            200,
            headers={'x-request-id': f'synthetic-model-{len(self.calls)}'},
            json={
                'id': f'synthetic-completion-{len(self.calls)}',
                'model': MODEL_ID,
                'choices': [
                    {
                        'finish_reason': finish_reason,
                        'message': {'role': 'assistant', 'content': content},
                    }
                ],
            },
        )


def _registry(provider: SyntheticProvider) -> ModelGatewayRegistry:
    registry = ModelGatewayRegistry()

    def factory(config: ModelGatewayConfig) -> OpenAICompatibleModelGateway:
        return OpenAICompatibleModelGateway(config, transport=httpx.MockTransport(provider.handle))

    registry.register(PROTOCOL, factory)
    return registry


def _expect(response: httpx.Response, status_code: int, step: str) -> dict[str, Any]:
    if response.status_code != status_code:
        raise RuntimeError(f'{step} failed with HTTP {response.status_code}: {response.text}')
    return cast(dict[str, Any], response.json())


def _message_url(claim_id: str, session_id: str) -> str:
    return f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'


def _submit(
    client: TestClient,
    *,
    claim_id: str,
    session_id: str,
    run_id: str,
    suffix: str,
    text: str,
    revision: int,
) -> httpx.Response:
    return client.post(
        _message_url(claim_id, session_id),
        headers={
            **CLAIMANT_AUTH,
            'Idempotency-Key': f'{run_id}-{suffix}',
            'If-Match': str(revision),
        },
        json={
            'client_message_id': f'{run_id}-{suffix}',
            'content': {'type': 'text', 'text': text},
            'evidence_refs': [],
        },
    )


def _assert_atomic_failure(
    app: FastAPI,
    *,
    claim_id: str,
    session_id: str,
    run_id: str,
    suffix: str,
    expected_revision: int,
    expected_messages: int,
    expected_decisions: int,
) -> None:
    repository = app.state.data_runtime_bundle.repository
    claim = repository.get_claim(claim_id, 'cus_demo')
    if claim is None or claim.revision != expected_revision:
        raise RuntimeError(f'{suffix} changed the Claim revision.')
    if len(repository.list_messages(claim_id, session_id, 'cus_demo')) != expected_messages:
        raise RuntimeError(f'{suffix} left a partial message.')
    if len(repository.list_agent_decisions(claim_id, 'cus_demo')) != expected_decisions:
        raise RuntimeError(f'{suffix} left a partial Agent decision.')
    if (
        repository.find_idempotency(
            'cus_demo', _message_url(claim_id, session_id), f'{run_id}-{suffix}'
        )
        is not None
    ):
        raise RuntimeError(f'{suffix} left a partial idempotency record.')


def _first_process(
    run_id: str,
    registry: ModelGatewayRegistry,
) -> tuple[str, str, str, int]:
    app = create_app(model_gateway_registry=registry)
    with TestClient(app, raise_server_exceptions=False) as client:
        created = _expect(
            client.post(
                '/api/v1/claims',
                headers={**CLAIMANT_AUTH, 'Idempotency-Key': f'{run_id}-claim'},
                json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
            ),
            201,
            'claim creation',
        )
        claim_id = str(cast(dict[str, Any], created['claim'])['claim_id'])
        session_id = str(cast(dict[str, Any], created['session'])['session_id'])
        success = _expect(
            _submit(
                client,
                claim_id=claim_id,
                session_id=session_id,
                run_id=run_id,
                suffix='success',
                text='A synthetic rear-end incident occurred in Auckland. Nobody was injured.',
                revision=1,
            ),
            200,
            'model-backed message turn',
        )
        if int(success['claim_revision']) != 2:
            raise RuntimeError('The accepted model turn did not commit revision 2.')
        repository = app.state.data_runtime_bundle.repository
        decisions = repository.list_agent_decisions(claim_id, 'cus_demo')
        if len(decisions) != 1 or decisions[0].model_provenance is None:
            raise RuntimeError('The accepted model turn did not persist model provenance.')
        provenance = decisions[0].model_provenance
        if provenance.provider_model != MODEL_ID or provenance.provider_request_id is None:
            raise RuntimeError('The accepted model provenance is incomplete.')
        if MODEL_ID in json.dumps(success):
            raise RuntimeError('Internal model provenance leaked into the claimant response.')
        return claim_id, session_id, decisions[0].decision_id, int(success['claim_revision'])


def _second_process(
    run_id: str,
    registry: ModelGatewayRegistry,
    provider: SyntheticProvider,
    claim_id: str,
    session_id: str,
    decision_id: str,
    revision: int,
) -> dict[str, object]:
    app = create_app(model_gateway_registry=registry)
    with TestClient(app, raise_server_exceptions=False) as client:
        repository = app.state.data_runtime_bundle.repository
        decisions = repository.list_agent_decisions(claim_id, 'cus_demo')
        if [item.decision_id for item in decisions] != [decision_id]:
            raise RuntimeError('The model decision did not recover after application restart.')
        call_count = len(provider.calls)
        replay = _expect(
            _submit(
                client,
                claim_id=claim_id,
                session_id=session_id,
                run_id=run_id,
                suffix='success',
                text='A synthetic rear-end incident occurred in Auckland. Nobody was injured.',
                revision=1,
            ),
            200,
            'idempotent model turn replay',
        )
        if int(replay['claim_revision']) != revision or len(provider.calls) != call_count:
            raise RuntimeError(
                'Idempotent replay called the model or changed the committed result.'
            )

        changed_replay = _submit(
            client,
            claim_id=claim_id,
            session_id=session_id,
            run_id=run_id,
            suffix='success',
            text='Changed input under the same idempotency key.',
            revision=1,
        )
        if changed_replay.status_code != 409:
            raise RuntimeError('Changed input under one idempotency key was not rejected.')

        expected_messages = len(repository.list_messages(claim_id, session_id, 'cus_demo'))
        expected_decisions = len(decisions)
        failures = [
            ('timeout', '[timeout] synthetic timeout', 503, 'DEPENDENCY_UNAVAILABLE'),
            ('malformed', '[malformed] synthetic malformed output', 502, 'DEPENDENCY_FAILED'),
            ('incomplete', '[incomplete] synthetic truncated output', 502, 'DEPENDENCY_FAILED'),
            (
                'unauthorised',
                '[unauthorised] synthetic metadata escalation',
                502,
                'DEPENDENCY_FAILED',
            ),
        ]
        for suffix, text, status_code, error_code in failures:
            response = _submit(
                client,
                claim_id=claim_id,
                session_id=session_id,
                run_id=run_id,
                suffix=suffix,
                text=text,
                revision=revision,
            )
            body = _expect(response, status_code, suffix)
            if cast(dict[str, Any], body['error'])['code'] != error_code:
                raise RuntimeError(f'{suffix} returned the wrong bounded error.')
            _assert_atomic_failure(
                app,
                claim_id=claim_id,
                session_id=session_id,
                run_id=run_id,
                suffix=suffix,
                expected_revision=revision,
                expected_messages=expected_messages,
                expected_decisions=expected_decisions,
            )

        stale_calls = len(provider.calls)
        stale = _submit(
            client,
            claim_id=claim_id,
            session_id=session_id,
            run_id=run_id,
            suffix='stale',
            text='This stale turn must not reach the model.',
            revision=1,
        )
        if stale.status_code != 409 or len(provider.calls) != stale_calls:
            raise RuntimeError('A stale revision was not rejected before model execution.')

        recovered_claim = repository.get_claim(claim_id, 'cus_demo')
        if recovered_claim is None or recovered_claim.revision != revision:
            raise RuntimeError('The committed Claim was not stable after failure checks.')
        return {
            'claim_id': claim_id,
            'revision': revision,
            'model_decisions': expected_decisions,
            'model_calls': len(provider.calls),
            'idempotent_replay': 'verified_without_model_call',
            'restart_recovery': 'verified',
            'failure_atomicity': [item[0] for item in failures],
            'stale_revision': 'rejected_before_model_call',
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Verify the model-backed local MVP turn against MongoDB and MinIO composition.'
    )
    parser.add_argument('--env-file', type=Path, default=DEFAULT_ENVIRONMENT)
    arguments = parser.parse_args()
    values = load_environment_example(arguments.env_file)
    if values.get('DATA_RUNTIME_PROFILE') != 'local_mvp':
        raise SystemExit('The smoke requires DATA_RUNTIME_PROFILE=local_mvp.')
    values.update(
        {
            'AGENT_RUNTIME_PROFILE': 'model_gateway',
            'MODEL_PROTOCOL_ADAPTER': PROTOCOL,
            'MODEL_BASE_URL': 'https://synthetic-model.invalid/v1',
            'MODEL_IDENTIFIER': MODEL_ID,
            'MODEL_API_KEY_ENV': '',
            'MODEL_SUPPORTS_STRUCTURED_OUTPUT': 'true',
            'MODEL_SUPPORTS_TOOLS': 'false',
        }
    )
    run_id = f'local-model-mvp-{uuid4().hex[:12]}'
    provider = SyntheticProvider()
    registry = _registry(provider)
    with isolated_environment(values):
        claim_id, session_id, decision_id, revision = _first_process(run_id, registry)
        result = _second_process(
            run_id,
            registry,
            provider,
            claim_id,
            session_id,
            decision_id,
            revision,
        )
    print(
        json.dumps(
            {'status': 'PASS', 'provider': 'deterministic_mock_transport', **result},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == '__main__':
    main()
