from datetime import datetime
from typing import Any, Protocol

from pydantic import Field

from backend.domain.models import ContractModel
from backend.domain.retrieval import (
    ClaimHistoryFacts,
    ClaimHistoryRetrievalRecord,
    ClaimHistorySearchRequest,
    PolicyFacts,
    PolicyRetrievalRecord,
    PolicySearchRequest,
    RetrievalSource,
    RetrievalUncertainty,
)
from backend.services.support import now_utc


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


class RetrievalUnavailable(Exception):
    """The provider could not be reached, timed out, or refused the request.

    Raised instead of returning an empty envelope so an absent answer can never
    be mistaken for a negative finding.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class PolicyHistoryAdapter(Protocol):
    """Stable retrieval boundary implemented by fixtures now and AWS later."""

    def search_policy(self, command: PolicySearchRequest) -> ProviderLookupEnvelope:
        raise NotImplementedError

    def search_claim_history(self, command: ClaimHistorySearchRequest) -> ProviderLookupEnvelope:
        raise NotImplementedError

    def connection_status(self) -> str:
        raise NotImplementedError


_FIXTURE_POLICIES: dict[str, dict[str, Any]] = {
    'synthetic-policy-101': {
        'policy_reference': 'synthetic-policy-101',
        'product': 'motor',
        'status': 'active',
        'effective_from': '2026-01-01T00:00:00Z',
        'effective_to': '2027-01-01T00:00:00Z',
        'excess_amount': 500.0,
        'currency': 'NZD',
        'coverage_sections': ['accidental_damage', 'third_party_liability'],
        # Provider-only fields below are deliberately present in the fixture so
        # tests can prove the mapping discards them.
        'fraud_label': 'elevated',
        'risk_score': 0.82,
        'policy_conclusion': 'covered',
    },
    'synthetic-policy-ambiguous': {
        'policy_reference': 'synthetic-policy-ambiguous',
        'product': 'motor',
        'status': 'active',
        'coverage_sections': ['accidental_damage'],
    },
}

_FIXTURE_HISTORIES: dict[str, dict[str, Any]] = {
    'synthetic-history-204': {
        'history_reference': 'synthetic-history-204',
        'incident_type': 'motor',
        'occurred_at': '2025-10-03T00:00:00Z',
        'status': 'closed',
        'outcome': 'settled',
        'fraud_finding': 'none',
        'internal_note': 'Provider-only commentary that must not cross the boundary.',
    },
}

_AMBIGUOUS_POLICY_UNCERTAINTY = ProviderUncertainty(
    code='COVERAGE_SECTION_INCOMPLETE',
    detail='The fixture policy does not state whether this event type is covered.',
)


class MockPolicyHistoryAdapter(PolicyHistoryAdapter):
    """Deterministic fixture retrieval with a controllable outage.

    The outage is explicit rather than random so the unavailable path is a
    demonstrable business path rather than a flaky test.
    """

    def __init__(self, outage: RetrievalUnavailable | None = None) -> None:
        self._outage = outage
        self._lookups = 0

    def reset_demo_state(self) -> dict[str, int]:
        cleared = {'mock_retrieval_lookups': self._lookups}
        self._lookups = 0
        self._outage = None
        return cleared

    def set_outage(self, outage: RetrievalUnavailable | None) -> None:
        self._outage = outage

    def connection_status(self) -> str:
        return 'unavailable' if self._outage is not None else 'using_fixture'

    def _guard(self) -> None:
        if self._outage is not None:
            raise self._outage
        self._lookups += 1

    def search_policy(self, command: PolicySearchRequest) -> ProviderLookupEnvelope:
        self._guard()
        payload = _FIXTURE_POLICIES.get(command.policy_reference)
        if payload is None:
            raise LookupError(command.policy_reference)
        uncertainty = (
            [_AMBIGUOUS_POLICY_UNCERTAINTY]
            if command.policy_reference == 'synthetic-policy-ambiguous'
            else []
        )
        return ProviderLookupEnvelope(
            provider='fixture_policy_administration',
            provider_reference=command.policy_reference,
            retrieved_at=now_utc(),
            payload=payload,
            uncertainty=uncertainty,
        )

    def search_claim_history(self, command: ClaimHistorySearchRequest) -> ProviderLookupEnvelope:
        self._guard()
        payload = _FIXTURE_HISTORIES.get(command.history_reference)
        if payload is None:
            raise LookupError(command.history_reference)
        return ProviderLookupEnvelope(
            provider='fixture_claims_history',
            provider_reference=command.history_reference,
            retrieved_at=now_utc(),
            payload=payload,
            uncertainty=[],
        )
