"""Typed, provider-neutral contracts for bounded Staff Agent read tools."""

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.domain.models import (
    ContractModel,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceStatus,
    HandoffRecord,
    HandoffStatus,
    HandoffType,
    NeededFor,
    ResponsibleParty,
    WorkflowState,
    WorkingClaim,
)
from backend.domain.workbench import ClaimLifecycleState, WorkbenchQueueKey


class StaffClaimSearchCandidate(ContractModel):
    """Minimal authoritative projection returned by the Claim search boundary."""

    claim: WorkingClaim
    lifecycle_state: ClaimLifecycleState
    assignee_id: str | None = None
    queue: WorkbenchQueueKey


def _pending_evidence(records: Sequence[EvidenceRecord]) -> list[EvidenceRecord]:
    pending_file_states = {
        EvidenceFileStatus.AWAITING_UPLOAD,
        EvidenceFileStatus.UPLOADING,
        EvidenceFileStatus.UPLOADED,
        EvidenceFileStatus.PROCESSING,
        EvidenceFileStatus.FAILED,
    }
    return [
        record
        for record in records
        if record.status
        in {
            EvidenceStatus.PENDING,
            EvidenceStatus.MISSING,
            EvidenceStatus.INVALID,
            EvidenceStatus.UNOFFICIAL,
        }
        or record.file_status in pending_file_states
    ]


def build_staff_claim_search_candidate(
    claim: WorkingClaim,
    evidence: Sequence[EvidenceRecord],
    handoffs: Sequence[HandoffRecord],
) -> StaffClaimSearchCandidate:
    """Build the registered search fields without constructing a full Workbench Claim."""

    active_handoffs = sorted(
        (
            item
            for item in handoffs
            if item.status not in {HandoffStatus.RESOLVED, HandoffStatus.CANCELLED}
        ),
        key=lambda item: item.created_at,
    )
    pending_evidence = _pending_evidence(evidence)
    if (
        claim.claim_state.workflow_state is WorkflowState.CREATED
        or claim.external_claim is not None
    ):
        lifecycle = ClaimLifecycleState.CREATED
    elif (
        any(item.type is HandoffType.PROFESSIONAL_REVIEW for item in active_handoffs)
        or claim.claim_state.workflow_state is WorkflowState.PROFESSIONAL_REVIEW
    ):
        lifecycle = ClaimLifecycleState.PROFESSIONAL_REVIEW
    elif active_handoffs:
        lifecycle = ClaimLifecycleState.STAFF_SUPPORT
    elif claim.claim_state.workflow_state is WorkflowState.READY_FOR_NEXT:
        lifecycle = ClaimLifecycleState.READY_TO_CREATE
    elif claim.claim_state.workflow_state is WorkflowState.AWAITING_EVIDENCE:
        lifecycle = (
            ClaimLifecycleState.WAITING_EXTERNAL
            if any(
                item.responsible_party is ResponsibleParty.EXTERNAL_PARTY
                for item in pending_evidence
            )
            else ClaimLifecycleState.WAITING_CUSTOMER
        )
    else:
        lifecycle = ClaimLifecycleState.DRAFT_ACTIVE

    assigned_handoff = next(
        (item for item in reversed(active_handoffs) if item.assigned_to is not None),
        None,
    )
    assignee_id = assigned_handoff.assigned_to if assigned_handoff else claim.assignee_id
    if active_handoffs:
        queue = WorkbenchQueueKey.PROCESSING
    elif claim.terminal_disposition is not None:
        queue = WorkbenchQueueKey(claim.terminal_disposition.value.value)
    elif lifecycle is ClaimLifecycleState.WAITING_EXTERNAL:
        queue = WorkbenchQueueKey.WAITING_THIRD_PARTY
    elif lifecycle is ClaimLifecycleState.WAITING_CUSTOMER:
        claimant_material_required = any(
            NeededFor.CURRENT_ACTION in item.needed_for
            and item.responsible_party is ResponsibleParty.CLAIMANT
            for item in pending_evidence
        )
        queue = (
            WorkbenchQueueKey.WAITING_MATERIAL
            if claimant_material_required
            else WorkbenchQueueKey.WAITING_USER
        )
    else:
        queue = WorkbenchQueueKey.PROCESSING
    return StaffClaimSearchCandidate(
        claim=claim,
        lifecycle_state=lifecycle,
        assignee_id=assignee_id,
        queue=queue,
    )


def staff_claim_search_matches(
    candidate: StaffClaimSearchCandidate,
    filters: Mapping[str, object],
) -> bool:
    """Apply every registered Claim filter to one authoritative search projection."""

    claim = candidate.claim
    external_reference = claim.external_claim.claim_number if claim.external_claim else None
    claim_references = {claim.claim_id, external_reference}
    incident = claim.form.get('incident.occurred_at')
    incident_date = str(incident.value)[:10] if incident and incident.value is not None else None
    family_field = claim.form.get('claim.product_family')
    product_family = (
        str(family_field.value)
        if family_field and family_field.value is not None
        else claim.incident_type
    )
    return all(
        (
            not filters.get('claim_reference') or filters['claim_reference'] in claim_references,
            not filters.get('customer_reference')
            or filters['customer_reference'] == claim.customer_id,
            not filters.get('external_reference')
            or filters['external_reference'] == external_reference,
            not filters.get('created_date')
            or str(filters['created_date']) == claim.created_at.date().isoformat(),
            not filters.get('incident_date') or str(filters['incident_date']) == incident_date,
            not filters.get('product_family') or filters['product_family'] == product_family,
            not filters.get('lifecycle_state')
            or filters['lifecycle_state'] == candidate.lifecycle_state.value,
            not filters.get('assignee_id') or filters['assignee_id'] == candidate.assignee_id,
            not filters.get('queue') or filters['queue'] == candidate.queue.value,
        )
    )


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
