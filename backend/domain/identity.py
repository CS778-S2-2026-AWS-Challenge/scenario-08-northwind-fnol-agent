import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from backend.domain.admin_actions import AdminActionProjection
from backend.domain.ids import new_id
from backend.domain.models import PageInfo

PROFILE_NAME_MAX_LENGTH = 120
PROFILE_ADDRESS_MAX_LENGTH = 500
PROFILE_PHONE_MAX_LENGTH = 40
_PROFILE_EMAIL_PATTERN_TEXT = (
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r'@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+'
    r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$'
)
_PROFILE_EMAIL_PATTERN = re.compile(_PROFILE_EMAIL_PATTERN_TEXT)


def normalize_profile_email(value: str) -> str:
    """Return the canonical supported claimant email shape."""
    normalized = value.strip().lower()
    if len(normalized) > 254 or not _PROFILE_EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError('Enter a valid email address.')
    local_part, _ = normalized.rsplit('@', 1)
    if len(local_part) > 64:
        raise ValueError('Enter a valid email address.')
    return normalized


ProfileName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=PROFILE_NAME_MAX_LENGTH),
]
ProfileAddress = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=PROFILE_ADDRESS_MAX_LENGTH),
]
ProfileEmail = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=254,
        pattern=_PROFILE_EMAIL_PATTERN_TEXT,
    ),
    AfterValidator(normalize_profile_email),
]
ProfilePhone = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=PROFILE_PHONE_MAX_LENGTH)
]


@dataclass(slots=True)
class CustomerAccountRecord:
    customer_id: str
    email: str
    password_hash: str
    display_name: str
    legal_name: str = ''
    preferred_name: str | None = None
    date_of_birth: date | None = None
    phone: str = ''
    residential_address: str | None = None
    communication_preferences: dict[str, bool] = field(
        default_factory=lambda: {'email': True, 'sms': False}
    )
    claim_auto_fill_preferences: dict[str, bool] = field(
        default_factory=lambda: {
            'personal_details': False,
            'policy_number': False,
            'saved_assets': False,
            'payment_details': False,
            'identity_information': False,
        }
    )
    active: bool = True
    revision: int = 1
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def validate_customer_account_profile(account: CustomerAccountRecord) -> None:
    """Reject non-normalized or internally inconsistent persisted profile text."""
    try:
        normalized_email = normalize_profile_email(account.email)
    except ValueError as error:
        raise ValueError('invalid_email') from error
    if account.email != normalized_email:
        raise ValueError('invalid_email')
    if (
        not account.legal_name
        or len(account.legal_name) > PROFILE_NAME_MAX_LENGTH
        or account.legal_name != account.legal_name.strip()
    ):
        raise ValueError('invalid_legal_name')
    if account.preferred_name is not None and (
        not account.preferred_name
        or len(account.preferred_name) > PROFILE_NAME_MAX_LENGTH
        or account.preferred_name != account.preferred_name.strip()
    ):
        raise ValueError('invalid_preferred_name')
    if account.residential_address is not None and (
        not account.residential_address
        or len(account.residential_address) > PROFILE_ADDRESS_MAX_LENGTH
        or account.residential_address != account.residential_address.strip()
    ):
        raise ValueError('invalid_residential_address')
    if len(account.phone) > PROFILE_PHONE_MAX_LENGTH or account.phone != account.phone.strip():
        raise ValueError('invalid_phone')
    if account.display_name != (account.preferred_name or account.legal_name):
        raise ValueError('invalid_name_projection')


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

    email: ProfileEmail
    password: str = Field(min_length=8, max_length=256)
    display_name: ProfileName


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
    legal_name: str
    preferred_name: str | None = None
    date_of_birth: date | None = None
    email: str
    phone: str = ''
    residential_address: str | None = None


class CommunicationPreferences(BaseModel):
    email: bool
    sms: bool


class ClaimAutoFillPreferences(BaseModel):
    personal_details: bool = False
    policy_number: bool = False
    saved_assets: bool = False
    payment_details: bool = False
    identity_information: bool = False


