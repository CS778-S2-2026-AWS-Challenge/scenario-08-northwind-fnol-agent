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


class ExternalCapabilityDispatcher:
    """Validate registry identity and dispatch through an explicit adapter map."""

    def __init__(self, adapters: Mapping[str, Adapter] | None = None) -> None:
        self._adapters = dict(adapters or {})

    def discover(
        self, service_identity: str, *, product_family: str | None = None
    ) -> ExternalCapabilityResult:
        entry = service_registry_entry(service_identity)
        if product_family and product_family not in entry.product_families:
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
        self, service_identity: str, operation: str, payload: Mapping[str, Any]
    ) -> ExternalCapabilityResult:
        entry = service_registry_entry(service_identity)
        if operation == 'discover_capability':
            return self.discover(service_identity)
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
        adapter = self._adapters.get(service_identity)
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
