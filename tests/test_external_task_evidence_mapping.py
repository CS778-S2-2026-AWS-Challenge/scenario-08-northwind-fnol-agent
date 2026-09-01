from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.external_services import (
    ConflictingEvidenceOriginError,
    ExternalTaskClaimMismatchError,
    ExternalTaskDelivery,
    ExternalTaskEvidenceLink,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    UntraceableExternalEvidenceError,
    external_task_for_evidence,
    map_external_task_evidence,
)
from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    IntegrationSource,
)

CREATED_AT = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
UPDATED_AT = CREATED_AT + timedelta(minutes=5)


def _task(
    *,
    task_id: str = 'ext_task_1',
    claim_id: str = 'clm_1',
    status: ExternalTaskOperationStatus = ExternalTaskOperationStatus.PREPARED,
    delivery: ExternalTaskDelivery = ExternalTaskDelivery.NOT_SUBMITTED,
    failure_code: ExternalTaskFailureCode | None = None,
    provider_reference: str | None = None,
    integration_source: IntegrationSource = IntegrationSource.FIXTURE,
    updated_at: datetime = UPDATED_AT,
) -> ExternalTaskRecord:
    """Build a valid task, supplying delivery evidence whenever it claims submission."""

    submitted = delivery is ExternalTaskDelivery.SUBMITTED
    return ExternalTaskRecord(
        task_id=task_id,
        claim_id=claim_id,
        service_identity='vehicle_damage_assessment_routing',
        requested_action='vehicle_damage_assessment',
        integration_source=integration_source,
        status=status,
        delivery=delivery,
        delivery_evidence='transport-receipt-1' if submitted else None,
        failure_code=failure_code,
        provider_reference=provider_reference,
        created_at=CREATED_AT,
        updated_at=updated_at,
    )


def _evidence(
    *,
    evidence_id: str = 'evd_1',
    claim_id: str = 'clm_1',
    source: EvidenceSource = EvidenceSource.EXTERNAL_SYSTEM,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        claim_id=claim_id,
        kind='assessment_report',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        source=source,
        created_at=CREATED_AT,
        updated_at=UPDATED_AT,
    )


def _link(
    *,
    task_id: str = 'ext_task_1',
    evidence_id: str = 'evd_1',
    claim_id: str = 'clm_1',
) -> ExternalTaskEvidenceLink:
    return ExternalTaskEvidenceLink(
        task_id=task_id,
        evidence_id=evidence_id,
        claim_id=claim_id,
        linked_at=UPDATED_AT,
    )


def test_prepared_task_carries_claim_source_status_and_time() -> None:
    task = _task()

    assert task.claim_id == 'clm_1'
    assert task.integration_source is IntegrationSource.FIXTURE
    assert task.status is ExternalTaskOperationStatus.PREPARED
    assert task.created_at == CREATED_AT
    assert task.updated_at == UPDATED_AT


def test_accepted_task_requires_submission_and_no_failure_code() -> None:
    accepted = _task(
        status=ExternalTaskOperationStatus.ACCEPTED,
        delivery=ExternalTaskDelivery.SUBMITTED,
        provider_reference='provider-ref-1',
    )

    assert accepted.provider_reference == 'provider-ref-1'

    with pytest.raises(ValueError, match='must have been submitted'):
        _task(status=ExternalTaskOperationStatus.ACCEPTED)

    with pytest.raises(ValueError, match='cannot hold a failure code'):
        _task(
            status=ExternalTaskOperationStatus.ACCEPTED,
            delivery=ExternalTaskDelivery.SUBMITTED,
            failure_code=ExternalTaskFailureCode.TIMEOUT,
        )


def test_prepared_task_rejects_failure_code_and_submission() -> None:
    with pytest.raises(ValueError, match='cannot hold a failure code'):
        _task(failure_code=ExternalTaskFailureCode.TIMEOUT)

    with pytest.raises(ValueError, match='has not been submitted'):
        _task(delivery=ExternalTaskDelivery.SUBMITTED)


def test_unsubmitted_task_cannot_hold_a_provider_reference() -> None:
    """A reference can only exist once the provider has seen the request."""

    with pytest.raises(ValueError, match='cannot hold a provider reference'):
        _task(provider_reference='provider-ref-1')


def test_failure_status_requires_a_failure_code() -> None:
    with pytest.raises(ValueError, match='requires a failure code'):
        _task(status=ExternalTaskOperationStatus.TERMINAL_FAILURE)


def test_recorded_status_must_match_the_shared_classification() -> None:
    """A service cannot record a submitted timeout as an ordinary retryable failure."""

    with pytest.raises(ValueError, match='is unknown_outcome, not retryable_failure'):
        _task(
            status=ExternalTaskOperationStatus.RETRYABLE_FAILURE,
            delivery=ExternalTaskDelivery.SUBMITTED,
            failure_code=ExternalTaskFailureCode.TIMEOUT,
        )

    unknown = _task(
        status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
        delivery=ExternalTaskDelivery.SUBMITTED,
        failure_code=ExternalTaskFailureCode.TIMEOUT,
    )
    assert unknown.status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME


def test_submission_cannot_be_claimed_without_delivery_evidence() -> None:
    """No adapter records delivery yet, so a caller must not assert it."""

    with pytest.raises(ValueError, match='must name the evidence'):
        ExternalTaskRecord(
            task_id='ext_task_1',
            claim_id='clm_1',
            service_identity='vehicle_damage_assessment_routing',
            requested_action='vehicle_damage_assessment',
            integration_source=IntegrationSource.FIXTURE,
            status=ExternalTaskOperationStatus.RETRYABLE_FAILURE,
            delivery=ExternalTaskDelivery.SUBMITTED,
            failure_code=ExternalTaskFailureCode.UNAVAILABLE,
            created_at=CREATED_AT,
            updated_at=UPDATED_AT,
        )


