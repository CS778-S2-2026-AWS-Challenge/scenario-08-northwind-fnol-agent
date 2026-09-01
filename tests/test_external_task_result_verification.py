from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.external_services import (
    ConflictingEvidenceOriginError,
    ExternalRequestTaskMismatchError,
    ExternalTaskClaimMismatchError,
    ExternalTaskDelivery,
    ExternalTaskEvidenceLink,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    ExternalTaskResult,
    ExternalTaskResultVerification,
    ResultAlreadyVerifiedError,
    StaleVerificationError,
    TaskCannotHaveResultError,
    UntraceableExternalEvidenceError,
    assert_result_may_settle_fact,
    verify_external_task_result,
)
from backend.domain.models import ClaimState, EvidenceState, IntegrationSource, WorkflowState
from backend.domain.retrieval import RetrievalSource

RECEIVED_AT = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
CHECKED_AT = RECEIVED_AT + timedelta(minutes=5)
SERVICE = 'vehicle_damage_assessment_routing'
ACTION = 'vehicle_damage_assessment'
CLAIM = 'clm_1'
TASK = 'ext_task_1'
REVISION = 4


def _source() -> RetrievalSource:
    return RetrievalSource(
        system='controlled_assessment_fixture',
        reference='provider-ref-1',
        retrieved_at=RECEIVED_AT,
    )


def _result(
    *,
    result_id: str = 'ext_res_1',
    task_id: str = TASK,
    claim_id: str = CLAIM,
    verification: ExternalTaskResultVerification = ExternalTaskResultVerification.UNVERIFIED,
    verified_at: datetime | None = None,
    verified_against_revision: int | None = None,
    evidence_ids: list[str] | None = None,
) -> ExternalTaskResult:
    return ExternalTaskResult(
        result_id=result_id,
        task_id=task_id,
        claim_id=claim_id,
        source=_source(),
        summary='Assessor assigned for the recorded vehicle damage.',
        verification=verification,
        verified_at=verified_at,
        verified_against_revision=verified_against_revision,
        evidence_ids=evidence_ids if evidence_ids is not None else [],
        received_at=RECEIVED_AT,
    )


def _failure_code_for(status: ExternalTaskOperationStatus) -> ExternalTaskFailureCode | None:
    """The failure code the shared classification derives for each failed state."""

    return {
        ExternalTaskOperationStatus.UNKNOWN_OUTCOME: ExternalTaskFailureCode.TIMEOUT,
        ExternalTaskOperationStatus.RETRYABLE_FAILURE: ExternalTaskFailureCode.UNAVAILABLE,
        ExternalTaskOperationStatus.TERMINAL_FAILURE: ExternalTaskFailureCode.MALFORMED,
    }.get(status)


def _task(
    *,
    task_id: str = TASK,
    claim_id: str = CLAIM,
    status: ExternalTaskOperationStatus = ExternalTaskOperationStatus.ACCEPTED,
) -> ExternalTaskRecord:
    accepted = status is ExternalTaskOperationStatus.ACCEPTED
    unknown = status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME
    reached = accepted or unknown
    return ExternalTaskRecord(
        task_id=task_id,
        claim_id=claim_id,
        service_identity=SERVICE,
        requested_action=ACTION,
        integration_source=IntegrationSource.FIXTURE,
        status=status,
        delivery=(
            ExternalTaskDelivery.SUBMITTED if reached else ExternalTaskDelivery.NOT_SUBMITTED
        ),
        delivery_evidence=('transport-receipt-1' if reached else None),
        failure_code=_failure_code_for(status),
        created_at=RECEIVED_AT,
        updated_at=RECEIVED_AT,
    )


def _link(
    *,
    evidence_id: str = 'evd_1',
    task_id: str = TASK,
    claim_id: str = CLAIM,
) -> ExternalTaskEvidenceLink:
    return ExternalTaskEvidenceLink(
        task_id=task_id,
        evidence_id=evidence_id,
        claim_id=claim_id,
        linked_at=RECEIVED_AT,
    )


