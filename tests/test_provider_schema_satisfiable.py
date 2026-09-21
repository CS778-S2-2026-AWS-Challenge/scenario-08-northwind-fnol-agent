"""Validate complete transport schemas, including closed field variants and media."""

from dataclasses import replace
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from backend.adapters.model_gateway import OpenAICompatibleModelGateway, _google_provider_schema
from backend.domain.agent_v8 import V8TurnProposal
from backend.domain.external_service_registry import capability_context
from backend.services.agent import AgentEvidenceReference
from backend.services.model_request_planner import plan_model_turn
from tests.journey_v8_support import envelope, fact
from tests.test_turn_proposal_v8 import v8_context


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
    raw = envelope(
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
    variants = plan.response_schema['properties']['field_changes']['items']['anyOf']
    expected_keys = {'field_code', 'value', 'reported_text', 'precision'}
    if media:
        expected_keys.add('source_evidence_id')
    assert all(set(item['properties']) == expected_keys for item in variants)
