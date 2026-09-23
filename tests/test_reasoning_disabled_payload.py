"""Provider-specific reasoning controls verified against the published profiles."""

import httpx
import pytest

from backend.adapters.model_gateway import (
    GoogleGenerateContentModelGateway,
    OpenAICompatibleModelGateway,
)
from backend.domain.model_gateway import ModelGatewayError, ModelMessage, ModelRequest, ModelRole
from tests.test_model_gateway import gateway_config


def request() -> ModelRequest:
    return ModelRequest(
        model_profile_id='test-profile',
        purpose='agent_turn',
        prompt_version='current',
        privacy_class='synthetic_fnol',
        messages=[ModelMessage(role=ModelRole.USER, content='Record a rear-end collision.')],
        max_output_tokens=4500,
    )


def test_gemini_35_uses_verified_minimal_thinking_level() -> None:
    gateway = GoogleGenerateContentModelGateway(
        gateway_config(
            model='gemini-3.5-flash-lite',
            protocol='google_generate_content',
            reasoning_mode='disabled',
        )
    )
    payload = gateway._request_payload(request())
    generation = payload['generationConfig']
    assert isinstance(generation, dict)
    thinking = generation['thinkingConfig']
    assert thinking == {'thinkingLevel': 'minimal'}
    assert 'thinkingBudget' not in thinking


def test_openrouter_nonreasoning_model_does_not_send_reasoning_controls() -> None:
    gateway = OpenAICompatibleModelGateway(
        gateway_config(
            model='openai/gpt-4o-mini',
            base_url='https://openrouter.ai/api/v1',
        )
    )
    payload = gateway._request_payload(request())
    assert not {'reasoning_effort', 'reasoning', 'chat_template_kwargs'} & set(payload)


def test_provider_error_keeps_only_status_and_bounded_type() -> None:
    gateway = OpenAICompatibleModelGateway(
        gateway_config(model='openai/gpt-4o-mini'),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                400,
                json={
                    'error': {'type': 'invalid_request_error', 'message': 'sensitive provider text'}
                },
            )
        ),
    )
    with pytest.raises(ModelGatewayError) as caught:
        gateway.complete(request())
    assert caught.value.provider_status == 400
    assert caught.value.provider_error_type == 'invalid_request_error'
    assert 'sensitive' not in str(caught.value)
