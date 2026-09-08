"""Administration action projections derived from authoritative server state."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AdminActionAvailability(StrEnum):
    AVAILABLE = 'available'
    CONFIRMATION_REQUIRED = 'confirmation_required'
    BLOCKED = 'blocked'


class AdminActionProjection(BaseModel):
    """One server-projected Control Plane action for a specific resource revision."""

    model_config = ConfigDict(extra='forbid')

    action_code: str = Field(min_length=1, max_length=120)
    availability: AdminActionAvailability
    expected_revision: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, min_length=1, max_length=300)
