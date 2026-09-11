import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Protocol

from backend.domain.models import (
    AssessorRoutingFailureCode,
    AssessorRoutingResult,
    AssessorRoutingStatus,
    ClaimCreationStatus,
    CreateExternalClaimRequest,
    ExternalClaimResult,
    IntegrationSource,
    RouteAssessorRequest,
)
from backend.services.support import now_utc

AssessorFixtureFailure = AssessorRoutingFailureCode


class AdapterIdempotencyConflict(Exception):
    """The same provider-neutral idempotency reference was reused differently."""


class AssessorAdapterFailure(Exception):
    """Bounded fixture failure without a provider payload or secret."""

    def __init__(self, code: AssessorFixtureFailure) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class ClaimCreationOutcome:
    result: ExternalClaimResult
    replayed: bool


@dataclass(frozen=True, slots=True)
class AssessorRoutingOutcome:
    result: AssessorRoutingResult
    replayed: bool


@dataclass(frozen=True, slots=True)
class AssessorResultRequest:
    """Immutable task identity used to obtain one provider-neutral result."""

    task_id: str
    claim_id: str
    provider_reference: str
    accepted_at: datetime


@dataclass(frozen=True, slots=True)
class AssessorReturnedReport:
    """Bounded assessor output before Runtime persists its result and evidence."""

    summary: str
    source_system: str
    source_reference: str
    source_timestamp: datetime
    original_filename: str
    media_type: str
    content: bytes
    simulation_only: bool


@dataclass(frozen=True, slots=True)
class AssessorResultOutcome:
    """One returned assessor report and whether the adapter replayed it."""

    report: AssessorReturnedReport
    replayed: bool


class ClaimsServiceAdapter(Protocol):
    """Stable boundary implemented by fixtures now and an AWS adapter later."""

    @property
    def integration_source(self) -> IntegrationSource:
        raise NotImplementedError

    def create_claim(
        self,
        command: CreateExternalClaimRequest,
        request_fingerprint: str,
    ) -> ClaimCreationOutcome:
        raise NotImplementedError


