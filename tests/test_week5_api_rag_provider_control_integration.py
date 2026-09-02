import json
from datetime import UTC, datetime
from typing import cast

import httpx
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import MockEvidenceStorage
from backend.adapters.knowledge import FixtureKnowledgeDocumentStore, FixtureKnowledgeRetriever
from backend.adapters.model_gateway import ModelGatewayRegistry, OpenAICompatibleModelGateway
from backend.adapters.policy_history import MockPolicyHistoryAdapter
from backend.app import create_app
from backend.core.config import AgentRuntimeProfile, DataRuntimeProfile, IdentityMode, Settings
from backend.core.runtime_profiles import DataRuntimeBundle
from backend.domain.knowledge import KnowledgeChunk
from backend.domain.model_gateway import ModelProfileStatus
from backend.repositories.configuration import ConfigurationRepository
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
    knowledge_store = FixtureKnowledgeDocumentStore(
        (
            KnowledgeChunk(
                document_id='doc-integration-motor',
                chunk_id='chunk-integration-motor',
                title='The vehicle damage is now recorded.',
                document_type='policy_guidance',
                version='MVP-2026.1',
                section_path='motor/intake',
                page=1,
                source_uri='fixture://knowledge/doc-integration-motor',
                jurisdiction='NZ',
                insurer='Northwind Insurance',
                product='motor',
                effective_from=datetime(2026, 8, 1, tzinfo=UTC),
                effective_to=None,
                authority='northwind_synthetic_demo',
                visibility='customer_and_staff',
                checksum='checksum-integration-motor',
                ingested_at=datetime(2026, 8, 1, tzinfo=UTC),
                text='The vehicle damage is now recorded for the motor intake.',
            ),
        )
    )
    knowledge_retriever = FixtureKnowledgeRetriever(knowledge_store)
    data_bundle = DataRuntimeBundle(
        profile=DataRuntimeProfile.FIXTURE,
        repository=repository,
        evidence_storage=MockEvidenceStorage(),
        policy_history=MockPolicyHistoryAdapter(),
        knowledge_documents=knowledge_store,
        knowledge_retrieval=knowledge_retriever,
    )
    configuration_repository = ConfigurationRepository()
    provider_requests: list[dict[str, object]] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        provider_requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={'x-request-id': 'integration-provider-request'},
            json={
                'id': 'integration-completion',
                'model': 'control-plane-model',
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
            data_runtime_bundle=data_bundle,
            configuration_repository=configuration_repository,
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

        model_configuration = client.post(
            '/internal/v1/admin/configurations',
            headers=ADMIN_HEADERS,
            json={
                'domain': 'model',
                'impact': 'high',
                'values': {
                    'protocol': 'openai_compatible',
                    'provider': 'synthetic-provider',
                    'model_identifier': 'control-plane-model',
                    'base_url': 'https://provider.example/v1',
                    'credential_environment_variable': None,
                    'profile_id': 'integration-model-profile',
                    'purpose': 'agent_turn',
                    'privacy_class': 'synthetic_fnol',
                    'prompt_version': 'northwind-fnol-motor-claimant-v3',
                    'evaluation_status': 'configured',
                    'timeout_seconds': 30,
                    'structured_output': True,
                    'tools': False,
                },
                'reason': 'Publish the model runtime used by the integration path.',
            },
        )
        assert model_configuration.status_code == 201, model_configuration.text
        configuration_id = model_configuration.json()['configuration_id']
        validated = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/validate',
            headers={
                'Authorization': 'Bearer synthetic-admin',
                'Idempotency-Key': 'control-plane-model-validate',
                'If-Match': '1',
            },
            json={
                'scenario_results': [
                    {
                        'scenario_id': 'api-rag-provider-control',
                        'outcome': 'passed',
                        'evidence': 'Model configuration was validated before the claimant turn.',
                    }
                ]
            },
        )
        assert validated.status_code == 200, validated.text
        assert validated.json()['state'] == 'awaiting_approval'
        published = client.post(
            f'/internal/v1/admin/configurations/{configuration_id}/publish',
            headers={
                'Authorization': 'Bearer synthetic-release-approver',
                'Idempotency-Key': 'control-plane-model-publish',
                'If-Match': '2',
            },
            json={'reason': 'Approved for the controlled integration scenario.'},
        )
        assert published.status_code == 200, published.text
        assert published.json()['state'] == 'published'

        knowledge = client.post(
            '/internal/v1/knowledge/search',
            headers=INTEGRATION_HEADERS,
            json={
                'question': 'The vehicle damage is now recorded.',
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
        assert knowledge.json()['status'] == 'evidence_found'
        assert knowledge.json()['results'][0]['chunk_id'] == 'chunk-integration-motor'

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

        replay = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **CLAIMANT_HEADERS,
                'Idempotency-Key': 'integration-message',
                'If-Match': '1',
            },
            json={
                'client_message_id': 'integration-client-message',
                'content': {'type': 'text', 'text': 'The vehicle damage is now recorded.'},
                'evidence_refs': [],
            },
        )
        assert replay.status_code == 200
        assert replay.json() == message.json()
        assert len(provider_requests) == 1

        no_evidence = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **CLAIMANT_HEADERS,
                'Idempotency-Key': 'integration-no-evidence',
                'If-Match': str(message.json()['claim_revision']),
            },
            json={
                'client_message_id': 'integration-no-evidence-message',
                'content': {'type': 'text', 'text': 'A message with no matching knowledge.'},
                'evidence_refs': [],
            },
        )
        assert no_evidence.status_code == 200
        assert len(provider_requests) == 2
        no_evidence_messages = cast(list[dict[str, object]], provider_requests[1]['messages'])
        no_evidence_context = json.loads(cast(str, no_evidence_messages[1]['content']))
        assert no_evidence_context['knowledge_status'] == 'no_evidence'
        assert no_evidence_context['knowledge_citations'] == []

        request_body = provider_requests[0]
        assert request_body['model'] == 'control-plane-model'
        provider_messages = cast(list[dict[str, object]], request_body['messages'])
        system_prompt = cast(str, provider_messages[0]['content'])
        assert 'Prompt ID: `northwind-fnol-motor-claimant-v3`' in system_prompt
        assert 'untrusted reference material' in system_prompt
        model_context_content = cast(str, provider_messages[1]['content'])
        model_context = json.loads(model_context_content)
        assert model_context['knowledge_status'] == 'evidence_found'
        assert model_context['knowledge_citations'][0]['chunk_id'] == 'chunk-integration-motor'
