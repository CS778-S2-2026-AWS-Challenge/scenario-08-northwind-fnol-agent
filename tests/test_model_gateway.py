import json
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.adapters.model_gateway import (
    BedrockConverseModelGateway,
    ModelGatewayConfig,
    ModelGatewayRegistry,
    OpenAICompatibleModelGateway,
)
from backend.app import create_app
from backend.core.auth import Principal
from backend.core.config import AgentRuntimeProfile, Settings
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelMessage,
    ModelProfile,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelTool,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentProposalSource,
    AuthorityOutcome,
    Channel,
    CustomerNextStep,
    FormSource,
    FormStatus,
    FraudSignal,
    NeededFor,
    ResponsibleParty,
    StructuredFormField,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentTurnContext, authorised_state_changes, validate_proposal
from backend.services.model_agent import GatewayAgent
from backend.services.workbench import get_workbench_claim_detail


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


def test_bedrock_converse_gateway_normalises_structured_output_and_usage() -> None:
    class FakeBedrockClient:
        def __init__(self) -> None:
            self.payload: dict[str, object] | None = None

        def converse(self, **payload: object) -> dict[str, object]:
            self.payload = payload
            return {
                'output': {
                    'message': {
                        'role': 'assistant',
                        'content': [{'text': '{"action":"ASK"}'}],
                    }
                },
                'stopReason': 'end_turn',
                'usage': {'inputTokens': 9, 'outputTokens': 3, 'totalTokens': 12},
                'ResponseMetadata': {'RequestId': 'bedrock-request-1'},
            }

    client = FakeBedrockClient()
    gateway = BedrockConverseModelGateway(
        ModelGatewayConfig(
            base_url='',
            model='amazon.test-model',
            credential_environment_variable=None,
            timeout_seconds=5.0,
            capabilities=ModelCapabilities(structured_output=True),
            protocol='bedrock_converse',
            region='us-west-2',
            profile=ModelProfile(
                profile_id='bedrock-test',
                protocol='bedrock_converse',
                provider='aws',
                model_identifier='amazon.test-model',
                purpose='agent_turn',
                privacy_class='synthetic_fnol',
                capabilities=ModelCapabilities(structured_output=True),
                timeout_seconds=5.0,
                prompt_version='v1',
            ),
        ),
        client=client,
    )

    response = gateway.complete(
        ModelRequest(
            messages=[
                ModelMessage(role=ModelRole.SYSTEM, content='Return a proposal.'),
                ModelMessage(role=ModelRole.USER, content='Synthetic incident.'),
            ],
            response_schema={'type': 'object'},
        )
    )

    assert client.payload is not None
    assert client.payload['modelId'] == 'amazon.test-model'
    assert response.structured_output == {'action': 'ASK'}
    assert response.provider_request_id == 'bedrock-request-1'
    assert response.usage is not None and response.usage.total_tokens == 12


def test_bedrock_converse_requires_region_and_normalises_provider_failure() -> None:
    with pytest.raises(ModelGatewayError) as invalid_config:
        ModelGatewayConfig(
            base_url='',
            model='amazon.test-model',
            credential_environment_variable=None,
            timeout_seconds=5.0,
            capabilities=ModelCapabilities(),
            protocol='bedrock_converse',
        )
    assert invalid_config.value.code is ModelGatewayErrorCode.CONFIGURATION

    class FailingClient:
        def converse(self, **_payload: object) -> object:
            error = RuntimeError('provider body must not leak')
            error.response = {'ResponseMetadata': {'HTTPStatusCode': 500}}  # type: ignore[attr-defined]
            raise error

    gateway = BedrockConverseModelGateway(
        ModelGatewayConfig(
            base_url='',
            model='amazon.test-model',
            credential_environment_variable=None,
            timeout_seconds=5.0,
            capabilities=ModelCapabilities(),
            protocol='bedrock_converse',
            region='us-west-2',
        ),
        client=FailingClient(),
    )
    with pytest.raises(ModelGatewayError) as provider_error:
        gateway.complete(ModelRequest(messages=[]))
    assert provider_error.value.code is ModelGatewayErrorCode.PROVIDER
    assert provider_error.value.retryable is True
    assert 'provider body' not in str(provider_error.value)


