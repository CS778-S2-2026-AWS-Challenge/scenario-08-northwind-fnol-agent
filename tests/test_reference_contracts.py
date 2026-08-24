from pathlib import Path

from backend.domain.reference_contracts import (
    ExternalServiceScenario,
    FailureOutcomeCode,
    RagSourceInventory,
    RequirementReferenceStatus,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_INVENTORY = ROOT / 'backend' / 'demo_data' / 'knowledge' / 'source-inventory.json'
SERVICE_SCENARIO = (
    ROOT / 'tests' / 'fixtures' / 'journeys' / 'AT-10-claimant-authorised-assessor.json'
)


def load_source_inventory() -> RagSourceInventory:
    return RagSourceInventory.model_validate_json(SOURCE_INVENTORY.read_text(encoding='utf-8'))


def load_service_scenario() -> ExternalServiceScenario:
    return ExternalServiceScenario.model_validate_json(SERVICE_SCENARIO.read_text(encoding='utf-8'))


def test_source_inventory_is_machine_readable_and_preserves_authority_boundaries() -> None:
    inventory = load_source_inventory()

    assert len(inventory.sources) == 3
    assert {source.jurisdiction for source in inventory.sources} == {'NZ'}
    assert all(source.insurer is None for source in inventory.sources)
    assert all(source.northwind_applicability == 'unverified' for source in inventory.sources)
    assert all(source.known_limitations for source in inventory.sources)
    assert inventory.governance.public_sources_are_northwind_policy is False
    assert inventory.governance.unverified_northwind_facts == 'unknown'


def test_source_inventory_retains_metadata_needed_before_chunking() -> None:
    inventory = load_source_inventory()

    for source in inventory.sources:
        assert source.document_id
        assert source.source_uri.startswith('https://')
        assert source.authority.value
        assert source.issuer
        assert source.version
        assert source.retrieved_at
        assert source.visibility == 'public'
        assert source.usage_boundary
        assert source.sections
        assert source.checksum is None


def test_external_service_scenario_covers_consent_lifecycle_and_failures() -> None:
    scenario = load_service_scenario()

    input_support = {field.name: field.current_boundary_support for field in scenario.minimum_input}
    assert scenario.consent.required is True
    assert input_support['claimant_consent_ref'] == 'supported'
    assert {outcome.code for outcome in scenario.failure_outcomes} == set(FailureOutcomeCode)
    assert {'consent_required', 'authorised', 'submitting', 'queued', 'assigned', 'failed'} == {
        status.status for status in scenario.status_lifecycle
    }
    assert scenario.idempotency.automatic_retry_limit == 'not_yet_approved'


def test_external_service_scenario_does_not_claim_unverified_implementation() -> None:
    scenario = load_service_scenario()

    assert scenario.implementation_status == 'fixture_implemented'
    assert scenario.participant.provider_identity == 'unverified'
    assert scenario.claim_state_effects.failure_may_change == []
    assert {'coverage', 'fraud signal', 'claim approval or rejection'} <= set(
        scenario.claim_state_effects.must_not_change
    )
    assert any(
        reference.reference == 'Challenge Key Feature 2'
        and reference.status is RequirementReferenceStatus.UNVERIFIED_EXTERNAL_BRIEF
        for reference in scenario.requirement_references
    )
