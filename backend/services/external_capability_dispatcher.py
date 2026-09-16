"""Registry-backed Runtime dispatch for third-party capabilities.

The model may propose an operation, but this dispatcher is the only place that
turns a registered capability into an adapter call. Manual links and phone paths
return a typed next action and never create an ExternalTask.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.domain.external_service_registry import (
    ExternalServiceRegistryEntry,
    service_registry_entry,
)


@dataclass(frozen=True, slots=True)
class ExternalCapabilityResult:
    status: str
    service_identity: str
    registry_version: str
    access_form: str
    uses_external_task: bool
    payload: Mapping[str, Any]
    next_action: str


Adapter = Callable[[ExternalServiceRegistryEntry, Mapping[str, Any]], Mapping[str, Any]]


def _controlled_task_adapter(
    entry: ExternalServiceRegistryEntry,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return the provider-shaped acknowledgement used by controlled environments."""

    operation_id = str(payload['operation_id'])
    reference_prefix = entry.catalogue_reference or entry.service_identity
    return {
        'status': 'accepted',
        'provider_reference': f'{reference_prefix}-{operation_id.removeprefix("op_")[:8]}',
        'next_action': f'{entry.service_name} accepted the request for processing.',
    }


def controlled_external_capability_dispatcher() -> 'ExternalCapabilityDispatcher':
    """Compose registered task adapters for the controlled product runtime."""

    return ExternalCapabilityDispatcher(
        {
            service_identity: _controlled_task_adapter
            for service_identity in (
                'vehicle_recovery_request',
                'vehicle_repairer_booking',
                'home_emergency_repair_request',
                'contents_specialist_assessment',
            )
        }
    )


REGISTERED_OPERATIONS = frozenset(
    {
        'discover_capability',
        'load_requirements',
        'prepare_request',
        'classify_request',
        'check_authority',
        'submit_request',
        'track_request',
        'verify_response',
        'reconcile_response',
        'retry_request',
        'cancel_request',
        'escalate_failure',
    }
)
REQUEST_OPERATIONS = frozenset({'prepare_request', 'submit_request'})
RUNTIME_VALIDATION_OPERATIONS = frozenset(
    {'load_requirements', 'classify_request', 'check_authority'}
)
CONTROL_FIELDS = frozenset(
    {
        'claim_id',
        'claim_revision',
        'operation_id',
        'idempotency_key',
        'provider_reference',
        'consent_ref',
        'northwind_authority_ref',
        'result_reference',
    }
)


class ExternalCapabilityDispatcher:
    """Validate registry identity and dispatch through an explicit adapter map."""

    def __init__(self, adapters: Mapping[str, Adapter] | None = None) -> None:
        self._adapters = dict(adapters or {})

    def discover(self, service_identity: str, *, product_family: str) -> ExternalCapabilityResult:
        entry = service_registry_entry(service_identity)
        if product_family.strip().lower() not in entry.product_families:
            return ExternalCapabilityResult(
                status='unavailable',
                service_identity=entry.service_identity,
                registry_version='external-service-lifecycle.v1',
                access_form=entry.access_form,
                uses_external_task=entry.uses_external_task,
                payload={},
                next_action='Select a capability registered for this Claim product family.',
            )
        return ExternalCapabilityResult(
            status='available',
            service_identity=entry.service_identity,
            registry_version='external-service-lifecycle.v1',
            access_form=entry.access_form,
            uses_external_task=entry.uses_external_task,
            payload={
                'purpose': entry.purpose,
                'required_fields': entry.required_fields,
                'disclosure_fields': entry.disclosure_fields,
                'official_url': entry.official_url,
                'official_phone': entry.official_phone,
                'provenance': entry.provenance.value,
            },
            next_action='Collect the registered fields and verify authority before requesting.',
        )

    def execute(
        self,
        service_identity: str,
        operation: str,
        payload: Mapping[str, Any],
        *,
        product_family: str,
    ) -> ExternalCapabilityResult:
        entry = service_registry_entry(service_identity)
        if operation not in REGISTERED_OPERATIONS:
            return self._rejected(
                entry,
                'The requested external operation is not registered and was not executed.',
            )
        if operation == 'discover_capability':
            return self.discover(service_identity, product_family=product_family)
        if product_family.strip().lower() not in entry.product_families:
            return self._rejected(
                entry,
                'This capability is not registered for the current Claim product family.',
            )
        if (
            operation in {'submit_request', 'retry_request', 'cancel_request'}
            and not entry.uses_external_task
        ):
            return ExternalCapabilityResult(
                status='rejected',
                service_identity=service_identity,
                registry_version='external-service-lifecycle.v1',
                access_form=entry.access_form,
                uses_external_task=False,
                payload={},
                next_action=(
                    'Use the official link or phone path; manual capabilities do not create tasks.'
                ),
            )
        validation_error = self._validate_payload(entry, operation, payload)
        if validation_error is not None:
            return self._rejected(entry, validation_error)
        adapter = self._adapters.get(service_identity)
        if adapter is None and operation in RUNTIME_VALIDATION_OPERATIONS:
            return ExternalCapabilityResult(
                status='validated',
                service_identity=service_identity,
                registry_version='external-service-lifecycle.v1',
                access_form=entry.access_form,
                uses_external_task=entry.uses_external_task,
                payload={
                    'purpose': entry.purpose,
                    'required_fields': entry.required_fields,
                    'disclosure_fields': entry.disclosure_fields,
                },
                next_action='Use Runtime authority and the exact registered disclosure scope.',
            )
        if adapter is None:
            return ExternalCapabilityResult(
                status='unavailable',
                service_identity=service_identity,
                registry_version='external-service-lifecycle.v1',
                access_form=entry.access_form,
                uses_external_task=entry.uses_external_task,
                payload={},
                next_action='No configured adapter is available for this capability.',
            )
        result = dict(adapter(entry, payload))
        return ExternalCapabilityResult(
            status=str(result.get('status', 'unknown_outcome')),
            service_identity=service_identity,
            registry_version='external-service-lifecycle.v1',
            access_form=entry.access_form,
            uses_external_task=entry.uses_external_task,
            payload=result,
            next_action=str(result.get('next_action', 'Use the canonical lifecycle projection.')),
        )

    @staticmethod
    def _rejected(
        entry: ExternalServiceRegistryEntry, next_action: str
    ) -> ExternalCapabilityResult:
        return ExternalCapabilityResult(
            status='rejected',
            service_identity=entry.service_identity,
            registry_version='external-service-lifecycle.v1',
            access_form=entry.access_form,
            uses_external_task=entry.uses_external_task,
            payload={},
            next_action=next_action,
        )

    @staticmethod
    def _validate_payload(
        entry: ExternalServiceRegistryEntry,
        operation: str,
        payload: Mapping[str, Any],
    ) -> str | None:
        if not isinstance(payload, Mapping):
            return 'The external operation payload must be an object.'
        allowed = set(entry.required_fields) | set(entry.disclosure_fields) | set(CONTROL_FIELDS)
        unknown = sorted(set(payload) - allowed)
        if unknown:
            return f'Payload contains fields outside the registered disclosure scope: {unknown}.'
        if operation not in REQUEST_OPERATIONS:
            return None
        missing = [
            field
            for field in entry.required_fields
            if field not in payload or payload[field] in (None, '', [], {})
        ]
        if missing:
            return f'Payload is missing required registered fields: {missing}.'
        return None
