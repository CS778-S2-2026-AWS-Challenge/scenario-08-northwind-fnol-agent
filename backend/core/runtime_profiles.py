from collections.abc import Mapping
from dataclasses import dataclass
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


# These are capability statuses, not claims that a provider service is available.
# A non-fixture profile remains unavailable until its complete bundle is verified.
_PROFILE_CAPABILITIES: Mapping[DataRuntimeProfile, Mapping[str, str]] = MappingProxyType(
    {
        DataRuntimeProfile.FIXTURE: MappingProxyType(
            {capability: 'using_fixture' for capability in RUNTIME_CAPABILITIES}
        ),
        DataRuntimeProfile.CLOUDFLARE: MappingProxyType(
            {capability: 'pending_confirmation' for capability in RUNTIME_CAPABILITIES}
        ),
        DataRuntimeProfile.MONGODB: MappingProxyType(
            {capability: 'unavailable' for capability in RUNTIME_CAPABILITIES}
        ),
        DataRuntimeProfile.AWS: MappingProxyType(
            {capability: 'pending_confirmation' for capability in RUNTIME_CAPABILITIES}
        ),
    }
)


def runtime_capability_statuses(profile: DataRuntimeProfile) -> dict[str, str]:
    """Return a copy of the verified status table for one selected profile."""

    return dict(_PROFILE_CAPABILITIES[profile])


def missing_runtime_capabilities(profile: DataRuntimeProfile) -> tuple[str, ...]:
    """List capabilities that prevent a profile from being assembled."""

    return tuple(
        capability
        for capability, status in _PROFILE_CAPABILITIES[profile].items()
        if status != 'using_fixture'
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
    """Reject mislabeled or externally assembled unsupported provider bundles."""

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
