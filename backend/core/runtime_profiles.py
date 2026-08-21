from dataclasses import dataclass

from backend.adapters.evidence_storage import EvidenceStorage, MockEvidenceStorage
from backend.adapters.knowledge import (
    FixtureKnowledgeDocumentStore,
    FixtureKnowledgeRetriever,
    KnowledgeDocumentStore,
    KnowledgeRetriever,
)
from backend.adapters.policy_history import MockPolicyHistoryAdapter, PolicyHistoryAdapter
from backend.core.config import DataRuntimeProfile, Settings
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import PersistenceRepository


class RuntimeProfileConfigurationError(ValueError):
    """The selected deployment profile cannot provide one coherent adapter bundle."""


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

    raise RuntimeProfileConfigurationError(
        f'Data runtime profile {settings.data_runtime_profile.value!r} is not implemented. '
        'Startup refused; no fixture or second-provider fallback was assembled.'
    )
