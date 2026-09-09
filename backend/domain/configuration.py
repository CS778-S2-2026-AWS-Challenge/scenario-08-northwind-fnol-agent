from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.domain.admin_actions import AdminActionProjection
from backend.domain.models import PageInfo


class ConfigurationState(StrEnum):
    DRAFT = 'draft'
    VALIDATION = 'validation'
    AWAITING_APPROVAL = 'awaiting_approval'
    PUBLISHED = 'published'
    WITHDRAWN = 'withdrawn'
    SUPERSEDED = 'superseded'


class ConfigurationImpact(StrEnum):
    NORMAL = 'normal'
    HIGH = 'high'


class ApprovalDecision(StrEnum):
    APPROVED = 'approved'
    REJECTED = 'rejected'


class DataRuntimeProfileValue(StrEnum):
    FIXTURE = 'fixture'
    LOCAL_MVP = 'local_mvp'
    CLOUDFLARE = 'cloudflare'
    MONGODB = 'mongodb'
    AWS = 'aws'


class ObjectStorageAdapterValue(StrEnum):
    FIXTURE = 'fixture'
    S3_COMPATIBLE = 's3_compatible'


class IntegrationSourceValue(StrEnum):
    FIXTURE = 'fixture'
    CONFIGURED_SERVICE = 'configured_service'


REGISTERED_INTEGRATION_CAPABILITIES = {
    'persistence': 'persistence',
    'evidence_storage': 'evidence',
    'policy': 'policy_lookup',
    'claim_history': 'claim_history_lookup',
    'knowledge_documents': 'knowledge_ingestion',
    'knowledge_retrieval': 'knowledge_search',
    'claims_service': 'claim_creation',
    'assessor_service': 'assessor_routing',
    'handoff_dispatch': 'handoff_dispatch',
}
REGISTERED_INTEGRATION_IDS = tuple(REGISTERED_INTEGRATION_CAPABILITIES)


class IntegrationConfiguration(BaseModel):
    """Provider-neutral metadata for one registered external capability."""

    model_config = ConfigDict(extra='forbid')

    service_id: str = Field(min_length=1, max_length=100)
    capability: str = Field(min_length=1, max_length=100)
    source: IntegrationSourceValue
    enabled: bool = True
    health_check_timeout_seconds: float = Field(default=5.0, gt=0, le=30)


class AccessPolicyConfiguration(BaseModel):
    """Provider-neutral role and scope policy consumed by Admin authorization."""

    model_config = ConfigDict(extra='forbid')

    role: str = Field(min_length=1, max_length=100, pattern=r'^[a-z][a-z0-9_:-]*$')
    actor_type: Literal['administrator', 'staff', 'integration_service']
    scopes: list[str] = Field(min_length=1, max_length=50)
    visibility: list[str] = Field(default_factory=list, max_length=50)
    credential_reference: str | None = Field(default=None, max_length=200)
    active: bool = True


class DataProfileConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid')

    data_runtime_profile: DataRuntimeProfileValue
    object_storage_adapter: ObjectStorageAdapterValue


class ModelRuntimeConfiguration(BaseModel):
    """Provider-neutral model settings stored in a published Control Plane record."""

    model_config = ConfigDict(extra='forbid')

    protocol: str = Field(min_length=1, max_length=50, pattern=r'^[a-z][a-z0-9_]*$')
    provider: str = Field(min_length=1, max_length=100)
    model_identifier: str = Field(min_length=1, max_length=300)
    base_url: str = Field(min_length=1, max_length=500)
    credential_environment_variable: str | None = Field(
        default=None,
        max_length=200,
        pattern=r'^[A-Za-z_][A-Za-z0-9_]*$',
    )
    profile_id: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=100)
    privacy_class: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)
    evaluation_status: Literal['configured', 'degraded', 'unavailable']
    timeout_seconds: float = Field(gt=0)
    structured_output: bool = False
    tools: bool = False


class ModelRuntimeBinding(BaseModel):
    """Runtime-owned authority for model connection and claimant-turn capabilities."""

    model_config = ConfigDict(extra='forbid')

    protocol: str = Field(min_length=1, max_length=50)
    base_url: str = Field(max_length=500)
    credential_environment_variable: str | None = Field(default=None, max_length=200)
    purpose: str = Field(min_length=1, max_length=100)
    privacy_class: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)
    structured_output: bool
    tools: bool = False


