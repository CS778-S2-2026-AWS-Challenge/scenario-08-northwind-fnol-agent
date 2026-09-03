from dataclasses import replace
from datetime import UTC, datetime

import pytest

from backend.adapters.assessor_simulation import (
    SimulatedAssessmentOutcome,
    SimulatedAssessmentScenario,
    SimulatedVehicleDamageAssessorAdapter,
)
from backend.adapters.claims_service import AdapterIdempotencyConflict
from backend.domain.external_services import (
    ASSESSOR_REQUESTED_ACTION,
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecovery,
)
from backend.domain.models import (
    AssessorLocation,
    AssessorRoutingStatus,
    IntegrationSource,
    RouteAssessorRequest,
)


def _command(*, requested_action: str = ASSESSOR_REQUESTED_ACTION) -> RouteAssessorRequest:
    return RouteAssessorRequest(
        claim_id='clm_simulation',
        external_claim_id='ext_simulation',
        authorisation_ref='dec_simulation',
        claimant_consent_ref='cns_simulation',
        requested_action=requested_action,
        location=AssessorLocation(region='Auckland'),
    )


@pytest.mark.parametrize(
    ('scenario', 'status', 'delivery', 'failure', 'recovery', 'retryable'),
    [
        (
            SimulatedAssessmentScenario.UNAVAILABLE,
            ExternalTaskOperationStatus.RETRYABLE_FAILURE,
            ExternalTaskDelivery.NOT_SUBMITTED,
            ExternalTaskFailureCode.UNAVAILABLE,
            ExternalTaskRecovery.RETRY_SAME_OPERATION,
            True,
        ),
        (
            SimulatedAssessmentScenario.TIMEOUT,
            ExternalTaskOperationStatus.RETRYABLE_FAILURE,
            ExternalTaskDelivery.NOT_SUBMITTED,
            ExternalTaskFailureCode.TIMEOUT,
            ExternalTaskRecovery.RETRY_SAME_OPERATION,
            True,
        ),
        (
            SimulatedAssessmentScenario.REJECTED,
            ExternalTaskOperationStatus.TERMINAL_FAILURE,
            ExternalTaskDelivery.SUBMITTED,
            ExternalTaskFailureCode.ACCESS_DENIED,
            ExternalTaskRecovery.REVIEW_REQUIRED,
            False,
        ),
        (
            SimulatedAssessmentScenario.FAILED,
            ExternalTaskOperationStatus.TERMINAL_FAILURE,
            ExternalTaskDelivery.SUBMITTED,
            ExternalTaskFailureCode.MALFORMED,
            ExternalTaskRecovery.REVIEW_REQUIRED,
            False,
        ),
        (
            SimulatedAssessmentScenario.UNKNOWN_RESULT,
            ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
            ExternalTaskDelivery.SUBMITTED,
            ExternalTaskFailureCode.PARTIAL,
            ExternalTaskRecovery.RECONCILE_BEFORE_RETRY,
            False,
        ),
    ],
)
def test_failure_scenarios_return_explicit_non_success_outcomes(
    scenario: SimulatedAssessmentScenario,
    status: ExternalTaskOperationStatus,
    delivery: ExternalTaskDelivery,
    failure: ExternalTaskFailureCode,
    recovery: ExternalTaskRecovery,
    retryable: bool,
) -> None:
    adapter = SimulatedVehicleDamageAssessorAdapter(scenarios=(scenario,))

    outcome = adapter.route_assessor(_command(), 'fingerprint')

    assert outcome.source.value == 'fixture'
    assert outcome.operation_status is status
    assert outcome.delivery is delivery
    assert outcome.failure_code is failure
    assert outcome.recovery is recovery
    assert outcome.retryable is retryable
    assert outcome.routing is None
    assert outcome.provider_reference is None
    assert 'no external provider was contacted' in outcome.limitation
    assert (outcome.delivery_evidence is not None) is (delivery is ExternalTaskDelivery.SUBMITTED)


