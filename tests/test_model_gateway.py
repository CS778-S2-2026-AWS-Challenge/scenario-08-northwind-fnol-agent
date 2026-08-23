import json
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.model_gateway import (
    ModelGatewayConfig,
    ModelGatewayRegistry,
    OpenAICompatibleModelGateway,
)
from backend.app import create_app
from backend.core.config import AgentRuntimeProfile, Settings
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelTool,
)
from backend.domain.models import (
    AgentAction,
    AuthorityOutcome,
    Channel,
    CustomerNextStep,
    ResponsibleParty,
    WorkingClaim,
)
from backend.services.agent import AgentTurnContext, authorised_state_changes, validate_proposal
from backend.services.model_agent import GatewayAgent


def gateway_config(
    *,
    base_url: str = 'https://relay.example.test/v1',
    model: str = 'northwind-test-model',
    credential_environment_variable: str | None = None,
    structured_output: bool = True,
    tools: bool = True,
) -> ModelGatewayConfig:
    return ModelGatewayConfig(
        base_url=base_url,
        model=model,
        credential_environment_variable=credential_environment_variable,
        timeout_seconds=5.0,
        capabilities=ModelCapabilities(structured_output=structured_output, tools=tools),
    )


@pytest.mark.parametrize(
    ('base_url', 'model'),
    [
        ('https://api.provider.example/v1', 'official-model'),
        ('https://relay.example/v1', 'relay-model'),
        ('http://127.0.0.1:11434/v1', 'local-model'),
    ],
    ids=['official', 'relay', 'local'],
)
def test_openai_compatible_endpoints_switch_through_configuration_only(
    base_url: str,
    model: str,
) -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed['url'] = str(request.url)
        observed['payload'] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={'x-request-id': 'provider-request-1'},
            json={
                'id': 'completion-1',
                'model': model,
                'choices': [
                    {
                        'finish_reason': 'stop',
                        'message': {'role': 'assistant', 'content': '{"answer":"ok"}'},
                    }
                ],
                'usage': {
                    'prompt_tokens': 10,
                    'completion_tokens': 4,
                    'total_tokens': 14,
                },
            },
        )

    gateway = OpenAICompatibleModelGateway(
        gateway_config(base_url=base_url, model=model),
        transport=httpx.MockTransport(handler),
    )
    response = gateway.complete(
        ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content='Return a test object.')],
            response_schema={
                'type': 'object',
                'properties': {'answer': {'type': 'string'}},
                'required': ['answer'],
            },
        )
    )

    assert observed['url'] == f'{base_url}/chat/completions'
    payload = cast(dict[str, object], observed['payload'])
    assert payload['model'] == model
    assert cast(dict[str, object], payload['response_format'])['type'] == 'json_schema'
    assert response.structured_output == {'answer': 'ok'}
    assert response.provider_request_id == 'provider-request-1'
    assert response.usage is not None and response.usage.total_tokens == 14


