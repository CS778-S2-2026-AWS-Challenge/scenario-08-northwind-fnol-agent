import pytest

from backend.core.config import AgentRuntimeProfile, Settings


def test_environment_settings_parse_cors_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('NORTHWIND_ENVIRONMENT', 'test')
    monkeypatch.setenv(
        'NORTHWIND_CORS_ALLOW_ORIGINS',
        'http://localhost:5173, http://terminal.local:5173',
    )
    monkeypatch.setenv('NORTHWIND_CORS_ALLOW_CREDENTIALS', 'false')

    settings = Settings.from_environment()

    assert settings.environment == 'test'
    assert settings.cors_allow_origins == (
        'http://localhost:5173',
        'http://terminal.local:5173',
    )
    assert settings.expose_api_docs is True


def test_invalid_boolean_setting_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('NORTHWIND_CORS_ALLOW_CREDENTIALS', 'sometimes')

    with pytest.raises(ValueError, match='must be a boolean'):
        Settings.from_environment()


def test_wildcard_origin_cannot_use_credentials() -> None:
    with pytest.raises(ValueError, match='Wildcard CORS origins'):
        Settings(cors_allow_credentials=True)


@pytest.mark.parametrize(
    ('claimant_token', 'staff_token', 'integration_token'),
    [
        ('shared-token', 'shared-token', 'integration-token'),
        ('shared-token', 'staff-token', 'shared-token'),
        ('claimant-token', 'shared-token', 'shared-token'),
    ],
    ids=['claimant-staff', 'claimant-integration', 'staff-integration'],
)
def test_synthetic_tokens_must_be_pairwise_distinct(
    claimant_token: str,
    staff_token: str,
    integration_token: str,
) -> None:
    with pytest.raises(ValueError, match='must be pairwise distinct'):
        Settings(
            synthetic_claimant_token=claimant_token,
            synthetic_staff_token=staff_token,
            synthetic_integration_token=integration_token,
        )


def test_production_hides_interactive_api_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('NORTHWIND_ENVIRONMENT', 'production')

    settings = Settings.from_environment()

    assert settings.expose_api_docs is False


def test_model_gateway_settings_use_only_a_secret_environment_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('AGENT_RUNTIME_PROFILE', 'model_gateway')
    monkeypatch.setenv('MODEL_PROTOCOL_ADAPTER', 'openai_compatible')
    monkeypatch.setenv('MODEL_BASE_URL', 'http://127.0.0.1:11434/v1')
    monkeypatch.setenv('MODEL_IDENTIFIER', 'local-model')
    monkeypatch.setenv('MODEL_API_KEY_ENV', 'LOCAL_MODEL_API_KEY')
    monkeypatch.setenv('MODEL_TIMEOUT_SECONDS', '12.5')
    monkeypatch.setenv('MODEL_SUPPORTS_STRUCTURED_OUTPUT', 'true')
    monkeypatch.setenv('MODEL_SUPPORTS_TOOLS', 'false')

    settings = Settings.from_environment()

    assert settings.agent_runtime_profile is AgentRuntimeProfile.MODEL_GATEWAY
    assert settings.model_base_url == 'http://127.0.0.1:11434/v1'
    assert settings.model_identifier == 'local-model'
    assert settings.model_api_key_env == 'LOCAL_MODEL_API_KEY'
    assert settings.model_timeout_seconds == 12.5
    assert settings.model_supports_structured_output is True
    assert settings.model_supports_tools is False


def test_model_gateway_runtime_requires_endpoint_and_model() -> None:
    with pytest.raises(ValueError, match='MODEL_BASE_URL'):
        Settings(agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY)


def test_invalid_model_timeout_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('MODEL_TIMEOUT_SECONDS', 'not-a-number')

    with pytest.raises(ValueError, match='MODEL_TIMEOUT_SECONDS must be a number'):
        Settings.from_environment()
