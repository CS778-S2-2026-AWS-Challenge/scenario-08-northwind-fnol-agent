"""Typed, provider-neutral contracts for bounded Staff Agent read tools."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.domain.models import ContractModel


class StaffToolResultStatus(StrEnum):
    SUCCEEDED = 'succeeded'
    NO_RESULT = 'no_result'
    PARTIAL = 'partial'
    UNAVAILABLE = 'unavailable'
    DENIED = 'denied'
    FAILED = 'failed'
    UNKNOWN = 'unknown'


class StaffClaimSearchInput(ContractModel):
    claim_reference: str | None = Field(default=None, min_length=1, max_length=200)
    customer_reference: str | None = Field(default=None, min_length=1, max_length=200)
    incident_date: date | None = None
    created_date: date | None = None
    product_family: Literal['motor', 'home', 'contents'] | None = None
    lifecycle_state: str | None = Field(default=None, min_length=1, max_length=100)
    assignee_id: str | None = Field(default=None, min_length=1, max_length=100)
    queue: str | None = Field(default=None, min_length=1, max_length=100)
    external_reference: str | None = Field(default=None, min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=25)

    @model_validator(mode='after')
    def require_bounded_filter(self) -> 'StaffClaimSearchInput':
        if all(
            value is None
            for value in (
                self.claim_reference,
                self.customer_reference,
                self.incident_date,
                self.created_date,
                self.product_family,
                self.lifecycle_state,
                self.assignee_id,
                self.queue,
                self.external_reference,
            )
        ):
            raise ValueError('At least one registered Claim search filter is required.')
        return self


class StaffClaimReadInput(ContractModel):
    claim_id: str = Field(min_length=1, max_length=100)


class StaffSessionSearchInput(ContractModel):
    claim_id: str = Field(min_length=1, max_length=100)
    session_id: str | None = Field(default=None, min_length=1, max_length=100)
    started_date: date | None = None
    status: str | None = Field(default=None, min_length=1, max_length=50)
    actor: Literal['claimant', 'agent', 'staff', 'system'] | None = None
    message_contains: str | None = Field(default=None, min_length=2, max_length=100)
    limit: int = Field(default=10, ge=1, le=25)


class StaffSessionReadInput(ContractModel):
    claim_id: str = Field(min_length=1, max_length=100)
    session_id: str = Field(min_length=1, max_length=100)
    message_limit: int = Field(default=25, ge=1, le=50)


class StaffEvidenceListInput(ContractModel):
    claim_id: str = Field(min_length=1, max_length=100)
    status: str | None = Field(default=None, min_length=1, max_length=50)
    kind: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=25, ge=1, le=50)


class StaffEvidenceReadInput(ContractModel):
    claim_id: str = Field(min_length=1, max_length=100)
    evidence_id: str = Field(min_length=1, max_length=100)


class StaffKnowledgeSearchInput(ContractModel):
    question: str = Field(min_length=1, max_length=500)
    jurisdiction: str = Field(min_length=2, max_length=20)
    visibility: Literal['customer_and_staff', 'internal_only', 'public']
    document_id: str | None = Field(default=None, min_length=1, max_length=200)
    authority: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    insurer: str = Field(min_length=1, max_length=200)
    product: Literal['motor', 'home', 'contents']
    effective_at: datetime
    limit: int = Field(default=5, ge=1, le=10)


class StaffPolicyHistoryInput(ContractModel):
    claim_id: str = Field(min_length=1, max_length=100)
    product: Literal['motor', 'home', 'contents'] | None = None
    effective_at: datetime | None = None
    limit: int = Field(default=10, ge=1, le=25)


class StaffClaimCollectionInput(ContractModel):
    claim_id: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=25, ge=1, le=50)


class StaffHandoffReadInput(StaffClaimCollectionInput):
    handoff_id: str | None = Field(default=None, min_length=1, max_length=120)


class StaffReviewSignalReadInput(StaffClaimCollectionInput):
    signal_id: str | None = Field(default=None, min_length=1, max_length=120)


class StaffWorkItemListInput(StaffClaimCollectionInput):
    work_item_id: str | None = Field(default=None, min_length=1, max_length=120)


class StaffCustomerUpdateReadInput(StaffClaimCollectionInput):
    update_id: str | None = Field(default=None, min_length=1, max_length=120)


class StaffExternalTaskStatusInput(ContractModel):
    claim_id: str = Field(min_length=1, max_length=100)
    task_id: str | None = Field(default=None, min_length=1, max_length=120)


class StaffToolResult(ContractModel):
    """Bounded observation returned to Runtime; never a Claim mutation."""

    tool_name: str = Field(pattern=r'^staff\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$')
    registry_version: str = Field(pattern=r'^v\d+\.\d+$')
    call_id: str = Field(min_length=1, max_length=120)
    correlation_id: str = Field(min_length=1, max_length=120)
    status: StaffToolResultStatus
    output: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    record_ids: list[str] = Field(default_factory=list, max_length=100)
    query_scope: str = Field(min_length=1, max_length=200)
    effective_filters: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    failure_code: str | None = Field(default=None, min_length=1, max_length=100)
    retryable: bool = False
    next_action: str | None = Field(default=None, max_length=500)
    disclose_to_model: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


STAFF_TOOL_INPUT_MODELS: dict[str, type[BaseModel]] = {
    'staff.claim.search': StaffClaimSearchInput,
    'staff.claim.read': StaffClaimReadInput,
    'staff.session.search': StaffSessionSearchInput,
    'staff.session.read': StaffSessionReadInput,
    'staff.evidence.list': StaffEvidenceListInput,
    'staff.evidence.read': StaffEvidenceReadInput,
    'staff.knowledge.search': StaffKnowledgeSearchInput,
    'staff.policy.history': StaffPolicyHistoryInput,
    'staff.handoff.read': StaffHandoffReadInput,
    'staff.review_signal.read': StaffReviewSignalReadInput,
    'staff.work_item.list': StaffWorkItemListInput,
    'staff.external_task.status': StaffExternalTaskStatusInput,
    'staff.customer_update.read': StaffCustomerUpdateReadInput,
}


__all__ = [
    'STAFF_TOOL_INPUT_MODELS',
    'StaffClaimCollectionInput',
    'StaffClaimReadInput',
    'StaffClaimSearchInput',
    'StaffCustomerUpdateReadInput',
    'StaffEvidenceListInput',
    'StaffEvidenceReadInput',
    'StaffExternalTaskStatusInput',
    'StaffHandoffReadInput',
    'StaffKnowledgeSearchInput',
    'StaffPolicyHistoryInput',
    'StaffReviewSignalReadInput',
    'StaffSessionReadInput',
    'StaffSessionSearchInput',
    'StaffToolResult',
    'StaffToolResultStatus',
    'StaffWorkItemListInput',
]
