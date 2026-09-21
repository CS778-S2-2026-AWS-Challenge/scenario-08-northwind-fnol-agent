"""The claimant Runtime's single progress and outcome reduction boundary."""

from dataclasses import dataclass
from typing import Any

from backend.domain.branch_registry import BranchRuleEvaluator
from backend.domain.intake import next_requirement_step
from backend.domain.models import (
    CustomerNextStep,
    HandoffRecord,
    WorkflowState,
    WorkingClaim,
)


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    claim: WorkingClaim
    agent_message_text: str
    handoff: HandoffRecord | None
    confirmation_request: Any | None
    branch_evaluation: Any
    records: Any | None
    session: Any | None
    rejected_parts: list[dict[str, str]]


def recompute_progress(
    claim: WorkingClaim,
    evaluation: Any,
    *,
    open_handoffs: tuple[HandoffRecord, ...] = (),
    proposed_next_step: CustomerNextStep | None = None,
) -> tuple[WorkflowState, CustomerNextStep]:
    """Compute claimant workflow and next step from one post-mutation evaluation."""

    if claim.claim_state.workflow_state is WorkflowState.CREATED or claim.terminal_disposition:
        return claim.claim_state.workflow_state, claim.customer_next_step
    if claim.claim_state.workflow_state is WorkflowState.PROFESSIONAL_REVIEW:
        return claim.claim_state.workflow_state, claim.customer_next_step
    if any(item.status.value not in {'resolved', 'cancelled'} for item in open_handoffs):
        return claim.claim_state.workflow_state, proposed_next_step or claim.customer_next_step
    if evaluation.requirements.ready_pending_confirmation:
        return WorkflowState.COLLECTING, CustomerNextStep(
            status='confirmation_required',
            summary='Please confirm the recorded details before creating the Claim.',
            responsible_party='claimant',
            required_items=list(evaluation.requirements.recorded),
        )
    if evaluation.requirements.ready:
        return WorkflowState.READY_FOR_NEXT, proposed_next_step or next_requirement_step(
            evaluation.requirements
        )
    return WorkflowState.COLLECTING, proposed_next_step or next_requirement_step(
        evaluation.requirements
    )


def reduce_turn(
    claim: WorkingClaim,
    validated: Any,
    *,
    branch_evaluator: BranchRuleEvaluator,
    open_handoffs: tuple[HandoffRecord, ...] = (),
    proposed_next_step: CustomerNextStep | None = None,
    **_: Any,
) -> TurnOutcome:
    """Reduce a validated proposal without performing I/O or side effects.

    Persistence and external dispatch remain owned by the existing transaction
    services. This function is deliberately pure so callers cannot create a
    second Claim state store while migrating the legacy message adapter.
    """

    projected_form = dict(claim.form)
    for change in getattr(validated, 'form_changes', ()):
        projected_form[change.field_code] = change
    projected = claim.model_copy(update={'form': projected_form})
    evaluation = branch_evaluator.evaluate(
        projected,
        latest_message=None,
        recomputation_reason='turn_reducer',
    )
    workflow_state, next_step = recompute_progress(
        projected,
        evaluation,
        open_handoffs=open_handoffs,
        proposed_next_step=proposed_next_step,
    )
    reduced = projected.model_copy(
        update={
            'claim_state': projected.claim_state.model_copy(
                update={'workflow_state': workflow_state}
            ),
            'customer_next_step': next_step,
        }
    )
    return TurnOutcome(
        claim=reduced,
        agent_message_text=getattr(validated, 'reply', ''),
        handoff=None,
        confirmation_request=None,
        branch_evaluation=evaluation,
        records=None,
        session=None,
        rejected_parts=list(getattr(validated, 'rejected', [])),
    )
