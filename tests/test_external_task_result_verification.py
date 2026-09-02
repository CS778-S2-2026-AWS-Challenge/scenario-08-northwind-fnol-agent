from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.external_services import (
    ConflictingEvidenceOriginError,
    CrossClaimEvidenceError,
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
    TaskCannotHaveResultError,
    UnboundEvidenceSnapshotError,
    UnsettledResultError,
    UntraceableExternalEvidenceError,
    VerificationPrecedesStateError,
    assert_result_may_settle_fact,
    verify_external_task_result,
)
from backend.domain.models import (
    Channel,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    IntegrationSource,
    ResponsibleParty,
    WorkingClaim,
)
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
    updated_at: datetime = RECEIVED_AT,
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
        updated_at=updated_at,
    )


def _link(
    *,
    evidence_id: str = 'evd_1',
    task_id: str = TASK,
    claim_id: str = CLAIM,
    linked_at: datetime = RECEIVED_AT,
) -> ExternalTaskEvidenceLink:
    return ExternalTaskEvidenceLink(
        task_id=task_id,
        evidence_id=evidence_id,
        claim_id=claim_id,
        linked_at=linked_at,
    )


def _evidence(
    *,
    evidence_id: str = 'evd_1',
    claim_id: str = CLAIM,
    status: EvidenceStatus = EvidenceStatus.RECEIVED,
    updated_at: datetime = RECEIVED_AT,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        claim_id=claim_id,
        kind='assessment_report',
        status=status,
        file_status=EvidenceFileStatus.READY,
        source=EvidenceSource.EXTERNAL_SYSTEM,
        created_at=RECEIVED_AT,
        updated_at=updated_at,
    )


def _claim(
    *,
    claim_id: str = CLAIM,
    revision: int = REVISION,
    updated_at: datetime = RECEIVED_AT,
) -> WorkingClaim:
    return WorkingClaim(
        claim_id=claim_id,
        customer_id='cus_1',
        revision=revision,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        customer_next_step=CustomerNextStep(
            status='awaiting_assessment',
            summary='An assessor has been requested.',
            responsible_party=ResponsibleParty.EXTERNAL_PARTY,
        ),
        created_at=RECEIVED_AT,
        updated_at=updated_at,
    )


def _verify(
    result: ExternalTaskResult,
    *,
    task: ExternalTaskRecord | None = None,
    links: list[ExternalTaskEvidenceLink] | None = None,
    claim: WorkingClaim | None = None,
    evidence: list[EvidenceRecord] | None = None,
    checked_at: datetime = CHECKED_AT,
) -> ExternalTaskResult:
    return verify_external_task_result(
        result,
        task=task if task is not None else _task(),
        links=links if links is not None else [],
        claim=claim if claim is not None else _claim(),
        evidence=evidence if evidence is not None else [],
        checked_at=checked_at,
    )


def test_a_placed_and_attributed_answer_is_not_agreement() -> None:
    """Structural checks place a result; they do not compare it, so it needs review."""

    checked = _verify(_result(evidence_ids=['evd_1']), links=[_link()], evidence=[_evidence()])

    assert checked.verification is ExternalTaskResultVerification.REVIEW_REQUIRED
    assert checked.verified_at == CHECKED_AT
    assert checked.verified_against_revision == REVISION


def test_consistent_is_never_produced() -> None:
    """No input reaches agreement, because no comparison of content can be evidenced."""

    inputs = [
        _verify(_result()),
        _verify(_result(evidence_ids=['evd_1']), links=[_link()], evidence=[_evidence()]),
        _verify(
            _result(evidence_ids=['evd_1']),
            links=[_link()],
            evidence=[_evidence(status=EvidenceStatus.INCONSISTENT)],
        ),
        _verify(
            _result(evidence_ids=['evd_1']),
            task=_task(status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME),
            links=[_link()],
            evidence=[_evidence()],
        ),
    ]

    assert all(
        checked.verification is not ExternalTaskResultVerification.CONSISTENT for checked in inputs
    )


