"""Resolve the published claimant model catalog without exposing credentials."""

import os
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


def _secondary_settings_configuration(settings: Settings) -> ConfigurationRecord:
    """Describe the optional GPT profile without claiming provider readiness.

    The endpoint and secret name are configuration, never a provider response.  The
    profile is listed so the client can explain availability; selection remains gated
    by ``evaluation_status`` until a real credential is present.
    """
    endpoint = os.getenv('NOWCODING_MODEL_BASE_URL', 'https://nowcoding.ai/v1').strip()
    credential_name = os.getenv(
        'NOWCODING_MODEL_API_KEY_ENV',
        'NORTHWIND_MODEL_API_KEY',
    ).strip()
    configured = bool(endpoint and credential_name and os.getenv(credential_name, '').strip())
    return ConfigurationRecord(
        configuration_id='bootstrap-nowcoding-gpt54mini',
        domain='model',
        configuration_key=GPT_MODEL_PROFILE_ID,
        revision=1,
        state=ConfigurationState.PUBLISHED,
        impact='high',
        values={
            'protocol': 'openai_compatible',
            'provider': 'nowcoding',
            'model_identifier': 'gpt-5.4-mini',
            'base_url': endpoint,
            'credential_environment_variable': credential_name,
            'profile_id': GPT_MODEL_PROFILE_ID,
            'purpose': settings.model_purpose,
            'privacy_class': settings.model_privacy_class,
            'prompt_version': settings.model_prompt_version,
            'evaluation_status': 'configured' if configured else 'unavailable',
            'timeout_seconds': settings.model_timeout_seconds,
            'structured_output': True,
            'tools': True,
        },
        author='runtime-bootstrap',
        reason='Deployment-owned optional GPT claimant profile.',
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
    return sorted(parsed, key=lambda item: str(item.values.get('profile_id', '')))


def _default_first(
    records: list[ConfigurationRecord], default_profile_id: str
) -> list[ConfigurationRecord]:
    return sorted(
        records,
        key=lambda item: (
            item.values.get('profile_id') != default_profile_id,
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
        records = _parse(snapshot.configurations.values())
    else:
        records = _parse(app.state.configuration_repository.list_configurations('model'))
        if not records and (bootstrap := _settings_configuration(settings)):
            records = [bootstrap]
        if not any(record.values.get('profile_id') == GPT_MODEL_PROFILE_ID for record in records):
            records.append(_secondary_settings_configuration(settings))
        records = _parse(records)
    return _default_first(records, settings.model_profile_id)


def default_model_profile_id(
    request: object,
    records: list[ConfigurationRecord] | None = None,
) -> str | None:
    """Return the deployment-selected default, or the first available profile."""
    app = request.app  # type: ignore[attr-defined]
    settings: Settings = app.state.settings
    catalog = records if records is not None else model_catalog(request)
    available = [
        str(record.values['profile_id'])
        for record in catalog
        if record.values.get('profile_id')
        and record.values.get('evaluation_status') == 'configured'
    ]
    if settings.model_profile_id in available:
        return settings.model_profile_id
    return available[0] if available else None


def select_model_profile(request: object, requested: str | None) -> str:
    """Validate Session model selection against the current published catalog."""
    app = request.app  # type: ignore[attr-defined]
    settings: Settings = app.state.settings
    selected = requested or settings.model_profile_id
    if settings.agent_runtime_profile is not AgentRuntimeProfile.MODEL_GATEWAY:
        return selected
    catalog = model_catalog(request)
    available = {
        str(record.values.get('profile_id'))
        for record in catalog
        if record.values.get('profile_id')
        and record.values.get('evaluation_status') == 'configured'
    }
    if requested is None:
        selected = default_model_profile_id(request, catalog) or selected
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