def test_model_gateway_config_and_registry_reject_invalid_boundaries() -> None:
    with pytest.raises(ModelGatewayError, match='configuration'):
        gateway_config(base_url='not a url')
    with pytest.raises(ModelGatewayError, match='configuration'):
        gateway_config(model='')

    registry = ModelGatewayRegistry()
    registry.register('custom', lambda _config: OpenAICompatibleModelGateway(gateway_config()))
    with pytest.raises(ValueError, match='non-empty and unique'):
        registry.register('CUSTOM', lambda _config: OpenAICompatibleModelGateway(gateway_config()))
    with pytest.raises(ModelGatewayError, match='configuration'):
        registry.create('missing', gateway_config())


def test_bedrock_converse_maps_tool_use_and_budget() -> None:
    class ToolClient:
        def __init__(self) -> None:
            self.payload: dict[str, object] | None = None

        def converse(self, **payload: object) -> dict[str, object]:
            self.payload = payload
            return {
                'output': {
                    'message': {
                        'role': 'assistant',
                        'content': [
                            {
                                'toolUse': {
                                    'toolUseId': 'tool-1',
                                    'name': 'lookup_policy',
                                    'input': {'reference': 'synthetic-policy'},
                                }
                            }
                        ],
                    }
                }
            }

    client = ToolClient()
    gateway = BedrockConverseModelGateway(
        ModelGatewayConfig(
            base_url='',
            model='amazon.test-model',
            credential_environment_variable=None,
            timeout_seconds=5.0,
            capabilities=ModelCapabilities(tools=True),
            protocol='bedrock_converse',
            region='us-west-2',
        ),
        client=client,
    )
    response = gateway.complete(
        ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content='Use the tool.')],
            token_budget=128,
            tools=[
                ModelTool(
                    name='lookup_policy',
                    description='Lookup synthetic policy facts.',
                    input_schema={'type': 'object'},
                )
            ],
        )
    )
    assert client.payload is not None
    assert client.payload['inferenceConfig'] == {'maxTokens': 128}
    assert 'toolConfig' in client.payload
    assert response.tool_calls[0].call_id == 'tool-1'


@pytest.mark.parametrize(
    ('status', 'expected'),
    [
        (401, ModelGatewayErrorCode.AUTHENTICATION),
        (429, ModelGatewayErrorCode.RATE_LIMIT),
        (500, ModelGatewayErrorCode.PROVIDER),
    ],
)
def test_bedrock_provider_statuses_are_normalised(
    status: int,
    expected: ModelGatewayErrorCode,
) -> None:
    class ProviderError(RuntimeError):
        pass

    error = ProviderError('provider detail')
    error.response = {'ResponseMetadata': {'HTTPStatusCode': status}}  # type: ignore[attr-defined]

    with pytest.raises(ModelGatewayError) as captured:
        BedrockConverseModelGateway._raise_provider_error(error)
    assert captured.value.code is expected


def test_bedrock_timeout_and_credential_errors_are_normalised() -> None:
    class TimeoutError(RuntimeError):
        pass

    class CredentialError(RuntimeError):
        pass

    with pytest.raises(ModelGatewayError) as timeout:
        BedrockConverseModelGateway._raise_provider_error(TimeoutError())
    assert timeout.value.code is ModelGatewayErrorCode.TIMEOUT
    assert timeout.value.retryable is True

    with pytest.raises(ModelGatewayError) as credential:
        BedrockConverseModelGateway._raise_provider_error(CredentialError())
    assert credential.value.code is ModelGatewayErrorCode.AUTHENTICATION
    assert credential.value.retryable is False


def test_bedrock_malformed_response_is_rejected() -> None:
    gateway = BedrockConverseModelGateway(
        ModelGatewayConfig(
            base_url='',
            model='amazon.test-model',
            credential_environment_variable=None,
            timeout_seconds=5.0,
            capabilities=ModelCapabilities(),
            protocol='bedrock_converse',
            region='us-west-2',
        ),
        client=object(),
    )
    with pytest.raises(ModelGatewayError, match='invalid response'):
        gateway._normalise_response({'output': {'message': {'content': 'not-a-list'}}})


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

    oversized_provenance_gateway = OpenAICompatibleModelGateway(
        gateway_config(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    'model': 'm' * 301,
                    'choices': [
                        {
                            'finish_reason': 'stop',
                            'message': {'role': 'assistant', 'content': 'ok'},
                        }
                    ],
                },
            )
        ),
    )
    with pytest.raises(ModelGatewayError) as oversized_provenance_error:
        oversized_provenance_gateway.complete(ModelRequest(messages=[]))
    assert oversized_provenance_error.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE


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


