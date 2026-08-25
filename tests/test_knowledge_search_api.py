from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.core.runtime_profiles import DataRuntimeBundle, build_data_runtime_bundle
from backend.domain.knowledge import (
    KnowledgeChunk,
    KnowledgeRetrievalUnavailable,
    KnowledgeSearch,
)

AUTH = {'Authorization': 'Bearer synthetic-integration'}
ENDPOINT = '/internal/v1/knowledge/search'


class ControlledRetriever:
    def __init__(
        self,
        chunks: list[KnowledgeChunk] | None = None,
        unavailable: bool = False,
    ) -> None:
        self.chunks = chunks or []
        self.unavailable = unavailable
        self.last_request: KnowledgeSearch | None = None

    def connection_status(self) -> str:
        return 'configured_service'

    def search(self, request: KnowledgeSearch) -> list[KnowledgeChunk]:
        self.last_request = request
        if self.unavailable:
            raise KnowledgeRetrievalUnavailable('provider detail')
        return self.chunks


def citation_chunk() -> KnowledgeChunk:
    return KnowledgeChunk(
        document_id='nw-policy-motor-standard-mvp-2026-1',
        chunk_id='nw-policy-motor-standard-mvp-2026-1#MTR-EXC-01',
        title='Northwind Motor Standard Policy',
        document_type='synthetic_policy_wording',
        version='MVP-2026.1',
        section_path='MTR-EXC-01 - Excesses',
        page=None,
        source_uri='northwind://synthetic-policy/motor/MVP-2026.1',
        jurisdiction='NZ',
        insurer='Northwind Insurance',
        product='motor',
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=datetime(2027, 1, 1, tzinfo=UTC),
        authority='northwind_synthetic_demo',
        visibility='customer_and_staff',
        checksum='abc123',
        ingested_at=datetime(2026, 8, 25, tzinfo=UTC),
        text='The matching policy schedule supplies the excess amount.',
    )


def client_for(retriever: ControlledRetriever) -> TestClient:
    settings = Settings()
    fixture = build_data_runtime_bundle(settings)
    bundle = DataRuntimeBundle(
        profile=fixture.profile,
        repository=fixture.repository,
        evidence_storage=fixture.evidence_storage,
        policy_history=fixture.policy_history,
        knowledge_documents=fixture.knowledge_documents,
        knowledge_retrieval=retriever,
    )
    return TestClient(create_app(settings, data_runtime_bundle=bundle))


def request_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        'question': 'How much excess do I pay?',
        'jurisdiction': 'NZ',
        'visibility': 'customer_and_staff',
        'document_id': 'nw-policy-motor-standard-mvp-2026-1',
        'authority': 'northwind_synthetic_demo',
        'version': 'MVP-2026.1',
        'insurer': 'Northwind Insurance',
        'product': 'motor',
        'effective_at': '2026-08-25T00:00:00Z',
        'limit': 3,
    }
    payload.update(changes)
    return payload


def test_knowledge_search_returns_exact_citation_and_passes_full_scope() -> None:
    retriever = ControlledRetriever([citation_chunk()])
    with client_for(retriever) as client:
        response = client.post(ENDPOINT, headers=AUTH, json=request_payload())

    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'evidence_found'
    assert body['limitations'] == []
    assert body['results'][0]['chunk_id'].endswith('#MTR-EXC-01')
    assert body['results'][0]['section_path'] == 'MTR-EXC-01 - Excesses'
    assert body['results'][0]['text'] == 'The matching policy schedule supplies the excess amount.'
    assert retriever.last_request is not None
    assert retriever.last_request.document_id == 'nw-policy-motor-standard-mvp-2026-1'
    assert retriever.last_request.insurer == 'Northwind Insurance'
    assert retriever.last_request.effective_at == datetime(2026, 8, 25, tzinfo=UTC)


def test_knowledge_search_reports_empty_and_unavailable_without_inventing_results() -> None:
    with client_for(ControlledRetriever()) as client:
        empty = client.post(ENDPOINT, headers=AUTH, json=request_payload())
    with client_for(ControlledRetriever(unavailable=True)) as client:
        unavailable = client.post(ENDPOINT, headers=AUTH, json=request_payload())

    assert empty.json()['status'] == 'no_evidence'
    assert empty.json()['results'] == []
    assert empty.json()['limitations']
    assert unavailable.json() == {
        'status': 'unavailable',
        'results': [],
        'limitations': ['The knowledge service is temporarily unavailable.'],
    }


def test_knowledge_search_requires_integration_auth_and_complete_scope() -> None:
    with client_for(ControlledRetriever()) as client:
        no_auth = client.post(ENDPOINT, json=request_payload())
        claimant = client.post(
            ENDPOINT,
            headers={'Authorization': 'Bearer synthetic-claimant'},
            json=request_payload(),
        )
        missing_version = client.post(
            ENDPOINT,
            headers=AUTH,
            json=request_payload(version=''),
        )
        missing_timezone = client.post(
            ENDPOINT,
            headers=AUTH,
            json=request_payload(effective_at='2026-08-25T00:00:00'),
        )

    assert no_auth.status_code == 401
    assert claimant.status_code == 403
    assert missing_version.status_code == 422
    assert missing_timezone.status_code == 422
