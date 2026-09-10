"""Resolve the published claimant model catalog without exposing credentials."""

from collections.abc import Iterable
from datetime import UTC, datetime

from backend.core.config import AgentRuntimeProfile, Settings
from backend.core.errors import ApiError
from backend.domain.configuration import (
    ConfigurationRecord,
    ConfigurationState,
    ModelRuntimeConfiguration,
)
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
)

DEFAULT_MODEL_PROFILE_ID = 'qwen-local'
GPT_MODEL_PROFILE_ID = 'nowcoding-gpt54mini'


def _settings_configuration(settings: Settings) -> ConfigurationRecord | None:
    if not settings.model_base_url or not settings.model_identifier:
        return None
    return ConfigurationRecord(
        configuration_id='bootstrap-model',
        domain='model',
        configuration_key=settings.model_profile_id,
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact='high',
        values={
            'protocol': settings.model_protocol_adapter,
            'provider': settings.model_provider,
            'model_identifier': settings.model_identifier,
            'base_url': settings.model_base_url,
            'credential_environment_variable': settings.model_api_key_env,
            'profile_id': settings.model_profile_id,
            'purpose': settings.model_purpose,
            'privacy_class': settings.model_privacy_class,
            'prompt_version': settings.model_prompt_version,
            'evaluation_status': settings.model_evaluation_status,
            'timeout_seconds': settings.model_timeout_seconds,
            'structured_output': settings.model_supports_structured_output,
            'tools': settings.model_supports_tools,
        },
        author='runtime-bootstrap',
        reason='Deployment-owned bootstrap profile.',
        updated_at=datetime.now(UTC),
    )


def _parse(records: Iterable[ConfigurationRecord]) -> list[ConfigurationRecord]:
    parsed: list[ConfigurationRecord] = []
    for record in records:
        if record.domain != 'model' or record.state is not ConfigurationState.PUBLISHED:
            continue
        try:
            ModelRuntimeConfiguration.model_validate(record.values)
        except ValueError:
            continue
        parsed.append(record)
    return sorted(
        parsed,
        key=lambda item: (
            item.values.get('profile_id') != DEFAULT_MODEL_PROFILE_ID,
            str(item.values.get('profile_id', '')),
        ),
    )


def model_catalog(request: object) -> list[ConfigurationRecord]:
    """Return only published, structurally valid model profiles."""
    app = request.app  # type: ignore[attr-defined]
    settings: Settings = app.state.settings
    if settings.agent_runtime_profile is not AgentRuntimeProfile.MODEL_GATEWAY:
        return []
    resolver: RuntimeConfigurationResolver = app.state.runtime_configuration_resolver
    try:
        snapshot = resolver.snapshot()
    except RuntimeConfigurationResolutionError as error:
        raise ApiError(
            status_code=503,
            code='RUNTIME_CONFIGURATION_UNAVAILABLE',
            message='The active Runtime configuration is unavailable.',
            retryable=False,
        ) from error
    if snapshot.release_set_id is not None:
        return _parse(snapshot.configurations.values())
    records = _parse(app.state.configuration_repository.list_configurations('model'))
    return records or ([bootstrap] if (bootstrap := _settings_configuration(settings)) else [])


def select_model_profile(request: object, requested: str | None) -> str:
    """Validate Session model selection against the current published catalog."""
    app = request.app  # type: ignore[attr-defined]
    settings: Settings = app.state.settings
    selected = requested or DEFAULT_MODEL_PROFILE_ID
    if settings.agent_runtime_profile is not AgentRuntimeProfile.MODEL_GATEWAY:
        return selected
    available = {
        str(record.values.get('profile_id'))
        for record in model_catalog(request)
        if record.values.get('profile_id')
    }
    if selected not in available:
        raise ApiError(
            status_code=422,
            code='MODEL_PROFILE_UNAVAILABLE',
            message='The requested model profile is not published for this Runtime.',
            retryable=False,
        )
    return selected


def model_configuration(request: object, profile_id: str) -> ModelRuntimeConfiguration | None:
    """Return one published profile after applying the same catalog boundary."""
    for record in model_catalog(request):
        if record.values.get('profile_id') == profile_id:
            return ModelRuntimeConfiguration.model_validate(record.values)
    return None
