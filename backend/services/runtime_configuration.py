"""Resolve one coherent set of published runtime configuration."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from backend.domain.configuration import (
    REGISTERED_INTEGRATION_IDS,
    ConfigurationRecord,
    ConfigurationState,
)
from backend.domain.knowledge_admin import KnowledgeSourceRecord, KnowledgeVersionState
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.repositories.release_set import ReleaseSetRepository


class RuntimeConfigurationResolutionError(RuntimeError):
    """The active release cannot provide a safe runtime configuration."""


@dataclass(frozen=True, slots=True)
class RuntimeConfigurationSnapshot:
    """One immutable view of the active release and its published records."""

    environment: str
    runtime_profile: str
    release_set_id: str | None
    configurations: Mapping[str, ConfigurationRecord]
    integrations: Mapping[str, ConfigurationRecord]
    knowledge: Mapping[str, KnowledgeSourceRecord]

    def get(self, domain: str) -> ConfigurationRecord | None:
        """Return the configuration for ``domain`` in this snapshot, if present.

        Args:
            domain: Stable Control Plane configuration domain.

        Returns:
            The published configuration referenced by this snapshot, or ``None`` when
            the legacy no-release fallback is in use or the domain is absent.

        Raises:
            RuntimeConfigurationResolutionError: If the requested domain is absent from
                an active Release Set.
        """

        configuration = self.configurations.get(domain)
        if self.release_set_id is not None and configuration is None:
            raise RuntimeConfigurationResolutionError(
                f'Active release set {self.release_set_id!r} does not reference {domain!r}.'
            )
        return configuration

    def knowledge_for_product(self, product: str) -> KnowledgeSourceRecord | None:
        """Return the selected published knowledge version for a product family.

        Args:
            product: Canonical product-family scope used by retrieval.

        Returns:
            The selected published knowledge version, or ``None`` in the explicit
            no-release fallback when no published catalog entry exists.

        Raises:
            RuntimeConfigurationResolutionError: If an active Release Set does not
                select a version for ``product``.
        """

        knowledge = self.knowledge.get(product)
        if self.release_set_id is not None and knowledge is None:
            raise RuntimeConfigurationResolutionError(
                f'Active release set {self.release_set_id!r} does not reference '
                f'knowledge for {product!r}.'
            )
        return knowledge


class RuntimeConfigurationResolver:
    """Resolve runtime domains from one active Release Set.

    A published Release Set is authoritative whenever one exists for the selected
    environment and runtime profile. The no-release fallback preserves the existing
    developer/fixture bootstrap path; it resolves only a single published domain and
    never combines records from an active Release Set with fallback records.
    """

    def __init__(
        self,
        configuration_repository: ConfigurationRepository,
        release_set_repository: ReleaseSetRepository,
        knowledge_repository: KnowledgeAdminRepository | None = None,
        *,
        environment: str,
        runtime_profile: str,
    ) -> None:
        self._configuration_repository = configuration_repository
        self._release_set_repository = release_set_repository
        self._knowledge_repository = knowledge_repository
        self._environment = environment
        self._runtime_profile = runtime_profile

    def snapshot(self) -> RuntimeConfigurationSnapshot:
        """Load and validate one coherent published runtime snapshot.

        Returns:
            A snapshot containing only published configuration revisions referenced by
            the active Release Set, or an explicitly marked no-release fallback view.

        Raises:
            RuntimeConfigurationResolutionError: If a referenced configuration is
                missing, has the wrong domain, or is no longer published.
        """

        release = self._release_set_repository.active(self._environment, self._runtime_profile)
        if release is None:
            return RuntimeConfigurationSnapshot(
                environment=self._environment,
                runtime_profile=self._runtime_profile,
                release_set_id=None,
                configurations=MappingProxyType({}),
                integrations=MappingProxyType({}),
                knowledge=MappingProxyType({}),
            )

        resolved: dict[str, ConfigurationRecord] = {}
        for domain, reference in release.configuration_refs.items():
            configuration = self._configuration_repository.get(
                reference.configuration_id,
                reference.revision,
            )
            if (
                configuration is None
                or configuration.domain != domain
                or configuration.state is not ConfigurationState.PUBLISHED
            ):
                raise RuntimeConfigurationResolutionError(
                    f'Release set {release.release_set_id!r} references an unavailable '
                    f'published configuration for {domain!r}.'
                )
            resolved[domain] = configuration
        resolved_knowledge: dict[str, KnowledgeSourceRecord] = {}
        for product, knowledge_reference in release.knowledge_refs.items():
            if self._knowledge_repository is None:
                raise RuntimeConfigurationResolutionError(
                    'An active Release Set references knowledge but no knowledge repository '
                    'is configured.'
                )
            knowledge = self._knowledge_repository.get(knowledge_reference.knowledge_id)
            if (
                knowledge is None
                or knowledge.revision != knowledge_reference.revision
                or knowledge.product != product
                or knowledge.state is not KnowledgeVersionState.PUBLISHED
            ):
                raise RuntimeConfigurationResolutionError(
                    f'Release set {release.release_set_id!r} references an unavailable '
                    f'published knowledge version for {product!r}.'
                )
            resolved_knowledge[product] = knowledge
        resolved_integrations: dict[str, ConfigurationRecord] = {}
        for service_id, integration_reference in release.integration_refs.items():
            integration = self._configuration_repository.get(
                integration_reference.configuration_id,
                integration_reference.revision,
            )
            if (
                integration is None
                or integration.domain != 'integration'
                or integration.state is not ConfigurationState.PUBLISHED
                or integration.values.get('service_id') != service_id
            ):
                raise RuntimeConfigurationResolutionError(
                    f'Release set {release.release_set_id!r} references an unavailable '
                    f'published integration for {service_id!r}.'
                )
            resolved_integrations[service_id] = integration
        return RuntimeConfigurationSnapshot(
            environment=self._environment,
            runtime_profile=self._runtime_profile,
            release_set_id=release.release_set_id,
            configurations=MappingProxyType(resolved),
            integrations=MappingProxyType(resolved_integrations),
            knowledge=MappingProxyType(resolved_knowledge),
        )

    def resolve(self, domain: str) -> ConfigurationRecord | None:
        """Resolve one domain without mixing an active release and fallback records.

        Args:
            domain: Stable Control Plane configuration domain.

        Returns:
            The selected published configuration, or ``None`` when no active release
            exists and the legacy domain has no published record.

        Raises:
            RuntimeConfigurationResolutionError: If an active Release Set omits the
                requested domain or references an invalid record.
        """

        snapshot = self.snapshot()
        if snapshot.release_set_id is not None:
            return snapshot.get(domain)
        return self._configuration_repository.active(domain)

    def resolve_knowledge(self, product: str) -> KnowledgeSourceRecord | None:
        """Resolve knowledge from the active Release Set or explicit fallback."""

        snapshot = self.snapshot()
        if snapshot.release_set_id is not None:
            return snapshot.knowledge_for_product(product)
        if self._knowledge_repository is None:
            return None
        return self._knowledge_repository.published_for_product(product)

    def resolve_integrations(
        self,
        snapshot: RuntimeConfigurationSnapshot | None = None,
    ) -> tuple[ConfigurationRecord, ...]:
        """Resolve the exact integration set selected for the active runtime."""

        resolved_snapshot = snapshot or self.snapshot()
        if resolved_snapshot.release_set_id is not None:
            return tuple(resolved_snapshot.integrations.values())
        records: list[ConfigurationRecord] = []
        for service_id in REGISTERED_INTEGRATION_IDS:
            record = self._configuration_repository.active('integration', service_id)
            if record is not None:
                records.append(record)
        return tuple(records)