class FailingGateway:
    def __init__(self, code: ModelGatewayErrorCode, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True, tools=False)

    def complete(self, _request: ModelRequest) -> ModelResponse:
        raise ModelGatewayError(self.code, retryable=self.retryable)


def model_gateway_settings(protocol: str) -> Settings:
    return Settings(
        agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
        model_protocol_adapter=protocol,
        model_base_url='https://model.example.test/v1',
        model_identifier='northwind-test-model',
    )


def submit_model_message(
    gateway: StaticGateway | FailingGateway,
    *,
    protocol: str,
) -> tuple[httpx.Response, FixtureRepository, WorkingClaim, str, str]:
    registry = ModelGatewayRegistry()
    registry.register(protocol, lambda _config: gateway)
    repository = FixtureRepository()
    headers = {'Authorization': 'Bearer synthetic-claimant'}
    with TestClient(
        create_app(
            model_gateway_settings(protocol),
            repository=repository,
            model_gateway_registry=registry,
        ),
        raise_server_exceptions=False,
    ) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**headers, 'Idempotency-Key': f'{protocol}-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
        )
        assert created.status_code == 201
        claim_id = created.json()['claim']['claim_id']
        session_id = created.json()['session']['session_id']
        before_claim = repository.get_claim(claim_id, 'cus_demo')
        assert before_claim is not None
        response = client.post(
            f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages',
            headers={
                **headers,
                'Idempotency-Key': f'{protocol}-message',
                'If-Match': '1',
            },
            json={
                'client_message_id': f'{protocol}-client-message',
                'content': {'type': 'text', 'text': 'A synthetic rear-end incident.'},
                'evidence_refs': [],
            },
        )
    return response, repository, before_claim, claim_id, session_id


def assert_model_message_failure_is_atomic(
    repository: FixtureRepository,
    before_claim: WorkingClaim,
    claim_id: str,
    session_id: str,
    protocol: str,
) -> None:
    assert repository.get_claim(claim_id, 'cus_demo') == before_claim
    assert repository.list_messages(claim_id, session_id, 'cus_demo') == []
    assert repository.list_agent_decisions(claim_id, 'cus_demo') == []
    route = f'/api/v1/claims/{claim_id}/sessions/{session_id}/messages'
    assert repository.find_idempotency('cus_demo', route, f'{protocol}-message') is None


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


def _form_field(
    value: object,
    timestamp: datetime,
    *,
    needed_for: NeededFor = NeededFor.CURRENT_ACTION,
) -> StructuredFormField:
    return StructuredFormField(
        value=value,
        source=FormSource.CLAIMANT,
        source_refs=['msg_private_gateway'],
        status=FormStatus.CONFIRMED,
        needed_for=needed_for,
        confidence=1.0,
        updated_at=timestamp,
        updated_by=ActorReference(
            actor_type=ActorType.CLAIMANT,
            actor_id='cus_private_gateway',
        ),
    )


def _model_proposal_output(
    *,
    action: str = 'UPDATE',
    customer_reason: str = 'The claimant supplied an update.',
    customer_response: str = 'The update was recorded.',
    next_step_summary: str = 'Continue the report.',
    form_changes: list[dict[str, object]] | None = None,
    state_changes: list[dict[str, object]] | None = None,
    proposed_signals: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        'action': action,
        'reason_codes': ['MODEL_UPDATE'],
        'customer_reason': customer_reason,
        'customer_response': customer_response,
        'customer_next_step': {
            'status': 'continue',
            'summary': next_step_summary,
            'responsible_party': 'claimant',
            'required_items': [],
        },
        'form_changes': form_changes or [],
        'state_changes': state_changes or [],
        'proposed_signals': proposed_signals or [],
        'required_tools': [],
        'next_action_requirements': [],
        'handoff_priority': None,
    }


