"""Provider-neutral, durable records for one Agent Runtime turn.

These records deliberately surround ``WorkingClaim``.  They describe planning,
authority and execution evidence; they never become a second source of Claim truth.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from backend.domain.models import (
    AgentAuthority,
    AgentProposalSource,
    ContractModel,
    CustomerNextStep,
    ProposedContentsItem,
    ProposedFormChange,
    RuntimeConfigurationProvenance,
)


class TurnPlanRecord(ContractModel):
    turn_id: str = Field(min_length=1, max_length=120)
    claim_id: str = Field(min_length=1, max_length=120)
    session_id: str = Field(min_length=1, max_length=120)
    trigger_message_id: str = Field(min_length=1, max_length=120)
    model_profile_id: str = Field(min_length=1, max_length=100)
    intents: list[str] = Field(default_factory=list, max_length=20)
    conversation_moves: list[str] = Field(default_factory=list, max_length=20)
    candidate_fields: list[str] = Field(default_factory=list, max_length=100)
    tool_requests: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    runtime_directive: Literal[
        'runtime.continue',
        'runtime.wait_for_user',
        'runtime.pause_for_review',
    ]
    limitations: list[str] = Field(default_factory=list, max_length=20)
    created_at: datetime


class AgentProposalRecord(ContractModel):
    proposal_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    claim_id: str = Field(min_length=1, max_length=120)
    session_id: str = Field(min_length=1, max_length=120)
    action_code: str = Field(min_length=1, max_length=120)
    runtime_directive: str = Field(min_length=1, max_length=120)
    reason_codes: list[str] = Field(min_length=1, max_length=40)
    customer_reason: str = Field(min_length=1, max_length=1000)
    customer_response: str = Field(min_length=1, max_length=5000)
    customer_next_step: CustomerNextStep
    form_changes: list[ProposedFormChange] = Field(default_factory=list, max_length=100)
    contents_item_changes: list[ProposedContentsItem] = Field(default_factory=list, max_length=100)
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    proposal_source: AgentProposalSource
    model_profile_id: str = Field(min_length=1, max_length=100)
    runtime_configuration: RuntimeConfigurationProvenance | None = None
    created_at: datetime


class ActionEnvelopeRecord(ContractModel):
    envelope_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    claim_id: str = Field(min_length=1, max_length=120)
    namespace: Literal['conversation', 'claim', 'human', 'external', 'runtime']
    action_code: str = Field(min_length=1, max_length=120)
    target_ref: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=1)
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    authority: AgentAuthority
    status: Literal['approved', 'rejected', 'executed', 'failed', 'unknown']
    idempotency_key: str | None = Field(default=None, max_length=200)
    created_at: datetime


class ExecutionPlanRecord(ContractModel):
    execution_plan_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    claim_id: str = Field(min_length=1, max_length=120)
    expected_revision: int = Field(ge=1)
    envelope_ids: list[str] = Field(default_factory=list, max_length=100)
    approved_envelope_ids: list[str] = Field(default_factory=list, max_length=100)
    rejected_envelope_ids: list[str] = Field(default_factory=list, max_length=100)
    status: Literal['prepared', 'executed', 'partially_executed', 'rejected', 'failed']
    created_at: datetime
    finished_at: datetime | None = None


class ToolResultRecord(ContractModel):
    result_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    claim_id: str = Field(min_length=1, max_length=120)
    tool_call_id: str = Field(min_length=1, max_length=120)
    tool_name: str = Field(min_length=1, max_length=120)
    status: Literal['succeeded', 'unavailable', 'failed', 'unknown']
    output: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    created_at: datetime


class TurnResultRecord(ContractModel):
    result_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    claim_id: str = Field(min_length=1, max_length=120)
    session_id: str = Field(min_length=1, max_length=120)
    trigger_message_id: str = Field(min_length=1, max_length=120)
    agent_message_id: str = Field(min_length=1, max_length=120)
    execution_plan_id: str = Field(min_length=1, max_length=120)
    status: Literal['succeeded', 'partially_succeeded', 'blocked', 'unavailable', 'failed']
    resulting_claim_revision: int = Field(ge=1)
    customer_response: str = Field(min_length=1, max_length=5000)
    state_change_refs: list[str] = Field(default_factory=list, max_length=100)
    tool_result_refs: list[str] = Field(default_factory=list, max_length=100)
    work_item_refs: list[str] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    created_at: datetime


class RuntimeWorkItemRecord(ContractModel):
    work_item_id: str = Field(min_length=1, max_length=120)
    claim_id: str = Field(min_length=1, max_length=120)
    turn_id: str = Field(min_length=1, max_length=120)
    kind: Literal[
        'question', 'confirmation', 'evidence', 'professional_review', 'external', 'system'
    ]
    subject_ref: str = Field(min_length=1, max_length=200)
    owner: Literal['claimant', 'staff', 'system', 'external']
    status: Literal['open', 'in_progress', 'completed', 'cancelled', 'unavailable']
    blocks_action: str | None = Field(default=None, max_length=120)
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class RuntimeTurnRecords(ContractModel):
    """The atomic child-record bundle for one applied Agent turn."""

    turn_plan: TurnPlanRecord
    proposal: AgentProposalRecord
    execution_plan: ExecutionPlanRecord
    action_envelopes: list[ActionEnvelopeRecord] = Field(default_factory=list)
    tool_results: list[ToolResultRecord] = Field(default_factory=list)
    result: TurnResultRecord
    work_items: list[RuntimeWorkItemRecord] = Field(default_factory=list)


def validate_runtime_turn_links(
    records: RuntimeTurnRecords,
    *,
    claim_id: str,
    session_id: str,
    trigger_message_id: str,
    agent_message_id: str,
    expected_revision: int,
    resulting_revision: int,
) -> None:
    """Validate the foreign-key-like links inside one persisted Runtime turn.

    Runtime records are immutable evidence.  Repositories therefore reject a
    bundle whose records refer to different Claims, sessions, turns, revisions,
    or messages instead of allowing a partially connected execution trace.
    """

    turn_id = records.turn_plan.turn_id
    if records.turn_plan.claim_id != claim_id or records.turn_plan.session_id != session_id:
        raise ValueError('Runtime turn plan scope does not match the Claim session.')
    if records.turn_plan.trigger_message_id != trigger_message_id:
        raise ValueError('Runtime turn plan trigger does not match the claimant message.')
    if records.proposal.turn_id != turn_id or records.proposal.claim_id != claim_id:
        raise ValueError('Runtime proposal is not linked to the turn and Claim.')
    if records.proposal.session_id != session_id:
        raise ValueError('Runtime proposal session does not match the Claim session.')
    if records.execution_plan.turn_id != turn_id or records.execution_plan.claim_id != claim_id:
        raise ValueError('Runtime execution plan is not linked to the turn and Claim.')
    if records.execution_plan.expected_revision != expected_revision:
        raise ValueError('Runtime execution plan revision does not match the mutation.')

    envelope_ids = {item.envelope_id for item in records.action_envelopes}
    if records.execution_plan.envelope_ids != [
        item.envelope_id for item in records.action_envelopes
    ]:
        raise ValueError('Runtime execution plan envelope order does not match the records.')
    if not set(records.execution_plan.approved_envelope_ids).issubset(envelope_ids):
        raise ValueError('Runtime execution plan references an unknown approved envelope.')
    if not set(records.execution_plan.rejected_envelope_ids).issubset(envelope_ids):
        raise ValueError('Runtime execution plan references an unknown rejected envelope.')
    for envelope in records.action_envelopes:
        if envelope.turn_id != turn_id or envelope.claim_id != claim_id:
            raise ValueError('Runtime action envelope is not linked to the turn and Claim.')
        if envelope.expected_revision != expected_revision:
            raise ValueError('Runtime action envelope revision does not match the mutation.')

    for tool_result in records.tool_results:
        if tool_result.turn_id != turn_id or tool_result.claim_id != claim_id:
            raise ValueError('Runtime tool result is not linked to the turn and Claim.')
    if records.result.tool_result_refs != [item.result_id for item in records.tool_results]:
        raise ValueError('Runtime result tool references do not match the records.')

    work_item_ids = {item.work_item_id for item in records.work_items}
    for work_item in records.work_items:
        if work_item.turn_id != turn_id or work_item.claim_id != claim_id:
            raise ValueError('Runtime work item is not linked to the turn and Claim.')
    if not set(records.result.work_item_refs).issubset(work_item_ids):
        raise ValueError('Runtime result references an unknown work item.')

    result = records.result
    if (
        result.turn_id != turn_id
        or result.claim_id != claim_id
        or result.session_id != session_id
        or result.trigger_message_id != trigger_message_id
        or result.agent_message_id != agent_message_id
        or result.execution_plan_id != records.execution_plan.execution_plan_id
        or result.resulting_claim_revision != resulting_revision
    ):
        raise ValueError('Runtime result is not linked to the applied Agent mutation.')
    if records.proposal.model_profile_id != records.turn_plan.model_profile_id:
        raise ValueError('Runtime proposal and turn plan use different model profiles.')
