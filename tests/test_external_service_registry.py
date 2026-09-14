import pytest

from backend.domain.external_service_registry import (
    LIFECYCLE_REGISTRY,
    REGISTRY_ENTRIES,
    REGISTRY_VERSION,
    ExternalCapabilityProvenance,
    ExternalLifecycleStatus,
    InvalidExternalLifecycleTransition,
    assert_lifecycle_transition,
    lifecycle_definition,
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
    assert (
        entries['police_guidance_or_official_link'].provenance
        is ExternalCapabilityProvenance.MANUAL
    )
    assert 'Simulation-only' in entries['vehicle_damage_assessment_routing'].limitation


def test_unknown_service_has_no_implicit_capability() -> None:
    with pytest.raises(KeyError, match='No canonical external-service entry'):
        service_registry_entry('unregistered-provider')
