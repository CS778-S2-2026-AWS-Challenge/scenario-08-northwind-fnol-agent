"""Application helpers for revision-valid Dynamic Form branch evaluations."""

from collections.abc import Sequence
from datetime import datetime

from backend.domain.branch_registry import BranchRuleEvaluator
from backend.domain.ids import new_id
from backend.domain.models import (
    AgentAction,
    BranchEvaluationRecord,
    BranchEvaluationStatus,
    WorkingClaim,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.support import now_utc


def latest_applied_branch_evaluation(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> BranchEvaluationRecord | None:
    """Return the newest immutable applied evaluation valid before or at a Claim revision.

    Args:
        repository: The selected provider-neutral persistence boundary.
        claim: The Claim snapshot whose evaluation history is being reconciled.

    Returns:
        The newest applicable record, or ``None`` when the Claim has no prior evaluation.
    """

    eligible = [
        record
        for record in repository.list_branch_evaluations(claim.claim_id, claim.customer_id)
        if record.status is BranchEvaluationStatus.APPLIED
        and record.resulting_claim_revision is not None
        and record.resulting_claim_revision <= claim.revision
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda record: (
            record.resulting_claim_revision or 0,
            record.created_at,
            record.evaluation_id,
        ),
    )


def build_applied_branch_evaluation(
    claim: WorkingClaim,
    *,
    repository: PersistenceRepository | None = None,
    previous_evaluation: BranchEvaluationRecord | None = None,
    recomputation_reason: str,
    session_id: str | None = None,
    turn_id: str | None = None,
    current_action: AgentAction | str | None = None,
    trigger_source_refs: Sequence[str] = (),
    created_at: datetime | None = None,
) -> BranchEvaluationRecord:
    """Build immutable evidence for an evaluation of the resulting Claim revision."""

    if previous_evaluation is None and repository is not None:
        previous_evaluation = latest_applied_branch_evaluation(repository, claim)
    evaluated = BranchRuleEvaluator().evaluate(
        claim,
        trigger_source_refs=trigger_source_refs,
        current_action=current_action or claim.claim_state.next_action,
        recomputation_reason=recomputation_reason,
        previous_evaluation=previous_evaluation,
    )
    return BranchEvaluationRecord(
        evaluation_id=new_id('brn'),
        claim_id=claim.claim_id,
        session_id=session_id or claim.active_session_id,
        turn_id=turn_id,
        evaluated_against_claim_revision=claim.revision,
        resulting_claim_revision=claim.revision,
        field_registry_version=evaluated.field_registry_version,
        branch_rules_version=evaluated.branch_rules_version,
        selected_family=evaluated.selected_family,
        unresolved_family_conflict=evaluated.unresolved_family_conflict,
        branch_results=evaluated.branch_results,
        field_selection_results=evaluated.field_selection,
        work_item_intents=evaluated.work_item_intents,
        handoff_intents=evaluated.handoff_intents,
        evidence_intents=evaluated.evidence_intents,
        consent_intents=evaluated.consent_intents,
        integration_intents=evaluated.integration_intents,
        interruption_result=evaluated.interruption_result,
        permitted_actions=evaluated.permitted_actions,
        permitted_tools=evaluated.permitted_tools,
        recomputation_reason=evaluated.recomputation_reason,
        status=BranchEvaluationStatus.APPLIED,
        created_at=created_at or now_utc(),
    )


__all__ = ['build_applied_branch_evaluation', 'latest_applied_branch_evaluation']
