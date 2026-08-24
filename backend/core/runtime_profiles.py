from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from backend.adapters.evidence_storage import EvidenceStorage, MockEvidenceStorage
from backend.adapters.knowledge import (
    FixtureKnowledgeDocumentStore,
    FixtureKnowledgeRetriever,
)
from backend.adapters.policy_history import MockPolicyHistoryAdapter, PolicyHistoryAdapter
from backend.core.config import DataRuntimeProfile, Settings
from backend.domain.knowledge import KnowledgeDocumentStore, KnowledgeRetriever
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import PersistenceRepository


class RuntimeProfileConfigurationError(ValueError):
    """The selected deployment profile cannot provide one coherent adapter bundle."""


RUNTIME_CAPABILITIES = (
    'persistence',
    'evidence_storage',
    'policy',
    'claim_history',
    'knowledge_documents',
    'knowledge_retrieval',
)


class RuntimeCapabilityStatus(StrEnum):
    USING_FIXTURE = 'using_fixture'
    VERIFIED = 'verified'
    PENDING_CONFIRMATION = 'pending_confirmation'
    UNAVAILABLE = 'unavailable'

    @property
    def start_capable(self) -> bool:
        return self in {self.USING_FIXTURE, self.VERIFIED}


# This table records readiness honestly: fixture and verified provider capabilities can
# start, while pending or unavailable capabilities cannot.
_PROFILE_CAPABILITIES: Mapping[DataRuntimeProfile, Mapping[str, RuntimeCapabilityStatus]] = (
    MappingProxyType(
        {
            DataRuntimeProfile.FIXTURE: MappingProxyType(
                {
                    capability: RuntimeCapabilityStatus.USING_FIXTURE
                    for capability in RUNTIME_CAPABILITIES
                }
            ),
            DataRuntimeProfile.CLOUDFLARE: MappingProxyType(
                {
                    capability: RuntimeCapabilityStatus.PENDING_CONFIRMATION
                    for capability in RUNTIME_CAPABILITIES
                }
            ),
            DataRuntimeProfile.MONGODB: MappingProxyType(
                {
                    capability: RuntimeCapabilityStatus.UNAVAILABLE
                    for capability in RUNTIME_CAPABILITIES
                }
            ),
            DataRuntimeProfile.AWS: MappingProxyType(
                {
                    capability: RuntimeCapabilityStatus.PENDING_CONFIRMATION
                    for capability in RUNTIME_CAPABILITIES
                }
            ),
        }
    )
)


def runtime_capability_statuses(profile: DataRuntimeProfile) -> dict[str, str]:
    """Return a serialisable copy of the capability status table for one profile."""

    return {
        capability: status.value for capability, status in _PROFILE_CAPABILITIES[profile].items()
    }


def missing_runtime_capabilities(profile: DataRuntimeProfile) -> tuple[str, ...]:
    """List capabilities that prevent a profile from being assembled."""

    return tuple(
        capability
        for capability, status in _PROFILE_CAPABILITIES[profile].items()
        if not status.start_capable
    )


@dataclass(frozen=True, slots=True)
class DataRuntimeBundle:
    profile: DataRuntimeProfile
    repository: PersistenceRepository
    evidence_storage: EvidenceStorage
    policy_history: PolicyHistoryAdapter
    knowledge_documents: KnowledgeDocumentStore
    knowledge_retrieval: KnowledgeRetriever

    def readiness_checks(self) -> dict[str, str]:
        return {
            'persistence': 'using_fixture',
            'evidence_storage': self.evidence_storage.connection_status(),
            'policy': self.policy_history.connection_status(),
            'claim_history': self.policy_history.connection_status(),
            'knowledge_documents': self.knowledge_documents.connection_status(),
            'knowledge_retrieval': self.knowledge_retrieval.connection_status(),
        }


def validate_data_runtime_bundle(settings: Settings, bundle: DataRuntimeBundle) -> None:
    """Apply the independent composition guard for externally supplied bundles."""

    if bundle.profile is not settings.data_runtime_profile:
        raise RuntimeProfileConfigurationError(
            'The data runtime bundle does not match DATA_RUNTIME_PROFILE.'
        )
    if bundle.profile is not DataRuntimeProfile.FIXTURE:
        raise RuntimeProfileConfigurationError(
            f'Externally supplied {bundle.profile.value!r} data runtime bundles are not '
            'supported until that complete provider bundle is implemented and validated.'
        )


def build_data_runtime_bundle(settings: Settings) -> DataRuntimeBundle:
    """Build exactly one profile; unsupported profiles fail instead of mixing adapters."""

    if settings.data_runtime_profile is DataRuntimeProfile.FIXTURE:
        knowledge_documents = FixtureKnowledgeDocumentStore()
        return DataRuntimeBundle(
            profile=DataRuntimeProfile.FIXTURE,
            repository=FixtureRepository(),
            evidence_storage=MockEvidenceStorage(),
            policy_history=MockPolicyHistoryAdapter(),
            knowledge_documents=knowledge_documents,
            knowledge_retrieval=FixtureKnowledgeRetriever(knowledge_documents),
        )

    missing = ', '.join(missing_runtime_capabilities(settings.data_runtime_profile))
    raise RuntimeProfileConfigurationError(
        f'Data runtime profile {settings.data_runtime_profile.value!r} cannot start; '
        f'missing or unverified capabilities: {missing}. Startup refused; no fixture '
        'or second-provider fallback was assembled.'
    )
