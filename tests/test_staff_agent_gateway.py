from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from backend.domain.knowledge import KnowledgeChunk, KnowledgeRetrievalUnavailable
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelGatewayError,
    ModelRequest,
    ModelResponse,
    ModelUsage,
)
from backend.domain.models import WorkingClaim
from backend.domain.release import ReleaseSetRecord, ReleaseSetState, now_utc
from backend.domain.staff_agent import StaffAgentModelOutput
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.operations import OperationRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.services.model_operations import ModelOperationsRecorder
from backend.services.runtime_configuration import RuntimeConfigurationResolver
from backend.services.staff_agent import (
    GatewayStaffAgent,
    ProfileSelectingStaffAgent,
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
        model_profile_id='nowcoding-gpt54mini',
    )


def test_gateway_staff_agent_builds_structured_request_and_returns_output() -> None:
    output = StaffAgentModelOutput(answer='Check the evidence trail.', drafts=[])
    gateway = StubGateway(
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output=output.model_dump(mode='json'),
            provider_model='gpt54-mini',
            provider_request_id='req-1',
            usage=ModelUsage(input_tokens=20, output_tokens=5, total_tokens=25),
        )
    )
    operations = OperationRepository()

    result = GatewayStaffAgent(gateway, ModelOperationsRecorder(operations)).respond(_context())

    assert result.output.answer == 'Check the evidence trail.'
    assert result.provider_model == 'gpt54-mini'
    request = gateway.requests[0]
    assert request.model_profile_id == 'nowcoding-gpt54mini'
    assert request.required_capabilities == ModelCapabilities(structured_output=True)
    message_content = request.messages[1].content
    assert message_content is not None
    assert message_content.startswith('{"question":"What should I check next?"')
    operation = operations.metrics_records()[0]
    assert operation.kind.value == 'model_invocation'
    assert operation.state.value == 'succeeded'
    assert operation.result is not None
    assert operation.result['total_tokens'] == 25
    assert operation.result['provider_model'] == 'gpt54-mini'


def test_profile_selecting_staff_agent_uses_session_model_profile() -> None:
    output = StaffAgentModelOutput(answer='Use the saved model profile.', drafts=[])
    gateway = StubGateway(
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output=output.model_dump(mode='json'),
            provider_model='gpt54-mini',
            provider_request_id='req-profile-selector',
        )
    )

    result = ProfileSelectingStaffAgent(lambda profile_id: gateway).respond(_context())

    assert result.output.answer == 'Use the saved model profile.'
    assert gateway.requests[0].model_profile_id == 'nowcoding-gpt54mini'


@pytest.mark.parametrize(
    'status',
    [ModelCompletionStatus.INCOMPLETE, ModelCompletionStatus.REFUSED],
)
def test_gateway_staff_agent_fails_for_incomplete_or_refused_response(
    status: ModelCompletionStatus,
) -> None:
    gateway = StubGateway(ModelResponse(completion_status=status))
    operations = OperationRepository()
    with pytest.raises(ModelGatewayError):
        GatewayStaffAgent(gateway, ModelOperationsRecorder(operations)).respond(_context())
    record = operations.metrics_records()[0]
    assert record.state.value == 'failed'
    assert record.error_code in {'MODEL_INCOMPLETE_RESPONSE', 'MODEL_REFUSED_RESPONSE'}


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
        self,
        chunks: list[KnowledgeChunk] | None = None,
        unavailable: bool = False,
        unavailable_code: str = 'PROVIDER_UNAVAILABLE',
    ) -> None:
        self.chunks = chunks or []
        self.unavailable = unavailable
        self.unavailable_code = unavailable_code
        self.search_calls = 0

    def connection_status(self) -> str:
        return 'available'

    def search(self, request: Any) -> list[KnowledgeChunk]:
        self.search_calls += 1
        if self.unavailable:
            raise KnowledgeRetrievalUnavailable(
                'The knowledge provider is unavailable.', code=self.unavailable_code
            )
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
    citations, status, limitations = _knowledge_context(StubRetriever([chunk]), 'safety', [])
    assert status == 'evidence_found'
    assert limitations == ()
    assert citations[0]['chunk_id'] == 'chunk-1'
    unavailable, unavailable_status, unavailable_limitations = _knowledge_context(
        StubRetriever(unavailable=True), 'safety', []
    )
    assert unavailable == ()
    assert unavailable_status == 'unavailable'
    assert unavailable_limitations == ('The knowledge service is temporarily unavailable.',)

    timed_out, timeout_status, timeout_limitations = _knowledge_context(
        StubRetriever(unavailable=True, unavailable_code='provider_timeout'), 'safety', []
    )
    assert timed_out == ()
    assert timeout_status == 'timeout'
    assert timeout_limitations == (
        'The knowledge service did not respond within the request budget.',
    )


def test_staff_agent_knowledge_context_preserves_release_resolution_failure() -> None:
    retriever = StubRetriever()

    releases = ReleaseSetRepository()
    releases.create(
        ReleaseSetRecord(
            release_set_id='rel_missing_staff_knowledge',
            environment='test',
            runtime_profile='fixture',
            revision=1,
            state=ReleaseSetState.PUBLISHED,
            configuration_refs={},
            author='test-admin',
            reason='Exercise missing staff knowledge selection.',
            effective_time=now_utc(),
            updated_at=now_utc(),
        )
    )
    resolver = RuntimeConfigurationResolver(
        ConfigurationRepository(),
        releases,
        environment='test',
        runtime_profile='fixture',
    )

    def resolve_version(product: str) -> str | None:
        selected = resolver.resolve_knowledge(product)
        return selected.version if selected is not None else None

    citations, status, limitations = _knowledge_context(
        retriever,
        'safety',
        [cast(WorkingClaim, SimpleNamespace(incident_type='motor'))],
        resolve_version,
    )

    assert citations == ()
    assert status == 'unavailable'
    assert limitations == (
        'The active runtime release does not select an approved knowledge version.',
    )
    assert retriever.search_calls == 0
