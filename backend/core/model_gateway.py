from backend.adapters.model_gateway import (
    ModelGatewayConfig,
    ModelGatewayRegistry,
    default_model_gateway_registry,
)
from backend.core.config import Settings
from backend.domain.model_gateway import ModelCapabilities, ModelGateway


def build_model_gateway(
    settings: Settings,
    registry: ModelGatewayRegistry | None = None,
) -> ModelGateway:
    resolved_registry = registry or default_model_gateway_registry()
    return resolved_registry.create(
        settings.model_protocol_adapter,
        ModelGatewayConfig(
            base_url=settings.model_base_url,
            model=settings.model_identifier,
            credential_environment_variable=settings.model_api_key_env,
            timeout_seconds=settings.model_timeout_seconds,
            capabilities=ModelCapabilities(
                structured_output=settings.model_supports_structured_output,
                tools=settings.model_supports_tools,
            ),
        ),
    )
