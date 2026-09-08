from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.admin_actions import AdminActionProjection
from backend.domain.ids import new_id
from backend.domain.models import PageInfo


@dataclass(slots=True)
class StaffAccountRecord:
    staff_id: str
    email: str
    password_hash: str
    display_name: str
    roles: tuple[str, ...] = ('claims_professional',)
    active: bool = True
    revision: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class StaffAuthSessionRecord:
    token_hash: str
    staff_id: str
    created_at: datetime
    expires_at: datetime
    session_id: str = field(default_factory=lambda: new_id('ias'))
    revoked_at: datetime | None = None
    revision: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class StaffPresenceRecord(BaseModel):
    """Short-lived, provider-neutral staff presence used for Workbench eligibility."""

    staff_id: str = Field(min_length=1, max_length=100)
    online: bool
    available: bool
    last_seen_at: datetime
    expires_at: datetime
    revision: int = Field(default=1, ge=1)
    updated_at: datetime

    def is_claimable(self, now: datetime) -> bool:
        return self.online and self.available and self.expires_at > now


class StaffPresenceUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    online: bool = True
    available: bool = True
    lease_seconds: int = Field(default=60, ge=15, le=300)


class StaffLoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class AuthenticatedStaffSession(BaseModel):
    staff_id: str
    access_token: str
    token_type: str = 'Bearer'
    expires_at: datetime
    development_identity: bool = False


class CurrentStaffSession(BaseModel):
    staff_id: str
    expires_at: datetime | None = None
    development_identity: bool = False


class StaffProfileProjection(BaseModel):
    staff_id: str
    display_name: str
    email: str
    roles: list[str]
    development_identity: bool = False


class AdminStaffAccountProjection(BaseModel):
    staff_id: str
    email: str
    display_name: str
    roles: list[str]
    active: bool
    revision: int = Field(ge=1)
    updated_at: datetime
    allowed_actions: list[AdminActionProjection] = Field(default_factory=list)


class AdminStaffAccountPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    roles: list[str] | None = Field(default=None, min_length=1, max_length=20)
    active: bool | None = None


class AdminStaffAccountCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: str = Field(min_length=3, max_length=254)
    initial_password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    roles: list[str] = Field(min_length=1, max_length=20)


class AdminStaffAccountPage(BaseModel):
    items: list[AdminStaffAccountProjection]
    page: PageInfo
