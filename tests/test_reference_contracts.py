import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.domain.reference_contracts import (
    ExternalServiceScenario,
    FailureOutcomeCode,
    RagSourceInventory,
    RequirementReferenceStatus,
    ServiceLifecycleStatus,
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


def test_source_inventory_uses_explicit_printed_and_pdf_page_locators() -> None:
    inventory = load_source_inventory()
    icnz_source = next(
        source
        for source in inventory.sources
        if source.document_id == 'src_icnz_fair_insurance_code_2020'
    )

    assert icnz_source.sections[0].printed_pages == [3, 4]
    assert icnz_source.sections[0].pdf_page_indices == [4, 5]
    assert icnz_source.sections[1].printed_pages == [10]
    assert icnz_source.sections[1].pdf_page_indices == [11]

    payload = json.loads(SOURCE_INVENTORY.read_text(encoding='utf-8'))
    first_icnz_section = payload['sources'][1]['sections'][0]
    first_icnz_section['pdf_page_indices'] = [4]
    with pytest.raises(ValidationError, match='map one to one'):
        RagSourceInventory.model_validate(payload)


def test_external_service_scenario_covers_consent_lifecycle_and_failures() -> None:
    scenario = load_service_scenario()

    input_support = {field.name: field.current_boundary_support for field in scenario.minimum_input}
    assert scenario.consent.required is True
    assert input_support['claimant_consent_ref'] == 'gap_for_issue_252'
    assert {outcome.code for outcome in scenario.failure_outcomes} == set(FailureOutcomeCode)
    assert {
        'consent_required',
        'authorised',
        'submitting',
        'queued',
        'assigned',
        'retryable_failure',
        'terminal_failure',
    } == {status.status for status in scenario.status_lifecycle}
    terminality = {status.status: status.terminal for status in scenario.status_lifecycle}
    assert terminality[ServiceLifecycleStatus.RETRYABLE_FAILURE] is False
    assert terminality[ServiceLifecycleStatus.TERMINAL_FAILURE] is True
    outcomes = {outcome.code: outcome for outcome in scenario.failure_outcomes}
    assert (
        outcomes[FailureOutcomeCode.TIMEOUT].lifecycle_status
        is ServiceLifecycleStatus.RETRYABLE_FAILURE
    )
    assert (
        outcomes[FailureOutcomeCode.UNAVAILABLE].lifecycle_status
        is ServiceLifecycleStatus.RETRYABLE_FAILURE
    )
    assert (
        outcomes[FailureOutcomeCode.ACCESS_DENIED].lifecycle_status
        is ServiceLifecycleStatus.TERMINAL_FAILURE
    )
    assert (
        outcomes[FailureOutcomeCode.MALFORMED].lifecycle_status
        is ServiceLifecycleStatus.TERMINAL_FAILURE
    )
    assert scenario.idempotency.automatic_retry_limit == 'not_yet_approved'


def test_external_service_scenario_rejects_retryable_terminal_failure() -> None:
    payload = json.loads(SERVICE_SCENARIO.read_text(encoding='utf-8'))
    payload['failure_outcomes'][0]['lifecycle_status'] = 'terminal_failure'

    with pytest.raises(ValidationError, match='timeout must use retryable_failure'):
        ExternalServiceScenario.model_validate(payload)


def test_external_service_scenario_does_not_promise_unapproved_cancellation() -> None:
    scenario = load_service_scenario()

    assert (
        scenario.consent.withdrawal_boundary.provider_cancellation_status
        == 'requires_separately_approved_capability'
    )
    assert (
        'does not promise provider cancellation or recall'
        in scenario.consent.withdrawal_boundary.after_provider_acceptance
    )


def test_external_service_scenario_does_not_claim_unverified_implementation() -> None:
    scenario = load_service_scenario()

    assert scenario.implementation_status == 'contract_only'
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