@pytest.mark.parametrize(
    ('scenario', 'routing_status'),
    [
        (SimulatedAssessmentScenario.ASSIGNED, AssessorRoutingStatus.ASSIGNED),
        (SimulatedAssessmentScenario.QUEUED, AssessorRoutingStatus.QUEUED),
    ],
)
def test_success_scenarios_are_identified_as_simulation(
    monkeypatch: pytest.MonkeyPatch,
    scenario: SimulatedAssessmentScenario,
    routing_status: AssessorRoutingStatus,
) -> None:
    timestamp = datetime(2026, 9, 3, tzinfo=UTC)
    monkeypatch.setattr('backend.adapters.assessor_simulation.now_utc', lambda: timestamp)
    adapter = SimulatedVehicleDamageAssessorAdapter(scenarios=(scenario,))

    outcome = adapter.route_assessor(_command(), 'fingerprint')

    assert outcome.operation_status is ExternalTaskOperationStatus.ACCEPTED
    assert outcome.delivery is ExternalTaskDelivery.SUBMITTED
    assert outcome.delivery_evidence is not None
    assert outcome.delivery_evidence.startswith('simulation acknowledgement:')
    assert outcome.failure_code is None
    assert outcome.recovery is None
    assert outcome.routing is not None
    assert outcome.routing.routing_status is routing_status
    assert outcome.routing.limitations == [
        'Simulated vehicle-damage assessor; no external provider was contacted.'
    ]
    assert outcome.provider_reference is not None


def test_retryable_failure_advances_to_success_with_the_same_identity() -> None:
    adapter = SimulatedVehicleDamageAssessorAdapter(
        scenarios=(
            SimulatedAssessmentScenario.UNAVAILABLE,
            SimulatedAssessmentScenario.ASSIGNED,
        )
    )

    failed = adapter.route_assessor(_command(), 'fingerprint')
    accepted = adapter.route_assessor(_command(), 'fingerprint')
    replay = adapter.route_assessor(_command(), 'fingerprint')

    assert failed.operation_status is ExternalTaskOperationStatus.RETRYABLE_FAILURE
    assert accepted.operation_status is ExternalTaskOperationStatus.ACCEPTED
    assert replay == replace(accepted, replayed=True)


def test_unknown_result_replays_without_advancing_to_a_second_scenario() -> None:
    adapter = SimulatedVehicleDamageAssessorAdapter(
        scenarios=(
            SimulatedAssessmentScenario.UNKNOWN_RESULT,
            SimulatedAssessmentScenario.ASSIGNED,
        )
    )

    first = adapter.route_assessor(_command(), 'fingerprint')
    replay = adapter.route_assessor(_command(), 'fingerprint')

    assert first.operation_status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME
    assert replay.operation_status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME
    assert replay.replayed is True


def test_changed_request_fingerprint_is_rejected() -> None:
    adapter = SimulatedVehicleDamageAssessorAdapter()
    adapter.route_assessor(_command(), 'fingerprint-one')

    with pytest.raises(AdapterIdempotencyConflict):
        adapter.route_assessor(_command(), 'fingerprint-two')


def test_another_requested_action_is_outside_the_simulation() -> None:
    adapter = SimulatedVehicleDamageAssessorAdapter()

    with pytest.raises(ValueError, match='vehicle damage assessment only'):
        adapter.route_assessor(_command(requested_action='repair_authorisation'), 'fingerprint')


def test_accepted_outcome_cannot_claim_success_before_submission() -> None:
    accepted = SimulatedVehicleDamageAssessorAdapter().route_assessor(_command(), 'fingerprint')

    with pytest.raises(ValueError, match='must have been submitted'):
        replace(
            accepted,
            delivery=ExternalTaskDelivery.NOT_SUBMITTED,
            delivery_evidence=None,
        )


def test_simulation_outcome_requires_an_explicit_non_live_limitation() -> None:
    with pytest.raises(ValueError, match='non-live limitation'):
        SimulatedAssessmentOutcome(
            source=IntegrationSource.FIXTURE,
            operation_status=ExternalTaskOperationStatus.RETRYABLE_FAILURE,
            delivery=ExternalTaskDelivery.NOT_SUBMITTED,
            delivery_evidence=None,
            failure_code=ExternalTaskFailureCode.UNAVAILABLE,
            recovery=ExternalTaskRecovery.RETRY_SAME_OPERATION,
            retryable=True,
            routing=None,
            provider_reference=None,
            limitation='',
        )