def test_openai_compatible_gateway_normalises_tool_calls() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                'model': 'tool-model',
                'choices': [
                    {
                        'finish_reason': 'tool_calls',
                        'message': {
                            'role': 'assistant',
                            'content': None,
                            'tool_calls': [
                                {
                                    'id': 'call-1',
                                    'type': 'function',
                                    'function': {
                                        'name': 'find_policy',
                                        'arguments': '{"policy_id":"pol-1"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )

    gateway = OpenAICompatibleModelGateway(gateway_config(), transport=httpx.MockTransport(handler))
    response = gateway.complete(
        ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content='Find the policy.')],
            tools=[
                ModelTool(
                    name='find_policy',
                    description='Find a policy by ID.',
                    input_schema={
                        'type': 'object',
                        'properties': {'policy_id': {'type': 'string'}},
                    },
                )
            ],
        )
    )

    assert response.tool_calls[0].name == 'find_policy'
    assert response.tool_calls[0].arguments == {'policy_id': 'pol-1'}


@pytest.mark.parametrize(
    ('model_request', 'structured_output', 'tools'),
    [
        (
            ModelRequest(messages=[], response_schema={'type': 'object'}),
            False,
            True,
        ),
        (
            ModelRequest(
                messages=[],
                tools=[ModelTool(name='test', description='Test.', input_schema={})],
            ),
            True,
            False,
        ),
    ],
    ids=['structured-output', 'tools'],
)
def test_capability_failures_are_explicit_and_happen_before_transport(
    model_request: ModelRequest,
    structured_output: bool,
    tools: bool,
) -> None:
    transport_called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal transport_called
        transport_called = True
        return httpx.Response(500)

    gateway = OpenAICompatibleModelGateway(
        gateway_config(structured_output=structured_output, tools=tools),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(model_request)

    assert captured.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY
    assert transport_called is False


@pytest.mark.parametrize(
    ('status_code', 'expected_code', 'retryable'),
    [
        (401, ModelGatewayErrorCode.AUTHENTICATION, False),
        (403, ModelGatewayErrorCode.AUTHENTICATION, False),
        (429, ModelGatewayErrorCode.RATE_LIMIT, True),
        (500, ModelGatewayErrorCode.PROVIDER, True),
    ],
)
def test_provider_http_failures_are_normalised_without_response_details(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_code: ModelGatewayErrorCode,
    retryable: bool,
) -> None:
    secret = 'secret-model-key-value'
    monkeypatch.setenv('TEST_MODEL_API_KEY', secret)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers['Authorization'] == f'Bearer {secret}'
        return httpx.Response(status_code, text=f'provider body includes {secret}')

    gateway = OpenAICompatibleModelGateway(
        gateway_config(credential_environment_variable='TEST_MODEL_API_KEY'),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(ModelRequest(messages=[]))

    assert captured.value.code is expected_code
    assert captured.value.retryable is retryable
    assert secret not in str(captured.value)


def test_timeout_and_malformed_responses_are_normalised() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout('provider-specific timeout detail', request=request)

    timeout_gateway = OpenAICompatibleModelGateway(
        gateway_config(), transport=httpx.MockTransport(timeout_handler)
    )
    with pytest.raises(ModelGatewayError) as timeout_error:
        timeout_gateway.complete(ModelRequest(messages=[]))
    assert timeout_error.value.code is ModelGatewayErrorCode.TIMEOUT
    assert timeout_error.value.retryable is True

    malformed_gateway = OpenAICompatibleModelGateway(
        gateway_config(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={'choices': []})),
    )
    with pytest.raises(ModelGatewayError) as malformed_error:
        malformed_gateway.complete(ModelRequest(messages=[]))
    assert malformed_error.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE


class StaticGateway:
    def __init__(self, response: ModelResponse) -> None:
        self.response = response
        self.last_request: ModelRequest | None = None

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True, tools=False)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.last_request = request
        return self.response


def _working_claim() -> WorkingClaim:
    timestamp = datetime.now(UTC)
    return WorkingClaim(
        claim_id='clm_gateway',
        customer_id='cus_gateway',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_gateway_agent_uses_neutral_contract_and_keeps_authority_external() -> None:
    gateway = StaticGateway(
        ModelResponse(
            structured_output={
                'action': 'CREATE_CLAIM',
                'reason_codes': ['MODEL_SAYS_READY'],
                'customer_reason': 'The supplied details appear ready.',
                'customer_response': 'Your report is ready for the next controlled step.',
                'customer_next_step': {
                    'status': 'review_required',
                    'summary': 'Northwind must review claim creation.',
                    'responsible_party': 'northwind',
                    'required_items': [],
                },
                'form_changes': [],
                'state_changes': [{'path': 'claim_state.next_action', 'to': 'CREATE_CLAIM'}],
                'proposed_signals': [],
                'required_tools': [],
                'next_action_requirements': [],
                'handoff_priority': None,
                'controlled_rule_authorised': False,
            }
        )
    )
    agent = GatewayAgent(gateway)
    proposal = agent.propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-gateway',
            trigger_message_id='msg-gateway',
            message_text='Please create the claim.',
            evidence_refs=[],
        )
    )

    assert gateway.last_request is not None
    assert gateway.last_request.response_schema is not None
    assert proposal.action is AgentAction.CREATE_CLAIM
    authority = validate_proposal(proposal)
    assert authority.outcome is AuthorityOutcome.REVIEW_REQUIRED
    assert authorised_state_changes(proposal, authority) == []


def test_gateway_agent_cannot_claim_controlled_rule_authority() -> None:
    gateway = StaticGateway(
        ModelResponse(
            structured_output={
                'action': 'HANDOFF',
                'reason_codes': ['HUMAN_SUPPORT_REQUESTED'],
                'customer_reason': 'Human support was requested.',
                'customer_response': 'Northwind support will review this request.',
                'customer_next_step': {
                    'status': 'review_required',
                    'summary': 'Northwind must review the proposed handoff.',
                    'responsible_party': 'northwind',
                    'required_items': [],
                },
                'form_changes': [],
                'state_changes': [{'path': 'claim_state.next_action', 'to': 'HANDOFF'}],
                'proposed_signals': [],
                'required_tools': [],
                'next_action_requirements': [],
                'handoff_priority': 'standard',
                'controlled_rule_authorised': True,
            }
        )
    )

    proposal = GatewayAgent(gateway).propose_turn(
        AgentTurnContext(
            claim=_working_claim(),
            session_id='ses-gateway',
            trigger_message_id='msg-gateway',
            message_text='I want a person.',
            evidence_refs=[],
        )
    )

    assert proposal.controlled_rule_authorised is False
    assert validate_proposal(proposal).outcome is AuthorityOutcome.REVIEW_REQUIRED


def test_gateway_agent_rejects_model_requested_server_tools() -> None:
    gateway = StaticGateway(
        ModelResponse(
            structured_output={
                'action': 'UPDATE',
                'reason_codes': ['MODEL_TOOL_REQUEST'],
                'customer_reason': 'A model requested a server tool.',
                'customer_response': 'No tool has run.',
                'customer_next_step': {
                    'status': 'continue',
                    'summary': 'Continue without executing an untrusted tool request.',
                    'responsible_party': 'claimant',
                    'required_items': [],
                },
                'form_changes': [],
                'state_changes': [],
                'proposed_signals': [],
                'required_tools': [{'tool': 'policy_history', 'operation': 'search_policy'}],
                'next_action_requirements': [],
                'handoff_priority': None,
                'controlled_rule_authorised': False,
            }
        )
    )

    with pytest.raises(ModelGatewayError) as captured:
        GatewayAgent(gateway).propose_turn(
            AgentTurnContext(
                claim=_working_claim(),
                session_id='ses-gateway',
                trigger_message_id='msg-gateway',
                message_text='Look up my policy.',
                evidence_refs=[],
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY


def test_custom_protocol_registration_composes_without_route_changes() -> None:
    response = ModelResponse(
        structured_output={
            'action': 'UPDATE',
            'reason_codes': ['TEST'],
            'customer_reason': 'Test.',
            'customer_response': 'Test.',
            'customer_next_step': {
                'status': 'test',
                'summary': 'Test.',
                'responsible_party': 'claimant',
                'required_items': [],
            },
            'form_changes': [],
            'state_changes': [],
            'proposed_signals': [],
            'required_tools': [],
            'next_action_requirements': [],
            'handoff_priority': None,
            'controlled_rule_authorised': False,
        }
    )
    registry = ModelGatewayRegistry()
    registry.register('custom_test', lambda _config: StaticGateway(response))
    settings = Settings(
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='custom_test',
        model_base_url='https://custom.example/model',
        model_identifier='custom-model',
    )

    with TestClient(create_app(settings, model_gateway_registry=registry)) as client:
        readiness = client.get('/health/ready')
        openapi = client.get('/openapi.json').json()

    assert readiness.json()['checks']['agent'] == 'configured'
    assert all('model' not in path for path in openapi['paths'])


def test_gateway_agent_requires_structured_output_at_composition() -> None:
    registry = ModelGatewayRegistry()
    registry.register(
        'no_structured_output',
        lambda _config: OpenAICompatibleModelGateway(gateway_config(structured_output=False)),
    )
    settings = Settings(
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter='no_structured_output',
        model_base_url='https://custom.example/model',
        model_identifier='custom-model',
        model_supports_structured_output=False,
    )

    with pytest.raises(ModelGatewayError) as captured:
        create_app(settings, model_gateway_registry=registry)

    assert captured.value.code is ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY


def test_missing_credential_reference_fails_without_naming_or_echoing_a_secret() -> None:
    gateway = OpenAICompatibleModelGateway(
        gateway_config(credential_environment_variable='MISSING_MODEL_SECRET')
    )

    with pytest.raises(ModelGatewayError) as captured:
        gateway.complete(ModelRequest(messages=[]))

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION
    assert 'MISSING_MODEL_SECRET' not in str(captured.value)


def test_endpoint_credentials_are_rejected_as_configuration() -> None:
    with pytest.raises(ModelGatewayError) as captured:
        gateway_config(base_url='https://embedded:secret@provider.example/v1')

    assert captured.value.code is ModelGatewayErrorCode.CONFIGURATION
    assert 'embedded' not in str(captured.value)
    assert 'secret' not in str(captured.value)