def _state(
    *,
    evidence: EvidenceState = EvidenceState.RECEIVED,
    workflow_state: WorkflowState = WorkflowState.COLLECTING,
) -> ClaimState:
    return ClaimState(evidence=evidence, workflow_state=workflow_state)


def _verify(
    result: ExternalTaskResult,
    *,
    task: ExternalTaskRecord | None = None,
    links: list[ExternalTaskEvidenceLink] | None = None,
    claim_id: str = CLAIM,
    claim_state: ClaimState | None = None,
    claim_revision: int = REVISION,
    checked_at: datetime = CHECKED_AT,
) -> ExternalTaskResult:
    return verify_external_task_result(
        result,
        task=task if task is not None else _task(),
        links=links if links is not None else [],
        claim_id=claim_id,
        claim_state=claim_state if claim_state is not None else _state(),
        claim_revision=claim_revision,
        checked_at=checked_at,
    )


def test_accepted_task_with_its_material_named_is_consistent() -> None:
    checked = _verify(_result(evidence_ids=['evd_1']), links=[_link()])

    assert checked.verification is ExternalTaskResultVerification.CONSISTENT
    assert checked.verified_at == CHECKED_AT
    assert checked.verified_against_revision == REVISION


def test_answer_without_material_is_still_answerable() -> None:
    """A provider reporting no record found produces an answer and no material."""

    checked = _verify(_result(), links=[])

    assert checked.verification is ExternalTaskResultVerification.CONSISTENT


def test_result_naming_none_of_its_own_task_material_needs_review() -> None:
    checked = _verify(_result(), links=[_link(), _link(evidence_id='evd_2')])

    assert checked.verification is ExternalTaskResultVerification.REVIEW_REQUIRED


def test_result_naming_some_of_its_own_task_material_is_consistent() -> None:
    checked = _verify(
        _result(evidence_ids=['evd_1']),
        links=[_link(), _link(evidence_id='evd_2')],
    )

    assert checked.verification is ExternalTaskResultVerification.CONSISTENT


def test_material_on_another_task_does_not_count_as_this_task_material() -> None:
    """Links for a different task leave this task holding none, so absence stays answerable."""

    checked = _verify(_result(), links=[_link(evidence_id='evd_9', task_id='ext_task_2')])

    assert checked.verification is ExternalTaskResultVerification.CONSISTENT


def test_unknown_outcome_task_can_never_be_consistent() -> None:
    checked = _verify(
        _result(evidence_ids=['evd_1']),
        task=_task(status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME),
        links=[_link()],
    )

    assert checked.verification is ExternalTaskResultVerification.REVIEW_REQUIRED


def test_unknown_outcome_outranks_an_inconsistent_claim() -> None:
    """An unreconciled delivery cannot support the stronger claim of a conflict."""

    checked = _verify(
        _result(evidence_ids=['evd_1']),
        task=_task(status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME),
        links=[_link()],
        claim_state=_state(evidence=EvidenceState.INCONSISTENT),
    )

    assert checked.verification is ExternalTaskResultVerification.REVIEW_REQUIRED


def test_inconsistent_claim_evidence_makes_the_result_inconsistent() -> None:
    checked = _verify(
        _result(evidence_ids=['evd_1']),
        links=[_link()],
        claim_state=_state(evidence=EvidenceState.INCONSISTENT),
    )

    assert checked.verification is ExternalTaskResultVerification.INCONSISTENT


def test_claim_already_in_professional_review_needs_review() -> None:
    """A result must not settle a fact underneath the person the claim was escalated to."""

    checked = _verify(
        _result(evidence_ids=['evd_1']),
        links=[_link()],
        claim_state=_state(workflow_state=WorkflowState.PROFESSIONAL_REVIEW),
    )

    assert checked.verification is ExternalTaskResultVerification.REVIEW_REQUIRED


