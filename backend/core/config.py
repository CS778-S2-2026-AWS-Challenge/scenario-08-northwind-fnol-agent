import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import TypeAdapter

from backend.domain.configuration import ModelRuntimeBinding


class DataRuntimeProfile(str, Enum):
    FIXTURE = 'fixture'
    LOCAL_MVP = 'local_mvp'
    CLOUDFLARE = 'cloudflare'
    MONGODB = 'mongodb'
    AWS = 'aws'


class AgentRuntimeProfile(str, Enum):
    CONTROLLED = 'controlled'
    MODEL_GATEWAY = 'model_gateway'


class ObjectStorageAdapter(str, Enum):
    FIXTURE = 'fixture'
    S3_COMPATIBLE = 's3_compatible'


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


def _float_setting(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError as error:
        raise ValueError(f'{name} must be a number.') from error


_ENVIRONMENT_REFERENCE = re.compile(r'^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$')


def load_model_runtime_bindings(
    path: Path,
    *,
    require_endpoints: bool = False,
) -> tuple[ModelRuntimeBinding, ...]:
    """Load deployment model bindings and resolve endpoint references.

    Args:
        path: JSON manifest whose private endpoints may use ``${VARIABLE}`` references.
        require_endpoints: Whether unresolved endpoint references fail immediately.

    Returns:
        Validated bindings containing the process-resolved endpoint values.

    Raises:
        ValueError: The manifest is invalid, duplicated, or references a missing endpoint.
    """
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(payload, list):
            raise ValueError('the binding manifest must contain a list')
        for item in payload:
            if not isinstance(item, dict):
                continue
            base_url = item.get('base_url')
            if not isinstance(base_url, str):
                continue
            reference = _ENVIRONMENT_REFERENCE.fullmatch(base_url)
            if reference is None:
                continue
            environment_variable = reference.group(1)
            resolved = os.getenv(environment_variable, '').strip()
            if not resolved and require_endpoints:
                raise ValueError(
                    f'{environment_variable} referenced by {path} must contain a model endpoint.'
                )
            item['base_url'] = resolved
        bindings = TypeAdapter(list[ModelRuntimeBinding]).validate_python(payload)
    except (OSError, ValueError) as error:
        raise ValueError(f'Invalid model binding manifest: {path}') from error
    profile_ids = [item.profile_id for item in bindings]
    if len(profile_ids) != len(set(profile_ids)):
        raise ValueError(f'{path} must not contain duplicate model profile IDs.')
    return tuple(bindings)


def _model_runtime_bindings_setting(name: str) -> tuple[ModelRuntimeBinding, ...]:
    raw_path = os.getenv(name, '').strip()
    if not raw_path:
        return ()
    try:
        return load_model_runtime_bindings(Path(raw_path))
    except ValueError as error:
        raise ValueError(
            f'{name} must point to a valid model binding JSON file: {error}'
        ) from error


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
    synthetic_release_approver_token: str = 'synthetic-release-approver'
    synthetic_integration_token: str = 'synthetic-integration'
    claimant_session_ttl_minutes: int = 30
    staff_session_ttl_minutes: int = 480
    identity_db_path: str = '.northwind-identity.sqlite3'
    staff_identity_db_path: str = '.northwind-staff-identity.sqlite3'
    control_plane_db_path: str = '.northwind-control-plane.sqlite3'
    staff_bootstrap_email: str = ''
    staff_bootstrap_password: str = ''
    staff_bootstrap_display_name: str = 'Northwind Claims Professional'
    data_runtime_profile: DataRuntimeProfile = DataRuntimeProfile.FIXTURE
    agent_runtime_profile: AgentRuntimeProfile = AgentRuntimeProfile.CONTROLLED
    model_protocol_adapter: str = 'openai_compatible'
    model_profile_id: str = 'qwen-local'
    model_provider: str = 'qwen-local'
    model_purpose: str = 'agent_turn'
    model_privacy_class: str = 'synthetic_fnol'
    model_prompt_version: str = 'northwind-fnol-claimant-v6'
    model_evaluation_status: str = 'configured'
    model_base_url: str = ''
    model_identifier: str = ''
    model_api_key_env: str | None = None
    model_timeout_seconds: float = 30.0
    model_supports_structured_output: bool = True
    model_supports_tools: bool = False
    model_supports_image_input: bool = False
    model_supports_document_input: bool = False
    model_runtime_bindings: tuple[ModelRuntimeBinding, ...] = ()
    object_storage_adapter: ObjectStorageAdapter = ObjectStorageAdapter.FIXTURE

    def __post_init__(self) -> None:
        if not isinstance(self.data_runtime_profile, DataRuntimeProfile):
            raise ValueError('data_runtime_profile must be a DataRuntimeProfile value.')
        if not isinstance(self.agent_runtime_profile, AgentRuntimeProfile):
            raise ValueError('agent_runtime_profile must be an AgentRuntimeProfile value.')
        if not isinstance(self.object_storage_adapter, ObjectStorageAdapter):
            raise ValueError('object_storage_adapter must be an ObjectStorageAdapter value.')
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
            self.synthetic_release_approver_token,
            self.synthetic_integration_token,
        }
        if len(synthetic_tokens) != 5:
            raise ValueError(
                'Synthetic claimant, staff, administrator, release approver, and '
                'integration tokens must be pairwise distinct.'
            )
        if self.claimant_session_ttl_minutes <= 0:
            raise ValueError('NORTHWIND_CLAIMANT_SESSION_TTL_MINUTES must be greater than zero.')
        if self.staff_session_ttl_minutes <= 0:
            raise ValueError('NORTHWIND_STAFF_SESSION_TTL_MINUTES must be greater than zero.')
        if bool(self.staff_bootstrap_email) != bool(self.staff_bootstrap_password):
            raise ValueError(
                'NORTHWIND_STAFF_BOOTSTRAP_EMAIL and '
                'NORTHWIND_STAFF_BOOTSTRAP_PASSWORD must be configured together.'
            )
        if self.staff_bootstrap_password and len(self.staff_bootstrap_password) < 12:
            raise ValueError(
                'NORTHWIND_STAFF_BOOTSTRAP_PASSWORD must contain at least 12 characters.'
            )
        if self.agent_runtime_profile is AgentRuntimeProfile.MODEL_GATEWAY:
            if not self.model_protocol_adapter.strip():
                raise ValueError('MODEL_PROTOCOL_ADAPTER must not be empty.')
            if not self.model_base_url.strip():
                raise ValueError('MODEL_BASE_URL must not be empty.')
            if not self.model_identifier.strip():
                raise ValueError('MODEL_IDENTIFIER must not be empty.')
            if self.model_timeout_seconds <= 0:
                raise ValueError('MODEL_TIMEOUT_SECONDS must be greater than zero.')
            if self.model_evaluation_status not in {
                'configured',
                'degraded',
                'unavailable',
            }:
                raise ValueError(
                    'MODEL_EVALUATION_STATUS must be configured, degraded, or unavailable.'
                )

    @property
    def developer_mode(self) -> bool:
        return self.identity_mode is IdentityMode.DEVELOPER

    @classmethod
    def from_environment(cls) -> 'Settings':
        environment = os.getenv('NORTHWIND_ENVIRONMENT', 'development').strip().lower()
        raw_identity_mode = os.getenv(
            'NORTHWIND_IDENTITY_MODE',
            IdentityMode.NORMAL.value,
        )
        try:
            identity_mode = IdentityMode(raw_identity_mode.strip().lower())
        except ValueError as error:
            allowed = ', '.join(mode.value for mode in IdentityMode)
            raise ValueError(
                f'NORTHWIND_IDENTITY_MODE must be exactly one of: {allowed}.'
            ) from error
        raw_profile = os.getenv('DATA_RUNTIME_PROFILE', DataRuntimeProfile.FIXTURE.value)
        try:
            data_runtime_profile = DataRuntimeProfile(raw_profile.strip().lower())
        except ValueError as error:
            allowed = ', '.join(profile.value for profile in DataRuntimeProfile)
            raise ValueError(f'DATA_RUNTIME_PROFILE must be exactly one of: {allowed}.') from error
        raw_agent_profile = os.getenv('AGENT_RUNTIME_PROFILE', AgentRuntimeProfile.CONTROLLED.value)
        try:
            agent_runtime_profile = AgentRuntimeProfile(raw_agent_profile.strip().lower())
        except ValueError as error:
            allowed = ', '.join(profile.value for profile in AgentRuntimeProfile)
            raise ValueError(f'AGENT_RUNTIME_PROFILE must be exactly one of: {allowed}.') from error
        model_runtime_bindings = _model_runtime_bindings_setting('MODEL_RUNTIME_BINDINGS_PATH')
        model_profile_id = os.getenv('MODEL_PROFILE_ID', 'qwen-local').strip()
        selected_binding = next(
            (item for item in model_runtime_bindings if item.profile_id == model_profile_id),
            None,
        )
        if model_runtime_bindings and selected_binding is None:
            raise ValueError('MODEL_PROFILE_ID must identify a configured deployment binding.')
        credential_environment_variable = (
            selected_binding.credential_environment_variable
            if selected_binding
            else os.getenv('MODEL_API_KEY_ENV', '').strip() or None
        )
        raw_object_storage = os.getenv(
            'NORTHWIND_OBJECT_STORAGE_ADAPTER',
            ObjectStorageAdapter.FIXTURE.value,
        )
        try:
            object_storage_adapter = ObjectStorageAdapter(raw_object_storage.strip().lower())
        except ValueError as error:
            allowed = ', '.join(adapter.value for adapter in ObjectStorageAdapter)
            raise ValueError(
                f'NORTHWIND_OBJECT_STORAGE_ADAPTER must be exactly one of: {allowed}.'
            ) from error
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
            synthetic_release_approver_token=os.getenv(
                'NORTHWIND_SYNTHETIC_RELEASE_APPROVER_TOKEN',
                'synthetic-release-approver',
            ),
            synthetic_integration_token=os.getenv(
                'NORTHWIND_SYNTHETIC_INTEGRATION_TOKEN',
                'synthetic-integration',
            ),
            claimant_session_ttl_minutes=int(
                os.getenv('NORTHWIND_CLAIMANT_SESSION_TTL_MINUTES', '30')
            ),
            staff_session_ttl_minutes=int(os.getenv('NORTHWIND_STAFF_SESSION_TTL_MINUTES', '480')),
            identity_db_path=os.getenv(
                'NORTHWIND_IDENTITY_DB_PATH', '.northwind-identity.sqlite3'
            ).strip(),
            staff_identity_db_path=os.getenv(
                'NORTHWIND_STAFF_IDENTITY_DB_PATH',
                '.northwind-staff-identity.sqlite3',
            ).strip(),
            control_plane_db_path=os.getenv(
                'NORTHWIND_CONTROL_PLANE_DB_PATH',
                '.northwind-control-plane.sqlite3',
            ).strip(),
            staff_bootstrap_email=os.getenv('NORTHWIND_STAFF_BOOTSTRAP_EMAIL', '').strip().lower(),
            staff_bootstrap_password=os.getenv('NORTHWIND_STAFF_BOOTSTRAP_PASSWORD', ''),
            staff_bootstrap_display_name=os.getenv(
                'NORTHWIND_STAFF_BOOTSTRAP_DISPLAY_NAME',
                'Northwind Claims Professional',
            ).strip(),
            data_runtime_profile=data_runtime_profile,
            agent_runtime_profile=agent_runtime_profile,
            model_protocol_adapter=(
                selected_binding.protocol
                if selected_binding
                else os.getenv('MODEL_PROTOCOL_ADAPTER', 'openai_compatible').strip()
            ),
            model_profile_id=model_profile_id,
            model_provider=(
                selected_binding.provider
                if selected_binding
                else os.getenv('MODEL_PROVIDER', 'qwen-local').strip()
            ),
            model_purpose=(
                selected_binding.purpose
                if selected_binding
                else os.getenv('MODEL_PURPOSE', 'agent_turn').strip()
            ),
            model_privacy_class=(
                selected_binding.privacy_class
                if selected_binding
                else os.getenv('MODEL_PRIVACY_CLASS', 'synthetic_fnol').strip()
            ),
            model_prompt_version=(
                selected_binding.prompt_version
                if selected_binding
                else os.getenv('MODEL_PROMPT_VERSION', 'northwind-fnol-claimant-v6').strip()
            ),
            model_evaluation_status=os.getenv('MODEL_EVALUATION_STATUS', 'configured').strip()
            if selected_binding is None
            else selected_binding.evaluation_status,
            model_base_url=(
                selected_binding.base_url
                if selected_binding
                else os.getenv('MODEL_BASE_URL', '').strip()
            ),
            model_identifier=(
                selected_binding.model_identifier
                if selected_binding
                else os.getenv('MODEL_IDENTIFIER', '').strip()
            ),
            model_api_key_env=credential_environment_variable,
            model_timeout_seconds=_float_setting('MODEL_TIMEOUT_SECONDS', 30.0),
            model_supports_structured_output=(
                selected_binding.structured_output
                if selected_binding
                else _boolean_setting('MODEL_SUPPORTS_STRUCTURED_OUTPUT', True)
            ),
            model_supports_tools=(
                selected_binding.tools
                if selected_binding
                else _boolean_setting('MODEL_SUPPORTS_TOOLS', False)
            ),
            model_supports_image_input=(
                selected_binding.image_input
                if selected_binding
                else _boolean_setting('MODEL_SUPPORTS_IMAGE_INPUT', False)
            ),
            model_supports_document_input=(
                selected_binding.document_input
                if selected_binding
                else _boolean_setting('MODEL_SUPPORTS_DOCUMENT_INPUT', False)
            ),
            model_runtime_bindings=model_runtime_bindings,
            object_storage_adapter=object_storage_adapter,
        )