class AssessorServiceAdapter(Protocol):
    """Stable assessor boundary without assumptions about a future AWS schema.

    An implementation declares the source class its answers carry. The entry
    decision and the installed adapter are chosen separately at startup, so
    without a declaration nothing could tell a fixture double from a configured
    service, and a mismatched pair would be indistinguishable from a correct one.
    The declaration is required rather than defaulted: an implementation that
    forgot to state its source would otherwise be read as whichever value the
    default happened to be, which is the mislabelling this boundary exists to
    prevent.
    """

    integration_source: IntegrationSource

    def route_assessor(
        self,
        command: RouteAssessorRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome:
        raise NotImplementedError

    def receive_result(
        self,
        command: AssessorResultRequest,
        request_fingerprint: str,
    ) -> AssessorResultOutcome:
        """Return one bounded result for an accepted assessor task.

        Args:
            command: Persisted task identity and provider acknowledgement.
            request_fingerprint: Stable identity for an idempotent receive operation.

        Returns:
            Provider-neutral report content and replay state.

        Raises:
            AdapterIdempotencyConflict: The task identity is reused with changed data.
            AssessorAdapterFailure: The adapter cannot return a usable result.
        """

        raise NotImplementedError


class MockClaimsServiceAdapter(ClaimsServiceAdapter):
    """Deterministic in-memory adapter keyed by the working claim ID."""

    def __init__(self) -> None:
        self._created: dict[str, tuple[str, ExternalClaimResult]] = {}

    @property
    def integration_source(self) -> IntegrationSource:
        return IntegrationSource.FIXTURE

    def connection_status(self) -> str:
        return 'using_fixture'

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
    """Deterministic mock route keyed by the authorised requested action.

    Its answers are synthetic: the assessor reference is fixture-prefixed and the
    result states that no production assessor was contacted. It declares `FIXTURE`
    so a composition cannot present those answers as a configured service's.
    """

    integration_source = IntegrationSource.FIXTURE

    def connection_status(self) -> str:
        return 'using_fixture'

    def __init__(
        self,
        *,
        failure_sequence: tuple[AssessorFixtureFailure, ...] = (),
        routing_status: AssessorRoutingStatus = AssessorRoutingStatus.ASSIGNED,
    ) -> None:
        if routing_status not in {AssessorRoutingStatus.ASSIGNED, AssessorRoutingStatus.QUEUED}:
            raise ValueError('The assessor fixture supports assigned or queued success only.')
        self._routed: dict[str, tuple[str, AssessorRoutingResult]] = {}
        self._returned: dict[str, tuple[str, AssessorReturnedReport]] = {}
        self._accepted_fingerprints: dict[str, str] = {}
        self._attempts: dict[str, int] = {}
        self._failure_sequence = failure_sequence
        self._routing_status = routing_status

    def reset_demo_state(self) -> dict[str, int]:
        cleared = {
            'mock_assessor_results': len(self._routed),
            'mock_assessment_reports': len(self._returned),
        }
        self._routed.clear()
        self._returned.clear()
        self._accepted_fingerprints.clear()
        self._attempts.clear()
        return cleared

    def route_assessor(
        self,
        command: RouteAssessorRequest,
        request_fingerprint: str,
    ) -> AssessorRoutingOutcome:
        route_key = ':'.join(
            (
                command.claim_id,
                command.external_claim_id,
                command.authorisation_ref,
                command.claimant_consent_ref,
                command.requested_action,
            )
        )
        accepted_fingerprint = self._accepted_fingerprints.get(route_key)
        if accepted_fingerprint is None:
            self._accepted_fingerprints[route_key] = request_fingerprint
        elif accepted_fingerprint != request_fingerprint:
            raise AdapterIdempotencyConflict(route_key)

        existing = self._routed.get(route_key)
        if existing is not None:
            fingerprint, result = existing
            if fingerprint != request_fingerprint:
                raise AdapterIdempotencyConflict(route_key)
            return AssessorRoutingOutcome(result=result, replayed=True)

        attempt = self._attempts.get(route_key, 0)
        self._attempts[route_key] = attempt + 1
        if attempt < len(self._failure_sequence):
            raise AssessorAdapterFailure(self._failure_sequence[attempt])

        digest = sha256(route_key.encode('utf-8')).hexdigest()[:10].upper()
        timestamp = now_utc()
        assigned = self._routing_status is AssessorRoutingStatus.ASSIGNED
        result = AssessorRoutingResult(
            routing_status=self._routing_status,
            assessor_reference=f'asr_fixture_{digest.lower()}' if assigned else None,
            queue_reference=f'QUE-{command.location.region[:3].upper()}-{digest[:5]}',
            next_step=(
                'An assessor will review the confirmed claim information.'
                if assigned
                else 'An assessor coordinator must assign the next available assessor.'
            ),
            expected_by=timestamp + timedelta(hours=48),
            limitations=['Synthetic fixture routing; no production assessor was contacted.'],
        )
        self._routed[route_key] = (request_fingerprint, result)
        return AssessorRoutingOutcome(result=result, replayed=False)

    def receive_result(
        self,
        command: AssessorResultRequest,
        request_fingerprint: str,
    ) -> AssessorResultOutcome:
        """Produce one deterministic, explicitly simulation-only assessment report.

        Args:
            command: Persisted task identity and provider acknowledgement.
            request_fingerprint: Stable identity for an idempotent receive operation.

        Returns:
            A JSON assessment report labelled as controlled fixture output.

        Raises:
            AdapterIdempotencyConflict: The task identity is reused with changed data.
            ValueError: A required task identity value is empty.
        """

        if not all(
            value.strip()
            for value in (command.task_id, command.claim_id, command.provider_reference)
        ):
            raise ValueError('An assessor result requires complete task identity.')
        held = self._returned.get(command.task_id)
        if held is not None:
            fingerprint, report = held
            if fingerprint != request_fingerprint:
                raise AdapterIdempotencyConflict(command.task_id)
            return AssessorResultOutcome(report=report, replayed=True)

        digest = sha256(f'{command.task_id}:{command.provider_reference}'.encode()).hexdigest()[:12]
        summary = (
            'The controlled assessment fixture returned a simulation-only vehicle damage '
            'report for Northwind review.'
        )
        source_reference = f'fixture-assessment/{digest}'
        content = json.dumps(
            {
                'assessment': {
                    'classification': 'vehicle_damage_review_required',
                    'summary': summary,
                },
                'claim_id': command.claim_id,
                'limitations': [
                    'Synthetic fixture report; no production assessor was contacted.',
                    'The report does not decide cover or approve repairs.',
                ],
                'provider_reference': command.provider_reference,
                'simulation_only': True,
                'source_reference': source_reference,
                'source_timestamp': command.accepted_at.isoformat(),
                'task_id': command.task_id,
            },
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
        report = AssessorReturnedReport(
            summary=summary,
            source_system='controlled_assessment_fixture',
            source_reference=source_reference,
            source_timestamp=command.accepted_at,
            original_filename=f'vehicle-damage-assessment-{digest}.json',
            media_type='application/json',
            content=content,
            simulation_only=True,
        )
        self._returned[command.task_id] = (request_fingerprint, report)
        return AssessorResultOutcome(report=report, replayed=False)
