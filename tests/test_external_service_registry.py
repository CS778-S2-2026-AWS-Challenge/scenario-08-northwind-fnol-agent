import pytest

from backend.domain.external_service_registry import (
    LIFECYCLE_REGISTRY,
    REGISTRY_ENTRIES,
    REGISTRY_VERSION,
    ExternalCapabilityProvenance,
    ExternalLifecycleStatus,
    ExternalTaskResultVerification,
    InvalidExternalLifecycleTransition,
    assert_lifecycle_transition,
    assert_persisted_operation_transition,
    build_lifecycle_projection,
    lifecycle_definition,
    project_operation_status,
    projection_metadata,
    service_registry_entry,
)
from backend.domain.external_services import (
    ASSESSOR_SERVICE_IDENTITY,
)
from backend.domain.external_services import (
    ExternalTaskResultVerification as PersistedResultVerification,
)


def test_registry_has_one_complete_definition_for_each_status() -> None:
    statuses = [definition.status for definition in LIFECYCLE_REGISTRY]

    assert REGISTRY_VERSION == 'external-service-lifecycle.v1'
    assert len(statuses) == len(set(statuses))
    assert set(statuses) == set(ExternalLifecycleStatus)
    assert all(definition.claimant_meaning for definition in LIFECYCLE_REGISTRY)
    assert all(definition.staff_meaning for definition in LIFECYCLE_REGISTRY)
    assert all(definition.agent_meaning for definition in LIFECYCLE_REGISTRY)
    assert PersistedResultVerification is ExternalTaskResultVerification


def test_unknown_outcome_requires_reconciliation_and_cannot_imply_completion() -> None:
    definition = lifecycle_definition(ExternalLifecycleStatus.UNKNOWN_OUTCOME)

    assert definition.requires_reconciliation is True
    assert definition.implies_completion is False
    assert definition.recovery == 'Reconcile before retry.'


@pytest.mark.parametrize(
    ('current', 'proposed'),
    [
        (ExternalLifecycleStatus.PREPARED, ExternalLifecycleStatus.SUBMITTING),
        (ExternalLifecycleStatus.SUBMITTING, ExternalLifecycleStatus.ACCEPTED),
        (ExternalLifecycleStatus.ACCEPTED, ExternalLifecycleStatus.ASSIGNED),
        (ExternalLifecycleStatus.UNKNOWN_OUTCOME, ExternalLifecycleStatus.ACCEPTED),
        (ExternalLifecycleStatus.RESULT_RECEIVED, ExternalLifecycleStatus.RESULT_VERIFIED),
    ],
)
def test_registry_allows_documented_transitions(
    current: ExternalLifecycleStatus,
    proposed: ExternalLifecycleStatus,
) -> None:
    assert_lifecycle_transition(current, proposed)


def test_registry_rejects_unsafe_transition_from_unknown_outcome() -> None:
    with pytest.raises(InvalidExternalLifecycleTransition, match='unknown_outcome'):
        assert_lifecycle_transition(
            ExternalLifecycleStatus.UNKNOWN_OUTCOME,
            ExternalLifecycleStatus.RETRYABLE_FAILURE,
        )


def test_registry_rejects_unknown_status() -> None:
    with pytest.raises(InvalidExternalLifecycleTransition, match='Unknown lifecycle status'):
        lifecycle_definition('completed')


def test_registered_paths_preserve_manual_and_simulated_boundaries() -> None:
    entries = {entry.service_identity: entry for entry in REGISTRY_ENTRIES}

    assert entries['vehicle_damage_assessment_routing'].provenance is (
        ExternalCapabilityProvenance.SIMULATED
    )
    assert entries['repairer_information_or_link'].provenance is ExternalCapabilityProvenance.MANUAL
    assert entries['repairer_information_or_link'].uses_external_task is False
    assert entries['police_105_reporting_guidance'].catalogue_reference == 'P3-NZP-REPORT'
    assert entries['police_105_reporting_guidance'].uses_external_task is False
    assert entries['police_traffic_crash_report_guidance'].catalogue_reference == 'P3-NZP-TCR'
    assert entries['police_traffic_crash_report_guidance'].uses_external_task is False
    assert 'Simulation-only' in entries['vehicle_damage_assessment_routing'].limitation


def test_unknown_service_has_no_implicit_capability() -> None:
    with pytest.raises(KeyError, match='No canonical external-service entry'):
        service_registry_entry('unregistered-provider')


@pytest.mark.parametrize(
    ('current', 'proposed'),
    [
        (ExternalLifecycleStatus.PREPARED, ExternalLifecycleStatus.ACCEPTED),
        (ExternalLifecycleStatus.PREPARED, ExternalLifecycleStatus.RETRYABLE_FAILURE),
        (ExternalLifecycleStatus.RETRYABLE_FAILURE, ExternalLifecycleStatus.ACCEPTED),
    ],
)
def test_persisted_transition_validates_transient_submission_stage(
    current: ExternalLifecycleStatus, proposed: ExternalLifecycleStatus
) -> None:
    assert_persisted_operation_transition(current.value, proposed.value)


