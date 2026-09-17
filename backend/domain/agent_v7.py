"""Narrow model-output contracts for Agent Context Runtime v7."""

from typing import Literal

from pydantic import Field

from backend.domain.model_gateway import ModelProposedContentsItem, ModelProposedFormChange
from backend.domain.models import ContractModel


class V7AnswerProposal(ContractModel):
    reply: str = Field(min_length=1, max_length=2000)
    next_step: str = Field(min_length=1, max_length=500)
    reason_codes: list[str] = Field(min_length=1, max_length=20)


class V7IntakeProposal(V7AnswerProposal):
    field_changes: list[ModelProposedFormChange] = Field(default_factory=list, max_length=50)
    contents_item_changes: list[ModelProposedContentsItem] = Field(
        default_factory=list,
        max_length=30,
    )
    service_offer_ids: list[str] = Field(default_factory=list, max_length=3)


class V7ExternalOfferProposal(V7AnswerProposal):
    service_offer_ids: list[str] = Field(min_length=1, max_length=3)


class V7EvidenceActionProposal(V7AnswerProposal):
    action: Literal['reuse', 'remove']
    evidence_id: str = Field(min_length=1, max_length=120)
    source_claim_id: str | None = Field(default=None, max_length=120)
    removal_scope: Literal['draft', 'persisted'] | None = None


class V7ClaimCreationProposal(V7AnswerProposal):
    ready: bool


class V7SourcedSummaryProposal(ContractModel):
    summary: str = Field(min_length=1, max_length=10_000)
    source_refs: list[str] = Field(min_length=1, max_length=100)
    truncated: bool
    limitations: list[str] = Field(default_factory=list, max_length=20)
