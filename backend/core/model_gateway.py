from backend.adapters.model_gateway import (
    ModelGatewayConfig,
    ModelGatewayRegistry,
    default_model_gateway_registry,
)
from backend.core.config import Settings
from backend.domain.model_gateway import ModelCapabilities, ModelGateway, ModelProfile


def build_model_gateway(
    settings: Settings,
    registry: ModelGatewayRegistry | None = None,
) -> ModelGateway:
    resolved_registry = registry or default_model_gateway_registry()
    capabilities = ModelCapabilities(
        structured_output=settings.model_supports_structured_output,
        tools=settings.model_supports_tools,
    )
    profile = ModelProfile(
        profile_id=settings.model_profile_id,
        protocol=settings.model_protocol_adapter,
        provider=settings.model_provider,
        model_identifier=settings.model_identifier,
        credential_reference=settings.model_api_key_env,
        purpose=settings.model_purpose,
        privacy_class=settings.model_privacy_class,
        capabilities=capabilities,
        timeout_seconds=settings.model_timeout_seconds,
        prompt_version=settings.model_prompt_version,
    )
    return resolved_registry.create(
        settings.model_protocol_adapter,
        ModelGatewayConfig(
            base_url=settings.model_base_url,
            model=settings.model_identifier,
            credential_environment_variable=settings.model_api_key_env,
            timeout_seconds=settings.model_timeout_seconds,
            capabilities=capabilities,
            protocol=settings.model_protocol_adapter,
            region=settings.model_region,
            profile=profile,
        ),
    )
