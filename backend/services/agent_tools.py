"""Runtime-owned implementations for the small, read-only tool surface."""

from collections.abc import Mapping

from backend.domain.agent_tool_registry import tool_contract
from backend.domain.models import WorkingClaim


def read_claim_for_runtime(
    claim: WorkingClaim,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """Return the current Claim projection for the authenticated turn.

    The caller supplies the already-authorised current Claim loaded by the message
    transaction. No provider response or fixture is manufactured here, and the tool
    accepts no caller-selected claim identifier, preventing cross-claim reads.
    """

    contract = tool_contract('claim.read')
    if arguments:
        raise ValueError('claim.read does not accept input arguments.')
    form = {
        field_code: {
            'value': field.value,
            'status': field.status.value,
            'source': field.source.value,
            'needed_for': field.needed_for.value,
        }
        for field_code, field in sorted(claim.form.items())
        if field.needed_for.value == 'current_action'
    }
    return {
        'tool': contract.name,
        'claim_id': claim.claim_id,
        'revision': claim.revision,
        'incident_type': claim.incident_type,
        'workflow_state': claim.claim_state.workflow_state.value,
        'next_action': claim.claim_state.next_action.value,
        'customer_next_step': claim.customer_next_step.model_dump(mode='json'),
        'form': form,
        'evidence_summary': claim.evidence_summary.model_dump(mode='json'),
    }