def test_projection_metadata_is_complete_for_persisted_statuses() -> None:
    for status in (
        ExternalLifecycleStatus.PREPARED,
        ExternalLifecycleStatus.ACCEPTED,
        ExternalLifecycleStatus.RETRYABLE_FAILURE,
        ExternalLifecycleStatus.TERMINAL_FAILURE,
        ExternalLifecycleStatus.UNKNOWN_OUTCOME,
    ):
        metadata = projection_metadata(status)
        assert metadata.label and metadata.pending_owner and metadata.next_action


def test_lifecycle_projection_carries_registry_and_role_safe_contract() -> None:
    projection = build_lifecycle_projection(
        service_identity=ASSESSOR_SERVICE_IDENTITY,
        operation_status=ExternalLifecycleStatus.ACCEPTED,
        result_status=ExternalLifecycleStatus.RESULT_RECEIVED,
        result_verification=ExternalTaskResultVerification.UNVERIFIED,
    )
    assert projection.registry_version == REGISTRY_VERSION
    assert projection.operation_status is ExternalLifecycleStatus.ACCEPTED
    assert projection.result_status is ExternalLifecycleStatus.RESULT_RECEIVED
    assert projection.result_verification is ExternalTaskResultVerification.UNVERIFIED
    assert projection.state_invariants
    assert projection.allowed_next


def test_verified_result_replaces_acknowledgement_guidance_without_implying_writeback() -> None:
    projection = build_lifecycle_projection(
        service_identity=ASSESSOR_SERVICE_IDENTITY,
        operation_status=ExternalLifecycleStatus.ACCEPTED,
        result_status=ExternalLifecycleStatus.RESULT_VERIFIED,
        result_verification=ExternalTaskResultVerification.CONSISTENT,
    )

    assert projection.status_label == 'Result checked'
    assert projection.verification_state == 'consistent'
    assert projection.pending_owner == 'claims_professional'
    assert 'authorised Claim decision' in projection.next_action
    assert projection.allowed_next == (ExternalLifecycleStatus.WRITTEN_BACK,)


def test_late_result_does_not_override_unknown_outcome_reconciliation() -> None:
    projection = build_lifecycle_projection(
        service_identity=ASSESSOR_SERVICE_IDENTITY,
        operation_status=ExternalLifecycleStatus.UNKNOWN_OUTCOME,
        result_status=ExternalLifecycleStatus.RESULT_VERIFIED,
        result_verification=ExternalTaskResultVerification.CONSISTENT,
    )

    assert projection.status_label == 'Outcome not confirmed'
    assert projection.verification_state == 'reconciliation_required'
    assert projection.pending_owner == 'claims_professional'
    assert projection.requires_reconciliation is True
    assert projection.needs_attention is True


@pytest.mark.parametrize(
    'status', [ExternalLifecycleStatus.QUEUED, ExternalLifecycleStatus.ASSIGNED]
)
def test_assessor_progress_uses_only_matching_provider_reference(
    status: ExternalLifecycleStatus,
) -> None:
    assert (
        project_operation_status(
            service_identity=ASSESSOR_SERVICE_IDENTITY,
            operation_status=ExternalLifecycleStatus.ACCEPTED,
            provider_reference='provider-1',
            service_progress_status=status,
            service_progress_reference='provider-1',
        )
        is status
    )

    assert (
        project_operation_status(
            service_identity=ASSESSOR_SERVICE_IDENTITY,
            operation_status=ExternalLifecycleStatus.ACCEPTED,
            provider_reference='provider-1',
            service_progress_status=status,
            service_progress_reference='provider-2',
        )
        is ExternalLifecycleStatus.ACCEPTED
    )


@pytest.mark.parametrize(
    'status',
    [
        ExternalLifecycleStatus.PREPARED,
        ExternalLifecycleStatus.ACCEPTED,
        ExternalLifecycleStatus.QUEUED,
        ExternalLifecycleStatus.ASSIGNED,
        ExternalLifecycleStatus.RETRYABLE_FAILURE,
        ExternalLifecycleStatus.TERMINAL_FAILURE,
        ExternalLifecycleStatus.UNKNOWN_OUTCOME,
    ],
)
def test_assessor_every_advertised_projectable_status_builds(
    status: ExternalLifecycleStatus,
) -> None:
    entry = service_registry_entry(ASSESSOR_SERVICE_IDENTITY)

    assert status in entry.projectable_statuses
    assert (
        build_lifecycle_projection(
            service_identity=ASSESSOR_SERVICE_IDENTITY,
            operation_status=status,
        ).operation_status
        is status
    )


