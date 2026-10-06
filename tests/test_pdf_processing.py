"""Automatic PDF processing contracts; provider and storage remain in-memory."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, cast
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from backend.adapters.evidence_storage import EvidenceStorageUnavailable, MockEvidenceStorage
from backend.adapters.model_gateway import ModelGatewayRegistry
from backend.app import create_app
from backend.core.config import AgentRuntimeProfile, DataRuntimeProfile, IdentityMode, Settings
from backend.core.errors import ApiError
from backend.core.runtime_profiles import DataRuntimeBundle, build_data_runtime_bundle
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelRequest,
    ModelResponse,
)
from backend.domain.models import CompleteEvidenceProcessingRequest, EvidenceFileStatus
from backend.repositories.fixture import FixtureRepository
from backend.repositories.protocols import IdempotencyRecord
from backend.services.evidence import (
    complete_evidence_processing,
    defer_evidence_processing,
    reserve_evidence_processing,
)
from backend.services.pdf_processing import (
    PDF_PROCESSING_PROMPT_VERSION,
    PdfEvidenceProcessor,
)

# The governed OpenRouter GPT-4o profile these tests configure for PDF reading.
PDF_PROFILE = 'openrouter-gpt-4o'

AUTH = {'Authorization': 'Bearer synthetic-claimant'}
PDF = b'%PDF-1.4\nNorthwind simulated police reference NZP-1042\n%%EOF\n'


class Gateway:
    capabilities = ModelCapabilities(structured_output=True, document_input=True)

    def __init__(
        self,
        response: ModelResponse | ModelGatewayError,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        self.response = response
        self.on_complete = on_complete
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.on_complete is not None:
            callback = self.on_complete
            self.on_complete = None
            callback()
        if isinstance(self.response, ModelGatewayError):
            raise self.response
        return self.response


def _uploaded_pdf(
    *,
    content: bytes = PDF,
    worker: object | None = None,
) -> tuple[FixtureRepository, MockEvidenceStorage, str, str, int]:
    repository = FixtureRepository()
    storage = MockEvidenceStorage()
    app = create_app(
        Settings(
            business_seed_path='config/business-seed.json',
            environment='test',
            identity_mode=IdentityMode.DEVELOPER,
        ),
        repository=repository,
        evidence_storage=storage,
    )
    if worker is not None:
        app.state.evidence_processing_worker = worker
    with TestClient(app) as client:
        created = client.post(
            '/api/v1/claims',
            headers={**AUTH, 'Idempotency-Key': 'pdf-processing-claim'},
            json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
        )
        claim_id = str(created.json()['claim']['claim_id'])
        requested = client.post(
            f'/api/v1/claims/{claim_id}/evidence/uploads',
            headers={
                **AUTH,
                'Idempotency-Key': 'pdf-processing-upload',
                'If-Match': '1',
            },
            json={
                'kind': 'police_report',
                'original_filename': 'police-report.pdf',
                'media_type': 'application/pdf',
                'size_bytes': len(content),
            },
        )
        evidence_id = str(requested.json()['evidence_id'])
        uploaded = client.put(
            f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/content',
            headers={**AUTH, 'Content-Type': 'application/pdf'},
            content=content,
        )
        assert uploaded.status_code == 204
        completed = client.post(
            f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/complete',
            headers={
                **AUTH,
                'Idempotency-Key': 'pdf-processing-complete',
                'If-Match': str(requested.json()['revision']),
            },
            json={'upload_checksum': f'sha256:{sha256(content).hexdigest()}'},
        )
        assert completed.status_code == 202
    return repository, storage, claim_id, evidence_id, int(completed.json()['revision'])


def _processor(
    repository: FixtureRepository,
    storage: MockEvidenceStorage,
    gateway: Gateway,
) -> tuple[PdfEvidenceProcessor, list[object]]:
    resolvers: list[object] = []

    def factory(resolver: object) -> Gateway:
        resolvers.append(resolver)
        return gateway

    return PdfEvidenceProcessor(repository, storage, factory, PDF_PROFILE), resolvers


def _evidence(repository: FixtureRepository, claim_id: str, evidence_id: str) -> Any:
    claim = cast(Any, repository.get_claim_internal(claim_id))
    return cast(Any, repository.get_evidence(claim_id, evidence_id, claim.customer_id))


def _save_evidence(
    repository: FixtureRepository,
    claim_id: str,
    evidence_id: str,
    **updates: object,
) -> Any:
    claim = cast(Any, repository.get_claim_internal(claim_id))
    record = _evidence(repository, claim_id, evidence_id).model_copy(update=updates)
    repository.save_evidence(record, claim.customer_id)
    return record


def test_pdf_processing_proposes_registered_fact_with_bounded_provenance() -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf()
    gateway = Gateway(
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            provider_model='openai/gpt-4o',
            provider_request_id='provider-request-1',
            structured_output={
                'facts': [
                    {
                        'field_code': 'authorities.police_report_reference',
                        'value': 'NZP-1042',
                        'confidence': 0.97,
                    }
                ]
            },
        )
    )
    processor, resolvers = _processor(repository, storage, gateway)
    record = _evidence(repository, claim_id, evidence_id)

    processor.process(record, revision)

    claim = cast(Any, repository.get_claim_internal(claim_id))
    stored = _evidence(repository, claim_id, evidence_id)
    proposal = claim.form['authorities.police_report_reference']
    assert stored.file_status is EvidenceFileStatus.READY
    assert proposal.status.value == 'proposed'
    assert proposal.source.value == 'document'
    assert proposal.source_refs == [evidence_id, f'evidence:{evidence_id}:material:1']
    assert stored.provenance['processing_model_profile_id'] == PDF_PROFILE
    assert stored.provenance['processing_prompt_version'] == PDF_PROCESSING_PROMPT_VERSION
    assert stored.provenance['processing_provider_model'] == 'openai/gpt-4o'
    assert stored.provenance['processing_provider_request_id'] == 'provider-request-1'
    assert str(stored.provenance['processing_operation_id']).startswith('epr_')
    assert gateway.requests[0].required_capabilities.document_input is True
    resolver = cast(Any, resolvers[0])
    assert resolver.resolve(evidence_id, 'application/pdf') == PDF
    assert resolver.resolve('evd_other', 'application/pdf') is None


def test_pdf_upload_completion_wakes_configured_processing_worker() -> None:
    worker = Mock()

    _uploaded_pdf(worker=worker)

    worker.wake.assert_called_once_with()


def test_pdf_with_no_eligible_facts_becomes_ready_without_confirming_fields() -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf()
    gateway = Gateway(
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output={'facts': []},
        )
    )
    processor, _ = _processor(repository, storage, gateway)

    processor.process(
        _evidence(repository, claim_id, evidence_id),
        revision,
    )

    claim = cast(Any, repository.get_claim_internal(claim_id))
    stored = _evidence(repository, claim_id, evidence_id)
    assert stored.file_status is EvidenceFileStatus.READY
    assert stored.provenance['extraction_state'] == 'no_facts'
    assert claim.form == {}


@pytest.mark.parametrize(
    'error',
    [
        ModelGatewayError(ModelGatewayErrorCode.TIMEOUT, retryable=True),
        ModelGatewayError(ModelGatewayErrorCode.RATE_LIMIT, retryable=True),
        ModelGatewayError(ModelGatewayErrorCode.CONFIGURATION),
    ],
)
def test_retryable_provider_failures_return_current_pdf_to_queue(
    error: ModelGatewayError,
) -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf()
    processor, _ = _processor(repository, storage, Gateway(error))

    processor.process(
        _evidence(repository, claim_id, evidence_id),
        revision,
    )

    stored = _evidence(repository, claim_id, evidence_id)
    assert stored.file_status is EvidenceFileStatus.PROCESSING
    assert stored.provenance['processing_state'] == 'queued'
    assert stored.provenance['processing_attempt'] == 1
    assert 'processing_lease_expires_at' not in str(
        {key: value for key, value in stored.provenance.items() if value is not None}
    )


@pytest.mark.parametrize(
    ('content', 'response'),
    [
        (b'not-a-pdf', ModelResponse()),
        (
            PDF,
            ModelResponse(
                completion_status=ModelCompletionStatus.INCOMPLETE,
                structured_output={'facts': []},
            ),
        ),
        (
            PDF,
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={'unexpected': []},
            ),
        ),
        (
            PDF,
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={'facts': [{'field_code': 'unknown.field', 'value': 'x'}]},
            ),
        ),
        (
            PDF,
            ModelGatewayError(ModelGatewayErrorCode.PROVIDER, retryable=False),
        ),
    ],
)
def test_invalid_pdf_malformed_result_and_terminal_rejection_fail_truthfully(
    content: bytes,
    response: ModelResponse | ModelGatewayError,
) -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf(content=content)
    gateway = Gateway(response)
    processor, _ = _processor(repository, storage, gateway)

    processor.process(
        _evidence(repository, claim_id, evidence_id),
        revision,
    )

    stored = _evidence(repository, claim_id, evidence_id)
    assert stored.file_status is EvidenceFileStatus.FAILED
    assert stored.provenance['processing_state'] == 'failed'
    assert (
        'provider' not in str(stored.provenance).lower()
        or 'processing_provider' not in str(stored.provenance).lower()
    )
    if content == b'not-a-pdf':
        assert gateway.requests == []


def test_registered_field_with_invalid_value_is_terminal_malformed_response() -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf()
    processor, _ = _processor(
        repository,
        storage,
        Gateway(
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={
                    'facts': [
                        {
                            'field_code': 'incident.injury_occurred',
                            'value': 'not-a-boolean',
                        }
                    ]
                },
            )
        ),
    )

    processor.process(_evidence(repository, claim_id, evidence_id), revision)

    stored = _evidence(repository, claim_id, evidence_id)
    assert stored.file_status is EvidenceFileStatus.FAILED
    assert stored.provenance['processing_failure_code'] == 'MODEL_MALFORMED_RESPONSE'


def test_object_store_outage_returns_reserved_pdf_to_retryable_queue() -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf()
    storage.set_outage(EvidenceStorageUnavailable('OBJECT_STORE_UNAVAILABLE', 'secret detail'))
    processor, _ = _processor(repository, storage, Gateway(ModelResponse()))

    processor.process(_evidence(repository, claim_id, evidence_id), revision)

    stored = _evidence(repository, claim_id, evidence_id)
    assert stored.file_status is EvidenceFileStatus.PROCESSING
    assert stored.provenance['processing_state'] == 'queued'
    assert stored.provenance['processing_last_failure'] == 'MODEL_EVIDENCE_UNAVAILABLE'
    assert 'secret detail' not in str(stored.provenance)


@pytest.mark.parametrize(
    ('mutation', 'failure_code'),
    [
        ('missing_identity', 'PDF_OBJECT_IDENTITY_MISSING'),
        ('size_mismatch', 'PDF_OBJECT_INTEGRITY_INVALID'),
    ],
)
def test_invalid_current_object_fails_without_calling_provider(
    mutation: str,
    failure_code: str,
) -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf()
    current = _evidence(repository, claim_id, evidence_id)
    if mutation == 'missing_identity':
        provenance = dict(current.provenance)
        provenance.pop('storage_key')
        record = _save_evidence(
            repository,
            claim_id,
            evidence_id,
            provenance=provenance,
        )
    else:
        record = _save_evidence(
            repository,
            claim_id,
            evidence_id,
            size_bytes=cast(int, current.size_bytes) + 1,
        )
    gateway = Gateway(ModelResponse())
    processor, _ = _processor(repository, storage, gateway)

    processor.process(record, revision)

    stored = _evidence(repository, claim_id, evidence_id)
    assert stored.file_status is EvidenceFileStatus.FAILED
    assert stored.provenance['processing_failure_code'] == failure_code
    assert gateway.requests == []


def test_legacy_queued_pdf_without_operation_identity_gets_stable_identity() -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf()
    current = _evidence(repository, claim_id, evidence_id)
    provenance = dict(current.provenance)
    provenance.pop('processing_operation_id')
    legacy = _save_evidence(
        repository,
        claim_id,
        evidence_id,
        provenance=provenance,
    )
    processor, _ = _processor(
        repository,
        storage,
        Gateway(
            ModelResponse(
                completion_status=ModelCompletionStatus.COMPLETE,
                structured_output={'facts': []},
            )
        ),
    )

    processor.process(legacy, revision)

    stored = _evidence(repository, claim_id, evidence_id)
    assert str(stored.provenance['processing_operation_id']).startswith('epr_')
    assert stored.file_status is EvidenceFileStatus.READY


def test_stale_material_generation_is_rejected_before_provider_invocation() -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf()
    gateway = Gateway(
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output={'facts': []},
        )
    )
    processor, _ = _processor(repository, storage, gateway)
    stale = _evidence(repository, claim_id, evidence_id).model_copy(update={'material_version': 0})

    with pytest.raises(ApiError) as conflict:
        processor.process(stale, revision)

    assert conflict.value.code == 'INVALID_STATE_TRANSITION'
    assert gateway.requests == []


def test_active_processing_lease_blocks_dispatch_and_expired_lease_is_recoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _, claim_id, evidence_id, revision = _uploaded_pdf()
    first_claim, first_reservation, attempt = reserve_evidence_processing(
        repository, claim_id, evidence_id, revision, 1
    )

    with pytest.raises(ApiError) as active:
        reserve_evidence_processing(repository, claim_id, evidence_id, first_claim.revision, 1)

    assert active.value.code == 'INVALID_STATE_TRANSITION'
    assert attempt == 1
    lease = first_reservation.provenance['processing_lease_expires_at']
    assert isinstance(lease, str)
    monkeypatch.setattr(
        'backend.services.evidence.now_utc',
        lambda: datetime.fromisoformat(lease) + timedelta(seconds=1),
    )

    second_claim, second_reservation, second_attempt = reserve_evidence_processing(
        repository, claim_id, evidence_id, first_claim.revision, 1
    )

    assert second_claim.revision == first_claim.revision + 1
    assert second_attempt == 2
    assert (
        second_reservation.provenance['processing_operation_id']
        == first_reservation.provenance['processing_operation_id']
    )


def test_stale_processing_callback_cannot_overwrite_current_material_generation() -> None:
    repository, _, claim_id, evidence_id, revision = _uploaded_pdf()
    before = _evidence(repository, claim_id, evidence_id)

    with pytest.raises(ApiError) as conflict:
        complete_evidence_processing(
            repository,
            claim_id,
            evidence_id,
            CompleteEvidenceProcessingRequest(outcome='ready', facts=[]),
            'stale-material-callback',
            str(revision),
            expected_material_version=before.material_version + 1,
        )

    assert conflict.value.code == 'INVALID_STATE_TRANSITION'
    assert _evidence(repository, claim_id, evidence_id) == before


def test_persistent_model_runtime_composes_and_runs_one_pdf_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, storage, claim_id, evidence_id, _ = _uploaded_pdf()
    fixture_bundle = build_data_runtime_bundle(
        Settings(
            business_seed_path='config/business-seed.json',
            environment='test',
            identity_mode=IdentityMode.DEVELOPER,
        )
    )
    persistent_bundle = DataRuntimeBundle(
        profile=DataRuntimeProfile.LOCAL_MVP,
        repository=repository,
        evidence_storage=storage,
        policy_history=fixture_bundle.policy_history,
        claim_history=fixture_bundle.claim_history,
        knowledge_documents=fixture_bundle.knowledge_documents,
        knowledge_retrieval=fixture_bundle.knowledge_retrieval,
    )
    monkeypatch.setattr('backend.app.build_data_runtime_bundle', lambda settings: persistent_bundle)
    gateway = Gateway(
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output={'facts': []},
        )
    )
    registry = ModelGatewayRegistry()
    registry.register('openai_compatible', lambda config: gateway)
    app = create_app(
        Settings(
            business_seed_path='config/business-seed.json',
            environment='test',
            identity_mode=IdentityMode.DEVELOPER,
            data_runtime_profile=DataRuntimeProfile.LOCAL_MVP,
            agent_runtime_profile=AgentRuntimeProfile.MODEL_GATEWAY,
            model_base_url='https://openrouter.example/v1',
            model_profile_id=PDF_PROFILE,
            pdf_model_profile_id=PDF_PROFILE,
            model_protocol_adapter='openai_compatible',
            model_provider='openrouter',
            model_identifier='openai/gpt-4o',
            model_supports_document_input=True,
        ),
        model_gateway_registry=registry,
    )
    worker = cast(Any, app.state.evidence_processing_worker)
    assert worker is app.state.image_recovery_worker
    assert worker is not None
    start = Mock()
    stop = Mock()
    monkeypatch.setattr(worker, 'start', start)
    monkeypatch.setattr(worker, 'stop', stop)

    with TestClient(app):
        pass

    start.assert_called_once_with()
    stop.assert_called_once_with()
    worker.run_once()
    stored = _evidence(repository, claim_id, evidence_id)
    assert stored.file_status is EvidenceFileStatus.READY
    assert stored.provenance['extraction_state'] == 'no_facts'
    assert gateway.requests[0].purpose == 'evidence_processing'


def test_duplicate_dispatch_with_stale_revision_cannot_call_provider_twice() -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf()
    gateway = Gateway(
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output={'facts': []},
        )
    )
    processor, _ = _processor(repository, storage, gateway)
    record = _evidence(repository, claim_id, evidence_id)

    processor.process(record, revision)
    with pytest.raises(ApiError) as conflict:
        processor.process(record, revision)

    assert conflict.value.code == 'REVISION_CONFLICT'
    assert len(gateway.requests) == 1


def test_completion_revision_race_requeues_pdf_without_committing_stale_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf()

    def mutate_claim(key: str = 'completion-race') -> None:
        current = cast(Any, repository.get_claim_internal(claim_id))
        repository.save_claim_mutation(
            current.model_copy(update={'revision': current.revision + 1}),
            current.revision,
            IdempotencyRecord(
                actor_id=current.customer_id,
                route=f'/api/v1/claims/{claim_id}/test-revision-race/{key}',
                key=key,
                request_fingerprint=f'{key}-v1',
                claim_id=claim_id,
                session_id=current.active_session_id or '',
            ),
        )

    requeue_attempts = 0

    def defer_after_one_more_claim_race(*args: Any, **kwargs: Any) -> None:
        nonlocal requeue_attempts
        requeue_attempts += 1
        if requeue_attempts == 1:
            mutate_claim('requeue-race')
        defer_evidence_processing(*args, **kwargs)

    monkeypatch.setattr(
        'backend.services.pdf_processing.defer_evidence_processing',
        defer_after_one_more_claim_race,
    )

    gateway = Gateway(
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output={
                'facts': [
                    {
                        'field_code': 'authorities.police_report_reference',
                        'value': 'NZP-RACE',
                    }
                ]
            },
        ),
        on_complete=mutate_claim,
    )
    processor, _ = _processor(repository, storage, gateway)

    processor.process(_evidence(repository, claim_id, evidence_id), revision)

    queued = _evidence(repository, claim_id, evidence_id)
    assert queued.file_status is EvidenceFileStatus.PROCESSING
    assert queued.provenance['processing_state'] == 'queued'
    assert queued.provenance['processing_last_failure'] == 'CLAIM_REVISION_CONFLICT'
    assert cast(Any, repository.get_claim_internal(claim_id)).form == {}
    assert requeue_attempts == 2

    current_revision = cast(Any, repository.get_claim_internal(claim_id)).revision
    processor.process(queued, current_revision)

    stored = _evidence(repository, claim_id, evidence_id)
    claim = cast(Any, repository.get_claim_internal(claim_id))
    assert stored.file_status is EvidenceFileStatus.READY
    assert claim.form['authorities.police_report_reference'].value == 'NZP-RACE'
    assert len(gateway.requests) == 2


def test_completion_non_revision_error_is_not_requeued_as_a_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf()
    gateway = Gateway(
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output={'facts': []},
        )
    )
    processor, _ = _processor(repository, storage, gateway)

    def reject_completion(*args: Any, **kwargs: Any) -> None:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='The completion is no longer valid.',
        )

    monkeypatch.setattr(
        'backend.services.pdf_processing.complete_evidence_processing',
        reject_completion,
    )

    with pytest.raises(ApiError) as error:
        processor.process(_evidence(repository, claim_id, evidence_id), revision)

    assert error.value.code == 'INVALID_STATE_TRANSITION'
    stored = _evidence(repository, claim_id, evidence_id)
    assert stored.provenance['processing_state'] == 'running'


def test_claimant_projection_never_exposes_processing_operation_or_provider_metadata() -> None:
    repository, storage, claim_id, evidence_id, revision = _uploaded_pdf()
    gateway = Gateway(
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            provider_model='openai/gpt-4o',
            provider_request_id='private-provider-request',
            structured_output={'facts': []},
        )
    )
    processor, _ = _processor(repository, storage, gateway)
    processor.process(
        _evidence(repository, claim_id, evidence_id),
        revision,
    )
    app = create_app(
        Settings(
            business_seed_path='config/business-seed.json',
            environment='test',
            identity_mode=IdentityMode.DEVELOPER,
        ),
        repository=repository,
        evidence_storage=storage,
    )
    with TestClient(app) as client:
        response = client.get(f'/api/v1/claims/{claim_id}/evidence', headers=AUTH)

    assert response.status_code == 200
    assert 'processing_operation_id' not in response.text
    assert 'private-provider-request' not in response.text
    assert 'upload_checksum' not in response.text