def test_nothing_this_produces_can_settle_a_claim_fact() -> None:
    """The refusal in assert_result_may_settle_fact is the point, not an accident."""

    checked = _verify(_result(evidence_ids=['evd_1']), links=[_link()], evidence=[_evidence()])

    with pytest.raises(UnsettledResultError):
        assert_result_may_settle_fact(checked, claim_revision=REVISION)


def test_material_the_result_names_being_inconsistent_makes_it_inconsistent() -> None:
    checked = _verify(
        _result(evidence_ids=['evd_1']),
        links=[_link()],
        evidence=[_evidence(status=EvidenceStatus.INCONSISTENT)],
    )

    assert checked.verification is ExternalTaskResultVerification.INCONSISTENT


def test_a_conflict_in_material_this_result_does_not_name_is_not_attributed_to_it() -> None:
    """A conflict elsewhere on the claim is not this provider's conflict."""

    checked = _verify(
        _result(evidence_ids=['evd_1']),
        links=[_link()],
        evidence=[
            _evidence(),
            _evidence(evidence_id='evd_unrelated', status=EvidenceStatus.INCONSISTENT),
        ],
    )

    assert checked.verification is ExternalTaskResultVerification.REVIEW_REQUIRED


def test_a_result_naming_no_material_cannot_be_inconsistent() -> None:
    checked = _verify(
        _result(),
        evidence=[_evidence(status=EvidenceStatus.INCONSISTENT)],
    )

    assert checked.verification is ExternalTaskResultVerification.REVIEW_REQUIRED


def test_unknown_outcome_outranks_a_conflict_in_named_material() -> None:
    """An unreconciled delivery cannot support attributing a conflict to the provider."""

    checked = _verify(
        _result(evidence_ids=['evd_1']),
        task=_task(status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME),
        links=[_link()],
        evidence=[_evidence(status=EvidenceStatus.INCONSISTENT)],
    )

    assert checked.verification is ExternalTaskResultVerification.REVIEW_REQUIRED


def test_evidence_order_does_not_change_the_answer() -> None:
    """Two records for one claim must resolve the same way whichever order they arrive in."""

    clean = _evidence(evidence_id='evd_2')
    conflicting = _evidence(status=EvidenceStatus.INCONSISTENT)

    forward = _verify(
        _result(evidence_ids=['evd_1']), links=[_link()], evidence=[clean, conflicting]
    )
    reverse = _verify(
        _result(evidence_ids=['evd_1']), links=[_link()], evidence=[conflicting, clean]
    )

    assert forward.verification is reverse.verification
    assert forward.verification is ExternalTaskResultVerification.INCONSISTENT


def test_the_revision_recorded_comes_from_the_claim_snapshot() -> None:
    """State and revision cannot disagree, because only one snapshot is accepted."""

    checked = _verify(_result(), claim=_claim(revision=REVISION + 3))

    assert checked.verified_against_revision == REVISION + 3


def test_an_already_verified_result_is_refused() -> None:
    already = _result(
        verification=ExternalTaskResultVerification.INCONSISTENT,
        verified_at=CHECKED_AT,
        verified_against_revision=REVISION,
    )

    with pytest.raises(ResultAlreadyVerifiedError):
        _verify(already)


def test_a_snapshot_of_another_claim_is_refused() -> None:
    with pytest.raises(ExternalTaskClaimMismatchError):
        _verify(_result(), claim=_claim(claim_id='clm_2'))


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
    with pytest.raises(VerificationPrecedesStateError, match='the result arriving'):
        _verify(_result(), checked_at=RECEIVED_AT - timedelta(minutes=1))


def test_the_argument_is_left_unchanged() -> None:
    original = _result(evidence_ids=['evd_1'])

    _verify(original, links=[_link()], evidence=[_evidence()])

    assert original.verification is ExternalTaskResultVerification.UNVERIFIED
    assert original.verified_at is None
    assert original.verified_against_revision is None


