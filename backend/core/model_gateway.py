from backend.adapters.model_gateway import (
    ModelGatewayConfig,
    ModelGatewayRegistry,
    default_model_gateway_registry,
)
from backend.core.config import Settings
from backend.domain.configuration import ModelRuntimeConfiguration
from backend.domain.model_gateway import (
    CLAIMANT_AGENT_PRIVACY_CLASS,
    CLAIMANT_AGENT_PURPOSE,
    ModelCapabilities,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelProfile,
    ModelProfileStatus,
    ModelRequest,
    ModelResponse,
)
from backend.prompts import MOTOR_CLAIMANT_PROMPT_ID
from backend.repositories.configuration import ConfigurationRepository


def _model_gateway_config_from_runtime(
    configuration: ModelRuntimeConfiguration,
) -> ModelGatewayConfig:
    capabilities = ModelCapabilities(
        structured_output=configuration.structured_output,
        tools=configuration.tools,
    )
    profile = ModelProfile(
        profile_id=configuration.profile_id,
        protocol=configuration.protocol,
        provider=configuration.provider,
        model_identifier=configuration.model_identifier,
        credential_reference=configuration.credential_environment_variable,
        purpose=configuration.purpose,
        privacy_class=configuration.privacy_class,
        capabilities=capabilities,
        timeout_seconds=configuration.timeout_seconds,
        prompt_version=configuration.prompt_version,
        evaluation_status=ModelProfileStatus(configuration.evaluation_status),
    )
    return ModelGatewayConfig(
        base_url=configuration.base_url,
        model=configuration.model_identifier,
        credential_environment_variable=configuration.credential_environment_variable,
        timeout_seconds=configuration.timeout_seconds,
        capabilities=capabilities,
        profile=profile,
    )


def _runtime_configuration_matches_settings(
    configuration: ModelRuntimeConfiguration,
    settings: Settings,
) -> bool:
    return (
        configuration.evaluation_status == ModelProfileStatus.CONFIGURED.value
        and configuration.protocol.strip().lower()
        == settings.model_protocol_adapter.strip().lower()
        and configuration.base_url.rstrip('/') == settings.model_base_url.rstrip('/')
        and configuration.credential_environment_variable == settings.model_api_key_env
        and configuration.purpose == CLAIMANT_AGENT_PURPOSE
        and configuration.privacy_class == CLAIMANT_AGENT_PRIVACY_CLASS
        and configuration.prompt_version == MOTOR_CLAIMANT_PROMPT_ID
        and configuration.structured_output
    )


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
        evaluation_status=ModelProfileStatus(settings.model_evaluation_status),
    )
    return resolved_registry.create(
        settings.model_protocol_adapter,
        ModelGatewayConfig(
            base_url=settings.model_base_url,
            model=settings.model_identifier,
            credential_environment_variable=settings.model_api_key_env,
            timeout_seconds=settings.model_timeout_seconds,
            capabilities=capabilities,
            profile=profile,
        ),
    )


def build_scoped_model_gateway(
    settings: Settings,
    *,
    purpose: str,
    privacy_class: str,
    prompt_version: str,
    profile_suffix: str,
    registry: ModelGatewayRegistry | None = None,
) -> ModelGateway:
    """Build an explicit purpose profile over the configured provider connection."""

    resolved_registry = registry or default_model_gateway_registry()
    capabilities = ModelCapabilities(
        structured_output=settings.model_supports_structured_output,
        tools=settings.model_supports_tools,
    )
    profile = ModelProfile(
        profile_id=f'{settings.model_profile_id}-{profile_suffix}',
        protocol=settings.model_protocol_adapter,
        provider=settings.model_provider,
        model_identifier=settings.model_identifier,
        credential_reference=settings.model_api_key_env,
        purpose=purpose,
        privacy_class=privacy_class,
        capabilities=capabilities,
        timeout_seconds=settings.model_timeout_seconds,
        prompt_version=prompt_version,
        evaluation_status=ModelProfileStatus(settings.model_evaluation_status),
    )
    return resolved_registry.create(
        settings.model_protocol_adapter,
        ModelGatewayConfig(
            base_url=settings.model_base_url,
            model=settings.model_identifier,
            credential_environment_variable=settings.model_api_key_env,
            timeout_seconds=settings.model_timeout_seconds,
            capabilities=capabilities,
            profile=profile,
        ),
    )


class ConfigurationBackedModelGateway:
    """Resolve the active published model configuration for every model turn.

    The Settings-derived gateway is retained only as a bootstrap path for existing
    fixture callers. Once a published ``model`` configuration exists, it is the
    runtime authority and is resolved before the provider request is made.
    """

    def __init__(
        self,
        settings: Settings,
        configuration_repository: ConfigurationRepository,
        registry: ModelGatewayRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._configuration_repository = configuration_repository
        self._registry = registry

    @property
    def capabilities(self) -> ModelCapabilities:
        active = self._configuration_repository.active('model')
        if active is None:
            return build_model_gateway(self._settings, self._registry).capabilities
        try:
            configuration = ModelRuntimeConfiguration.model_validate(active.values)
        except ValueError as error:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from error
        if not _runtime_configuration_matches_settings(configuration, self._settings):
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        return ModelCapabilities(
            structured_output=configuration.structured_output,
            tools=configuration.tools,
        )

    def complete(self, request: ModelRequest) -> ModelResponse:
        active = self._configuration_repository.active('model')
        if active is None:
            gateway = build_model_gateway(self._settings, self._registry)
        else:
            try:
                configuration = ModelRuntimeConfiguration.model_validate(active.values)
            except ValueError as error:
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from error
            if not _runtime_configuration_matches_settings(configuration, self._settings):
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
            registry = self._registry or default_model_gateway_registry()
            gateway = registry.create(
                configuration.protocol,
                _model_gateway_config_from_runtime(configuration),
            )
        return gateway.complete(request)
