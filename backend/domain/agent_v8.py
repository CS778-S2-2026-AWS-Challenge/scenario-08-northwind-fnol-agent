"""Unified claimant turn contract for Agent Context Runtime v8."""

from typing import Annotated, Any, Literal

from pydantic import Field

from backend.domain.models import (
    ContentsLossType,
    ContentsOwnership,
    ContractModel,
    FactPrecision,
    MoneyAmount,
)


class V8FieldChange(ContractModel):
    field_code: str = Field(min_length=1, max_length=100)
    value: Any
    reported_text: str | None = Field(default=None, max_length=200)
    precision: FactPrecision = FactPrecision.EXACT
    # Present only for the media profile.  The text profile's bound provider
    # schema omits it, while keeping the optional field here lets the Runtime
    # use one parser for both profile variants.
    source_evidence_id: str | None = Field(default=None, max_length=100)


class V8ContentsItemChange(ContractModel):
    item_id: str | None = Field(default=None, max_length=100)
    description: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=100)
    quantity: int = Field(default=1, ge=1)
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    loss_type: ContentsLossType
    ownership: ContentsOwnership
    estimated_value: MoneyAmount | None = None
    reported_text: str | None = Field(default=None, max_length=200)


class V8NextQuestion(ContractModel):
    field_codes: list[str] = Field(min_length=1, max_length=3)
    wording: str = Field(min_length=1, max_length=250)
    reason: Literal[
        'safety_first',
        'branch_just_activated',
        'blocks_creation',
        'clarify_conflict',
        'natural_follow_up',
    ]


class V8ServiceSuggestion(ContractModel):
    service_identity: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=1, max_length=150)


class V8StateProposal(ContractModel):
    path: Literal['claim_state.urgency', 'claim_state.customer_support']
    to: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=150)


class V8Escalation(ContractModel):
    kind: Literal[
        'urgent_safety',
        'human_requested',
        'accessibility',
        'distress',
        'professional_review',
    ]
    reason: str = Field(min_length=1, max_length=150)


class V8TurnProposal(ContractModel):
    reply: str = Field(min_length=1, max_length=500)
    reason_codes: list[Annotated[str, Field(min_length=1, max_length=50)]] = Field(
        min_length=1, max_length=5
    )
    field_changes: list[V8FieldChange] = Field(default_factory=list, max_length=8)
    contents_item_changes: list[V8ContentsItemChange] = Field(default_factory=list, max_length=6)
    next_question: V8NextQuestion | None = None
    service_suggestions: list[V8ServiceSuggestion] = Field(default_factory=list, max_length=3)
    state_proposals: list[V8StateProposal] = Field(default_factory=list, max_length=2)
    escalation: V8Escalation | None = None
    ready_to_create: bool = False
    confirms_batch: bool = False
