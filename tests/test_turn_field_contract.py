from datetime import UTC, datetime

import pytest

from backend.domain.branch_registry import BranchRuleEvaluator
from backend.domain.model_gateway import ModelGatewayError, ModelProposedFormChange
from backend.domain.models import (
    Channel,
    CustomerNextStep,
    ResponsibleParty,
    WorkingClaim,
)
from backend.domain.turn_field_contract import TurnFieldContractViolation
from backend.services.model_agent import _merge_field_contract_repair
from backend.services.turn_field_contract import (
    bind_provider_schema,
    compile_turn_field_contract,
    validate_field_changes,
)

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)


def _home_claim() -> WorkingClaim:
    return WorkingClaim(
        claim_id='clm_field_contract',
        customer_id='cus_field_contract',
        revision=3,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='home',
        active_session_id='ses_field_contract',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def _response_schema() -> dict[str, object]:
    return {
        'type': 'object',
        'properties': {
            'field_changes': {
                'type': 'array',
                'maxItems': 50,
                'items': {
                    'type': 'object',
                    'properties': {
                        'field_code': {'type': 'string'},
                        'value': {},
                    },
                    'required': ['field_code', 'value'],
                    'additionalProperties': False,
                },
            }
        },
    }


def test_one_turn_contract_drives_all_registered_value_shapes_and_schema() -> None:
    evaluation = BranchRuleEvaluator().evaluate(_home_claim(), recomputation_reason='test')

    contract = compile_turn_field_contract(evaluation)
    schema = bind_provider_schema(_response_schema(), contract)

    assert contract.branch_evaluation_revision == 3
    assert {item.value_type for item in contract.fields} == {
        'boolean',
        'enum',
        'location',
        'temporal',
        'text',
        'text_list',
    }
    assert 'claimant.client_number' not in contract.by_code
    variants = schema['properties']['field_changes']['items']['oneOf']  # type: ignore[index]
    product_family = next(
        item
        for item in variants
        if item['properties']['field_code']['const'] == 'claim.product_family'
    )
    assert product_family['properties']['value']['enum'] == ['contents', 'home', 'motor']
    assert schema['properties']['field_changes']['maxItems'] == len(contract.fields)  # type: ignore[index]


def test_runtime_normalises_only_unambiguous_values_and_rejects_unknown_fields() -> None:
    evaluation = BranchRuleEvaluator().evaluate(_home_claim(), recomputation_reason='test')
    contract = compile_turn_field_contract(evaluation)
    changes = [
        ModelProposedFormChange(field_code='incident.injury_or_danger', value=' no '),
        ModelProposedFormChange(field_code='claim.product_family', value='HOME'),
        ModelProposedFormChange(field_code='incident.description', value='  Burst pipe  '),
        ModelProposedFormChange(field_code='incident.location', value='  Kitchen  '),
        ModelProposedFormChange(
            field_code='property.affected_areas',
            value=[' Kitchen ', ' Hall '],
        ),
        ModelProposedFormChange(field_code='incident.occurred_at', value='2026-09-18T08:30:00Z'),
    ]

    values = {item.field_code: item.value for item in validate_field_changes(contract, changes)}

    assert values == {
        'incident.injury_or_danger': False,
        'claim.product_family': 'home',
        'incident.description': 'Burst pipe',
        'incident.location': 'Kitchen',
        'property.affected_areas': ['Kitchen', 'Hall'],
        'incident.occurred_at': '2026-09-18T08:30:00Z',
    }
    with pytest.raises(TurnFieldContractViolation):
        validate_field_changes(
            contract,
            [ModelProposedFormChange(field_code='claimant.client_number', value='hidden')],
        )


def test_repair_can_replace_only_the_invalid_field_changes() -> None:
    original: dict[str, object] = {
        'action_code': 'conversation.answer',
        'customer_response': 'Original governed response.',
        'field_changes': [
            {'field_code': 'incident.description', 'value': 'Rear-end collision'},
            {'field_code': 'incident.injury_or_danger', 'value': 'maybe'},
        ],
        'service_offer_ids': ['vehicle-damage-assessment'],
    }
    repaired: dict[str, object] = {
        'action_code': 'claim.create',
        'customer_response': 'Attempted rewrite.',
        'field_changes': [
            {'field_code': 'incident.injury_or_danger', 'value': False},
        ],
        'service_offer_ids': [],
    }

    merged = _merge_field_contract_repair(
        original,
        repaired,
        {'incident.injury_or_danger'},
    )

    assert merged['action_code'] == 'conversation.answer'
    assert merged['customer_response'] == 'Original governed response.'
    assert merged['service_offer_ids'] == ['vehicle-damage-assessment']
    assert merged['field_changes'] == [
        {'field_code': 'incident.description', 'value': 'Rear-end collision'},
        {'field_code': 'incident.injury_or_danger', 'value': False},
    ]
    with pytest.raises(ModelGatewayError):
        _merge_field_contract_repair(
            original,
            {'field_changes': [{'field_code': 'incident.description', 'value': 'changed'}]},
            {'incident.injury_or_danger'},
        )
