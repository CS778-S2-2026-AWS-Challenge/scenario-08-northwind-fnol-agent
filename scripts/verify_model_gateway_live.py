"""Exercise a configured model gateway with synthetic FNOL context.

This command intentionally performs a real provider call. It must only be run with an
explicitly authorised, budgeted environment and synthetic data. No credential or full model
response is printed.
"""

import json

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from backend.core.config import AgentRuntimeProfile, Settings
from backend.core.model_gateway import build_model_gateway
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelGatewayError,
    ModelMessage,
    ModelRequest,
    ModelRole,
)


class LiveVerificationOutput(BaseModel):
    """Strict structured result required for a successful live verification."""

    model_config = ConfigDict(extra='forbid')

    action: str
    response: str

    @field_validator('action', 'response')
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('value must not be blank')
        return value


def main() -> int:
    try:
        settings = Settings.from_environment()
        if settings.agent_runtime_profile is not AgentRuntimeProfile.MODEL_GATEWAY:
            print('status=live_call_not_run reason=MODEL_GATEWAY_PROFILE_REQUIRED')
            return 2

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
    except ModelGatewayError as error:
        retryable = str(error.retryable).lower()
        print(f'status=live_call_failed code={error.code.value} retryable={retryable}')
        return 1
    except ValueError:
        print('status=live_call_failed code=configuration retryable=false')
        return 1
    if response.completion_status is not ModelCompletionStatus.COMPLETE:
        print(
            f'status=live_call_failed code={response.completion_status.value}_response '
            'retryable=false'
        )
        return 1
    if response.structured_output is None:
        print('status=live_call_failed code=malformed_response retryable=false')
        return 1
    try:
        LiveVerificationOutput.model_validate(response.structured_output)
    except ValidationError:
        print('status=live_call_failed code=malformed_response retryable=false')
        return 1
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
