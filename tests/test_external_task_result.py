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
    StaleVerificationError,
    TaskCannotHaveResultError,
    UnsettledResultError,
    UntraceableExternalEvidenceError,
    assert_result_evidence_is_linked,
    assert_result_matches_task,
    assert_result_may_settle_fact,
)
from backend.domain.models import IntegrationSource
from backend.domain.retrieval import RetrievalSource

RECEIVED_AT = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
VERIFIED_AT = RECEIVED_AT + timedelta(minutes=5)
SERVICE = 'vehicle_damage_assessment_routing'
ACTION = 'vehicle_damage_assessment'
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
    task_id: str = 'ext_task_1',
    claim_id: str = 'clm_1',
    summary: str = 'Assessor assigned for the recorded vehicle damage.',
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
        summary=summary,
        verification=verification,
        verified_at=verified_at,
        verified_against_revision=(
            verified_against_revision
            if verified_against_revision is not None or verified_at is None
            else REVISION
        ),
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
    task_id: str = 'ext_task_1',
    claim_id: str = 'clm_1',
    status: ExternalTaskOperationStatus = ExternalTaskOperationStatus.ACCEPTED,
) -> ExternalTaskRecord:
    accepted = status is ExternalTaskOperationStatus.ACCEPTED
    unknown = status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME
    return ExternalTaskRecord(
        task_id=task_id,
        claim_id=claim_id,
        service_identity=SERVICE,
        requested_action=ACTION,
        integration_source=IntegrationSource.FIXTURE,
        status=status,
        delivery=(
            ExternalTaskDelivery.SUBMITTED
            if accepted or unknown
            else ExternalTaskDelivery.NOT_SUBMITTED
        ),
        delivery_evidence=('transport-receipt-1' if accepted or unknown else None),
        failure_code=_failure_code_for(status),
        created_at=RECEIVED_AT,
        updated_at=RECEIVED_AT,
    )


def _link(
    *,
    evidence_id: str = 'evd_1',
    task_id: str = 'ext_task_1',
    claim_id: str = 'clm_1',
) -> ExternalTaskEvidenceLink:
    return ExternalTaskEvidenceLink(
        task_id=task_id,
        evidence_id=evidence_id,
        claim_id=claim_id,
        linked_at=RECEIVED_AT,
    )


def test_a_result_carries_its_source_and_starts_unverified() -> None:
    result = _result()

    assert result.source.system == 'controlled_assessment_fixture'
    assert result.source.reference == 'provider-ref-1'
    assert result.source.retrieved_at == RECEIVED_AT
    assert result.verification is ExternalTaskResultVerification.UNVERIFIED
    assert result.verified_at is None


def test_the_verification_vocabulary_cannot_express_a_confirmed_fact() -> None:
    """A provider answer is evidence about the claim, never the claim's own record."""

    assert {v.value for v in ExternalTaskResultVerification} == {
        'unverified',
        'consistent',
        'inconsistent',
        'review_required',
    }
    assert not any('confirm' in v.value for v in ExternalTaskResultVerification)


def test_a_result_can_carry_no_material_at_all() -> None:
    """A provider reporting no record found is an answer, not an absence of one."""

    assert _result(summary='No matching record was found.').evidence_ids == []


@pytest.mark.parametrize(
    'verification',
    [
        ExternalTaskResultVerification.CONSISTENT,
        ExternalTaskResultVerification.INCONSISTENT,
        ExternalTaskResultVerification.REVIEW_REQUIRED,
    ],
)
def test_a_checked_result_must_say_when_it_was_checked(
    verification: ExternalTaskResultVerification,
) -> None:
    with pytest.raises(ValueError, match='must record when it was'):
        _result(verification=verification)

    checked = _result(verification=verification, verified_at=VERIFIED_AT)
    assert checked.verified_at == VERIFIED_AT


def test_an_unverified_result_cannot_record_a_verification_time() -> None:
    with pytest.raises(ValueError, match='cannot record a verification time'):
        _result(verified_at=VERIFIED_AT)


def test_a_result_cannot_be_verified_before_it_was_received() -> None:
    with pytest.raises(ValueError, match='cannot be verified before it was received'):
        _result(
            verification=ExternalTaskResultVerification.CONSISTENT,
            verified_at=RECEIVED_AT - timedelta(seconds=1),
        )


def test_result_evidence_must_be_unique_and_named() -> None:
    with pytest.raises(ValueError, match='must be unique'):
        _result(evidence_ids=['evd_1', 'evd_1'])

    with pytest.raises(ValueError, match='must name something'):
        _result(evidence_ids=['evd_1', '  '])


def test_a_result_must_say_something_readable() -> None:
    with pytest.raises(ValueError, match='say something readable'):
        _result(summary='   ')


def test_a_result_agreeing_with_its_task_passes() -> None:
    assert_result_matches_task(_result(), _task())


def test_a_result_naming_another_task_is_rejected() -> None:
    with pytest.raises(ExternalRequestTaskMismatchError, match='names task'):
        assert_result_matches_task(_result(), _task(task_id='ext_task_other'))


def test_a_result_on_another_claim_cannot_use_this_task() -> None:
    with pytest.raises(ExternalRequestTaskMismatchError, match='does not match task'):
        assert_result_matches_task(_result(), _task(claim_id='clm_other'))


