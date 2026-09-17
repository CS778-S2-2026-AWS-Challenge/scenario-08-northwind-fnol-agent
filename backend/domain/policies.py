"""Account-owned policy summaries used for governed selection and provenance."""

from datetime import datetime
from enum import Enum
from typing import Annotated, cast

from pydantic import Field, StringConstraints, model_validator
from pydantic_core import PydanticUndefined

from backend.domain.models import ContractModel, PageInfo

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
PolicyId = Annotated[str, StringConstraints(pattern=r'^pol_[a-f0-9]{20}$')]


class PolicyProductFamily(str, Enum):
    MOTOR = 'motor'
    HOME = 'home'
    CONTENTS = 'contents'


class PolicyVerificationStatus(str, Enum):
    UNVERIFIED = 'unverified'
    VERIFIED = 'verified'


class PolicySummaryRecord(ContractModel):
    policy_id: PolicyId
    customer_id: str = Field(min_length=1, max_length=200)
    policy_number: ShortText
    display_name: ShortText
    product_family: PolicyProductFamily
    verification_status: PolicyVerificationStatus = PolicyVerificationStatus.UNVERIFIED
    revision: int = Field(default=1, ge=1)
    active: bool = True
    created_at: datetime
    updated_at: datetime

    @model_validator(mode='after')
    def validate_timestamps(self) -> 'PolicySummaryRecord':
        if self.updated_at < self.created_at:
            raise ValueError('A policy summary cannot be updated before it is created.')
        return self


class PolicySummaryProjection(ContractModel):
    policy_id: PolicyId
    policy_number: str
    display_name: str
    product_family: PolicyProductFamily
    verification_status: PolicyVerificationStatus
    revision: int
    active: bool
    created_at: datetime
    updated_at: datetime


class CreatePolicySummaryRequest(ContractModel):
    policy_number: ShortText
    display_name: ShortText
    product_family: PolicyProductFamily


def _omitted_short_text() -> str:
    return cast(str, PydanticUndefined)


class UpdatePolicySummaryRequest(ContractModel):
    policy_number: ShortText = Field(default_factory=_omitted_short_text)
    display_name: ShortText = Field(default_factory=_omitted_short_text)

    @model_validator(mode='after')
    def require_change(self) -> 'UpdatePolicySummaryRequest':
        if not self.model_fields_set:
            raise ValueError('At least one policy summary field must be supplied.')
        return self


class PolicySummaryListResponse(ContractModel):
    items: list[PolicySummaryProjection]
    page: PageInfo


class PolicyAssociationSnapshot(ContractModel):
    policy_id: PolicyId
    policy_revision: int = Field(ge=1)
    policy_number: ShortText
    product_family: PolicyProductFamily
    verification_status: PolicyVerificationStatus


def project_policy_summary(policy: PolicySummaryRecord) -> PolicySummaryProjection:
    return PolicySummaryProjection.model_validate(policy.model_dump(exclude={'customer_id'}))


def snapshot_policy_summary(policy: PolicySummaryRecord) -> PolicyAssociationSnapshot:
    return PolicyAssociationSnapshot(
        policy_id=policy.policy_id,
        policy_revision=policy.revision,
        policy_number=policy.policy_number,
        product_family=policy.product_family,
        verification_status=policy.verification_status,
    )