def test_assessor_declares_submitting_as_transient_not_projectable() -> None:
    entry = service_registry_entry(ASSESSOR_SERVICE_IDENTITY)

    assert entry.transient_statuses == (ExternalLifecycleStatus.SUBMITTING,)
    assert ExternalLifecycleStatus.SUBMITTING not in entry.projectable_statuses
    with pytest.raises(InvalidExternalLifecycleTransition, match='not projectable'):
        build_lifecycle_projection(
            service_identity=ASSESSOR_SERVICE_IDENTITY,
            operation_status=ExternalLifecycleStatus.SUBMITTING,
        )


@pytest.mark.parametrize(
    ('operation_status', 'result_status', 'verification'),
    [
        (operation_status, result_status, verification)
        for operation_status in (
            ExternalLifecycleStatus.ACCEPTED,
            ExternalLifecycleStatus.UNKNOWN_OUTCOME,
        )
        for result_status, verification in (
            (ExternalLifecycleStatus.RESULT_RECEIVED, ExternalTaskResultVerification.UNVERIFIED),
            (ExternalLifecycleStatus.RESULT_VERIFIED, ExternalTaskResultVerification.CONSISTENT),
            (ExternalLifecycleStatus.RESULT_VERIFIED, ExternalTaskResultVerification.INCONSISTENT),
            (
                ExternalLifecycleStatus.RESULT_VERIFIED,
                ExternalTaskResultVerification.REVIEW_REQUIRED,
            ),
        )
    ],
)
def test_projection_preserves_every_result_verification_outcome(
    operation_status: ExternalLifecycleStatus,
    result_status: ExternalLifecycleStatus,
    verification: ExternalTaskResultVerification,
) -> None:
    projection = build_lifecycle_projection(
        service_identity=ASSESSOR_SERVICE_IDENTITY,
        operation_status=operation_status,
        result_status=result_status,
        result_verification=verification,
    )

    assert projection.result_status is result_status
    assert projection.result_verification is verification


@pytest.mark.parametrize(
    ('operation_status', 'result_status', 'verification'),
    [
        (
            ExternalLifecycleStatus.PREPARED,
            ExternalLifecycleStatus.RESULT_RECEIVED,
            ExternalTaskResultVerification.UNVERIFIED,
        ),
        (
            ExternalLifecycleStatus.ACCEPTED,
            ExternalLifecycleStatus.WRITTEN_BACK,
            ExternalTaskResultVerification.CONSISTENT,
        ),
        (
            ExternalLifecycleStatus.ACCEPTED,
            ExternalLifecycleStatus.RESULT_RECEIVED,
            ExternalTaskResultVerification.CONSISTENT,
        ),
        (
            ExternalLifecycleStatus.ACCEPTED,
            ExternalLifecycleStatus.RESULT_VERIFIED,
            ExternalTaskResultVerification.UNVERIFIED,
        ),
        (
            ExternalLifecycleStatus.ACCEPTED,
            ExternalLifecycleStatus.ACCEPTED,
            ExternalTaskResultVerification.UNVERIFIED,
        ),
    ],
)
def test_projection_rejects_illegal_operation_result_coordinates(
    operation_status: ExternalLifecycleStatus,
    result_status: ExternalLifecycleStatus,
    verification: ExternalTaskResultVerification,
) -> None:
    with pytest.raises(InvalidExternalLifecycleTransition):
        build_lifecycle_projection(
            service_identity=ASSESSOR_SERVICE_IDENTITY,
            operation_status=operation_status,
            result_status=result_status,
            result_verification=verification,
        )


def test_projection_rejects_verification_without_result_stage() -> None:
    with pytest.raises(InvalidExternalLifecycleTransition, match='requires a result'):
        build_lifecycle_projection(
            service_identity=ASSESSOR_SERVICE_IDENTITY,
            operation_status=ExternalLifecycleStatus.ACCEPTED,
            result_verification=ExternalTaskResultVerification.UNVERIFIED,
        )


def test_projection_rejects_result_stage_without_verification() -> None:
    with pytest.raises(InvalidExternalLifecycleTransition, match='requires a verification'):
        build_lifecycle_projection(
            service_identity=ASSESSOR_SERVICE_IDENTITY,
            operation_status=ExternalLifecycleStatus.ACCEPTED,
            result_status=ExternalLifecycleStatus.RESULT_RECEIVED,
        )


def test_prepared_state_does_not_claim_reserved_operation_identity() -> None:
    prepared = lifecycle_definition(ExternalLifecycleStatus.PREPARED)

    assert 'operation_id' not in prepared.state_invariants
    assert 'dispatch_reserved_at' not in prepared.state_invariants
    assert {'operation_id', 'idempotency_key', 'dispatch_reserved_at'} <= set(
        prepared.transition_preconditions
    )


def test_lifecycle_projection_rejects_unknown_or_unsupported_service_state() -> None:
    with pytest.raises(KeyError, match='No canonical external-service entry'):
        build_lifecycle_projection(service_identity='fake', operation_status='accepted')
    with pytest.raises(InvalidExternalLifecycleTransition, match='not projectable'):
        build_lifecycle_projection(
            service_identity='repairer_information_or_link',
            operation_status=ExternalLifecycleStatus.PREPARED,
        )
