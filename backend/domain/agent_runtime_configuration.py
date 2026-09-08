"""Typed Control Plane configuration consumed by the Agent runtime."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentInstructionConfiguration(BaseModel):
    """Versioned system instruction compiled into claimant model requests."""

    model_config = ConfigDict(extra='forbid')

    prompt_version: str = Field(min_length=1, max_length=100)
    purpose: Literal['claimant_agent'] = 'claimant_agent'
    system_prompt: str = Field(min_length=1, max_length=50_000)


class AgentToolPolicyConfiguration(BaseModel):
    """Additional allow-list over server-registered actions and tools."""

    model_config = ConfigDict(extra='forbid')

    policy_version: str = Field(min_length=1, max_length=100)
    allowed_action_codes: list[str] = Field(min_length=1, max_length=100)
    allowed_tool_names: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def require_unique_entries(self) -> 'AgentToolPolicyConfiguration':
        for values, label in (
            (self.allowed_action_codes, 'allowed_action_codes'),
            (self.allowed_tool_names, 'allowed_tool_names'),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f'{label} must not contain duplicates.')
        return self


class ControlledRulesConfiguration(BaseModel):
    """Bounded overlay for registered Dynamic Form branch rules."""

    model_config = ConfigDict(extra='forbid')

    rules_version: str = Field(min_length=1, max_length=100)
    disabled_rule_ids: list[str] = Field(default_factory=list, max_length=100)
    observation_rule_ids: list[str] = Field(default_factory=list, max_length=100)

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


AgentRuntimeConfiguration = (
    AgentInstructionConfiguration
    | AgentToolPolicyConfiguration
    | ControlledRulesConfiguration
    | AgentFeatureSettingsConfiguration
)
