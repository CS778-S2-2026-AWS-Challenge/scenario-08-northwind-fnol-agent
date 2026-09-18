import json
from pathlib import Path

import pytest

from backend.core.config import (
    AgentRuntimeProfile,
    IdentityMode,
    ObjectStorageAdapter,
    Settings,
)


def test_environment_settings_parse_cors_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('NORTHWIND_ENVIRONMENT', 'test')
    monkeypatch.setenv(
        'NORTHWIND_CORS_ALLOW_ORIGINS',
        'http://localhost:5173, http://terminal.local:5173',
    )
    monkeypatch.setenv('NORTHWIND_CORS_ALLOW_CREDENTIALS', 'false')

    settings = Settings.from_environment()

    assert settings.environment == 'test'
    assert settings.identity_mode is IdentityMode.NORMAL
    assert settings.developer_mode is False
    assert settings.cors_allow_origins == (
        'http://localhost:5173',
        'http://terminal.local:5173',
    )
    assert settings.expose_api_docs is True


def test_identity_mode_must_be_explicitly_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('NORTHWIND_ENVIRONMENT', 'test')
    monkeypatch.setenv('NORTHWIND_IDENTITY_MODE', 'developer')

    settings = Settings.from_environment()

    assert settings.identity_mode is IdentityMode.DEVELOPER
    assert settings.developer_mode is True


def test_invalid_identity_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('NORTHWIND_IDENTITY_MODE', 'automatic')

    with pytest.raises(ValueError, match='NORTHWIND_IDENTITY_MODE must be exactly one of'):
        Settings.from_environment()


@pytest.mark.parametrize('environment', ['production', 'staging', 'sandbox', 'unknown'])
def test_developer_identity_mode_fails_outside_allow_list(environment: str) -> None:
    with pytest.raises(ValueError, match='allowed only in development or test'):
        Settings(environment=environment, identity_mode=IdentityMode.DEVELOPER)


def test_invalid_boolean_setting_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('NORTHWIND_CORS_ALLOW_CREDENTIALS', 'sometimes')

    with pytest.raises(ValueError, match='must be a boolean'):
        Settings.from_environment()


def test_wildcard_origin_cannot_use_credentials() -> None:
    with pytest.raises(ValueError, match='Wildcard CORS origins'):
        Settings(cors_allow_credentials=True)


def test_runtime_profiles_require_enum_values() -> None:
    with pytest.raises(ValueError, match='data_runtime_profile must be'):
        Settings(data_runtime_profile='fixture')  # type: ignore[arg-type]
    with pytest.raises(ValueError, match='agent_runtime_profile must be'):
        Settings(agent_runtime_profile='controlled')  # type: ignore[arg-type]
    with pytest.raises(ValueError, match='object_storage_adapter must be'):
        Settings(object_storage_adapter='fixture')  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ('claimant_token', 'staff_token', 'admin_token', 'integration_token'),
    [
        ('shared-token', 'shared-token', 'admin-token', 'integration-token'),
        ('shared-token', 'staff-token', 'shared-token', 'integration-token'),
        ('shared-token', 'staff-token', 'admin-token', 'shared-token'),
        ('claimant-token', 'shared-token', 'shared-token', 'integration-token'),
        ('claimant-token', 'shared-token', 'admin-token', 'shared-token'),
        ('claimant-token', 'staff-token', 'shared-token', 'shared-token'),
    ],
    ids=[
        'claimant-staff',
        'claimant-admin',
        'claimant-integration',
        'staff-admin',
        'staff-integration',
        'admin-integration',
    ],
)
def test_synthetic_tokens_must_be_pairwise_distinct(
    claimant_token: str,
    staff_token: str,
    admin_token: str,
    integration_token: str,
) -> None:
    with pytest.raises(ValueError, match='must be pairwise distinct'):
        Settings(
            synthetic_claimant_token=claimant_token,
            synthetic_staff_token=staff_token,
            synthetic_admin_token=admin_token,
            synthetic_integration_token=integration_token,
        )


def test_production_hides_interactive_api_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('NORTHWIND_ENVIRONMENT', 'production')

    settings = Settings.from_environment()

    assert settings.expose_api_docs is False
    assert settings.identity_mode is IdentityMode.NORMAL


