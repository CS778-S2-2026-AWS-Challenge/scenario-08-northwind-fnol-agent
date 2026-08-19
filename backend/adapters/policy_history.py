from datetime import datetime
from typing import Any

from pydantic import Field

from backend.domain.models import ContractModel
from backend.domain.retrieval import (
    ClaimHistoryFacts,
    ClaimHistoryRetrievalRecord,
    PolicyFacts,
    PolicyRetrievalRecord,
    RetrievalSource,
    RetrievalUncertainty,
)


class ProviderUncertainty(ContractModel):
    code: str = Field(min_length=1, max_length=100)
    detail: str = Field(min_length=1, max_length=500)


class ProviderLookupEnvelope(ContractModel):
    """Internal adapter input; payload is never copied wholesale into domain state."""

    provider: str = Field(min_length=1, max_length=100)
    provider_reference: str = Field(min_length=1, max_length=200)
    retrieved_at: datetime
    payload: dict[str, Any]
    uncertainty: list[ProviderUncertainty] = Field(default_factory=list, max_length=100)


def _source(envelope: ProviderLookupEnvelope) -> RetrievalSource:
    return RetrievalSource(
        system=envelope.provider,
        reference=envelope.provider_reference,
        retrieved_at=envelope.retrieved_at,
    )


def _uncertainty(envelope: ProviderLookupEnvelope) -> list[RetrievalUncertainty]:
    return [
        RetrievalUncertainty(code=item.code, detail=item.detail) for item in envelope.uncertainty
    ]


def map_policy_provider_payload(
    *,
    retrieval_id: str,
    claim_id: str,
    envelope: ProviderLookupEnvelope,
) -> PolicyRetrievalRecord:
    """Map the allow-listed policy fields and discard all other provider data."""

    payload = envelope.payload
    facts = PolicyFacts.model_validate(
        {
            'policy_reference': payload.get('policy_reference'),
            'product': payload.get('product'),
            'status': payload.get('status'),
            'effective_from': payload.get('effective_from'),
            'effective_to': payload.get('effective_to'),
            'excess_amount': payload.get('excess_amount'),
            'currency': payload.get('currency'),
            'coverage_sections': payload.get('coverage_sections', []),
        }
    )
    return PolicyRetrievalRecord(
        retrieval_id=retrieval_id,
        claim_id=claim_id,
        source=_source(envelope),
        facts=facts,
        uncertainty=_uncertainty(envelope),
    )


def map_history_provider_payload(
    *,
    retrieval_id: str,
    claim_id: str,
    envelope: ProviderLookupEnvelope,
) -> ClaimHistoryRetrievalRecord:
    """Map the allow-listed history fields without carrying provider-only scoring."""

    payload = envelope.payload
    facts = ClaimHistoryFacts.model_validate(
        {
            'history_reference': payload.get('history_reference'),
            'incident_type': payload.get('incident_type'),
            'occurred_at': payload.get('occurred_at'),
            'status': payload.get('status'),
            'outcome': payload.get('outcome'),
        }
    )
    return ClaimHistoryRetrievalRecord(
        retrieval_id=retrieval_id,
        claim_id=claim_id,
        source=_source(envelope),
        facts=facts,
        uncertainty=_uncertainty(envelope),
    )