def test_only_a_consistent_result_may_settle_a_fact() -> None:
    assert_result_may_settle_fact(
        _result(
            verification=ExternalTaskResultVerification.CONSISTENT,
            verified_at=VERIFIED_AT,
        ),
        claim_revision=REVISION,
    )


@pytest.mark.parametrize(
    ('verification', 'verified_at', 'expected'),
    [
        (ExternalTaskResultVerification.UNVERIFIED, None, 'has not been checked'),
        (ExternalTaskResultVerification.INCONSISTENT, VERIFIED_AT, 'conflicts with the claim'),
        (ExternalTaskResultVerification.REVIEW_REQUIRED, VERIFIED_AT, 'needs review'),
    ],
)
def test_an_unsettled_result_is_refused_and_says_which_it_is(
    verification: ExternalTaskResultVerification,
    verified_at: datetime | None,
    expected: str,
) -> None:
    """The caller should learn which state it holds, not only that it cannot proceed."""

    with pytest.raises(UnsettledResultError, match=expected):
        assert_result_may_settle_fact(
            _result(verification=verification, verified_at=verified_at),
            claim_revision=REVISION,
        )


@pytest.mark.parametrize(
    'status',
    [
        ExternalTaskOperationStatus.PREPARED,
        ExternalTaskOperationStatus.RETRYABLE_FAILURE,
        ExternalTaskOperationStatus.TERMINAL_FAILURE,
    ],
)
def test_a_task_that_received_no_answer_cannot_carry_a_result(
    status: ExternalTaskOperationStatus,
) -> None:
    """A prepared task was never sent, and a failed one got nothing back."""

    with pytest.raises(TaskCannotHaveResultError, match='received no provider answer'):
        assert_result_matches_task(_result(), _task(status=status))


def test_an_unknown_outcome_may_carry_a_late_answer() -> None:
    """Reconciliation is exactly where a late provider answer arrives."""

    assert_result_matches_task(_result(), _task(status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME))


def test_result_evidence_must_reach_it_through_a_link() -> None:
    assert_result_evidence_is_linked(_result(evidence_ids=['evd_1']), [_link()])


def test_result_evidence_with_no_link_is_rejected() -> None:
    with pytest.raises(UntraceableExternalEvidenceError, match='no link attributes'):
        assert_result_evidence_is_linked(_result(evidence_ids=['evd_1']), [])


def test_result_evidence_linked_under_another_claim_is_rejected() -> None:
    """The bypass the evidence link boundary already closes."""

    with pytest.raises(ExternalTaskClaimMismatchError, match='linked under claim'):
        assert_result_evidence_is_linked(
            _result(evidence_ids=['evd_1']), [_link(claim_id='clm_other')]
        )


def test_result_evidence_produced_by_another_task_is_rejected() -> None:
    with pytest.raises(ConflictingEvidenceOriginError, match='linked to task'):
        assert_result_evidence_is_linked(
            _result(evidence_ids=['evd_1']), [_link(task_id='ext_task_other')]
        )


def test_a_checked_result_must_name_the_revision_it_was_checked_against() -> None:
    with pytest.raises(ValueError, match='must name the claim revision'):
        ExternalTaskResult(
            result_id='ext_res_1',
            task_id='ext_task_1',
            claim_id='clm_1',
            source=_source(),
            summary='Assessor assigned.',
            verification=ExternalTaskResultVerification.CONSISTENT,
            verified_at=VERIFIED_AT,
            verified_against_revision=None,
            received_at=RECEIVED_AT,
        )


def test_an_unverified_result_cannot_name_a_revision() -> None:
    with pytest.raises(ValueError, match='cannot name a revision'):
        _result(verified_against_revision=REVISION)


def test_a_consistent_result_cannot_settle_a_later_revision() -> None:
    """A check made against an earlier claim no longer covers the current one."""

    consistent = _result(
        verification=ExternalTaskResultVerification.CONSISTENT,
        verified_at=VERIFIED_AT,
    )

    with pytest.raises(StaleVerificationError, match='no longer covers it'):
        assert_result_may_settle_fact(consistent, claim_revision=REVISION + 1)


def test_conflicting_evidence_links_fail_closed_in_either_order() -> None:
    """Keeping one link per identifier would let list order decide attribution."""

    mine = _link(task_id='ext_task_1')
    other = _link(task_id='ext_task_other')

    for links in ([other, mine], [mine, other]):
        with pytest.raises(ConflictingEvidenceOriginError, match='more than one task'):
            assert_result_evidence_is_linked(_result(evidence_ids=['evd_1']), links)


def test_a_repeated_identical_link_is_one_origin() -> None:
    assert_result_evidence_is_linked(_result(evidence_ids=['evd_1']), [_link(), _link()])


def test_a_cross_claim_link_fails_closed_in_either_order() -> None:
    mine = _link(claim_id='clm_1')
    other = _link(claim_id='clm_other')

    for links in ([other, mine], [mine, other]):
        with pytest.raises(ExternalTaskClaimMismatchError, match='not clm_1 alone'):
            assert_result_evidence_is_linked(_result(evidence_ids=['evd_1']), links)
