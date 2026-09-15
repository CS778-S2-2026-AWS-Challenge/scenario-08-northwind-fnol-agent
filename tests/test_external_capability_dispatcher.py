from collections.abc import Mapping
from typing import Any

from backend.domain.external_service_registry import (
    ExternalServiceRegistryEntry,
    capability_catalogue,
)
from backend.services.agent_tools import dispatch_external_service_tool
from backend.services.external_capability_dispatcher import ExternalCapabilityDispatcher


def test_catalogue_is_product_scoped_and_contains_real_manual_entry() -> None:
    motor = capability_catalogue('motor')
    assert any(item.service_identity == 'vehicle_repairer_booking' for item in motor)
    police = next(
        item for item in motor if item.service_identity == 'police_105_reporting_guidance'
    )
    assert police.official_phone == '105'
    assert police.uses_external_task is False


def test_manual_capability_cannot_be_submitted_as_external_task() -> None:
    result = ExternalCapabilityDispatcher().execute(
        'police_105_reporting_guidance',
        'submit_request',
        {},
        product_family='motor',
    )
    assert result.status == 'rejected'
    assert result.uses_external_task is False


def test_configured_capability_without_adapter_is_typed_unavailable() -> None:
    result = ExternalCapabilityDispatcher().execute(
        'vehicle_repairer_booking',
        'submit_request',
        {
            'claim.vehicle.registration': 'ABC123',
            'claim.vehicle.damage_summary': 'rear damage',
            'claimant.contact.phone': '0210000000',
        },
        product_family='motor',
    )
    assert result.status == 'unavailable'
    assert result.uses_external_task is True


def test_runtime_tool_dispatch_returns_typed_registry_result() -> None:
    result = dispatch_external_service_tool(
        ExternalCapabilityDispatcher(),
        tool_name='external_service.discover_capability',
        service_identity='vehicle_repairer_booking',
        product_family='motor',
    )
    assert result['status'] == 'available'
    assert result['registry_version'] == 'external-service-lifecycle.v1'


def test_unknown_operation_and_wrong_product_family_never_call_adapter() -> None:
    calls: list[str] = []

    def adapter(
        _entry: ExternalServiceRegistryEntry, _payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        calls.append('called')
        return {'status': 'accepted'}

    dispatcher = ExternalCapabilityDispatcher({'vehicle_repairer_booking': adapter})
    unknown = dispatcher.execute(
        'vehicle_repairer_booking',
        'not_registered',
        {},
        product_family='motor',
    )
    wrong_family = dispatcher.execute(
        'vehicle_repairer_booking',
        'submit_request',
        {},
        product_family='home',
    )
    assert unknown.status == 'rejected'
    assert wrong_family.status == 'rejected'
    assert calls == []


def test_required_and_extra_fields_are_rejected_before_adapter() -> None:
    calls: list[str] = []

    def adapter(
        _entry: ExternalServiceRegistryEntry, _payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        calls.append('called')
        return {'status': 'accepted'}

    dispatcher = ExternalCapabilityDispatcher({'vehicle_repairer_booking': adapter})
    missing = dispatcher.execute(
        'vehicle_repairer_booking',
        'submit_request',
        {'claim.vehicle.registration': 'ABC123'},
        product_family='motor',
    )
    extra = dispatcher.execute(
        'vehicle_repairer_booking',
        'submit_request',
        {
            'claim.vehicle.registration': 'ABC123',
            'claim.vehicle.damage_summary': 'rear damage',
            'claimant.contact.phone': '0210000000',
            'claimant.email': 'not-registered@example.test',
        },
        product_family='motor',
    )
    assert missing.status == 'rejected'
    assert extra.status == 'rejected'
    assert calls == []
