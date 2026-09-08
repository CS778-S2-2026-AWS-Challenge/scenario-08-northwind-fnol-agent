"""Safe administration projections for identity sessions."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.admin_actions import AdminActionProjection
from backend.domain.models import PageInfo


class AdminSessionState(StrEnum):
    ACTIVE = 'active'
    EXPIRED = 'expired'
    REVOKED = 'revoked'


class AdminAccountSessionProjection(BaseModel):
    """One revocable identity session without bearer-token material."""

    model_config = ConfigDict(extra='forbid')

    session_id: str = Field(pattern=r'^ias_[A-Za-z0-9_-]{1,96}$')
    state: AdminSessionState
    revision: int = Field(ge=1)
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    updated_at: datetime
    allowed_actions: list[AdminActionProjection] = Field(default_factory=list)


class AdminAccountSessionPage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items: list[AdminAccountSessionProjection]
    page: PageInfo
