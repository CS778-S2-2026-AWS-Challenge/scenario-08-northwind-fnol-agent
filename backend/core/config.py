import os
from dataclasses import dataclass
from enum import Enum


class DataRuntimeProfile(str, Enum):
    FIXTURE = 'fixture'
    CLOUDFLARE = 'cloudflare'
    MONGODB = 'mongodb'
    AWS = 'aws'


class IdentityMode(str, Enum):
    NORMAL = 'normal'
    DEVELOPER = 'developer'


def _csv_setting(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    values = tuple(value.strip() for value in raw_value.split(',') if value.strip())
    return values or default


def _boolean_setting(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off'}:
        return False
    raise ValueError(f'{name} must be a boolean value.')


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str = 'development'
    identity_mode: IdentityMode = IdentityMode.NORMAL
    cors_allow_origins: tuple[str, ...] = ('*',)
    cors_allow_credentials: bool = False
    expose_api_docs: bool = True
    synthetic_claimant_token: str = 'synthetic-claimant'
    synthetic_staff_token: str = 'synthetic-staff'
    synthetic_admin_token: str = 'synthetic-admin'
    synthetic_integration_token: str = 'synthetic-integration'
    data_runtime_profile: DataRuntimeProfile = DataRuntimeProfile.FIXTURE

    def __post_init__(self) -> None:
        if not isinstance(self.data_runtime_profile, DataRuntimeProfile):
            raise ValueError('data_runtime_profile must be a DataRuntimeProfile value.')
        if not isinstance(self.identity_mode, IdentityMode):
            raise ValueError('identity_mode must be an IdentityMode value.')
        if self.identity_mode is IdentityMode.DEVELOPER and self.environment not in {
            'development',
            'test',
        }:
            raise ValueError(
                'Developer identity mode is allowed only in development or test environments.'
            )
        if self.cors_allow_credentials and '*' in self.cors_allow_origins:
            raise ValueError('Wildcard CORS origins cannot be used with credentials.')
        synthetic_tokens = {
            self.synthetic_claimant_token,
            self.synthetic_staff_token,
            self.synthetic_admin_token,
            self.synthetic_integration_token,
        }
        if len(synthetic_tokens) != 4:
            raise ValueError(
                'Synthetic claimant, staff, administrator, and integration tokens '
                'must be pairwise distinct.'
            )

    @property
    def developer_mode(self) -> bool:
        return self.identity_mode is IdentityMode.DEVELOPER

    @classmethod
    def from_environment(cls) -> 'Settings':
        environment = os.getenv('NORTHWIND_ENVIRONMENT', 'development').strip().lower()
        raw_identity_mode = os.getenv('NORTHWIND_IDENTITY_MODE', IdentityMode.NORMAL.value)
        try:
            identity_mode = IdentityMode(raw_identity_mode.strip().lower())
        except ValueError as error:
            allowed = ', '.join(mode.value for mode in IdentityMode)
            raise ValueError(f'NORTHWIND_IDENTITY_MODE must be exactly one of: {allowed}.') from error
        raw_profile = os.getenv('DATA_RUNTIME_PROFILE', DataRuntimeProfile.FIXTURE.value)
        try:
            data_runtime_profile = DataRuntimeProfile(raw_profile.strip().lower())
        except ValueError as error:
            allowed = ', '.join(profile.value for profile in DataRuntimeProfile)
            raise ValueError(f'DATA_RUNTIME_PROFILE must be exactly one of: {allowed}.') from error
        return cls(
            environment=environment,
            identity_mode=identity_mode,
            cors_allow_origins=_csv_setting('NORTHWIND_CORS_ALLOW_ORIGINS', ('*',)),
            cors_allow_credentials=_boolean_setting(
                'NORTHWIND_CORS_ALLOW_CREDENTIALS',
                False,
            ),
            expose_api_docs=environment != 'production',
            synthetic_claimant_token=os.getenv(
                'NORTHWIND_SYNTHETIC_CLAIMANT_TOKEN',
                'synthetic-claimant',
            ),
            synthetic_staff_token=os.getenv(
                'NORTHWIND_SYNTHETIC_STAFF_TOKEN',
                'synthetic-staff',
            ),
            synthetic_admin_token=os.getenv(
                'NORTHWIND_SYNTHETIC_ADMIN_TOKEN',
                'synthetic-admin',
            ),
            synthetic_integration_token=os.getenv(
                'NORTHWIND_SYNTHETIC_INTEGRATION_TOKEN',
                'synthetic-integration',
            ),
            data_runtime_profile=data_runtime_profile,
        )
