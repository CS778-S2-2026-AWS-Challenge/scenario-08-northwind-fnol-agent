import json
from typing import cast

import httpx
from fastapi.testclient import TestClient

from backend.adapters.model_gateway import ModelGatewayRegistry, OpenAICompatibleModelGateway
from backend.app import create_app
from backend.core.config import AgentRuntimeProfile, IdentityMode, Settings
from backend.domain.model_gateway import ModelProfileStatus
from backend.repositories.fixture import FixtureRepository

INTEGRATION_HEADERS = {'Authorization': 'Bearer synthetic-integration'}
CLAIMANT_HEADERS = {'Authorization': 'Bearer synthetic-claimant'}
ADMIN_HEADERS = {
    'Authorization': 'Bearer synthetic-admin',
    'Idempotency-Key': 'control-plane-create',
}


def _proposal() -> dict[str, object]:
    return {
        'action': 'UPDATE',
        'reason_codes': ['MODEL_UPDATE'],
        'customer_reason': 'The claimant supplied an update.',
        'customer_response': 'The update was recorded.',
        'customer_next_step': {
            'status': 'continue',
            'summary': 'Continue the report.',
            'responsible_party': 'claimant',
            'required_items': [],
        },
        'form_changes': [],
        'state_changes': [],
        'proposed_signals': [],
        'required_tools': [],
        'next_action_requirements': [],
        'handoff_priority': None,
    }


def test_api_rag_provider_and_control_plane_share_one_composition_root() -> None:
    repository = FixtureRepository()

    def transport_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={'x-request-id': 'integration-provider-request'},
            json={
                'id': 'integration-completion',
                'model': 'gpt-5.4-mini',
                'choices': [
                    {
                        'finish_reason': 'stop',
                        'message': {
                            'role': 'assistant',
                            'content': json.dumps(_proposal()),
                        },
                    }
                ],
            },
        )

    registry = ModelGatewayRegistry()
    registry.register(
        'openai_compatible',
        lambda config: OpenAICompatibleModelGateway(
            config,
            transport=httpx.MockTransport(transport_handler),
        ),
    )
    settings = Settings(
        environment='test',
        identity_mode=IdentityMode.DEVELOPER,
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_base_url='https://provider.example/v1',
        model_identifier='gpt-5.4-mini',
        model_provider='synthetic-provider',
        model_evaluation_status=ModelProfileStatus.CONFIGURED.value,
    )

    with TestClient(
        create_app(
            settings,
            repository=repository,
            model_gateway_registry=registry,
        )
    ) as client:
        readiness = client.get('/health/ready')
        assert readiness.status_code == 200
        assert readiness.json()['checks']['agent'] == 'configured'

        claim_response = client.post(
            '/api/v1/claims',
            headers={**CLAIMANT_HEADERS, 'Idempotency-Key': 'integration-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
        )
        assert claim_response.status_code == 201
        claim = cast(dict[str, object], claim_response.json()['claim'])
        claim_id = str(claim['claim_id'])
        session = cast(dict[str, object], claim_response.json()['session'])
        session_id = str(session['session_id'])

        knowledge = client.post(
            '/internal/v1/knowledge/search',
            headers=INTEGRATION_HEADERS,
            json={
                'question': 'What information is needed for this motor report?',
                'jurisdiction': 'NZ',
                'visibility': 'customer_and_staff',
                'authority': 'northwind_synthetic_demo',
                'version': 'MVP-2026.1',
                'insurer': 'Northwind Insurance',
                'product': 'motor',
                'effective_at': '2026-08-25T00:00:00Z',
                'limit': 3,
            },
        )
        assert knowledge.status_code == 200
        assert knowledge.json()['status'] in {'evidence_found', 'no_evidence'}

        policy = client.post(
            '/internal/v1/policy/search',
            headers=INTEGRATION_HEADERS,
            json={'claim_id': claim_id, 'policy_reference': 'synthetic-policy-101'},
        )
        assert policy.status_code == 200
        assert policy.json()['status'] == 'evidence_found'
        assert policy.json()['source']['reference'] == 'synthetic-policy-101'

        message = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={**CLAIMANT_HEADERS, 'Idempotency-Key': 'integration-message', 'If-Match': '1'},
            json={
                'client_message_id': 'integration-client-message',
                'content': {'type': 'text', 'text': 'The vehicle damage is now recorded.'},
                'evidence_refs': [],
            },
        )
        assert message.status_code == 200
        assert message.json()['decision']['action'] == 'UPDATE'

        created = client.post(
            '/internal/v1/admin/configurations',
            headers=ADMIN_HEADERS,
            json={
                'domain': 'feature',
                'values': {'enabled': True},
                'reason': 'Integration test configuration.',
            },
        )
        assert created.status_code == 201
        configuration_id = created.json()['configuration_id']
        validated = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/validate',
            headers={
                'Authorization': 'Bearer synthetic-admin',
                'Idempotency-Key': 'control-plane-validate',
                'If-Match': '1',
            },
            json={
                'scenario_results': [
                    {
                        'scenario_id': 'api-rag-provider-control',
                        'outcome': 'passed',
                        'evidence': 'All four boundaries responded through one app.',
                    }
                ]
            },
        )
        assert validated.status_code == 200
        assert validated.json()['state'] == 'published'
