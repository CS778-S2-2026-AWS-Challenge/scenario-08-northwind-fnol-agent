from backend.adapters.model_gateway import (
    ModelGatewayConfig,
    ModelGatewayRegistry,
    default_model_gateway_registry,
)
from backend.core.config import Settings
from backend.domain.configuration import ConfigurationRecord, ModelRuntimeConfiguration
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
from backend.repositories.release_set import ReleaseSetRepository
from backend.services.model_profiles import (
    GPT_MODEL_PROFILE_ID,
    _secondary_settings_configuration,
)
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
    RuntimeConfigurationSnapshot,
)


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
    runtime_configuration: ModelRuntimeConfiguration | None = None,
) -> ModelGateway:
    """Build an explicit purpose profile over the configured provider connection.

    Args:
        settings: Bootstrap settings used when no published model configuration exists.
        purpose: Consumer purpose enforced by the resulting model profile.
        privacy_class: Data boundary enforced by the resulting model profile.
        prompt_version: Prompt contract enforced by the resulting model profile.
        profile_suffix: Stable suffix distinguishing this consumer profile.
        registry: Optional model protocol registry.
        runtime_configuration: Published provider-neutral model configuration selected
            by the active Release Set, when available.

    Returns:
        A provider-neutral gateway with the requested consumer boundary.

    Raises:
        ModelGatewayError: If the selected configuration cannot build a gateway.
    """

    resolved_registry = registry or default_model_gateway_registry()
    capabilities = ModelCapabilities(
        structured_output=(
            runtime_configuration.structured_output
            if runtime_configuration is not None
            else settings.model_supports_structured_output
        ),
        tools=(
            runtime_configuration.tools
            if runtime_configuration is not None
            else settings.model_supports_tools
        ),
    )
    profile_id = (
        runtime_configuration.profile_id if runtime_configuration else settings.model_profile_id
    )
    profile = ModelProfile(
        profile_id=f'{profile_id}-{profile_suffix}',
        protocol=(
            runtime_configuration.protocol
            if runtime_configuration is not None
            else settings.model_protocol_adapter
        ),
        provider=(
            runtime_configuration.provider
            if runtime_configuration is not None
            else settings.model_provider
        ),
        model_identifier=(
            runtime_configuration.model_identifier
            if runtime_configuration is not None
            else settings.model_identifier
        ),
        credential_reference=(
            runtime_configuration.credential_environment_variable
            if runtime_configuration is not None
            else settings.model_api_key_env
        ),
        purpose=purpose,
        privacy_class=privacy_class,
        capabilities=capabilities,
        timeout_seconds=(
            runtime_configuration.timeout_seconds
            if runtime_configuration is not None
            else settings.model_timeout_seconds
        ),
        prompt_version=prompt_version,
        evaluation_status=ModelProfileStatus(
            runtime_configuration.evaluation_status
            if runtime_configuration is not None
            else settings.model_evaluation_status
        ),
    )
    return resolved_registry.create(
        profile.protocol,
        ModelGatewayConfig(
            base_url=(
                runtime_configuration.base_url
                if runtime_configuration is not None
                else settings.model_base_url
            ),
            model=profile.model_identifier,
            credential_environment_variable=profile.credential_reference,
            timeout_seconds=profile.timeout_seconds,
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
        *,
        release_set_repository: ReleaseSetRepository | None = None,
        runtime_configuration_resolver: RuntimeConfigurationResolver | None = None,
    ) -> None:
        self._settings = settings
        self._configuration_repository = configuration_repository
        self._release_set_repository = release_set_repository
        self._registry = registry
        self._runtime_configuration_resolver = runtime_configuration_resolver

    def _active_model_configuration(
        self,
        profile_id: str | None = None,
    ) -> tuple[ModelRuntimeConfiguration | None, bool]:
        """Resolve the model and whether a published Release Set is authoritative."""
        try:
            if self._runtime_configuration_resolver is not None:
                snapshot = self._runtime_configuration_resolver.snapshot()
                if snapshot.release_set_id is not None:
                    configuration = snapshot.model(profile_id)
                else:
                    selected_profile = profile_id or self._settings.model_profile_id
                    configuration = self._configuration_repository.active('model', selected_profile)
                    if configuration is None and profile_id == GPT_MODEL_PROFILE_ID:
                        configuration = _secondary_settings_configuration(self._settings)
                    if configuration is None and profile_id is None:
                        configuration = self._configuration_repository.active('model')
                authoritative = snapshot.release_set_id is not None
            else:
                configuration = self._legacy_model_configuration(profile_id)
                authoritative = False
        except RuntimeConfigurationResolutionError:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from None
        if configuration is None:
            return None, authoritative
        try:
            return ModelRuntimeConfiguration.model_validate(configuration.values), authoritative
        except ValueError as error:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from error

    def _legacy_model_configuration(
        self,
        profile_id: str | None = None,
    ) -> ConfigurationRecord | None:
        """Resolve the pre-Release-Set model path for injected fixture callers."""
        configuration = None
        if self._release_set_repository is not None:
            release = self._release_set_repository.active(
                self._settings.environment,
                self._settings.data_runtime_profile.value,
            )
            if release is not None:
                reference = release.configuration_refs.get(f'model:{profile_id}') or (
                    release.configuration_refs.get('model')
                )
                if reference is None:
                    raise RuntimeConfigurationResolutionError(
                        f"Active release set {release.release_set_id!r} omits 'model'."
                    )
                configuration = self._configuration_repository.get(
                    reference.configuration_id,
                    reference.revision,
                )
                if (
                    configuration is None
                    or configuration.domain != 'model'
                    or configuration.state.value != 'published'
                ):
                    raise RuntimeConfigurationResolutionError(
                        f"Active release set {release.release_set_id!r} has an invalid 'model'."
                    )
        if configuration is not None:
            return configuration
        selected_profile = profile_id or self._settings.model_profile_id
        configuration = self._configuration_repository.active('model', selected_profile)
        if configuration is None and profile_id == GPT_MODEL_PROFILE_ID:
            configuration = _secondary_settings_configuration(self._settings)
        if configuration is None and profile_id is None:
            configuration = self._configuration_repository.active('model')
        return configuration

    @property
    def capabilities(self) -> ModelCapabilities:
        configuration, authoritative = self._active_model_configuration()
        if configuration is None:
            return build_model_gateway(self._settings, self._registry).capabilities
        if (
            not authoritative
            and configuration.profile_id != GPT_MODEL_PROFILE_ID
            and not _runtime_configuration_matches_settings(configuration, self._settings)
        ):
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
        return ModelCapabilities(
            structured_output=configuration.structured_output,
            tools=configuration.tools,
        )

    def complete(self, request: ModelRequest) -> ModelResponse:
        configuration, authoritative = self._active_model_configuration(request.model_profile_id)
        if configuration is None:
            gateway = build_model_gateway(self._settings, self._registry)
        else:
            if (
                not authoritative
                and configuration.profile_id != GPT_MODEL_PROFILE_ID
                and not _runtime_configuration_matches_settings(configuration, self._settings)
            ):
                raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION)
            registry = self._registry or default_model_gateway_registry()
            gateway = registry.create(
                configuration.protocol,
                _model_gateway_config_from_runtime(configuration),
            )
        return gateway.complete(request)

    def complete_for_snapshot(
        self,
        request: ModelRequest,
        snapshot: RuntimeConfigurationSnapshot,
    ) -> ModelResponse:
        """Complete a request with the model selected by the turn's existing snapshot.

        Args:
            request: Provider-neutral request for the current Agent turn.
            snapshot: Single Release Set snapshot already selected for that turn.

        Returns:
            The normalized provider response.

        Raises:
            ModelGatewayError: If the snapshot omits or contains an invalid model.
        """

        if snapshot.release_set_id is None:
            return self.complete(request)
        try:
            record = snapshot.model(request.model_profile_id)
            if record is None:
                raise RuntimeConfigurationResolutionError(
                    'The active Release Set does not select a model.'
                )
            configuration = ModelRuntimeConfiguration.model_validate(record.values)
        except (RuntimeConfigurationResolutionError, ValueError) as error:
            raise ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION) from error
        registry = self._registry or default_model_gateway_registry()
        gateway = registry.create(
            configuration.protocol,
            _model_gateway_config_from_runtime(configuration),
        )
        return gateway.complete(request)
