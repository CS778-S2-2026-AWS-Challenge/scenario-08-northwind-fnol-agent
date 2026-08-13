import pytest

from backend.core.config import Settings


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