class ClaimAutoFillCategory(str, Enum):
    PERSONAL_DETAILS = 'personal_details'
    POLICY_NUMBER = 'policy_number'
    SAVED_ASSETS = 'saved_assets'
    PAYMENT_DETAILS = 'payment_details'
    IDENTITY_INFORMATION = 'identity_information'


class ClaimAutoFillAction(str, Enum):
    REVIEW_AND_CONFIRM = 'review_and_confirm'
    SELECT_POLICY = 'select_policy'
    SELECT_ASSET = 'select_asset'
    CONFIRM_SEPARATELY = 'confirm_separately'


class ClaimAutoFillSuggestion(BaseModel):
    category: ClaimAutoFillCategory
    enabled: bool
    available: bool
    eligible: bool
    action: ClaimAutoFillAction


class ClaimAutoFillSuggestionManifest(BaseModel):
    claim_id: str
    claim_revision: int = Field(ge=1)
    account_revision: int = Field(ge=1)
    suggestions: list[ClaimAutoFillSuggestion]


class AccountProjection(BaseModel):
    customer_id: str
    profile: AccountProfile
    preferences: CommunicationPreferences
    claim_auto_fill_preferences: ClaimAutoFillPreferences
    revision: int = Field(ge=1)
    updated_at: datetime
    development_identity: bool = False


class ProfilePatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: ProfileEmail | None = None
    legal_name: ProfileName | None = None
    preferred_name: ProfileName | None = None
    date_of_birth: date | None = None
    phone: ProfilePhone | None = None
    residential_address: ProfileAddress | None = None
    # Transitional write alias for clients that have not moved to legal_name yet.
    display_name: ProfileName | None = None

    @field_validator('date_of_birth')
    @classmethod
    def date_of_birth_cannot_be_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError('date_of_birth cannot be in the future.')
        return value

    @model_validator(mode='after')
    def validate_compatibility_name(self) -> 'ProfilePatchRequest':
        if not self.model_fields_set:
            raise ValueError('At least one profile field must be supplied.')
        if 'legal_name' in self.model_fields_set and self.legal_name is None:
            raise ValueError('legal_name cannot be null.')
        if 'display_name' in self.model_fields_set and self.display_name is None:
            raise ValueError('display_name cannot be null.')
        if 'email' in self.model_fields_set and self.email is None:
            raise ValueError('email cannot be null.')
        if 'phone' in self.model_fields_set and self.phone is None:
            raise ValueError('phone cannot be null.')
        if (
            self.legal_name is not None
            and self.display_name is not None
            and self.legal_name.strip() != self.display_name.strip()
        ):
            raise ValueError('display_name and legal_name cannot describe different names.')
        return self


class PreferencesPatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: bool
    sms: bool


class ClaimAutoFillPreferencesPatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    personal_details: bool
    policy_number: bool
    saved_assets: bool
    payment_details: bool
    identity_information: bool


class AdminCustomerAccountProjection(BaseModel):
    customer_id: str
    email: str
    display_name: str
    legal_name: str
    preferred_name: str | None = None
    phone: str
    active: bool
    communication_preferences: CommunicationPreferences
    revision: int = Field(ge=1)
    updated_at: datetime
    allowed_actions: list[AdminActionProjection] = Field(default_factory=list)


class AdminCustomerAccountPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')

    legal_name: ProfileName | None = None
    preferred_name: ProfileName | None = None
    # Transitional alias: updates the currently visible canonical name.
    display_name: ProfileName | None = None
    phone: ProfilePhone | None = None
    active: bool | None = None


class AdminCustomerAccountCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: ProfileEmail
    initial_password: str = Field(min_length=8, max_length=256)
    display_name: ProfileName
    phone: ProfilePhone = ''


class AdminCustomerAccountPage(BaseModel):
    items: list[AdminCustomerAccountProjection]
    page: PageInfo