class ModelCostRate(BaseModel):
    """Published model price used for bounded operational estimates."""

    model_config = ConfigDict(extra='forbid')

    model_identifier: str = Field(min_length=1, max_length=300)
    input_microunits_per_million_tokens: int = Field(ge=0)
    output_microunits_per_million_tokens: int = Field(ge=0)


class OperationalConfiguration(BaseModel):
    """Published cost, rate-limit, and alert settings for Operations projections."""

    model_config = ConfigDict(extra='forbid')

    currency: str = Field(min_length=3, max_length=3, pattern=r'^[A-Z]{3}$')
    model_cost_rates: list[ModelCostRate] = Field(min_length=1, max_length=100)
    rate_limit_window_seconds: int = Field(ge=60, le=86400)
    token_alert_threshold: int = Field(ge=1)
    cost_alert_threshold_microunits: int = Field(ge=1)
    rate_limit_alert_count: int = Field(ge=1)

    @model_validator(mode='after')
    def require_unique_model_rates(self) -> 'OperationalConfiguration':
        identifiers = [item.model_identifier for item in self.model_cost_rates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError('model cost identifiers must be unique')
        return self


class ConfigurationRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @model_validator(mode='before')
    @classmethod
    def derive_legacy_configuration_key(cls, value: object) -> object:
        """Derive the publication key for records written before keyed domains existed."""
        if not isinstance(value, dict) or 'configuration_key' in value:
            return value
        normalized = dict(value)
        values = normalized.get('values')
        if normalized.get('domain') == 'integration' and isinstance(values, dict):
            service_id = values.get('service_id')
            if isinstance(service_id, str) and service_id:
                normalized['configuration_key'] = service_id
        return normalized

    configuration_id: str
    domain: str = Field(min_length=1, max_length=80)
    configuration_key: str = Field(default='default', min_length=1, max_length=100)
    revision: int = Field(ge=1)
    state: ConfigurationState
    impact: ConfigurationImpact
    values: dict[str, object]
    secret_references: dict[str, str] = Field(default_factory=dict)
    author: str
    reason: str
    validation_evidence: dict[str, object] | None = None
    effective_time: datetime | None = None
    previous_version: str | None = None
    rollback_target: str | None = None
    updated_at: datetime


class AdminConfigurationProjection(ConfigurationRecord):
    """Configuration record plus principal-aware lifecycle actions."""

    allowed_actions: list[AdminActionProjection] = Field(default_factory=list)


class AdminConfigurationPage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[AdminConfigurationProjection]
    page: PageInfo


class ConfigurationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    domain: str = Field(min_length=1, max_length=80)
    impact: ConfigurationImpact = ConfigurationImpact.NORMAL
    values: dict[str, object] = Field(default_factory=dict)
    secret_references: dict[str, str] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=500)


class ConfigurationPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    values: dict[str, object] | None = None
    secret_references: dict[str, str] | None = None
    reason: str = Field(min_length=1, max_length=500)


class ValidationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    scenario_results: list['ValidationScenarioResult'] = Field(min_length=1, max_length=100)


class ValidationScenarioResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    scenario_id: str = Field(min_length=1, max_length=120)
    outcome: Literal['passed', 'failed']
    evidence: str = Field(min_length=1, max_length=500)


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    reason: str = Field(min_length=1, max_length=500)
    rollback_target: str | None = None


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    decision: ApprovalDecision
    reason: str = Field(min_length=1, max_length=500)


class ConfigurationApprovalRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')

    approval_id: str
    configuration_id: str
    configuration_revision: int = Field(ge=1)
    reviewer: str = Field(min_length=1, max_length=200)
    decision: ApprovalDecision
    reason: str = Field(min_length=1, max_length=500)
    created_at: datetime


class AuditEvent(BaseModel):
    event_id: str
    configuration_id: str
    revision: int
    previous_revision: int | None = None
    actor: str
    action: str
    reason: str
    outcome: str
    changed_fields: list[str] = Field(default_factory=list)
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditEvent]
    page: dict[str, str | None]


def now_utc() -> datetime:
    return datetime.now(UTC)
