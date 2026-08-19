from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field

from backend.domain.models import ContractModel


class RetrievalKind(str, Enum):
    POLICY = 'policy'
    CLAIM_HISTORY = 'claim_history'


class RetrievalSource(ContractModel):
    """Provider provenance retained after raw transport data is discarded."""

    system: str = Field(min_length=1, max_length=100)
    reference: str = Field(min_length=1, max_length=200)
    retrieved_at: datetime


class RetrievalUncertainty(ContractModel):
    code: str = Field(min_length=1, max_length=100)
    detail: str = Field(min_length=1, max_length=500)


class PolicyFacts(ContractModel):
    policy_reference: str = Field(min_length=1, max_length=200)
    product: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=100)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    excess_amount: float | None = Field(default=None, ge=0.0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    coverage_sections: list[str] = Field(default_factory=list, max_length=100)


class ClaimHistoryFacts(ContractModel):
    history_reference: str = Field(min_length=1, max_length=200)
    incident_type: str | None = Field(default=None, max_length=100)
    occurred_at: datetime | None = None
    status: str | None = Field(default=None, max_length=100)
    outcome: str | None = Field(default=None, max_length=200)


class PolicyRetrievalRecord(ContractModel):
    retrieval_id: str = Field(min_length=1, max_length=100)
    claim_id: str = Field(min_length=1, max_length=100)
    kind: Literal[RetrievalKind.POLICY] = RetrievalKind.POLICY
    source: RetrievalSource
    facts: PolicyFacts
    uncertainty: list[RetrievalUncertainty] = Field(default_factory=list, max_length=100)


class ClaimHistoryRetrievalRecord(ContractModel):
    retrieval_id: str = Field(min_length=1, max_length=100)
    claim_id: str = Field(min_length=1, max_length=100)
    kind: Literal[RetrievalKind.CLAIM_HISTORY] = RetrievalKind.CLAIM_HISTORY
    source: RetrievalSource
    facts: ClaimHistoryFacts
    uncertainty: list[RetrievalUncertainty] = Field(default_factory=list, max_length=100)


type RetrievalRecord = PolicyRetrievalRecord | ClaimHistoryRetrievalRecord


class ReviewSignalRecord(ContractModel):
    """Staff-only evidence for professional review, never an automatic finding."""

    signal_id: str = Field(min_length=1, max_length=120)
    claim_id: str = Field(min_length=1, max_length=100)
    review_type: Literal['professional_review'] = 'professional_review'
    code: str = Field(min_length=1, max_length=100)
    source_refs: list[str] = Field(min_length=1, max_length=100)
    reason_codes: list[str] = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=1000)
    created_at: datetime


class RetrievalStatus(str, Enum):
    """Outcome of one retrieval attempt.

    `unavailable` means the provider could not answer. It never carries facts,
    because an absent answer must not be reported as a finding.
    """

    EVIDENCE_FOUND = 'evidence_found'
    NO_EVIDENCE = 'no_evidence'
    AMBIGUOUS = 'ambiguous'
    UNAVAILABLE = 'unavailable'


class PolicySearchRequest(ContractModel):
    claim_id: str = Field(min_length=1, max_length=100)
    policy_reference: str = Field(min_length=1, max_length=200)
    question: str | None = Field(default=None, min_length=1, max_length=500)
    effective_at: datetime | None = None


class ClaimHistorySearchRequest(ContractModel):
    """Purpose-limited history lookup.

    `purpose` is an allow-list rather than free text so a caller cannot widen
    the reason for reading a claimant's history.
    """

    claim_id: str = Field(min_length=1, max_length=100)
    history_reference: str = Field(min_length=1, max_length=200)
    purpose: Literal['relevant_history_review'] = 'relevant_history_review'
    limit: int = Field(default=10, ge=1, le=50)


class PolicySearchResponse(ContractModel):
    result_id: str = Field(min_length=1, max_length=100)
    status: RetrievalStatus
    source: RetrievalSource | None = None
    facts: PolicyFacts | None = None
    uncertainty: list[RetrievalUncertainty] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    retrieved_at: datetime


class ClaimHistorySearchResponse(ContractModel):
    result_id: str = Field(min_length=1, max_length=100)
    status: RetrievalStatus
    source: RetrievalSource | None = None
    facts: ClaimHistoryFacts | None = None
    uncertainty: list[RetrievalUncertainty] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    retrieved_at: datetime
