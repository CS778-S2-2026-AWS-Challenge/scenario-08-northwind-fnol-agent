from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import ValidationError

from backend.core.errors import ApiError
from backend.domain.configuration import (
    REGISTERED_INTEGRATION_CAPABILITIES,
    ConfigurationRecord,
    IntegrationConfiguration,
    IntegrationSourceValue,
)
from backend.services.runtime_configuration import RuntimeConfigurationResolver


class RuntimeIntegrationConfigurationError(ValueError):
    """A published Integration record contradicts the assembled runtime."""


@dataclass(frozen=True, slots=True)
class RuntimeIntegrationPolicySnapshot:
    release_set_id: str | None
    configurations: Mapping[str, ConfigurationRecord]
    actual_sources: Mapping[str, IntegrationSourceValue]

    def record(self, service_id: str) -> ConfigurationRecord | None:
        return self.configurations.get(service_id)

    def require(self, service_id: str) -> IntegrationConfiguration | None:
        record = self.record(service_id)
        if record is None:
            if self.release_set_id is None:
                return None
            raise ApiError(
                status_code=503,
                code='RELEASE_SET_INTEGRATION_NOT_SELECTED',
                message='The active runtime release does not select the required integration.',
            )
        try:
            configuration = _parse_configuration(record, service_id)
        except RuntimeIntegrationConfigurationError as error:
            raise ApiError(
                status_code=503,
                code='INTEGRATION_CONFIGURATION_INVALID',
                message='The published integration configuration is invalid.',
            ) from error
        if not configuration.enabled:
            raise ApiError(
                status_code=503,
                code='INTEGRATION_DISABLED',
                message='The required integration is disabled in the active configuration.',
            )
        actual_source = self.actual_sources.get(service_id)
        if actual_source is None or configuration.source is not actual_source:
            raise ApiError(
                status_code=503,
                code='INTEGRATION_CONFIGURATION_MISMATCH',
                message='The published integration source does not match the assembled adapter.',
            )
        return configuration


class RuntimeIntegrationPolicy:
    """Resolve published Integration policy against the adapters assembled by the process."""

    def __init__(
        self,
        resolver: RuntimeConfigurationResolver,
        actual_sources: Mapping[str, IntegrationSourceValue],
    ) -> None:
        self._resolver = resolver
        self._actual_sources = MappingProxyType(dict(actual_sources))

    def snapshot(self) -> RuntimeIntegrationPolicySnapshot:
        runtime = self._resolver.snapshot()
        records = self._resolver.resolve_integrations(runtime)
        by_service: dict[str, ConfigurationRecord] = {}
        for record in records:
            service_id = record.values.get('service_id')
            if isinstance(service_id, str):
                by_service[service_id] = record
        return RuntimeIntegrationPolicySnapshot(
            release_set_id=runtime.release_set_id,
            configurations=MappingProxyType(by_service),
            actual_sources=self._actual_sources,
        )

    def require(self, service_id: str) -> IntegrationConfiguration | None:
        return self.snapshot().require(service_id)

    def validate_selected(self) -> None:
        snapshot = self.snapshot()
        for service_id in snapshot.configurations:
            try:
                snapshot.require(service_id)
            except ApiError as error:
                if error.code == 'INTEGRATION_DISABLED':
                    continue
                raise RuntimeIntegrationConfigurationError(error.message) from error


def _parse_configuration(
    record: ConfigurationRecord,
    service_id: str,
) -> IntegrationConfiguration:
    try:
        configuration = IntegrationConfiguration.model_validate(record.values)
    except ValidationError as error:
        raise RuntimeIntegrationConfigurationError(
            f'Integration {service_id!r} has invalid published configuration.'
        ) from error
    expected_capability = REGISTERED_INTEGRATION_CAPABILITIES.get(service_id)
    if (
        configuration.service_id != service_id
        or configuration.capability != expected_capability
        or record.configuration_key != service_id
    ):
        raise RuntimeIntegrationConfigurationError(
            f'Integration {service_id!r} does not match its registered identity and capability.'
        )
    return configuration
