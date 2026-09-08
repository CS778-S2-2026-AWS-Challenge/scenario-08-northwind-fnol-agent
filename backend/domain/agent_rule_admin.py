from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.agent_runtime_configuration import AgentRuntimeConfiguration
from backend.domain.configuration import ConfigurationImpact, ConfigurationRecord
from backend.domain.models import PageInfo


class AgentRuleComponent(StrEnum):
    INSTRUCTIONS = 'instructions'
    TOOL_PERMISSIONS = 'tool_permissions'
    CONTROLLED_RULES = 'controlled_rules'
    FEATURE_SETTINGS = 'feature_settings'


class AgentRuleCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    values: AgentRuntimeConfiguration
    impact: ConfigurationImpact = ConfigurationImpact.HIGH
    reason: str = Field(min_length=1, max_length=500)


class AgentRulePage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[ConfigurationRecord]
    page: PageInfo
