from dataclasses import dataclass, replace
from datetime import timedelta
from enum import Enum
from hashlib import sha256

from backend.adapters.claims_service import AdapterIdempotencyConflict
from backend.domain.external_services import (
    ASSESSOR_REQUESTED_ACTION,
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecovery,
    classify_external_task_failure,
)
from backend.domain.models import (
    AssessorRoutingResult,
    AssessorRoutingStatus,
    IntegrationSource,
    RouteAssessorRequest,
)
from backend.services.support import now_utc

_SIMULATION_LIMITATION = 'Simulated vehicle-damage assessor; no external provider was contacted.'


class SimulatedAssessmentScenario(str, Enum):
    """Scripted outcome exposed by the non-live assessor simulation."""

    ASSIGNED = 'assigned'
    QUEUED = 'queued'
    UNAVAILABLE = 'unavailable'
    TIMEOUT = 'timeout'
    REJECTED = 'rejected'
    FAILED = 'failed'
    UNKNOWN_RESULT = 'unknown_result'


@dataclass(frozen=True, slots=True)
class SimulatedAssessmentOutcome:
    """Provider-neutral result of one simulated assessor invocation."""

    source: IntegrationSource
    operation_status: ExternalTaskOperationStatus
    delivery: ExternalTaskDelivery
    delivery_evidence: str | None
    failure_code: ExternalTaskFailureCode | None
    recovery: ExternalTaskRecovery | None
    retryable: bool
    routing: AssessorRoutingResult | None
    provider_reference: str | None
    limitation: str
    replayed: bool = False

    def __post_init__(self) -> None:
        if self.source is not IntegrationSource.FIXTURE:
            raise ValueError('The assessor simulation must remain labelled as fixture output.')
        if not self.limitation.strip():
            raise ValueError('The assessor simulation must state its non-live limitation.')
        if self.delivery is ExternalTaskDelivery.SUBMITTED:
            if self.delivery_evidence is None:
                raise ValueError('A submitted simulation outcome requires delivery evidence.')
        elif self.delivery_evidence is not None:
            raise ValueError('An unsubmitted simulation outcome cannot carry delivery evidence.')
        accepted = self.operation_status is ExternalTaskOperationStatus.ACCEPTED
        if accepted:
            if self.delivery is not ExternalTaskDelivery.SUBMITTED:
                raise ValueError('An accepted simulation outcome must have been submitted.')
            if self.routing is None or self.failure_code is not None:
                raise ValueError('An accepted simulation outcome requires routing and no failure.')
            if self.recovery is not None or self.retryable:
                raise ValueError('An accepted simulation outcome has no recovery or retry path.')
            if self.provider_reference is None:
                raise ValueError('An accepted simulation outcome requires a provider reference.')
            return
        if self.routing is not None or self.provider_reference is not None:
            raise ValueError(
                'A failed or unknown simulation outcome cannot report routing success.'
            )
        if self.failure_code is None:
            raise ValueError('A failed or unknown simulation outcome requires a failure code.')
        classification = classify_external_task_failure(
            failure_code=self.failure_code,
            delivery=self.delivery,
        )
        if (
            self.operation_status is not classification.operation_status
            or self.recovery is not classification.recovery
            or self.retryable is not classification.retryable
        ):
            raise ValueError('Simulation status, recovery, and retryability must agree.')