def test_unsubmitted_task_cannot_hold_delivery_evidence() -> None:
    with pytest.raises(ValueError, match='cannot hold delivery evidence'):
        ExternalTaskRecord(
            task_id='ext_task_1',
            claim_id='clm_1',
            service_identity='vehicle_damage_assessment_routing',
            requested_action='vehicle_damage_assessment',
            integration_source=IntegrationSource.FIXTURE,
            status=ExternalTaskOperationStatus.PREPARED,
            delivery=ExternalTaskDelivery.NOT_SUBMITTED,
            delivery_evidence='transport-receipt-1',
            created_at=CREATED_AT,
            updated_at=UPDATED_AT,
        )


def test_delivery_defaults_to_not_submitted() -> None:
    """The default keeps the documented assessor timeout behaviour unchanged."""

    task = ExternalTaskRecord(
        task_id='ext_task_1',
        claim_id='clm_1',
        service_identity='vehicle_damage_assessment_routing',
        requested_action='vehicle_damage_assessment',
        integration_source=IntegrationSource.FIXTURE,
        status=ExternalTaskOperationStatus.RETRYABLE_FAILURE,
        failure_code=ExternalTaskFailureCode.TIMEOUT,
        created_at=CREATED_AT,
        updated_at=UPDATED_AT,
    )

    assert task.delivery is ExternalTaskDelivery.NOT_SUBMITTED
    assert task.delivery_evidence is None


def test_task_update_cannot_precede_creation() -> None:
    with pytest.raises(ValueError, match='cannot precede creation'):
        _task(updated_at=CREATED_AT - timedelta(seconds=1))


@pytest.mark.parametrize('source', [EvidenceSource.CLAIMANT, EvidenceSource.STAFF])
def test_internally_sourced_evidence_has_no_external_origin(source: EvidenceSource) -> None:
    assert external_task_for_evidence(_evidence(source=source), []) is None


def test_external_evidence_resolves_to_its_task() -> None:
    assert external_task_for_evidence(_evidence(), [_link()]) == 'ext_task_1'


def test_resolver_rejects_a_link_declared_under_another_claim() -> None:
    """Matching on evidence id alone would let claim A borrow claim B's provenance."""

    with pytest.raises(ExternalTaskClaimMismatchError, match='does not match evidence claim'):
        external_task_for_evidence(_evidence(), [_link(claim_id='clm_other')])


def test_resolver_prefers_the_link_that_agrees_on_the_claim() -> None:
    links = [_link(claim_id='clm_other', task_id='ext_task_wrong'), _link()]

    assert external_task_for_evidence(_evidence(), links) == 'ext_task_1'


def test_external_evidence_without_a_link_is_rejected() -> None:
    """Unattributed provider material must not pass as ordinary evidence."""

    with pytest.raises(UntraceableExternalEvidenceError, match='names no originating task'):
        external_task_for_evidence(_evidence(), [_link(evidence_id='evd_other')])


def test_resolver_rejects_two_origins_for_one_record() -> None:
    """Provenance must not depend on which link happens to come first."""

    links = [_link(task_id='ext_task_1'), _link(task_id='ext_task_2')]

    with pytest.raises(ConflictingEvidenceOriginError, match='more than one external task'):
        external_task_for_evidence(_evidence(), links)

    with pytest.raises(ConflictingEvidenceOriginError, match='more than one external task'):
        external_task_for_evidence(_evidence(), list(reversed(links)))


def test_resolver_accepts_a_repeated_link_to_the_same_task() -> None:
    """The blocker is conflicting provenance, not a duplicated identical link."""

    assert external_task_for_evidence(_evidence(), [_link(), _link()]) == 'ext_task_1'


def test_mapping_rejects_two_origins_for_one_record() -> None:
    tasks = [_task(), _task(task_id='ext_task_2')]
    links = [_link(task_id='ext_task_1'), _link(task_id='ext_task_2')]

    with pytest.raises(ConflictingEvidenceOriginError, match='more than one external task'):
        map_external_task_evidence(tasks, links)


def test_mapping_lists_a_repeated_link_once() -> None:
    views = map_external_task_evidence([_task()], [_link(), _link()])

    assert views[0].evidence_ids == ['evd_1']


def test_mapping_groups_evidence_per_task_in_order() -> None:
    tasks = [_task(), _task(task_id='ext_task_2')]
    links = [
        _link(evidence_id='evd_1'),
        _link(task_id='ext_task_2', evidence_id='evd_2'),
        _link(evidence_id='evd_3'),
    ]

    views = map_external_task_evidence(tasks, links)

    assert [view.task.task_id for view in views] == ['ext_task_1', 'ext_task_2']
    assert views[0].evidence_ids == ['evd_1', 'evd_3']
    assert views[1].evidence_ids == ['evd_2']


def test_mapping_ignores_links_for_tasks_outside_the_projection() -> None:
    views = map_external_task_evidence([_task()], [_link(task_id='ext_task_absent')])

    assert views[0].evidence_ids == []


def test_mapping_rejects_a_link_that_crosses_claims() -> None:
    with pytest.raises(ExternalTaskClaimMismatchError, match='does not match task'):
        map_external_task_evidence([_task()], [_link(claim_id='clm_other')])


def test_task_with_no_evidence_projects_an_empty_list() -> None:
    views = map_external_task_evidence([_task()], [])

    assert views[0].evidence_ids == []