def test_gateway_agent_uses_neutral_contract_and_keeps_authority_external() -> None:
    gateway = StaticGateway(
        ModelResponse(
            provider_model='provider-model-private',
            provider_request_id='provider-request-private',
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
                'form_changes': [
                    {
                        'field_code': 'incident.description',
                        'value': 'A proposed incident description.',
                        'needed_for': 'current_action',
                        'confidence': 0.8,
                    }
                ],
                'state_changes': [{'path': 'claim_state.next_action', 'to': 'CREATE_CLAIM'}],
                'proposed_signals': [],
                'required_tools': [],
                'next_action_requirements': [],
                'handoff_priority': None,
            },
        )
    )
    agent = GatewayAgent(gateway)
    timestamp = datetime.now(UTC)
    claim = _working_claim().model_copy(
        update={
            'claim_id': 'clm_private_gateway',
            'customer_id': 'cus_private_gateway',
            'route': 'internal-model-route',
            'active_session_id': 'ses_private_gateway',
            'external_claim_fingerprint': 'private-external-fingerprint',
            'assessor_routing_fingerprint': 'private-assessor-fingerprint',
            'claim_state': _working_claim().claim_state.model_copy(
                update={'fraud_signal': FraudSignal.REVIEW_REQUIRED}
            ),
            'form': {
                'incident.description': _form_field('A synthetic rear-end incident.', timestamp),
                'incident.location': _form_field('Synthetic Road', timestamp),
                'policy.policy_number': _form_field(
                    'POLICY-PRIVATE', timestamp, needed_for=NeededFor.LATER_ACTION
                ),
                'vehicle.registration': _form_field(
                    'REG-PRIVATE', timestamp, needed_for=NeededFor.LATER_ACTION
                ),
                'authorities.police_report_reference': _form_field(
                    'POLICE-PRIVATE', timestamp, needed_for=NeededFor.LATER_ACTION
                ),
                'incident.cause': _form_field(
                    'Cause for later action', timestamp, needed_for=NeededFor.LATER_ACTION
                ),
            },
        }
    )
    proposal = agent.propose_turn(
        AgentTurnContext(
            claim=claim,
            session_id='ses-gateway',
            trigger_message_id='msg-gateway',
            message_text='Please create the claim.',
            evidence_refs=['evd_private_gateway'],
        )
    )

    assert gateway.last_request is not None
    assert gateway.last_request.response_schema is not None
    model_context = json.loads(gateway.last_request.messages[1].content)
    assert set(model_context) == {
        'claim',
        'message_text',
        'evidence_reference_count',
        'professional_review_required',
    }
    assert model_context['evidence_reference_count'] == 1
    assert set(model_context['claim']) == {
        'channel',
        'locale',
        'incident_type',
        'claim_state',
        'form',
        'evidence_summary',
        'customer_next_step',
    }
    assert 'fraud_signal' not in model_context['claim']['claim_state']
    assert set(model_context['claim']['form']) == {'incident.description'}
    assert set(model_context['claim']['form']['incident.description']) == {
        'value',
        'source',
        'status',
        'needed_for',
        'confidence',
    }
    serialised_context = json.dumps(model_context)
    for private_value in (
        'clm_private_gateway',
        'cus_private_gateway',
        'ses_private_gateway',
        'msg_private_gateway',
        'evd_private_gateway',
        'private-external-fingerprint',
        'private-assessor-fingerprint',
        'internal-model-route',
        'Synthetic Road',
        'POLICY-PRIVATE',
        'REG-PRIVATE',
        'POLICE-PRIVATE',
        'Cause for later action',
    ):
        assert private_value not in serialised_context
    assert proposal.action is AgentAction.CREATE_CLAIM
    assert proposal.proposal_source is AgentProposalSource.MODEL_GATEWAY
    assert proposal.model_provenance is not None
    assert proposal.model_provenance.provider_model == 'provider-model-private'
    assert proposal.model_provenance.provider_request_id == 'provider-request-private'
    assert proposal.form_changes[0].source is FormSource.INFERENCE
    assert proposal.form_changes[0].status is FormStatus.PROPOSED
    authority = validate_proposal(proposal)
    assert authority.outcome is AuthorityOutcome.REVIEW_REQUIRED
    assert authorised_state_changes(proposal, authority) == []


