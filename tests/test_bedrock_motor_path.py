import json
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.model_gateway import (
    BedrockConverseModelGateway,
    ModelGatewayRegistry,
)
from backend.app import create_app
from backend.core.config import AgentRuntimeProfile, Settings
from backend.repositories.fixture import FixtureRepository


def _bedrock_response(proposal: dict[str, object], request_number: int) -> httpx.Response:
    return httpx.Response(
        200,
        headers={'x-amzn-requestid': f'bedrock-motor-{request_number}'},
        json={
            'output': {
                'message': {
                    'role': 'assistant',
                    'content': [
                        {
                            'toolUse': {
                                'toolUseId': f'bedrock-motor-tool-{request_number}',
                                'name': 'northwind_agent_proposal',
                                'input': proposal,
                            }
                        }
                    ],
                }
            },
            'stopReason': 'tool_use',
            'usage': {'inputTokens': 200, 'outputTokens': 100, 'totalTokens': 300},
        },
    )


def _proposal(
    *,
    reason_code: str,
    response: str,
    next_status: str,
    next_summary: str,
    required_items: list[str],
    form_changes: list[dict[str, object]],
) -> dict[str, object]:
    return {
        'action': 'CONFIRM',
        'reason_codes': [reason_code],
        'customer_reason': 'The proposed incident facts need claimant review.',
        'customer_response': response,
        'customer_next_step': {
            'status': next_status,
            'summary': next_summary,
            'responsible_party': 'claimant',
            'required_items': required_items,
        },
        'form_changes': form_changes,
        'state_changes': [{'path': 'claim_state.next_action', 'to': 'CONFIRM'}],
        'proposed_signals': [],
        'required_tools': [],
        'next_action_requirements': [f'provide:{item}' for item in required_items],
        'handoff_priority': None,
    }


def test_bedrock_motor_turns_reach_claim_creation_without_reasking_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('TEST_BEDROCK_TOKEN', 'synthetic-bedrock-token')
    request_contexts: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        context = json.loads(payload['messages'][0]['content'][0]['text'])
        request_contexts.append(context)
        if len(request_contexts) == 1:
            return _bedrock_response(
                _proposal(
                    reason_code='MOTOR_FACTS_PROPOSED',
                    response=(
                        'I have recorded the rear impact, location, damage, and that nobody was '
                        'injured. Is the vehicle safe to drive?'
                    ),
                    next_status='provide_vehicle_status',
                    next_summary='Tell us whether the vehicle is safe to drive.',
                    required_items=['vehicle.drivable'],
                    form_changes=[
                        {
                            'field_code': 'incident.description',
                            'value': 'Another vehicle hit the rear of the claimant vehicle.',
                            'confidence': 0.98,
                        },
                        {
                            'field_code': 'incident.type',
                            'value': 'motor',
                            'confidence': 0.99,
                        },
                        {
                            'field_code': 'incident.location',
                            'value': 'Queen Street',
                            'confidence': 0.97,
                        },
                        {
                            'field_code': 'incident.injury_or_danger',
                            'value': False,
                            'confidence': 0.99,
                        },
                        {
                            'field_code': 'loss.description',
                            'value': 'Rear bumper damage',
                            'confidence': 0.96,
                        },
                    ],
                ),
                1,
            )
        return _bedrock_response(
            _proposal(
                reason_code='VEHICLE_STATUS_PROPOSED',
                response='I have recorded that the vehicle is safe to drive.',
                next_status='confirmation_required',
                next_summary='Review and confirm the proposed incident details.',
                required_items=[],
                form_changes=[
                    {'field_code': 'vehicle.drivable', 'value': True, 'confidence': 0.99}
                ],
            ),
            2,
        )

    registry = ModelGatewayRegistry()
    registry.register(
        'bedrock_converse',
        lambda config: BedrockConverseModelGateway(
            config,
            transport=httpx.MockTransport(handler),
        ),
    )
    settings = Settings(
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='bedrock_converse',
        model_base_url='https://bedrock-runtime.us-east-1.amazonaws.com',
        model_identifier='amazon.nova-2-lite-v1:0',
        model_api_key_env='TEST_BEDROCK_TOKEN',
        model_supports_tools=False,
    )
    claimant_headers = {'Authorization': 'Bearer synthetic-claimant'}

    with TestClient(
        create_app(
            settings,
            repository=FixtureRepository(),
            model_gateway_registry=registry,
        )
    ) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**claimant_headers, 'Idempotency-Key': 'bedrock-motor-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': None},
        )
        assert created.status_code == 201
        claim_id = created.json()['claim']['claim_id']
        session_id = created.json()['session']['session_id']

        first_turn = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **claimant_headers,
                'Idempotency-Key': 'bedrock-motor-turn-1',
                'If-Match': '1',
            },
            json={
                'client_message_id': 'bedrock-motor-message-1',
                'content': {
                    'type': 'text',
                    'text': (
                        'Another car hit the rear of mine on Queen Street this morning. Nobody '
                        'was injured, and the rear bumper is damaged.'
                    ),
                },
                'evidence_refs': [],
            },
        )
        assert first_turn.status_code == 200
        first_body = first_turn.json()
        assert first_body['agent_message'] is not None
        assert 'Is the vehicle safe to drive?' in first_body['agent_message']['content']['text']
        assert {change['field_code'] for change in first_body['form_changes']} == {
            'incident.description',
            'incident.type',
            'incident.location',
            'incident.injury_or_danger',
            'loss.description',
        }
        for change in first_body['form_changes']:
            assert change['field']['source_refs'] == [first_body['claimant_message']['message_id']]

        second_turn = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **claimant_headers,
                'Idempotency-Key': 'bedrock-motor-turn-2',
                'If-Match': str(first_body['claim_revision']),
            },
            json={
                'client_message_id': 'bedrock-motor-message-2',
                'content': {'type': 'text', 'text': 'Yes, the vehicle is safe to drive.'},
                'evidence_refs': [],
            },
        )
        assert second_turn.status_code == 200
        second_body = second_turn.json()
        assert [change['field_code'] for change in second_body['form_changes']] == [
            'vehicle.drivable'
        ]

        confirm = client.post(
            f'/api/v1/claims/{claim_id}/form/confirmations',
            headers={
                **claimant_headers,
                'Idempotency-Key': 'bedrock-motor-confirm',
                'If-Match': str(second_body['claim_revision']),
            },
            json={
                'field_codes': [
                    'incident.description',
                    'incident.type',
                    'incident.location',
                    'incident.injury_or_danger',
                    'loss.description',
                    'vehicle.drivable',
                ]
            },
        )
        assert confirm.status_code == 200
        assert confirm.json()['customer_next_step']['status'] == 'ready_to_create'

        external_claim = client.post(
            f'/api/v1/claims/{claim_id}/creation',
            headers={
                **claimant_headers,
                'Idempotency-Key': 'bedrock-motor-create',
                'If-Match': str(confirm.json()['revision']),
            },
        )
        assert external_claim.status_code == 201
        assert external_claim.json()['external_claim']['creation_status'] == 'created'

    first_claim_context = cast(dict[str, object], request_contexts[0]['claim'])
    second_claim_context = cast(dict[str, object], request_contexts[1]['claim'])
    assert first_claim_context['incident_type'] is None
    assert 'incident.location' in cast(list[str], second_claim_context['known_field_codes'])
    assert 'incident.location' not in cast(dict[str, object], second_claim_context['form'])
    assert 'Queen Street' not in json.dumps(second_claim_context)
