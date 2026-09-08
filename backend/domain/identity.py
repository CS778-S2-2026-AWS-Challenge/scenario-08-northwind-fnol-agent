from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.admin_actions import AdminActionProjection
from backend.domain.ids import new_id
from backend.domain.models import PageInfo


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
    active: bool = True
    revision: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class ClaimantAuthSessionRecord:
    token_hash: str
    customer_id: str
    created_at: datetime
    expires_at: datetime
    session_id: str = field(default_factory=lambda: new_id('ias'))
    revoked_at: datetime | None = None
    revision: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)


class AuthenticatedSession(BaseModel):
    customer_id: str
    access_token: str
    token_type: str = 'Bearer'
    expires_at: datetime
    development_identity: bool = False


class CurrentAuthSession(BaseModel):
    customer_id: str
    expires_at: datetime | None = None
    development_identity: bool = False


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
    development_identity: bool = False


class ProfilePatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    display_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(default='', max_length=40)


class PreferencesPatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: bool
    sms: bool


class AdminCustomerAccountProjection(BaseModel):
    customer_id: str
    email: str
    display_name: str
    phone: str
    active: bool
    communication_preferences: CommunicationPreferences
    revision: int = Field(ge=1)
    updated_at: datetime
    allowed_actions: list[AdminActionProjection] = Field(default_factory=list)


class AdminCustomerAccountPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    active: bool | None = None


class AdminCustomerAccountCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: str = Field(min_length=3, max_length=254)
    initial_password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(default='', max_length=40)


class AdminCustomerAccountPage(BaseModel):
    items: list[AdminCustomerAccountProjection]
    page: PageInfo
