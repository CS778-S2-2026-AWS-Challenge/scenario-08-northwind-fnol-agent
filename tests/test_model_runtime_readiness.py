from types import SimpleNamespace

import pytest

from backend.core.config import AgentRuntimeProfile, Settings
from backend.core.errors import ApiError
from backend.domain.configuration import ModelRuntimeConfiguration
from backend.services import model_profiles


def _configuration() -> ModelRuntimeConfiguration:
    return ModelRuntimeConfiguration(
        protocol='openai_compatible',
        provider='test-provider',
        model_identifier='test-model',
        base_url='https://model.example.invalid/v1',
        credential_environment_variable='NORTHWIND_TEST_MODEL_KEY',
        profile_id='test-model',
        purpose='agent_turn',
        privacy_class='synthetic_fnol',
        prompt_version='northwind-fnol-claimant-v7',
        evaluation_status='configured',
        timeout_seconds=30,
        structured_output=True,
        tools=True,
    )


def test_runtime_readiness_requires_the_named_process_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = _configuration()
    monkeypatch.delenv('NORTHWIND_TEST_MODEL_KEY', raising=False)

    missing = model_profiles.model_runtime_status(configuration)
    monkeypatch.setenv('NORTHWIND_TEST_MODEL_KEY', 'test-only-secret')
    ready = model_profiles.model_runtime_status(configuration)

    assert missing.published is True
    assert missing.runtime_ready is False
    assert missing.healthy is None
    assert missing.unavailable_reason == 'credential_unavailable'
    assert ready.runtime_ready is True
    assert ready.unavailable_reason is None


def test_published_but_non_ready_profile_cannot_be_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = model_profiles._settings_configuration(
        Settings(
            environment='test',
            agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
            model_profile_id='test-model',
            model_base_url='https://model.example.invalid/v1',
            model_identifier='test-model',
            model_api_key_env='NORTHWIND_TEST_MODEL_KEY',
        )
    )
    assert record is not None
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=Settings(
                    environment='test',
                    agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
                    model_profile_id='test-model',
                    model_base_url='https://model.example.invalid/v1',
                    model_identifier='test-model',
                    model_api_key_env='NORTHWIND_TEST_MODEL_KEY',
                )
            )
        )
    )
    monkeypatch.setattr(model_profiles, 'model_catalog', lambda _request: [record])
    monkeypatch.delenv('NORTHWIND_TEST_MODEL_KEY', raising=False)

    with pytest.raises(ApiError, match='not ready'):
        model_profiles.select_model_profile(request, 'test-model')

    monkeypatch.setenv('NORTHWIND_TEST_MODEL_KEY', 'test-only-secret')
    assert model_profiles.select_model_profile(request, 'test-model') == 'test-model'
