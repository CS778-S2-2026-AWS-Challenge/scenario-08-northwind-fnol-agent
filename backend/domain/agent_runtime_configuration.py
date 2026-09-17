"""Typed Control Plane configuration consumed by the Agent runtime."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.domain.agent_context_runtime import (
    ContextBudgetPolicy,
    ProviderCapability,
    RequestProfile,
)
from backend.domain.prompt_pack import PromptFragmentDefinition


class PublishedPromptFragment(PromptFragmentDefinition):
    """Immutable Prompt fragment content stored inside one configuration revision."""

    content: str = Field(min_length=1, max_length=20_000)


class AgentInstructionConfiguration(BaseModel):
    """Versioned system instruction compiled into claimant model requests."""

    model_config = ConfigDict(extra='forbid')

    prompt_version: str = Field(min_length=1, max_length=100)
    purpose: Literal['claimant_agent'] = 'claimant_agent'
    composition_mode: Literal['single', 'fragmented'] = 'single'
    system_prompt: str | None = Field(default=None, min_length=1, max_length=50_000)
    manifest_version: str | None = Field(default=None, min_length=1, max_length=100)
    fragments: list[PublishedPromptFragment] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def require_one_complete_composition(self) -> 'AgentInstructionConfiguration':
        if self.composition_mode == 'single':
            if self.system_prompt is None or self.fragments or self.manifest_version is not None:
                raise ValueError('A single Prompt configuration requires only system_prompt.')
            return self
        if self.system_prompt is not None or self.manifest_version is None or not self.fragments:
            raise ValueError('A fragmented Prompt configuration requires manifest and fragments.')
        fragment_ids = [item.fragment_id for item in self.fragments]
        if len(fragment_ids) != len(set(fragment_ids)):
            raise ValueError('Published Prompt fragment IDs must be unique.')
        return self


class AgentToolPolicyConfiguration(BaseModel):
    """Additional allow-list over server-registered actions and tools."""

    model_config = ConfigDict(extra='forbid')

    policy_version: str = Field(min_length=1, max_length=100)
    allowed_action_codes: list[str] = Field(min_length=1, max_length=100)
    allowed_tool_names: list[str] = Field(default_factory=list, max_length=100)
    request_profiles: list[RequestProfile] = Field(default_factory=list, max_length=20)
    provider_capabilities: dict[str, ProviderCapability] = Field(default_factory=dict)
    schema_registry: dict[str, dict[str, object]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def require_unique_entries(self) -> 'AgentToolPolicyConfiguration':
        for values, label in (
            (self.allowed_action_codes, 'allowed_action_codes'),
            (self.allowed_tool_names, 'allowed_tool_names'),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f'{label} must not contain duplicates.')
        profile_ids = [item.profile_id for item in self.request_profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError('request_profiles must not contain duplicate profile IDs.')
        return self


class ControlledRulesConfiguration(BaseModel):
    """Bounded overlay for registered Dynamic Form branch rules."""

    model_config = ConfigDict(extra='forbid')

    rules_version: str = Field(min_length=1, max_length=100)
    disabled_rule_ids: list[str] = Field(default_factory=list, max_length=100)
    observation_rule_ids: list[str] = Field(default_factory=list, max_length=100)
    route_policy_version: str | None = Field(default=None, max_length=100)
    context_catalogue_version: str | None = Field(default=None, max_length=100)
    context_budget_policy: ContextBudgetPolicy | None = None
    deterministic_responses: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def require_disjoint_unique_rules(self) -> 'ControlledRulesConfiguration':
        disabled = set(self.disabled_rule_ids)
        observed = set(self.observation_rule_ids)
        if len(disabled) != len(self.disabled_rule_ids):
            raise ValueError('disabled_rule_ids must not contain duplicates.')
        if len(observed) != len(self.observation_rule_ids):
            raise ValueError('observation_rule_ids must not contain duplicates.')
        if disabled & observed:
            raise ValueError('A controlled rule cannot be both disabled and observed.')
        return self


class AgentFeatureSettingsConfiguration(BaseModel):
    """Non-safety Agent capabilities that a published release may disable."""

    model_config = ConfigDict(extra='forbid')

    feature_version: str = Field(min_length=1, max_length=100)
    model_assisted_turns: bool = True
    knowledge_retrieval: bool = True
    external_service_offers: bool = True
    fragmented_prompt: bool = False
    budgeted_context: bool = False
    narrow_schema: bool = False
    verified_rolling_summary: bool = False
    isolated_execution: bool = False
    cache_layout_version: str | None = Field(default=None, max_length=100)


AgentRuntimeConfiguration = (
    AgentInstructionConfiguration
    | AgentToolPolicyConfiguration
    | ControlledRulesConfiguration
    | AgentFeatureSettingsConfiguration
)