@pytest.mark.parametrize(
    ('action', 'state_changes', 'expected_outcome'),
    [
        ('UPDATE', [{'path': 'claim_state.next_action', 'to': 'UPDATE'}], 'authorised'),
        (
            'CREATE_CLAIM',
            [{'path': 'claim_state.next_action', 'to': 'CREATE_CLAIM'}],
            'review_required',
        ),
        ('UPDATE', [{'path': 'claim_state.coverage', 'to': 'clear'}], 'blocked'),
    ],
)
def test_model_claimant_text_is_rendered_by_deterministic_authority(
    action: str,
    state_changes: list[dict[str, object]],
    expected_outcome: str,
) -> None:
    unsafe_text = (
        'Your claim is approved and not rejected. Northwind accepts liability, you are '
        'fraudulent, and emergency services were contacted.'
    )
    protocol = f'unsafe_claimant_text_{expected_outcome}'
    gateway = StaticGateway(
        ModelResponse(
            provider_model='private-provider-model',
            provider_request_id='private-provider-request',
            structured_output=_model_proposal_output(
                action=action,
                customer_reason=unsafe_text,
                customer_response=unsafe_text,
                next_step_summary=unsafe_text,
                state_changes=state_changes,
            ),
        )
    )

    response, repository, _before_claim, claim_id, session_id = submit_model_message(
        gateway,
        protocol=protocol,
    )

    assert response.status_code == 200
    decision = repository.list_agent_decisions(claim_id, 'cus_demo')[-1]
    assert decision.authority.outcome.value == expected_outcome
    claimant_payload = response.text.lower()
    for unsafe_fragment in (
        'approved',
        'rejected',
        'accepts liability',
        'fraudulent',
        'emergency services were contacted',
        'private-provider-model',
        'private-provider-request',
    ):
        assert unsafe_fragment not in claimant_payload
    messages = repository.list_messages(claim_id, session_id, 'cus_demo')
    assert unsafe_text not in str([message.content for message in messages])
    assert unsafe_text not in decision.customer_reason
    assert unsafe_text not in decision.customer_response
    assert unsafe_text not in decision.customer_next_step.summary


def test_model_signal_injection_is_rejected_before_workbench_persistence() -> None:
    protocol = 'invented_model_signal'
    gateway = StaticGateway(
        ModelResponse(
            structured_output=_model_proposal_output(
                proposed_signals=[
                    {
                        'signal_id': 'fraud_confirmed',
                        'code': 'FRAUD_CONFIRMED',
                        'status': 'confirmed',
                    }
                ]
            )
        )
    )

    response, repository, before_claim, claim_id, session_id = submit_model_message(
        gateway,
        protocol=protocol,
    )

    assert response.status_code == 502
    assert_model_message_failure_is_atomic(
        repository,
        before_claim,
        claim_id,
        session_id,
        protocol,
    )
    detail = get_workbench_claim_detail(
        repository,
        Principal(subject='stf_demo', actor_type='staff'),
        claim_id,
    )
    assert detail.signals == []


