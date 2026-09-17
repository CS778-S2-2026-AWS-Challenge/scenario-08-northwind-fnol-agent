"""Drive the motor assessor request into one scripted provider failure and through its recovery.

Each case starts as the AT-01 motor journey and stops at assessor consent. It then routes the
request against an adapter scripted to fail one way, reads what the claimant and staff are each
shown at that moment, and recovers only through an action the contract offers: the claimant's own
retry, or the Workbench action projected for the task. The routing step expects the failure's
documented status, and its error code is recorded as a fixture oracle, so a different failure
fails the run instead of passing as recovery evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi.testclient import TestClient

from backend.adapters.claims_service import (
    AssessorFixtureFailure,
    AssessorRoutingOutcome,
    MockAssessorServiceAdapter,
    ScriptedAssessorFailure,
)
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.domain.external_services import ExternalTaskDelivery
from backend.domain.models import AssessorRoutingResult, AssessorRoutingStatus, RouteAssessorRequest
from backend.repositories.fixture import FixtureRepository

from .engine import (
    Journey,
    build_record,
    delivered_materials,
    final_state,
    read_both_ends,
    seam_check,
)
from .motor_collision import (
    MOTOR_COLLISION_PACK,
    PACK_ID,
    RUBRIC_REFS,
    _assessor_read_back,
    _drive_to_assessor_consent,
    _look_up_assessor_task,
    _motor_input,
    _receive_assessment,
)
from .record import JourneyRunRecord, SeamCheck, SeamVerdict

Recovery = Literal['claimant_retry', 'staff_accept_review', 'staff_reconcile']
STAFF = 'claims_professional'


class _InterruptedDispatch(MockAssessorServiceAdapter):
    """Dies inside the provider call after the reservation, as a crashed process does."""

    def route_assessor(
        self, command: RouteAssessorRequest, request_fingerprint: str
    ) -> AssessorRoutingOutcome:
        raise RuntimeError('the dispatching process did not return')


class _NotRequiredRouting(MockAssessorServiceAdapter):
    """Answers with a routing status this runtime cannot turn into an assignment."""

    def route_assessor(
        self, command: RouteAssessorRequest, request_fingerprint: str
    ) -> AssessorRoutingOutcome:
        return AssessorRoutingOutcome(
            result=AssessorRoutingResult(
                routing_status=AssessorRoutingStatus.NOT_REQUIRED,
                assessor_reference=None,
                queue_reference=None,
                next_step='No assessor is required for this claim.',
                expected_by=datetime.now(UTC) + timedelta(hours=48),
                limitations=['Synthetic fixture routing; no production assessor was contacted.'],
            ),
            replayed=False,
        )


def _failing(
    *failures: AssessorFixtureFailure | ScriptedAssessorFailure,
) -> MockAssessorServiceAdapter:
    return MockAssessorServiceAdapter(failure_sequence=failures)


@dataclass(frozen=True)
class FailureCase:
    case_id: str
    adapter: Callable[[], MockAssessorServiceAdapter]
    route_status: int
    route_error: str
    recovery: Recovery
    # Seam -> tracking reference for disagreements already reported to their owner.
    known_defects: Mapping[str, str] = field(default_factory=dict)


_SENT_THEN_LOST = ScriptedAssessorFailure(
    code=AssessorFixtureFailure.TIMEOUT,
    delivery=ExternalTaskDelivery.SUBMITTED,
    delivery_evidence='fixture send acknowledged; no routing answer returned',
)
_RETRYABLE_OWNER = '#934'

FAILURE_CASES = {
    case.case_id: case
    for case in (
        FailureCase(
            'retryable-unavailable',
            lambda: _failing(AssessorFixtureFailure.UNAVAILABLE),
            503,
            'DEPENDENCY_UNAVAILABLE',
            'claimant_retry',
            {
                'failure.responsible_party': _RETRYABLE_OWNER,
                'failure.staff_can_find_work': _RETRYABLE_OWNER,
                'failure.staff_has_a_recovery_action': _RETRYABLE_OWNER,
            },
        ),
        FailureCase(
            'terminal-access-denied',
            lambda: _failing(AssessorFixtureFailure.ACCESS_DENIED),
            502,
            'DEPENDENCY_FAILED',
            'staff_accept_review',
        ),
        FailureCase(
            'terminal-not-required',
            _NotRequiredRouting,
            502,
            'DEPENDENCY_FAILED',
            'staff_accept_review',
        ),
        FailureCase(
            'unknown-outcome',
            lambda: _failing(_SENT_THEN_LOST),
            409,
            'INVALID_STATE_TRANSITION',
            'staff_reconcile',
        ),
        FailureCase(
            'interrupted-dispatch', _InterruptedDispatch, 500, 'INTERNAL_ERROR', 'staff_reconcile'
        ),
    )
}


def _failure_point_checks(journey: Journey, case: FailureCase) -> tuple[list[SeamCheck], bool]:
    """What each end is shown the moment routing fails, before anyone recovers."""

    claim_id = journey.claim_id
    claimant = journey.read(f'/api/v1/claims/{claim_id}', 'claimant')
    detail = journey.read(f'/api/v1/workbench/claims/{claim_id}', 'staff')
    requests = journey.items(f'/api/v1/workbench/claims/{claim_id}/external-requests', 'staff')
    lifecycle: dict[str, Any] = (requests[0].get('lifecycle') or {}) if requests else {}
    party = (claimant.get('customer_next_step') or {}).get('responsible_party')
    owner = lifecycle.get('pending_owner')
    listed = {
        item['claim_id']
        for item in journey.items('/api/v1/workbench/claims?view=all&limit=100', 'staff')
    }
    actions = [
        item['action_code']
        for item in detail.get('allowed_actions', [])
        if str(item['action_code']).startswith('external.')
    ]
    staff_named = STAFF in {party, owner}
    checks = [
        (
            'failure.responsible_party',
            'After the failure, who does each end say acts next?',
            str(party),
            f'lifecycle owner {owner}',
            party == owner,
            SeamVerdict.CONTRADICTORY,
        ),
        (
            'failure.staff_can_find_work',
            'When either end names staff as the next actor, is the claim in an active queue?',
            f'next step owned by {party}',
            f"lifecycle owner {owner}; in 'all': {claim_id in listed}",
            claim_id in listed or not staff_named,
            SeamVerdict.MISSING,
        ),
        (
            'failure.staff_has_a_recovery_action',
            'When either end names staff as the next actor, is a task action projected?',
            f'next step owned by {party}',
            f'external actions: {actions or "none"}',
            bool(actions) or not staff_named,
            SeamVerdict.MISSING,
        ),
    ]
    seams = [
        seam_check(
            seam,
            question,
            said,
            shown,
            SeamVerdict.CONSISTENT if agrees else disagreement,
            case.known_defects,
        )
        for seam, question, said, shown, agrees, disagreement in checks
    ]
    can_request = bool((claimant.get('external_service_action') or {}).get('can_request'))
    return seams, can_request


def run_assessor_failure(case: FailureCase, *, head: str) -> JourneyRunRecord:
    """Run one assessor failure and its recovery on a fresh fixture runtime."""

    settings = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)
    started_at = datetime.now(UTC)
    app = create_app(
        settings, repository=FixtureRepository(), assessor_service_adapter=case.adapter()
    )
    pack = MOTOR_COLLISION_PACK
    # An interrupted dispatch reaches the client as an HTTP 500; record it rather than raise.
    with TestClient(app, raise_server_exceptions=False) as client:
        journey = Journey(client)
        turns, evidence = _drive_to_assessor_consent(journey, _motor_input('AT-01', 0), pack)
        claim = f'/api/v1/claims/{journey.claim_id}'
        routed = journey.step(
            'route the assessor', 'POST', f'{claim}/assessor-routing', case.route_status, 'claimant'
        )
        failure_checks: list[SeamCheck] = []
        if routed is not None:
            journey.record_oracle(
                'route the assessor',
                {'error_code': case.route_error},
                {'error_code': (routed.get('error') or {}).get('code')},
            )
            failure_checks, can_request = _failure_point_checks(journey, case)
            resent = journey.step(
                'claimant resends the request',
                'POST',
                f'{claim}/assessor-routing',
                201 if can_request else 409,
                'claimant',
            )
            failure_checks.append(
                seam_check(
                    'failure.request_matches_resend',
                    'Does the offer to request again match what a resend does?',
                    f'can_request {can_request}',
                    f'resend HTTP {journey.steps[-1].http_status}',
                    SeamVerdict.CONSISTENT if resent is not None else SeamVerdict.CONTRADICTORY,
                    case.known_defects,
                )
            )
        task = _look_up_assessor_task(journey)
        workbench_task = f'/api/v1/workbench/claims/{journey.claim_id}/external-tasks/{task}'
        if task is not None and case.recovery == 'staff_accept_review':
            journey.step(
                'staff accepts the review',
                'POST',
                f'{workbench_task}/accept-review',
                201,
                'staff',
                {},
            )
        if task is not None and case.recovery == 'staff_reconcile':
            journey.step(
                'staff reconciles the response', 'POST', f'{workbench_task}/reconcile', 200, 'staff'
            )
        if case.recovery != 'staff_accept_review':
            _receive_assessment(journey, task, pack)
        materials = delivered_materials(journey, pack, evidence)
        shared = read_both_ends(journey, case.known_defects)
        seam_checks, visibility, consents = _assessor_read_back(journey, shared, case.known_defects)
        state = final_state(journey, shared)

    return build_record(
        scenario_id=f'motor-assessor-{case.case_id}',
        family='motor',
        pack_id=PACK_ID,
        rubric_refs=[*RUBRIC_REFS, 'failure recovery'],
        settings=settings,
        head=head,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        journey=journey,
        materials=materials,
        turns=turns,
        consents=consents,
        seam_checks=[*failure_checks, *seam_checks],
        visibility_checks=visibility,
        state=state,
    )
