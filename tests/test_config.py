import pytest

from backend.core.config import IdentityMode, Settings


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