def test_model_gateway_settings_use_only_a_secret_environment_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('AGENT_RUNTIME_PROFILE', 'model_gateway')
    monkeypatch.setenv('MODEL_PROTOCOL_ADAPTER', 'openai_compatible')
    monkeypatch.setenv('MODEL_BASE_URL', 'http://127.0.0.1:11434/v1')
    monkeypatch.setenv('MODEL_IDENTIFIER', 'local-model')
    monkeypatch.setenv('MODEL_API_KEY_ENV', 'LOCAL_MODEL_API_KEY')
    monkeypatch.setenv('MODEL_PROFILE_ID', 'local-agent-turn')
    monkeypatch.setenv('MODEL_PROVIDER', 'local-runtime')
    monkeypatch.setenv('MODEL_PURPOSE', 'agent_turn')
    monkeypatch.setenv('MODEL_PRIVACY_CLASS', 'synthetic_fnol')
    monkeypatch.setenv('MODEL_PROMPT_VERSION', 'northwind-fnol-motor-claimant-v4')
    monkeypatch.setenv('MODEL_EVALUATION_STATUS', 'configured')
    monkeypatch.setenv('MODEL_TIMEOUT_SECONDS', '12.5')
    monkeypatch.setenv('MODEL_SUPPORTS_STRUCTURED_OUTPUT', 'true')
    monkeypatch.setenv('MODEL_SUPPORTS_TOOLS', 'false')

    settings = Settings.from_environment()

    assert settings.agent_runtime_profile is AgentRuntimeProfile.MODEL_GATEWAY
    assert settings.model_base_url == 'http://127.0.0.1:11434/v1'
    assert settings.model_identifier == 'local-model'
    assert settings.model_api_key_env == 'LOCAL_MODEL_API_KEY'
    assert settings.model_profile_id == 'local-agent-turn'
    assert settings.model_provider == 'local-runtime'
    assert settings.model_purpose == 'agent_turn'
    assert settings.model_privacy_class == 'synthetic_fnol'
    assert settings.model_prompt_version == 'northwind-fnol-motor-claimant-v4'
    assert settings.model_evaluation_status == 'configured'
    assert settings.model_timeout_seconds == 12.5
    assert settings.model_supports_structured_output is True
    assert settings.model_supports_tools is False


def test_model_binding_manifest_selects_qwen_without_exposing_a_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('AGENT_RUNTIME_PROFILE', 'model_gateway')
    monkeypatch.setenv('MODEL_RUNTIME_BINDINGS_PATH', 'config/model-runtime-bindings.json')
    monkeypatch.setenv('NORTHWIND_QWEN_BASE_URL', 'http://qwen.test/v1')
    monkeypatch.delenv('MODEL_BASE_URL', raising=False)
    monkeypatch.delenv('MODEL_IDENTIFIER', raising=False)
    monkeypatch.delenv('MODEL_API_KEY_ENV', raising=False)
    monkeypatch.setenv('MODEL_PROVIDER', 'must-not-override-the-binding')
    monkeypatch.setenv('MODEL_SUPPORTS_TOOLS', 'false')

    settings = Settings.from_environment()

    assert settings.model_profile_id == 'qwen-local'
    assert settings.model_provider == 'qwen-local'
    assert settings.model_identifier == 'qwen3.8-27b'
    assert settings.model_api_key_env is None
    assert settings.model_supports_tools is True
    assert settings.model_reasoning_mode == 'disabled'
    assert [item.profile_id for item in settings.model_runtime_bindings] == [
        'qwen-local',
        'nowcoding-gpt55',
        'bedrock-nova2-lite',
        'google-gemini35-flash-lite',
    ]
    gpt = settings.model_runtime_bindings[1]
    assert gpt.model_identifier == 'gpt-5.5'
    assert gpt.credential_environment_variable == 'NORTHWIND_MODEL_API_KEY'
    bedrock = settings.model_runtime_bindings[2]
    assert bedrock.model_identifier == 'global.amazon.nova-2-lite-v1:0'
    assert bedrock.credential_environment_variable == 'AWS_BEARER_TOKEN_BEDROCK'
    assert bedrock.evaluation_status == 'unavailable'
    assert bedrock.image_input is True
    gemini = settings.model_runtime_bindings[3]
    assert gemini.protocol == 'google_generate_content'
    assert gemini.model_identifier == 'gemini-3.5-flash-lite'
    assert gemini.credential_environment_variable == 'GEMINI_API_KEY'
    assert gemini.tools is True
    assert gemini.image_input is True
    assert gemini.document_input is True


