import pytest
from pydantic import ValidationError

from backend.domain.agent_tool_registry import (
    STAFF_TOOL_REGISTRY,
    StaffToolResult,
    StaffToolResultStatus,
    staff_tool_contract,
)
from backend.domain.staff_agent_tools import STAFF_TOOL_OUTPUT_MODELS


def test_staff_registry_contains_the_published_read_surface() -> None:
    expected = {
        'staff.claim.search',
        'staff.claim.read',
        'staff.session.search',
        'staff.session.read',
        'staff.evidence.list',
        'staff.evidence.read',
        'staff.knowledge.search',
        'staff.policy.history',
        'staff.handoff.read',
        'staff.review_signal.read',
        'staff.work_item.list',
        'staff.external_task.status',
        'staff.customer_update.read',
    }

    assert set(STAFF_TOOL_REGISTRY) == expected
    assert all(contract.read_only for contract in STAFF_TOOL_REGISTRY.values())
    assert all(contract.registry_version == 'v1.0' for contract in STAFF_TOOL_REGISTRY.values())
    assert all(contract.effect == 'read' for contract in STAFF_TOOL_REGISTRY.values())
    assert all(contract.output_schema for contract in STAFF_TOOL_REGISTRY.values())
    assert all(contract.audit_required for contract in STAFF_TOOL_REGISTRY.values())
    assert all(contract.allowed_staff_roles for contract in STAFF_TOOL_REGISTRY.values())
    assert all(
        contract.required_scopes == {'workbench:read'} for contract in STAFF_TOOL_REGISTRY.values()
    )
    assert all(
        contract.tenant_scope == 'server-resolved-tenant'
        for contract in STAFF_TOOL_REGISTRY.values()
    )
    assert (
        STAFF_TOOL_REGISTRY['staff.external_task.status'].release_status == 'reserved-unavailable'
    )
    assert STAFF_TOOL_REGISTRY['staff.claim.search'].follow_up_tools == ('staff.claim.read',)
    assert STAFF_TOOL_REGISTRY['staff.evidence.list'].max_results == 50
    assert STAFF_TOOL_REGISTRY['staff.knowledge.search'].max_results == 10
    assert STAFF_TOOL_REGISTRY['staff.claim.read'].max_results == 1


def test_staff_registry_publishes_each_tools_closed_output_schema() -> None:
    for name, contract in STAFF_TOOL_REGISTRY.items():
        output_model = STAFF_TOOL_OUTPUT_MODELS[name]
        assert contract.output_schema == output_model.model_json_schema()
        assert contract.output_schema['additionalProperties'] is False

    assert (
        STAFF_TOOL_REGISTRY['staff.claim.search'].output_schema
        != STAFF_TOOL_REGISTRY['staff.claim.read'].output_schema
    )


def test_staff_registry_rejects_database_like_search_fields() -> None:
    schema = STAFF_TOOL_REGISTRY['staff.claim.search'].input_schema

    assert schema['additionalProperties'] is False
    properties = schema['properties']
    assert isinstance(properties, dict)
    assert {'sql', 'collection', 'field_path'}.isdisjoint(properties)


def test_staff_tool_contract_rejects_unknown_tool() -> None:
    with pytest.raises(ValueError, match='Unknown Staff Agent tool'):
        staff_tool_contract('staff.claim.missing')


def test_staff_tool_result_preserves_typed_failure_and_scope_metadata() -> None:
    result = StaffToolResult(
        tool_name='staff.claim.read',
        registry_version='v1.0',
        call_id='call-1',
        correlation_id='turn-1',
        status=StaffToolResultStatus.UNAVAILABLE,
        query_scope='explicit-claim',
        limitations=['provider_unavailable'],
        retryable=True,
    )

    assert result.status is StaffToolResultStatus.UNAVAILABLE
    assert result.retryable is True
    assert result.disclose_to_model is True


def test_staff_tool_result_rejects_claimant_tool_names() -> None:
    with pytest.raises(ValidationError):
        StaffToolResult(
            tool_name='claim.read',
            registry_version='v1.0',
            call_id='call-1',
            correlation_id='turn-1',
            status=StaffToolResultStatus.SUCCEEDED,
            query_scope='explicit-claim',
        )
