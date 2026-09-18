"""Compile and enforce one field contract for a complete model-backed turn."""

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from backend.domain.branch_registry import (
    BranchRegistrySnapshot,
    build_default_registry,
)
from backend.domain.models import BranchEvaluationResult, FieldSelectionState, TemporalFactValue
from backend.domain.turn_field_contract import (
    TurnFieldContract,
    TurnFieldContractViolation,
    TurnFieldDefinition,
    TurnFieldViolation,
)


def compile_turn_field_contract(
    evaluation: BranchEvaluationResult,
    registry: BranchRegistrySnapshot | None = None,
) -> TurnFieldContract:
    active_registry = registry or build_default_registry()
    if evaluation.field_registry_version != active_registry.field_registry_version:
        raise ValueError('The branch evaluation and field registry versions do not match.')
    if evaluation.branch_rules_version != active_registry.branch_rules_version:
        raise ValueError('The branch evaluation and branch-rule versions do not match.')

    definitions = active_registry.field_by_code
    fields: list[TurnFieldDefinition] = []
    for selection in sorted(evaluation.field_selection, key=lambda item: item.field_code):
        definition = definitions.get(selection.field_code)
        if (
            definition is None
            or definition.system_owned
            or not definition.claimant_visible
            or selection.selection_state
            in {FieldSelectionState.INACTIVE, FieldSelectionState.SYSTEM_OWNED}
        ):
            continue
        fields.append(
            TurnFieldDefinition(
                field_code=definition.code,
                value_type=definition.value_type,
                allowed_values=sorted(definition.allowed_values),
                selection_state=selection.selection_state,
                value_state=selection.value_state,
            )
        )

    identity = {
        'registry_version': active_registry.field_registry_version,
        'branch_rules_version': active_registry.branch_rules_version,
        'branch_evaluation_revision': evaluation.evaluated_against_claim_revision,
        'fields': [item.model_dump(mode='json') for item in fields],
    }
    digest = hashlib.sha256(
        json.dumps(identity, separators=(',', ':'), sort_keys=True).encode()
    ).hexdigest()[:20]
    return TurnFieldContract(
        contract_id=f'tfc_{digest}',
        registry_version=active_registry.field_registry_version,
        branch_rules_version=active_registry.branch_rules_version,
        branch_evaluation_revision=evaluation.evaluated_against_claim_revision,
        fields=fields,
    )


def _value_schema(field: TurnFieldDefinition) -> dict[str, object]:
    if field.value_type == 'boolean':
        return {'type': 'boolean'}
    if field.value_type == 'enum':
        return {'type': 'string', 'enum': field.allowed_values}
    if field.value_type == 'text_list':
        return {
            'type': 'array',
            'minItems': 1,
            'maxItems': 50,
            'items': {'type': 'string', 'minLength': 1},
        }
    # String is the narrow common representation accepted by the registry for
    # text, location, and temporal facts. Structured forms remain Runtime-valid
    # but are not requested from providers until their exact schema is registered.
    return {'type': 'string', 'minLength': 1}


def bind_provider_schema(
    schema: dict[str, object],
    contract: TurnFieldContract,
) -> dict[str, object]:
    bound = deepcopy(schema)
    properties = bound.get('properties')
    if not isinstance(properties, dict):
        raise ValueError('The response schema has no properties object.')
    field_changes = properties.get('field_changes')
    if not isinstance(field_changes, dict):
        return bound
    base_item = field_changes.get('items')
    if not isinstance(base_item, dict):
        raise ValueError('The field-change schema has no item contract.')
    base_properties = base_item.get('properties')
    if not isinstance(base_properties, dict):
        raise ValueError('The field-change item has no properties contract.')

    grouped_fields: dict[str, tuple[dict[str, object], list[str]]] = {}
    for field in contract.fields:
        value_schema = _value_schema(field)
        schema_key = json.dumps(value_schema, separators=(',', ':'), sort_keys=True)
        if schema_key not in grouped_fields:
            grouped_fields[schema_key] = (value_schema, [])
        grouped_fields[schema_key][1].append(field.field_code)

    variants: list[dict[str, object]] = []
    for value_schema, field_codes in grouped_fields.values():
        field_code_schema: dict[str, object] = {'type': 'string'}
        if len(field_codes) == 1:
            field_code_schema['const'] = field_codes[0]
        else:
            field_code_schema['enum'] = sorted(field_codes)
        variants.append(
            {
                'type': 'object',
                'properties': {
                    'field_code': field_code_schema,
                    'value': value_schema,
                },
                'required': ['field_code', 'value'],
            }
        )
    if variants:
        field_changes['items'] = {**base_item, 'oneOf': variants}
        field_changes['maxItems'] = min(
            int(field_changes.get('maxItems', 50)),
            len(contract.fields),
        )
    else:
        field_changes['items'] = base_item
        field_changes['maxItems'] = 0
    return bound


def normalise_field_value(field: TurnFieldDefinition, value: Any) -> Any:
    if field.value_type == 'boolean' and isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {'true', 'yes', '1'}:
            return True
        if normalized in {'false', 'no', '0'}:
            return False
    if field.value_type == 'enum' and isinstance(value, str):
        normalized = value.strip().casefold()
        matches = [item for item in field.allowed_values if item.casefold() == normalized]
        return matches[0] if len(matches) == 1 else value
    if field.value_type in {'text', 'location', 'temporal'} and isinstance(value, str):
        return value.strip()
    if field.value_type == 'text_list' and isinstance(value, list):
        return [item.strip() if isinstance(item, str) else item for item in value]
    return value


def _field_value_is_valid(field: TurnFieldDefinition, value: Any) -> bool:
    if field.value_type == 'text':
        return isinstance(value, str) and bool(value.strip())
    if field.value_type == 'boolean':
        return isinstance(value, bool)
    if field.value_type == 'enum':
        return isinstance(value, str) and value in field.allowed_values
    if field.value_type == 'location':
        return (isinstance(value, str) and bool(value.strip())) or (
            isinstance(value, Mapping) and bool(value)
        )
    if field.value_type == 'text_list':
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and bool(item.strip()) for item in value)
        )
    if field.value_type == 'temporal':
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, Mapping):
            try:
                TemporalFactValue.model_validate(value)
            except ValueError:
                return False
            return True
    return False


def validate_field_changes(
    contract: TurnFieldContract,
    changes: list[Any],
) -> list[Any]:
    allowed = contract.by_code
    validated: list[Any] = []
    violations: list[TurnFieldViolation] = []
    for change in changes:
        field_code = str(change.field_code)
        field = allowed.get(field_code)
        if field is None:
            violations.append(
                TurnFieldViolation(
                    field_code=field_code,
                    expected_value_type='not_allowed',
                    reason_code='field_not_allowed',
                )
            )
            continue
        value = normalise_field_value(field, change.value)
        if not _field_value_is_valid(field, value):
            violations.append(
                TurnFieldViolation(
                    field_code=field_code,
                    expected_value_type=field.value_type,
                    reason_code='invalid_value',
                )
            )
            continue
        validated.append(change.model_copy(update={'value': value}))
    if violations:
        raise TurnFieldContractViolation(violations)
    return validated
