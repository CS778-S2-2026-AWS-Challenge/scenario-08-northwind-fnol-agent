from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.external_services import (
    ExternalRequestTaskMismatchError,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    ExternalTaskResult,
    ExternalTaskResultVerification,
    UnsettledResultError,
    assert_result_matches_task,
    assert_result_may_settle_fact,
)
from backend.domain.models import IntegrationSource
from backend.domain.retrieval import RetrievalSource

RECEIVED_AT = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
VERIFIED_AT = RECEIVED_AT + timedelta(minutes=5)
SERVICE = 'vehicle_damage_assessment_routing'
ACTION = 'vehicle_damage_assessment'


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
        evidence_ids=evidence_ids if evidence_ids is not None else [],
        received_at=RECEIVED_AT,
    )


def _task(*, task_id: str = 'ext_task_1', claim_id: str = 'clm_1') -> ExternalTaskRecord:
    return ExternalTaskRecord(
        task_id=task_id,
        claim_id=claim_id,
        service_identity=SERVICE,
        requested_action=ACTION,
        integration_source=IntegrationSource.FIXTURE,
        status=ExternalTaskOperationStatus.PREPARED,
        created_at=RECEIVED_AT,
        updated_at=RECEIVED_AT,
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
        )
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
        assert_result_may_settle_fact(_result(verification=verification, verified_at=verified_at))
