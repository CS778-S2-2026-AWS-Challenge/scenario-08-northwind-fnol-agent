from collections.abc import Mapping

from backend.domain.branch_registry import CLAIMANT_HIDDEN_FIELDS
from backend.domain.models import StructuredFormField, WorkingClaim
from backend.repositories.protocols import PersistenceRepository


def project_claimant_form_fields(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    fields: Mapping[str, StructuredFormField],
) -> dict[str, StructuredFormField]:
    """Project structured fields across the claimant visibility boundary.

    Args:
        repository: Persistence boundary used to identify internal retrieval records.
        claim: Authoritative Claim that owns the structured fields.
        fields: Structured fields to project without mutating persisted state.

    Returns:
        Claimant-visible copies with hidden fields and internal retrieval references removed.
    """

    internal_refs = {
        record.retrieval_id
        for record in repository.list_retrieval_records(claim.claim_id, claim.customer_id)
    }
    projected: dict[str, StructuredFormField] = {}
    for field_code, fact in fields.items():
        if field_code in CLAIMANT_HIDDEN_FIELDS:
            continue
        visible_refs = [ref for ref in fact.source_refs if ref not in internal_refs]
        visible_assertions = [
            assertion.model_copy(
                update={
                    'source_refs': [
                        ref for ref in assertion.source_refs if ref not in internal_refs
                    ]
                }
            )
            for assertion in fact.assertions
            if any(ref not in internal_refs for ref in assertion.source_refs)
        ]
        projected[field_code] = fact.model_copy(
            update={
                'source_refs': visible_refs,
                'assertions': visible_assertions,
                'current_assertion_id': (
                    fact.current_assertion_id
                    if any(
                        assertion.assertion_id == fact.current_assertion_id
                        for assertion in visible_assertions
                    )
                    else None
                ),
            }
        )
    return projected