def test_every_decided_verification_is_reachable() -> None:
    """The vocabulary carries no value the check cannot produce."""

    decided = {
        _verify(_result(evidence_ids=['evd_1']), links=[_link()]).verification,
        _verify(
            _result(evidence_ids=['evd_1']),
            links=[_link()],
            claim_state=_state(evidence=EvidenceState.INCONSISTENT),
        ).verification,
        _verify(
            _result(),
            links=[_link()],
        ).verification,
    }

    assert decided == {
        ExternalTaskResultVerification.CONSISTENT,
        ExternalTaskResultVerification.INCONSISTENT,
        ExternalTaskResultVerification.REVIEW_REQUIRED,
    }


def test_link_order_does_not_change_the_answer() -> None:
    """Two links for one task must resolve the same way whichever order they arrive in."""

    first = _link(evidence_id='evd_1')
    second = _link(evidence_id='evd_2')

    forward = _verify(_result(evidence_ids=['evd_2']), links=[first, second])
    reverse = _verify(_result(evidence_ids=['evd_2']), links=[second, first])

    assert forward.verification is reverse.verification
    assert forward.verification is ExternalTaskResultVerification.CONSISTENT


def test_repeated_links_for_one_material_resolve_the_same_way() -> None:
    duplicated = _verify(_result(evidence_ids=['evd_1']), links=[_link(), _link()])

    assert duplicated.verification is ExternalTaskResultVerification.CONSISTENT


def test_an_already_verified_result_is_refused() -> None:
    already = _result(
        verification=ExternalTaskResultVerification.CONSISTENT,
        verified_at=CHECKED_AT,
        verified_against_revision=REVISION,
    )

    with pytest.raises(ResultAlreadyVerifiedError):
        _verify(already)


def test_state_from_another_claim_is_refused() -> None:
    with pytest.raises(ExternalTaskClaimMismatchError):
        _verify(_result(), claim_id='clm_2')


def test_result_for_another_task_is_refused() -> None:
    with pytest.raises(ExternalRequestTaskMismatchError):
        _verify(_result(task_id='ext_task_2'), task=_task())


@pytest.mark.parametrize(
    'status',
    [
        ExternalTaskOperationStatus.PREPARED,
        ExternalTaskOperationStatus.RETRYABLE_FAILURE,
        ExternalTaskOperationStatus.TERMINAL_FAILURE,
    ],
)
def test_a_task_that_received_no_answer_cannot_be_verified(
    status: ExternalTaskOperationStatus,
) -> None:
    with pytest.raises(TaskCannotHaveResultError):
        _verify(_result(), task=_task(status=status))


def test_material_no_link_accounts_for_is_refused() -> None:
    with pytest.raises(UntraceableExternalEvidenceError):
        _verify(_result(evidence_ids=['evd_1']), links=[])


def test_material_linked_to_another_task_is_refused() -> None:
    with pytest.raises(ConflictingEvidenceOriginError):
        _verify(_result(evidence_ids=['evd_1']), links=[_link(task_id='ext_task_2')])


def test_a_check_cannot_predate_the_answer() -> None:
    with pytest.raises(ValueError, match='before it arrived'):
        _verify(_result(), checked_at=RECEIVED_AT - timedelta(minutes=1))


def test_the_argument_is_left_unchanged() -> None:
    original = _result(evidence_ids=['evd_1'])

    _verify(original, links=[_link()])

    assert original.verification is ExternalTaskResultVerification.UNVERIFIED
    assert original.verified_at is None
    assert original.verified_against_revision is None


def test_a_consistent_result_may_then_settle_a_fact_at_that_revision() -> None:
    checked = _verify(_result(evidence_ids=['evd_1']), links=[_link()])

    assert_result_may_settle_fact(checked, claim_revision=REVISION)


def test_a_consistent_result_goes_stale_when_the_claim_moves() -> None:
    checked = _verify(_result(evidence_ids=['evd_1']), links=[_link()])

    with pytest.raises(StaleVerificationError):
        assert_result_may_settle_fact(checked, claim_revision=REVISION + 1)