def test_model_binding_manifest_rejects_invalid_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / 'bindings.json'
    path.write_text('{invalid', encoding='utf-8')
    monkeypatch.setenv('MODEL_RUNTIME_BINDINGS_PATH', str(path))

    with pytest.raises(ValueError, match='must point to a valid model binding JSON file'):
        Settings.from_environment()


def test_model_binding_manifest_rejects_duplicate_profiles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = json.loads(Path('config/model-runtime-bindings.json').read_text(encoding='utf-8'))
    path = tmp_path / 'bindings.json'
    path.write_text(json.dumps([source[0], source[0]]), encoding='utf-8')
    monkeypatch.setenv('MODEL_RUNTIME_BINDINGS_PATH', str(path))
    monkeypatch.setenv('NORTHWIND_QWEN_BASE_URL', 'http://qwen.test/v1')

    with pytest.raises(ValueError, match='must not contain duplicate model profile IDs'):
        Settings.from_environment()


def test_model_binding_manifest_rejects_an_unknown_default_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('MODEL_RUNTIME_BINDINGS_PATH', 'config/model-runtime-bindings.json')
    monkeypatch.setenv('NORTHWIND_QWEN_BASE_URL', 'http://qwen.test/v1')
    monkeypatch.setenv('MODEL_PROFILE_ID', 'missing-profile')

    with pytest.raises(ValueError, match='must identify a configured deployment binding'):
        Settings.from_environment()


def test_model_binding_manifest_rejects_a_missing_private_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('AGENT_RUNTIME_PROFILE', 'model_gateway')
    monkeypatch.setenv('MODEL_RUNTIME_BINDINGS_PATH', 'config/model-runtime-bindings.json')
    monkeypatch.delenv('NORTHWIND_QWEN_BASE_URL', raising=False)

    with pytest.raises(ValueError, match='MODEL_BASE_URL must not be empty'):
        Settings.from_environment()


def test_model_gateway_runtime_requires_endpoint_and_model() -> None:
    with pytest.raises(ValueError, match='MODEL_BASE_URL'):
        Settings(agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY)


def test_model_gateway_runtime_requires_adapter_model_and_positive_timeout() -> None:
    with pytest.raises(ValueError, match='MODEL_PROTOCOL_ADAPTER'):
        Settings(
            agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
            model_protocol_adapter='',
            model_base_url='http://127.0.0.1:11434/v1',
            model_identifier='local-model',
        )
    with pytest.raises(ValueError, match='MODEL_IDENTIFIER'):
        Settings(
            agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
            model_base_url='http://127.0.0.1:11434/v1',
        )
    with pytest.raises(ValueError, match='MODEL_TIMEOUT_SECONDS'):
        Settings(
            agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
            model_base_url='http://127.0.0.1:11434/v1',
            model_identifier='local-model',
            model_timeout_seconds=0,
        )


def test_model_gateway_runtime_rejects_unknown_evaluation_status() -> None:
    with pytest.raises(ValueError, match='MODEL_EVALUATION_STATUS'):
        Settings(
            agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
            model_base_url='http://127.0.0.1:11434/v1',
            model_identifier='local-model',
            model_evaluation_status='untested',
        )


def test_environment_rejects_unknown_agent_runtime_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('AGENT_RUNTIME_PROFILE', 'automatic-maybe')

    with pytest.raises(ValueError, match='AGENT_RUNTIME_PROFILE must be exactly one'):
        Settings.from_environment()


def test_invalid_model_timeout_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('MODEL_TIMEOUT_SECONDS', 'not-a-number')

    with pytest.raises(ValueError, match='MODEL_TIMEOUT_SECONDS must be a number'):
        Settings.from_environment()


def test_environment_selects_s3_compatible_object_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ADAPTER', 's3_compatible')

    settings = Settings.from_environment()

    assert settings.object_storage_adapter is ObjectStorageAdapter.S3_COMPATIBLE


def test_connection_values_alone_do_not_switch_object_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('NORTHWIND_OBJECT_STORAGE_ADAPTER', raising=False)
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ENDPOINT', 'http://localhost:9000')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID', 'local-access-key')
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY', 'local-secret-key')

    settings = Settings.from_environment()

    assert settings.object_storage_adapter is ObjectStorageAdapter.FIXTURE


def test_environment_rejects_unknown_object_storage_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('NORTHWIND_OBJECT_STORAGE_ADAPTER', 'minio-or-maybe-s3')

    with pytest.raises(ValueError, match='NORTHWIND_OBJECT_STORAGE_ADAPTER must be exactly one'):
        Settings.from_environment()