def test_evidence_owned_by_another_claim_is_refused() -> None:
    """Ownership is claim_id plus evidence_id, so a familiar identifier is not enough."""

    with pytest.raises(CrossClaimEvidenceError):
        _verify(
            _result(evidence_ids=['evd_1']),
            links=[_link()],
            evidence=[_evidence(claim_id='clm_2', status=EvidenceStatus.INCONSISTENT)],
        )


def test_evidence_written_after_the_claim_was_read_is_refused() -> None:
    """The decision records the claim revision, so it must not use later evidence."""

    with pytest.raises(UnboundEvidenceSnapshotError):
        _verify(
            _result(evidence_ids=['evd_1']),
            links=[_link()],
            evidence=[_evidence(updated_at=RECEIVED_AT + timedelta(seconds=1))],
        )


def test_evidence_as_new_as_the_claim_is_accepted() -> None:
    """An evidence mutation sets the claim to the newest record, so equal is the norm."""

    checked = _verify(
        _result(evidence_ids=['evd_1']),
        links=[_link()],
        evidence=[_evidence(updated_at=RECEIVED_AT)],
    )

    assert checked.verification is ExternalTaskResultVerification.REVIEW_REQUIRED


def test_an_unnamed_record_is_still_bound_to_the_snapshot() -> None:
    """The bundle is checked whole; a stale record does not become safe by going unnamed."""

    with pytest.raises(UnboundEvidenceSnapshotError):
        _verify(
            _result(evidence_ids=['evd_1']),
            links=[_link()],
            evidence=[
                _evidence(),
                _evidence(
                    evidence_id='evd_unrelated',
                    updated_at=RECEIVED_AT + timedelta(seconds=1),
                ),
            ],
        )


def test_a_check_cannot_predate_the_claim_snapshot_it_records() -> None:
    """A verification stamped before its claim existed describes a check that never happened."""

    later = RECEIVED_AT + timedelta(minutes=10)

    with pytest.raises(VerificationPrecedesStateError, match='the claim snapshot'):
        _verify(
            _result(evidence_ids=['evd_1']),
            links=[_link()],
            claim=_claim(updated_at=later),
            evidence=[_evidence(updated_at=later)],
            checked_at=RECEIVED_AT + timedelta(minutes=5),
        )


def test_a_check_cannot_predate_the_task_record_it_read() -> None:
    with pytest.raises(VerificationPrecedesStateError, match='the task record'):
        _verify(
            _result(),
            task=_task(updated_at=RECEIVED_AT + timedelta(minutes=10)),
            checked_at=RECEIVED_AT + timedelta(minutes=5),
        )


def test_a_check_cannot_predate_a_link_it_read() -> None:
    with pytest.raises(VerificationPrecedesStateError, match='evidence evd_1 being linked'):
        _verify(
            _result(evidence_ids=['evd_1']),
            links=[_link(linked_at=RECEIVED_AT + timedelta(minutes=10))],
            evidence=[_evidence()],
            checked_at=RECEIVED_AT + timedelta(minutes=5),
        )


def test_a_link_the_result_does_not_name_does_not_bind_the_check() -> None:
    """Only the state this decision depended on can make its timing impossible."""

    checked = _verify(
        _result(evidence_ids=['evd_1']),
        links=[
            _link(),
            _link(evidence_id='evd_other', linked_at=RECEIVED_AT + timedelta(minutes=10)),
        ],
        evidence=[_evidence()],
        checked_at=RECEIVED_AT + timedelta(minutes=5),
    )

    assert checked.verification is ExternalTaskResultVerification.REVIEW_REQUIRED


def test_a_check_at_the_moment_the_last_state_appeared_is_accepted() -> None:
    """The bound is impossibility, not a margin, so equality is allowed."""

    moment = RECEIVED_AT + timedelta(minutes=10)

    checked = _verify(
        _result(evidence_ids=['evd_1']),
        links=[_link()],
        claim=_claim(updated_at=moment),
        evidence=[_evidence(updated_at=moment)],
        checked_at=moment,
    )

    assert checked.verification is ExternalTaskResultVerification.REVIEW_REQUIRED
    assert checked.verified_at == moment
