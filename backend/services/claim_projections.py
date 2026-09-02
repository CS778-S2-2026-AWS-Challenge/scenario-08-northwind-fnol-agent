from backend.domain.evidence import evidence_summary_for
from backend.domain.models import ClaimantClaim, ClaimantHandoff, StructuredFormField, WorkingClaim
from backend.repositories.protocols import PersistenceRepository
from backend.services.evidence_visibility import claimant_visible_evidence
from backend.services.external_services import claimant_assessor_action
from backend.services.handoffs import claimant_handoff


def _claimant_form(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> dict[str, StructuredFormField]:
    """Keep fact provenance without exposing internal retrieval identifiers."""

    internal_refs = {
        record.retrieval_id
        for record in repository.list_retrieval_records(claim.claim_id, claim.customer_id)
    }
    if not internal_refs:
        return claim.form
    projected: dict[str, StructuredFormField] = {}
    for field_code, fact in claim.form.items():
        visible_refs = [ref for ref in fact.source_refs if ref not in internal_refs]
        projected[field_code] = (
            fact
            if len(visible_refs) == len(fact.source_refs)
            else fact.model_copy(update={'source_refs': visible_refs})
        )
    return projected


def claimant_claim_projection(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> ClaimantClaim:
    """Build the allow-listed customer projection from shared Claim Context.

    Args:
        repository: Persistence access for visibility-filtered child records.
        claim: The authoritative internal Working Claim.

    Returns:
        A claimant-safe projection containing only customer contract fields.
    """

    claimant_evidence = claimant_visible_evidence(
        repository.list_evidence(claim.claim_id, claim.customer_id)
    )
    handoff: ClaimantHandoff | None = None
    if claim.active_session_id is not None:
        open_handoffs = [
            item
            for item in repository.list_handoffs(claim.claim_id, claim.customer_id)
            if item.status.value not in {'resolved', 'cancelled'} and item.support_need is not None
        ]
        if open_handoffs:
            handoff = claimant_handoff(open_handoffs[-1])
    return ClaimantClaim(
        claim_id=claim.claim_id,
        revision=claim.revision,
        incident_type=claim.incident_type,
        workflow_state=claim.claim_state.workflow_state,
        form=_claimant_form(repository, claim),
        evidence_summary=evidence_summary_for(claimant_evidence),
        external_claim=claim.external_claim,
        external_service_action=claimant_assessor_action(repository, claim),
        customer_next_step=claim.customer_next_step,
        handoff=handoff,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )
