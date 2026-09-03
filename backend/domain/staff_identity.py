from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


@dataclass(slots=True)
class StaffAccountRecord:
    staff_id: str
    email: str
    password_hash: str
    display_name: str
    roles: tuple[str, ...] = ('claims_professional',)
    active: bool = True


@dataclass(slots=True)
class StaffAuthSessionRecord:
    token_hash: str
    staff_id: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


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
