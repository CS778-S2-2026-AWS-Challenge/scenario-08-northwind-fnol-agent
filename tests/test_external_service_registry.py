import pytest

from backend.domain.external_service_registry import (
    LIFECYCLE_REGISTRY,
    REGISTRY_ENTRIES,
    REGISTRY_VERSION,
    ExternalCapabilityProvenance,
    ExternalLifecycleStatus,
    InvalidExternalLifecycleTransition,
    assert_lifecycle_transition,
    assert_persisted_operation_transition,
    lifecycle_definition,
    projection_metadata,
    service_registry_entry,
)


def test_registry_has_one_complete_definition_for_each_status() -> None:
    statuses = [definition.status for definition in LIFECYCLE_REGISTRY]

    assert REGISTRY_VERSION == 'external-service-lifecycle.v1'
    assert len(statuses) == len(set(statuses))
    assert set(statuses) == set(ExternalLifecycleStatus)
    assert all(definition.claimant_meaning for definition in LIFECYCLE_REGISTRY)
    assert all(definition.staff_meaning for definition in LIFECYCLE_REGISTRY)
    assert all(definition.agent_meaning for definition in LIFECYCLE_REGISTRY)


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
