from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.domain.models import PageInfo


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    message: str = Field(min_length=1, max_length=2000)

    @field_validator('message', mode='before')
    @classmethod
    def normalize_message(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class FeedbackRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')

    feedback_id: str
    message: str = Field(min_length=1, max_length=2000)
    submitted_by_staff_id: str = Field(min_length=1, max_length=100)
    submitted_by_display_name: str = Field(min_length=1, max_length=120)
    source: Literal['workbench'] = 'workbench'
    created_at: datetime


class FeedbackReceipt(BaseModel):
    model_config = ConfigDict(extra='forbid')

    feedback_id: str
    created_at: datetime


class FeedbackPage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[FeedbackRecord]
    page: PageInfo
