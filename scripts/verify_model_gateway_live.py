"""Exercise a configured model gateway with synthetic FNOL context.

This command intentionally performs a real provider call. It must only be run with an
explicitly authorised, budgeted environment and synthetic data. No credential or full model
response is printed.
"""

import json

from backend.core.config import AgentRuntimeProfile, Settings
from backend.core.model_gateway import build_model_gateway
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelMessage,
    ModelRequest,
    ModelRole,
)


def main() -> int:
    settings = Settings.from_environment()
    if settings.agent_runtime_profile is not AgentRuntimeProfile.MODEL_GATEWAY:
        raise SystemExit('Set AGENT_RUNTIME_PROFILE=model_gateway before running this command.')

    gateway = build_model_gateway(settings)
    response = gateway.complete(
        ModelRequest(
            purpose=settings.model_purpose,
            prompt_version=settings.model_prompt_version,
            privacy_class=settings.model_privacy_class,
            required_capabilities=ModelCapabilities(structured_output=True),
            messages=[
                ModelMessage(
                    role=ModelRole.SYSTEM,
                    content=(
                        'You are a Northwind FNOL proposal generator. Return a JSON object '
                        'with an action and a short customer-safe response. Use only the '
                        'synthetic incident supplied by the user.'
                    ),
                ),
                ModelMessage(
                    role=ModelRole.USER,
                    content=json.dumps(
                        {
                            'incident_type': 'motor',
                            'incident_description': (
                                'Synthetic rear-end collision; no injury reported.'
                            ),
                            'urgency': 'normal',
                        },
                        separators=(',', ':'),
                    ),
                ),
            ],
            response_schema={
                'type': 'object',
                'properties': {
                    'action': {'type': 'string'},
                    'response': {'type': 'string'},
                },
                'required': ['action', 'response'],
                'additionalProperties': False,
            },
        )
    )
    if response.completion_status is not ModelCompletionStatus.COMPLETE:
        raise SystemExit('The model endpoint did not return a complete response.')
    if response.structured_output is None:
        raise SystemExit('The model endpoint did not return the required structured output.')
    print(
        json.dumps(
            {
                'status': 'live_call_succeeded',
                'profile_id': settings.model_profile_id,
                'protocol': settings.model_protocol_adapter,
                'provider': settings.model_provider,
                'model': response.provider_model,
                'request_id_present': bool(response.provider_request_id),
                'usage': response.usage.model_dump(mode='json') if response.usage else None,
                'capabilities': gateway.capabilities.model_dump(mode='json'),
            },
            separators=(',', ':'),
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
