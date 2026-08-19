from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from typing import Protocol

from backend.domain.models import (
    AssessorRoutingResult,
    AssessorRoutingStatus,
    ClaimCreationStatus,
    CreateExternalClaimRequest,
    ExternalClaimResult,
    IntegrationSource,
    RouteAssessorRequest,
)
from backend.services.support import now_utc


class AdapterIdempotencyConflict(Exception):
    """The same provider-neutral idempotency reference was reused differently."""


@dataclass(frozen=True, slots=True)
class ClaimCreationOutcome:
    result: ExternalClaimResult
    replayed: bool


@dataclass(frozen=True, slots=True)
class AssessorRoutingOutcome:
    result: AssessorRoutingResult
    replayed: bool


class ClaimsServiceAdapter(Protocol):
    """Stable boundary implemented by fixtures now and an AWS adapter later."""

    def create_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome:
        raise NotImplementedError


class AssessorServiceAdapter(Protocol):
    """Stable assessor boundary without assumptions about a future AWS schema."""

    def route_assessor(
        self,
        command: RouteAssessorRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome:
        raise NotImplementedError


class MockClaimsServiceAdapter(ClaimsServiceAdapter):
    """Deterministic in-memory adapter keyed by the working claim ID."""

    def __init__(self) -> None:
        self._created: dict[str, tuple[str, ExternalClaimResult]] = {}

    def reset_demo_state(self) -> dict[str, int]:
        cleared = {'mock_claim_results': len(self._created)}
        self._created.clear()
        return cleared

    def create_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome:
        existing = self._created.get(command.working_claim_id)
        if existing is not None:
            fingerprint, result = existing
            if fingerprint != request_fingerprint:
                raise AdapterIdempotencyConflict(command.working_claim_id)
            return ClaimCreationOutcome(result=result, replayed=True)

        digest = sha256(command.working_claim_id.encode('utf-8')).hexdigest()[:10].upper()
        timestamp = now_utc()
        result = ExternalClaimResult(
            external_claim_id=f'ext_fixture_{digest.lower()}',
            claim_number=f'NWF-{timestamp.year}-{digest[:6]}',
            creation_status=ClaimCreationStatus.CREATED,
            route=command.route,
            next_step='Claims intake review',
            source=IntegrationSource.FIXTURE,
            expected_by=timestamp + timedelta(hours=24),
            created_at=timestamp,
        )
        self._created[command.working_claim_id] = (request_fingerprint, result)
        return ClaimCreationOutcome(result=result, replayed=False)


class MockAssessorServiceAdapter(AssessorServiceAdapter):
    """Deterministic mock route keyed by the authorised requested action."""

    def __init__(self) -> None:
        self._routed: dict[str, tuple[str, AssessorRoutingResult]] = {}

    def reset_demo_state(self) -> dict[str, int]:
        cleared = {'mock_assessor_results': len(self._routed)}
        self._routed.clear()
        return cleared

    def route_assessor(
        self,
        command: RouteAssessorRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome:
        route_key = f'{command.claim_id}:{command.authorisation_ref}:{command.requested_action}'
        existing = self._routed.get(route_key)
        if existing is not None:
            fingerprint, result = existing
            if fingerprint != request_fingerprint:
                raise AdapterIdempotencyConflict(route_key)
            return AssessorRoutingOutcome(result=result, replayed=True)

        digest = sha256(route_key.encode('utf-8')).hexdigest()[:10].upper()
        timestamp = now_utc()
        result = AssessorRoutingResult(
            routing_status=AssessorRoutingStatus.ASSIGNED,
            assessor_reference=f'asr_fixture_{digest.lower()}',
            queue_reference=f'QUE-{command.location.region[:3].upper()}-{digest[:5]}',
            next_step='An assessor will review the confirmed claim information.',
            expected_by=timestamp + timedelta(hours=48),
            limitations=['Synthetic fixture routing; no production assessor was contacted.'],
        )
        self._routed[route_key] = (request_fingerprint, result)
        return AssessorRoutingOutcome(result=result, replayed=False)
