from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.models import (
    CustomerNextStep,
    Urgency,
    WorkbenchClaimDetail,
    WorkbenchClaimItem,
    WorkbenchClaimListResponse,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.protocols import PersistenceRepository


def _customer_reference(customer_id: str) -> str:
    return customer_id.replace('cus_', 'customer-')


def _queue_for(claim: WorkingClaim) -> str:
    if claim.claim_state.workflow_state == WorkflowState.PROFESSIONAL_REVIEW:
        return 'professional_review'
    if claim.claim_state.workflow_state == WorkflowState.AWAITING_EVIDENCE:
        return 'awaiting_evidence'
    if claim.claim_state.workflow_state == WorkflowState.READY_FOR_NEXT:
        return 'ready_to_progress'
    if claim.claim_state.workflow_state == WorkflowState.CREATED:
        return 'created_routed'
    return 'new_untriaged'


def _priority_for(claim: WorkingClaim) -> str:
    if claim.claim_state.urgency == Urgency.URGENT:
        return 'urgent'
    return 'standard'


def _internal_flags_for(claim: WorkingClaim) -> list[str]:
    flags = []
    if claim.claim_state.fraud_signal.value == 'review_required':
        flags.append('FRAUD_REVIEW_REQUIRED')
    return flags


def _assigned_to_for(claim: WorkingClaim) -> str | None:
    # Return persisted assignment if available, otherwise None
    # TODO: wire to persistent handoff/assignment records (PR #81)
    return None


def _internal_notes_for(claim: WorkingClaim) -> str:
    # Return persisted internal notes if available
    # TODO: wire to persistent action/handoff notes (PR #81)
    return ''


def list_workbench_claims(
    repository: PersistenceRepository,
    principal: Principal,
    view: str | None = None,
) -> WorkbenchClaimListResponse:
    if principal.actor_type != 'staff':
        raise ApiError(
            status_code=403,
            code='AUTHORIZATION_REQUIRED',
            message='Staff credentials required to access the workbench.',
        )

    claims = repository.list_claims()
    items: list[WorkbenchClaimItem] = []
    for claim in claims:
        queue = _queue_for(claim)
        if view is not None and view != 'all' and queue != view:
            continue
        items.append(
            WorkbenchClaimItem(
                claim_id=claim.claim_id,
                revision=claim.revision,
                customer_reference=_customer_reference(claim.customer_id),
                incident_type=claim.incident_type,
                workflow_state=claim.claim_state.workflow_state,
                customer_next_step=claim.customer_next_step,
                assigned_to=_assigned_to_for(claim),
                internal_flags=_internal_flags_for(claim),
                queue=queue,
                priority=_priority_for(claim),
                created_at=claim.created_at,
                updated_at=claim.updated_at,
            )
        )

    return WorkbenchClaimListResponse(items=items, page=None)


def get_workbench_claim(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
) -> WorkbenchClaimDetail:
    if principal.actor_type != 'staff':
        raise ApiError(
            status_code=403,
            code='AUTHORIZATION_REQUIRED',
            message='Staff credentials required to access the workbench.',
        )

    claim = repository.get_claim_by_id(claim_id)
    if claim is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The claim was not found.',
        )

    return WorkbenchClaimDetail(
        claim_id=claim.claim_id,
        revision=claim.revision,
        customer_reference=_customer_reference(claim.customer_id),
        incident_type=claim.incident_type,
        claim_state=claim.claim_state,
        form=claim.form,
        customer_next_step=claim.customer_next_step,
        assigned_to=_assigned_to_for(claim),
        internal_flags=_internal_flags_for(claim),
        internal_notes=_internal_notes_for(claim),
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )
