from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.models import PageInfo


class EvaluationState(StrEnum):
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    UNKNOWN = 'unknown'


class EvaluationScenarioResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    scenario_id: str = Field(min_length=1, max_length=160)
    outcome: EvaluationState
    score: float | None = Field(default=None, ge=0, le=1)
    evidence: str = Field(min_length=1, max_length=500)


class EvaluationRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')

    evaluation_id: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=120)
    state: EvaluationState
    model_version: str = Field(min_length=1, max_length=200)
    knowledge_version: str | None = Field(default=None, max_length=200)
    rule_version: str | None = Field(default=None, max_length=200)
    configuration_id: str | None = Field(default=None, max_length=100)
    configuration_revision: int | None = Field(default=None, ge=1)
    dataset_id: str = Field(min_length=1, max_length=160)
    dataset_version: str = Field(min_length=1, max_length=100)
    fixture_version: str | None = Field(default=None, max_length=100)
    source_versions: list[str] = Field(default_factory=list, max_length=100)
    scenario_results: list[EvaluationScenarioResult] = Field(min_length=1, max_length=500)
    metrics: dict[str, float] = Field(default_factory=dict)
    threshold: float | None = Field(default=None, ge=0, le=1)
    error_code: str | None = Field(default=None, max_length=100)
    created_at: datetime
    completed_at: datetime | None = None


class EvaluationPage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[EvaluationRecord]
    page: PageInfo


class EvaluationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    purpose: str = Field(min_length=1, max_length=120)
    state: EvaluationState = EvaluationState.SUCCEEDED
    model_version: str = Field(min_length=1, max_length=200)
    knowledge_version: str | None = Field(default=None, max_length=200)
    rule_version: str | None = Field(default=None, max_length=200)
    configuration_id: str | None = Field(default=None, max_length=100)
    configuration_revision: int | None = Field(default=None, ge=1)
    dataset_id: str = Field(min_length=1, max_length=160)
    dataset_version: str = Field(min_length=1, max_length=100)
    fixture_version: str | None = Field(default=None, max_length=100)
    source_versions: list[str] = Field(default_factory=list, max_length=100)
    scenario_results: list[EvaluationScenarioResult] = Field(min_length=1, max_length=500)
    metrics: dict[str, float] = Field(default_factory=dict)
    threshold: float | None = Field(default=None, ge=0, le=1)
    error_code: str | None = Field(default=None, max_length=100)
