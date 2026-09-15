from backend.domain.external_service_registry import capability_catalogue
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
        'police_105_reporting_guidance', 'submit_request', {}
    )
    assert result.status == 'rejected'
    assert result.uses_external_task is False


def test_configured_capability_without_adapter_is_typed_unavailable() -> None:
    result = ExternalCapabilityDispatcher().execute(
        'vehicle_repairer_booking', 'submit_request', {'claim.vehicle.registration': 'ABC123'}
    )
    assert result.status == 'unavailable'
    assert result.uses_external_task is True


def test_runtime_tool_dispatch_returns_typed_registry_result() -> None:
    result = dispatch_external_service_tool(
        ExternalCapabilityDispatcher(),
        tool_name='external_service.discover_capability',
        service_identity='vehicle_repairer_booking',
    )
    assert result['status'] == 'available'
    assert result['registry_version'] == 'external-service-lifecycle.v1'