def test_model_provenance_is_persisted_without_claimant_exposure() -> None:
    protocol = 'model_provenance'
    gateway = StaticGateway(
        ModelResponse(
            provider_model='provider-model-audit-only',
            provider_request_id='provider-request-audit-only',
            structured_output=_model_proposal_output(
                form_changes=[
                    {
                        'field_code': 'incident.description',
                        'value': 'A model-proposed incident description.',
                    }
                ],
                state_changes=[{'path': 'claim_state.next_action', 'to': 'UPDATE'}],
            ),
        )
    )

    response, repository, _before_claim, claim_id, _session_id = submit_model_message(
        gateway,
        protocol=protocol,
    )

    assert response.status_code == 200
    assert 'provider-model-audit-only' not in response.text
    assert 'provider-request-audit-only' not in response.text
    decision = repository.list_agent_decisions(claim_id, 'cus_demo')[-1]
    assert decision.proposal_source is AgentProposalSource.MODEL_GATEWAY
    assert decision.model_provenance is not None
    assert decision.model_provenance.provider_model == 'provider-model-audit-only'
    assert decision.model_provenance.provider_request_id == 'provider-request-audit-only'
    assert decision.form_changes['incident.description'].updated_by.actor_id == 'model_gateway'


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

    with pytest.raises(ModelGatewayError) as captured:
        GatewayAgent(gateway).propose_turn(
            AgentTurnContext(
                claim=_working_claim(),
                session_id='ses-gateway',
                trigger_message_id='msg-gateway',
                message_text='I want a person.',
                evidence_refs=[],
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE


@pytest.mark.parametrize(
    ('metadata_name', 'metadata_value'),
    [
        ('source', 'claimant'),
        ('source', 'staff'),
        ('source', 'policy'),
        ('status', 'confirmed'),
    ],
)
def test_gateway_agent_rejects_model_controlled_fact_metadata(
    metadata_name: str,
    metadata_value: str,
) -> None:
    form_change = {
        'field_code': 'incident.description',
        'value': 'A model-proposed description.',
        metadata_name: metadata_value,
    }
    gateway = StaticGateway(
        ModelResponse(
            structured_output={
                'action': 'UPDATE',
                'reason_codes': ['MODEL_FACT_PROPOSAL'],
                'customer_reason': 'A fact was proposed.',
                'customer_response': 'Please review the proposed information.',
                'customer_next_step': {
                    'status': 'review_proposal',
                    'summary': 'Review the proposed information.',
                    'responsible_party': 'claimant',
                    'required_items': [],
                },
                'form_changes': [form_change],
                'state_changes': [],
                'proposed_signals': [],
                'required_tools': [],
                'next_action_requirements': [],
                'handoff_priority': None,
            }
        )
    )

    with pytest.raises(ModelGatewayError) as captured:
        GatewayAgent(gateway).propose_turn(
            AgentTurnContext(
                claim=_working_claim(),
                session_id='ses-gateway',
                trigger_message_id='msg-gateway',
                message_text='A synthetic incident.',
                evidence_refs=[],
            )
        )

    assert captured.value.code is ModelGatewayErrorCode.MALFORMED_RESPONSE


def test_model_fact_metadata_rejection_is_bounded_and_atomic_at_message_api() -> None:
    protocol = 'malicious_fact_metadata'
    gateway = StaticGateway(
        ModelResponse(
            structured_output={
                'action': 'UPDATE',
                'reason_codes': ['MODEL_FACT_PROPOSAL'],
                'customer_reason': 'A fact was proposed.',
                'customer_response': 'Please review the proposed information.',
                'customer_next_step': {
                    'status': 'review_proposal',
                    'summary': 'Review the proposed information.',
                    'responsible_party': 'claimant',
                    'required_items': [],
                },
                'form_changes': [
                    {
                        'field_code': 'incident.description',
                        'value': 'A model-controlled description.',
                        'source': 'claimant',
                        'status': 'confirmed',
                    }
                ],
                'state_changes': [],
                'proposed_signals': [],
                'required_tools': [],
                'next_action_requirements': [],
                'handoff_priority': None,
            }
        )
    )

    response, repository, before_claim, claim_id, session_id = submit_model_message(
        gateway,
        protocol=protocol,
    )

    assert response.status_code == 502
    assert response.json()['error'] == {
        'code': 'DEPENDENCY_FAILED',
        'message': 'The model service could not complete the request. The claim is unchanged.',
        'request_id': response.headers['X-Request-ID'],
        'retryable': False,
    }
    assert_model_message_failure_is_atomic(
        repository,
        before_claim,
        claim_id,
        session_id,
        protocol,
    )


@pytest.mark.parametrize(
    ('gateway_code', 'gateway_retryable', 'status_code', 'api_code', 'api_retryable'),
    [
        (ModelGatewayErrorCode.TIMEOUT, True, 503, 'DEPENDENCY_UNAVAILABLE', True),
        (ModelGatewayErrorCode.RATE_LIMIT, True, 503, 'DEPENDENCY_UNAVAILABLE', True),
        (ModelGatewayErrorCode.AUTHENTICATION, False, 502, 'DEPENDENCY_FAILED', False),
        (ModelGatewayErrorCode.CONFIGURATION, False, 502, 'DEPENDENCY_FAILED', False),
    ],
)
def test_model_gateway_failures_are_bounded_and_atomic_at_message_api(
    gateway_code: ModelGatewayErrorCode,
    gateway_retryable: bool,
    status_code: int,
    api_code: str,
    api_retryable: bool,
) -> None:
    protocol = f'failing_{gateway_code.value}'
    response, repository, before_claim, claim_id, session_id = submit_model_message(
        FailingGateway(gateway_code, retryable=gateway_retryable),
        protocol=protocol,
    )

    assert response.status_code == status_code
    error = response.json()['error']
    assert error['code'] == api_code
    assert error['retryable'] is api_retryable
    assert 'model.example.test' not in response.text
    assert gateway_code.value not in response.text
    assert_model_message_failure_is_atomic(
        repository,
        before_claim,
        claim_id,
        session_id,
        protocol,
    )


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
