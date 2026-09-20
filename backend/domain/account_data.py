"""Bounded account-owned policy and protected-data contracts."""

from datetime import datetime
from enum import Enum
from typing import Annotated, cast

from pydantic import Field, StringConstraints, field_validator, model_validator
from pydantic_core import PydanticUndefined

from backend.domain.models import ContractModel, PageInfo, StructuredFormField

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ProtectedNumber = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=4, max_length=80)
]


def _validate_protected_number(value: str, field_name: str) -> str:
    if len([character for character in value if character.isalnum()]) < 4:
        raise ValueError(f'{field_name} must contain at least four letters or digits.')
    return value


class IdentityDocumentType(str, Enum):
    DRIVER_LICENCE = 'driver_licence'
    PASSPORT = 'passport'


class PolicyNumberRecord(ContractModel):
    policy_id: str = Field(pattern=r'^pol_[a-f0-9]{20}$')
    customer_id: str = Field(min_length=1, max_length=200)
    policy_number: ShortText
    revision: int = Field(default=1, ge=1)
    active: bool = True
    created_at: datetime
    updated_at: datetime

    @model_validator(mode='after')
    def validate_timestamps(self) -> 'PolicyNumberRecord':
        if self.updated_at < self.created_at:
            raise ValueError('A policy cannot be updated before it is created.')
        return self


class ProtectedAccountRecord(ContractModel):
    customer_id: str = Field(min_length=1, max_length=200)
    protected_value: str = Field(min_length=1, max_length=1000)
    masked_value: str = Field(min_length=4, max_length=100)
    revision: int = Field(default=1, ge=1)
    active: bool = True
    created_at: datetime
    updated_at: datetime

    @model_validator(mode='after')
    def validate_timestamps(self) -> 'ProtectedAccountRecord':
        if self.updated_at < self.created_at:
            raise ValueError('A protected record cannot be updated before it is created.')
        return self


class PaymentDestinationRecord(ProtectedAccountRecord):
    payment_destination_id: str = Field(pattern=r'^pyd_[a-f0-9]{20}$')
    account_type: ShortText


class IdentityDocumentRecord(ProtectedAccountRecord):
    identity_id: str = Field(pattern=r'^idn_[a-f0-9]{20}$')
    document_type: IdentityDocumentType


class PolicyNumberProjection(ContractModel):
    policy_id: str
    policy_number: str
    revision: int
    active: bool
    created_at: datetime
    updated_at: datetime


class PaymentDestinationProjection(ContractModel):
    payment_destination_id: str
    account_type: str
    masked_account_number: str
    revision: int
    active: bool
    created_at: datetime
    updated_at: datetime


class IdentityDocumentProjection(ContractModel):
    identity_id: str
    document_type: IdentityDocumentType
    masked_document_number: str
    revision: int
    active: bool
    created_at: datetime
    updated_at: datetime


class CreatePolicyNumberRequest(ContractModel):
    policy_number: ShortText


class CreatePaymentDestinationRequest(ContractModel):
    account_type: ShortText
    account_number: ProtectedNumber

    @field_validator('account_number')
    @classmethod
    def require_meaningful_number(cls, value: str) -> str:
        return _validate_protected_number(value, 'account_number')


class CreateIdentityDocumentRequest(ContractModel):
    document_type: IdentityDocumentType
    document_number: ProtectedNumber

    @field_validator('document_number')
    @classmethod
    def require_meaningful_number(cls, value: str) -> str:
        return _validate_protected_number(value, 'document_number')


def _omitted_short_text() -> str:
    return cast(str, PydanticUndefined)


def _omitted_protected_number() -> str:
    return cast(str, PydanticUndefined)


class UpdatePolicyNumberRequest(ContractModel):
    policy_number: ShortText = Field(default_factory=_omitted_short_text)

    @model_validator(mode='after')
    def require_change(self) -> 'UpdatePolicyNumberRequest':
        if not self.model_fields_set:
            raise ValueError('policy_number must be supplied.')
        return self


class UpdatePaymentDestinationRequest(ContractModel):
    account_type: ShortText = Field(default_factory=_omitted_short_text)
    account_number: ProtectedNumber = Field(default_factory=_omitted_protected_number)

    @field_validator('account_number')
    @classmethod
    def require_meaningful_number(cls, value: str) -> str:
        return _validate_protected_number(value, 'account_number')

    @model_validator(mode='after')
    def require_change(self) -> 'UpdatePaymentDestinationRequest':
        if not self.model_fields_set:
            raise ValueError('At least one payment destination field must be supplied.')
        return self


class UpdateIdentityDocumentRequest(ContractModel):
    document_type: IdentityDocumentType | None = None
    document_number: ProtectedNumber = Field(default_factory=_omitted_protected_number)

    @field_validator('document_number')
    @classmethod
    def require_meaningful_number(cls, value: str) -> str:
        return _validate_protected_number(value, 'document_number')

    @model_validator(mode='after')
    def require_change(self) -> 'UpdateIdentityDocumentRequest':
        if not self.model_fields_set:
            raise ValueError('At least one identity document field must be supplied.')
        if 'document_type' in self.model_fields_set and self.document_type is None:
            raise ValueError('document_type cannot be null.')
        return self


class PolicyNumberListResponse(ContractModel):
    items: list[PolicyNumberProjection]
    page: PageInfo


class PaymentDestinationListResponse(ContractModel):
    items: list[PaymentDestinationProjection]
    page: PageInfo


class IdentityDocumentListResponse(ContractModel):
    items: list[IdentityDocumentProjection]
    page: PageInfo


class SelectPolicyNumberRequest(ContractModel):
    policy_id: str = Field(pattern=r'^pol_[a-f0-9]{20}$')


class ClaimPolicySelectionResponse(ContractModel):
    claim_id: str
    revision: int
    proposed_field: StructuredFormField


def project_policy(record: PolicyNumberRecord) -> PolicyNumberProjection:
    return PolicyNumberProjection.model_validate(record.model_dump(exclude={'customer_id'}))


def project_payment_destination(
    record: PaymentDestinationRecord,
) -> PaymentDestinationProjection:
    return PaymentDestinationProjection(
        payment_destination_id=record.payment_destination_id,
        account_type=record.account_type,
        masked_account_number=record.masked_value,
        revision=record.revision,
        active=record.active,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def project_identity_document(record: IdentityDocumentRecord) -> IdentityDocumentProjection:
    return IdentityDocumentProjection(
        identity_id=record.identity_id,
        document_type=record.document_type,
        masked_document_number=record.masked_value,
        revision=record.revision,
        active=record.active,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
