from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


@dataclass(slots=True)
class CustomerAccountRecord:
    customer_id: str
    email: str
    password_hash: str
    display_name: str
    phone: str = ''
    communication_preferences: dict[str, bool] = field(
        default_factory=lambda: {'email': True, 'sms': False}
    )


@dataclass(slots=True)
class ClaimantAuthSessionRecord:
    token_hash: str
    customer_id: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class AuthenticatedSession(BaseModel):
    customer_id: str
    access_token: str
    token_type: str = 'Bearer'
    expires_at: datetime
    development_identity: bool = True


class CurrentAuthSession(BaseModel):
    customer_id: str
    expires_at: datetime | None = None
    development_identity: bool = True


class AccountProfile(BaseModel):
    display_name: str
    email: str
    phone: str = ''


class CommunicationPreferences(BaseModel):
    email: bool
    sms: bool


class AccountProjection(BaseModel):
    customer_id: str
    profile: AccountProfile
    preferences: CommunicationPreferences
    development_identity: bool = True


class ProfilePatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    display_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(default='', max_length=40)


class PreferencesPatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: bool
    sms: bool
