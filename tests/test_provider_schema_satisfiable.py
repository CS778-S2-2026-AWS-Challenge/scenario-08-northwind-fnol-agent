"""Validate complete transport schemas, including closed field variants and media."""

from dataclasses import replace
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from backend.adapters.model_gateway import OpenAICompatibleModelGateway, _google_provider_schema
from backend.domain.agent_v8 import V8FieldChange, V8TurnProposal
from backend.domain.evidence import REGISTERED_EVIDENCE_KINDS
from backend.domain.external_service_registry import capability_context
from backend.domain.turn_field_contract import TurnFieldContractViolation
from backend.services.agent import AgentEvidenceReference
from backend.services.model_request_planner import plan_model_turn
from backend.services.prompt_composer import load_response_schema
from backend.services.turn_field_contract import validate_field_changes
from tests.journey_v8_support import envelope, fact
from tests.test_turn_proposal_v8 import v8_context


def _wire_envelope(**kwargs: Any) -> dict[str, Any]:
    """Return a provider reply that fills every key the strict wire schemas require."""

    return envelope(**kwargs) | {
        'northwind_questions': [],
        'turn_ending': 'question',
        'scope_note': None,
        'cited_sources': [],
    }


@pytest.mark.parametrize('family', ['motor', 'home', 'contents'])
@pytest.mark.parametrize('media', [False, True])
def test_full_schema_is_satisfiable_after_both_provider_translations(
    family: str, media: bool
) -> None:
    context = v8_context('A synthetic incident happened yesterday in Wellington.')
    assert context.runtime_policy is not None
    claim = context.claim.model_copy(update={'incident_type': family})
    context = replace(
        context,
        claim=claim,
        branch_evaluation=context.runtime_policy.branch_evaluator().evaluate(
            claim, latest_message=context.message_text, recomputation_reason='schema_acceptance'
        ),
        external_services=capability_context(family),
        evidence=(AgentEvidenceReference('evd_schema', 'image/png'),) if media else (),
        evidence_refs=['evd_schema'] if media else [],
    )
    plan = plan_model_turn(context)
    assert plan is not None
    raw = _wire_envelope(
        fields=[
            fact('incident.location', 'Wellington', 'in Wellington'),
            fact('incident.description', 'A synthetic incident', 'A synthetic incident'),
        ]
    )
    if media:
        for change in raw['field_changes']:
            change['source_evidence_id'] = 'evd_schema'
    V8TurnProposal.model_validate(raw)
    schemas = (
        OpenAICompatibleModelGateway._strict_response_schema(plan.response_schema),
        _google_provider_schema(plan.response_schema),
    )
    for schema in schemas:
        schema = cast(dict[str, Any], schema)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(raw)
    # One fixed answer-sheet row (#1159); Runtime checks values against the turn contract.
    item = plan.response_schema['properties']['field_changes']['items']
    expected_keys = {
        'field_code',
        'value',
        'reported_text',
        'precision',
        'disposition',
        'service_identity',
    }
    if media:
        expected_keys.add('source_evidence_id')
    assert set(item['properties']) == expected_keys
    google_fields = cast(dict[str, Any], schemas[1])['properties']['field_changes']['items']
    assert 'anyOf' not in google_fields
    assert set(google_fields['required']) == expected_keys
    assert set(google_fields['properties']) == expected_keys


def test_google_wire_value_union_does_not_replace_runtime_field_type_authority() -> None:
    plan = plan_model_turn(v8_context('My car cannot be driven.'))
    assert plan is not None
    assert plan.field_contract is not None
    invalid = _wire_envelope(fields=[fact('vehicle.drivable', 'home', 'My car')])
    google = cast(dict[str, Any], _google_provider_schema(plan.response_schema))
    Draft202012Validator(google).validate(invalid)
    strict = cast(
        dict[str, Any], OpenAICompatibleModelGateway._strict_response_schema(plan.response_schema)
    )
    # The fixed sheet accepts any registered value shape on the wire; the turn
    # contract in Runtime is the type authority.
    assert Draft202012Validator(strict).is_valid(invalid)
    change = V8FieldChange.model_validate(invalid['field_changes'][0])
    with pytest.raises(TurnFieldContractViolation):
        validate_field_changes(plan.field_contract, [change])
    rejected: list[Any] = []
    assert (
        validate_field_changes(
            plan.field_contract, [change], rejected_bounds=rejected, reject_invalid=True
        )
        == []
    )
    assert [item.field_code for item in rejected] == ['vehicle.drivable']


def test_the_model_chooses_document_kinds_only_from_the_registered_kinds() -> None:
    properties = cast(dict[str, Any], load_response_schema('claimant.turn.v1')['properties'])

    for key in ('document_requests', 'evidence_interpretations'):
        document_kind = properties[key]['items']['properties']['document_kind']
        assert document_kind == {'enum': sorted(REGISTERED_EVIDENCE_KINDS), 'type': 'string'}