class SimulatedVehicleDamageAssessorAdapter:
    """Explicitly non-live vehicle-damage assessor simulation.

    The adapter implements the stakeholder and minimum-input boundary confirmed by
    Issue #416. It never claims a configured-service source or a real provider call.
    A scripted scenario sequence lets later integration work exercise success,
    retryable, terminal, and unknown-result behavior deterministically.
    """

    integration_source = IntegrationSource.FIXTURE

    def __init__(
        self,
        *,
        scenarios: tuple[SimulatedAssessmentScenario, ...] = (
            SimulatedAssessmentScenario.ASSIGNED,
        ),
    ) -> None:
        if not scenarios:
            raise ValueError('The assessor simulation requires at least one scenario.')
        self._scenarios = scenarios
        self._attempts: dict[str, int] = {}
        self._fingerprints: dict[str, str] = {}
        self._settled: dict[str, SimulatedAssessmentOutcome] = {}

    def route_assessor(
        self,
        command: RouteAssessorRequest,
        request_fingerprint: str,
    ) -> SimulatedAssessmentOutcome:
        """Run one bounded simulated assessor request.

        Args:
            command: Provider-neutral assessor request authorised by Northwind and
                the claimant.
            request_fingerprint: Stable fingerprint for idempotent replay.

        Returns:
            The explicit simulated delivery, lifecycle, recovery, and routing result.

        Raises:
            AdapterIdempotencyConflict: The same operation identity is reused with
                changed request data.
            ValueError: The request targets another action or has an empty fingerprint.
        """

        if command.requested_action != ASSESSOR_REQUESTED_ACTION:
            raise ValueError('The simulation supports vehicle damage assessment only.')
        if not request_fingerprint.strip():
            raise ValueError('The simulation requires a request fingerprint.')
        route_key = self._route_key(command)
        held_fingerprint = self._fingerprints.get(route_key)
        if held_fingerprint is None:
            self._fingerprints[route_key] = request_fingerprint
        elif held_fingerprint != request_fingerprint:
            raise AdapterIdempotencyConflict(route_key)

        settled = self._settled.get(route_key)
        if settled is not None:
            return replace(settled, replayed=True)

        attempt = self._attempts.get(route_key, 0)
        self._attempts[route_key] = attempt + 1
        scenario = self._scenarios[min(attempt, len(self._scenarios) - 1)]
        outcome = self._outcome(command, route_key, scenario)
        if outcome.operation_status is not ExternalTaskOperationStatus.RETRYABLE_FAILURE:
            self._settled[route_key] = outcome
        return outcome

    @staticmethod
    def _route_key(command: RouteAssessorRequest) -> str:
        return ':'.join(
            (
                command.claim_id,
                command.external_claim_id,
                command.authorisation_ref,
                command.claimant_consent_ref,
                command.requested_action,
            )
        )

    @staticmethod
    def _failure_outcome(
        scenario: SimulatedAssessmentScenario,
    ) -> tuple[ExternalTaskFailureCode, ExternalTaskDelivery]:
        mapping = {
            SimulatedAssessmentScenario.UNAVAILABLE: (
                ExternalTaskFailureCode.UNAVAILABLE,
                ExternalTaskDelivery.NOT_SUBMITTED,
            ),
            SimulatedAssessmentScenario.TIMEOUT: (
                ExternalTaskFailureCode.TIMEOUT,
                ExternalTaskDelivery.NOT_SUBMITTED,
            ),
            SimulatedAssessmentScenario.REJECTED: (
                ExternalTaskFailureCode.ACCESS_DENIED,
                ExternalTaskDelivery.SUBMITTED,
            ),
            SimulatedAssessmentScenario.FAILED: (
                ExternalTaskFailureCode.MALFORMED,
                ExternalTaskDelivery.SUBMITTED,
            ),
            SimulatedAssessmentScenario.UNKNOWN_RESULT: (
                ExternalTaskFailureCode.PARTIAL,
                ExternalTaskDelivery.SUBMITTED,
            ),
        }
        return mapping[scenario]

    @classmethod
    def _outcome(
        cls,
        command: RouteAssessorRequest,
        route_key: str,
        scenario: SimulatedAssessmentScenario,
    ) -> SimulatedAssessmentOutcome:
        digest = sha256(route_key.encode('utf-8')).hexdigest()[:10]
        if scenario in {
            SimulatedAssessmentScenario.ASSIGNED,
            SimulatedAssessmentScenario.QUEUED,
        }:
            assigned = scenario is SimulatedAssessmentScenario.ASSIGNED
            provider_reference = f'sim_assessor_{digest}' if assigned else f'sim_queue_{digest}'
            timestamp = now_utc()
            return SimulatedAssessmentOutcome(
                source=IntegrationSource.FIXTURE,
                operation_status=ExternalTaskOperationStatus.ACCEPTED,
                delivery=ExternalTaskDelivery.SUBMITTED,
                delivery_evidence=f'simulation acknowledgement: {provider_reference}',
                failure_code=None,
                recovery=None,
                retryable=False,
                routing=AssessorRoutingResult(
                    routing_status=(
                        AssessorRoutingStatus.ASSIGNED if assigned else AssessorRoutingStatus.QUEUED
                    ),
                    assessor_reference=provider_reference if assigned else None,
                    queue_reference=f'SIM-{command.location.region[:3].upper()}-{digest[:5]}',
                    next_step=(
                        'A simulated assessor will review the confirmed claim information.'
                        if assigned
                        else 'A simulated coordinator must assign the next assessor.'
                    ),
                    expected_by=timestamp + timedelta(hours=48),
                    limitations=[_SIMULATION_LIMITATION],
                ),
                provider_reference=provider_reference,
                limitation=_SIMULATION_LIMITATION,
            )

        failure_code, delivery = cls._failure_outcome(scenario)
        classification = classify_external_task_failure(
            failure_code=failure_code,
            delivery=delivery,
        )
        return SimulatedAssessmentOutcome(
            source=IntegrationSource.FIXTURE,
            operation_status=classification.operation_status,
            delivery=delivery,
            delivery_evidence=(
                f'simulation response observed: {scenario.value}'
                if delivery is ExternalTaskDelivery.SUBMITTED
                else None
            ),
            failure_code=failure_code,
            recovery=classification.recovery,
            retryable=classification.retryable,
            routing=None,
            provider_reference=None,
            limitation=_SIMULATION_LIMITATION,
        )
