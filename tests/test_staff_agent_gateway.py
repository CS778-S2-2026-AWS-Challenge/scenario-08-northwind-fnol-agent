from datetime import UTC, datetime
from typing import Any

import pytest

from backend.domain.knowledge import KnowledgeChunk, KnowledgeRetrievalUnavailable
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelGatewayError,
    ModelRequest,
    ModelResponse,
)
from backend.domain.staff_agent import StaffAgentModelOutput
from backend.services.staff_agent import (
    GatewayStaffAgent,
    StaffAgentContext,
    _knowledge_context,
)


class StubGateway:
    def __init__(self, response: ModelResponse) -> None:
        self.response = response
        self.requests: list[ModelRequest] = []

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.response


def _context() -> StaffAgentContext:
    return StaffAgentContext(
        question='What should I check next?',
        claims=(),
        conversation=(),
        knowledge=(),
        knowledge_status='no_evidence',
    )


def test_gateway_staff_agent_builds_structured_request_and_returns_output() -> None:
    output = StaffAgentModelOutput(answer='Check the evidence trail.', drafts=[])
    gateway = StubGateway(
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output=output.model_dump(mode='json'),
            provider_model='gpt54-mini',
            provider_request_id='req-1',
        )
    )

    result = GatewayStaffAgent(gateway).respond(_context())

    assert result.output.answer == 'Check the evidence trail.'
    assert result.provider_model == 'gpt54-mini'
    request = gateway.requests[0]
    assert request.required_capabilities == ModelCapabilities(structured_output=True)
    assert request.messages[1].content.startswith('{"question":"What should I check next?"')


@pytest.mark.parametrize(
    'status',
    [ModelCompletionStatus.INCOMPLETE, ModelCompletionStatus.REFUSED],
)
def test_gateway_staff_agent_fails_for_incomplete_or_refused_response(
    status: ModelCompletionStatus,
) -> None:
    gateway = StubGateway(ModelResponse(completion_status=status))
    with pytest.raises(ModelGatewayError):
        GatewayStaffAgent(gateway).respond(_context())


def test_gateway_staff_agent_fails_for_unknown_or_malformed_response() -> None:
    for response in (
        ModelResponse(completion_status=ModelCompletionStatus.UNKNOWN),
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output={'answer': 42, 'drafts': []},
        ),
    ):
        with pytest.raises(ModelGatewayError):
            GatewayStaffAgent(StubGateway(response)).respond(_context())


class StubRetriever:
    def __init__(
        self, chunks: list[KnowledgeChunk] | None = None, unavailable: bool = False
    ) -> None:
        self.chunks = chunks or []
        self.unavailable = unavailable

    def connection_status(self) -> str:
        return 'available'

    def search(self, request: Any) -> list[KnowledgeChunk]:
        if self.unavailable:
            raise KnowledgeRetrievalUnavailable()
        return self.chunks


def test_staff_agent_knowledge_context_preserves_citations_and_failure_status() -> None:
    now = datetime.now(UTC)
    chunk = KnowledgeChunk(
        document_id='doc-1',
        chunk_id='chunk-1',
        title='Motor policy',
        document_type='policy',
        version='v1',
        section_path='Claims > Motor',
        page=1,
        source_uri='fixture://policy',
        jurisdiction='NZ',
        insurer='Northwind Insurance',
        product='motor',
        effective_from=now,
        effective_to=None,
        authority='northwind_synthetic_demo',
        visibility='customer_and_staff',
        checksum='checksum',
        ingested_at=now,
        text='Keep the vehicle safe.',
    )
    citations, status = _knowledge_context(StubRetriever([chunk]), 'safety', [])
    assert status == 'evidence_found'
    assert citations[0]['chunk_id'] == 'chunk-1'
    unavailable, unavailable_status = _knowledge_context(
        StubRetriever(unavailable=True), 'safety', []
    )
    assert unavailable == ()
    assert unavailable_status == 'unavailable'
