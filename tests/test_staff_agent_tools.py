from datetime import UTC, datetime

from backend.core.auth import Principal
from backend.domain.agent_tool_registry import STAFF_TOOL_REGISTRY
from backend.domain.knowledge import KnowledgeChunk, KnowledgeSearch
from backend.domain.models import (
    Channel,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    SessionRecord,
    WorkingClaim,
)
from backend.domain.staff_agent_tools import StaffToolResult
from backend.repositories.fixture import FixtureRepository
from backend.services.staff_agent_tools import StaffToolDispatcher


class _KnowledgeRetriever:
    def connection_status(self) -> str:
        return 'using_fixture'

    def search(self, request: KnowledgeSearch) -> list[KnowledgeChunk]:
        timestamp = datetime(2026, 9, 1, tzinfo=UTC)
        return [
            KnowledgeChunk(
                document_id='doc_motor_wording',
                chunk_id='chunk_collision',
                title='Motor wording',
                document_type='policy_wording',
                version=request.version or '1.0',
                section_path='Collision damage',
                page=4,
                source_uri='https://example.invalid/motor-wording',
                jurisdiction=request.jurisdiction,
                insurer=request.insurer,
                product=request.product,
                effective_from=timestamp,
                effective_to=None,
                authority=request.authority or 'approved',
                visibility=request.visibility,
                checksum='sha256:synthetic',
                ingested_at=timestamp,
                text='Synthetic wording excerpt for a bounded test.',
            )
        ]


def _repository() -> FixtureRepository:
    repository = FixtureRepository()
    timestamp = datetime(2026, 9, 14, 2, 30, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id='clm_staff_tool',
        customer_id='cus_staff_tool',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id='ses_staff_tool',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        summary='The claimant corrected the address.',
        started_at=timestamp,
        last_active_at=timestamp,
    )
    repository.create_claim(claim, session)
    repository.save_message(
        MessageRecord(
            message_id='msg_staff_tool',
            claim_id=claim.claim_id,
            session_id=session.session_id,
            actor='claimant',
            visibility=MessageVisibility.CLAIMANT_VISIBLE,
            content={'type': 'text', 'text': 'The corrected address is 1 Queen Street.'},
            created_at=timestamp,
        ),
        claim.customer_id,
    )
    repository.save_evidence(
        EvidenceRecord(
            evidence_id='evd_staff_tool',
            claim_id=claim.claim_id,
            kind='incident_photo',
            status=EvidenceStatus.RECEIVED,
            file_status=EvidenceFileStatus.READY,
            original_filename='damage.jpg',
            media_type='image/jpeg',
            size_bytes=120,
            source=EvidenceSource.CLAIMANT,
            provenance={
                'storage_key': 'must-not-leak',
                'provider_private_detail': 'must-not-leak',
            },
            created_at=timestamp,
            updated_at=timestamp,
        ),
        claim.customer_id,
    )
    return repository


def _dispatcher() -> StaffToolDispatcher:
    return StaffToolDispatcher(
        _repository(),
        Principal(
            subject='stf_tool_reader',
            actor_type='staff',
            scopes=frozenset({'workbench:read'}),
            auth_source='test:verified',
            synthetic=True,
        ),
    )


def _execute(
    dispatcher: StaffToolDispatcher,
    tool_name: str,
    arguments: dict[str, object],
    ordinal: int,
) -> StaffToolResult:
    return dispatcher.execute(
        tool_name,
        arguments,
        call_id=f'call-{ordinal}',
        correlation_id='turn-staff-tools',
        registry_version='v1.0',
        purpose=(
            STAFF_TOOL_REGISTRY[tool_name].purpose
            if tool_name in STAFF_TOOL_REGISTRY
            else 'unknown'
        ),
    )


def test_claim_session_and_evidence_tools_preserve_scope_and_sources() -> None:
    dispatcher = _dispatcher()

    claim_search = _execute(
        dispatcher,
        'staff.claim.search',
        {'created_date': '2026-09-14'},
        1,
    )
    claim_read = _execute(
        dispatcher,
        'staff.claim.read',
        {'claim_id': 'clm_staff_tool'},
        2,
    )
    session_search = _execute(
        dispatcher,
        'staff.session.search',
        {'claim_id': 'clm_staff_tool', 'message_contains': 'corrected address'},
        3,
    )
    session_read = _execute(
        dispatcher,
        'staff.session.read',
        {'claim_id': 'clm_staff_tool', 'session_id': 'ses_staff_tool'},
        4,
    )
    evidence_list = _execute(
        dispatcher,
        'staff.evidence.list',
        {'claim_id': 'clm_staff_tool', 'kind': 'incident_photo'},
        5,
    )
    evidence_read = _execute(
        dispatcher,
        'staff.evidence.read',
        {'claim_id': 'clm_staff_tool', 'evidence_id': 'evd_staff_tool'},
        6,
    )

    assert claim_search.status == 'succeeded'
    assert claim_search.record_ids == ['clm_staff_tool']
    assert claim_read.source_refs == ['clm_staff_tool']
    assert session_search.record_ids == ['ses_staff_tool']
    assert session_read.record_ids == ['ses_staff_tool', 'msg_staff_tool']
    assert evidence_list.record_ids == ['evd_staff_tool']
    assert evidence_read.source_refs == ['clm_staff_tool', 'evd_staff_tool']
    assert 'storage_key' not in str(evidence_read.output)
    assert 'provider_private_detail' not in str(evidence_read.output)
    assert evidence_read.limitations == [
        'Raw bytes and storage-owned provenance were not read or disclosed.'
    ]


def test_dispatch_rejects_unknown_malformed_duplicate_and_non_staff_calls() -> None:
    dispatcher = _dispatcher()
    unknown = _execute(dispatcher, 'staff.claim.unknown', {}, 1)
    malformed_name = _execute(dispatcher, 'drop database', {}, 9)
    malformed = _execute(
        dispatcher,
        'staff.claim.read',
        {'claim_id': 'clm_staff_tool', 'arbitrary_collection': 'claims'},
        2,
    )
    first = _execute(
        dispatcher,
        'staff.claim.read',
        {'claim_id': 'clm_staff_tool'},
        3,
    )
    duplicate = _execute(
        dispatcher,
        'staff.claim.read',
        {'claim_id': 'clm_staff_tool'},
        3,
    )
    claimant_dispatcher = StaffToolDispatcher(
        _repository(), Principal(subject='cus_staff_tool', actor_type='claimant')
    )
    denied = _execute(
        claimant_dispatcher,
        'staff.claim.read',
        {'claim_id': 'clm_staff_tool'},
        4,
    )
    unscoped_dispatcher = StaffToolDispatcher(
        _repository(), Principal(subject='stf_unscoped', actor_type='staff')
    )
    unscoped = _execute(
        unscoped_dispatcher,
        'staff.claim.read',
        {'claim_id': 'clm_staff_tool'},
        5,
    )
    version_mismatch = dispatcher.execute(
        'staff.claim.read',
        {'claim_id': 'clm_staff_tool'},
        call_id='call-version',
        correlation_id='turn-staff-tools',
        registry_version='v9.9',
        purpose='staff_claim_context',
    )
    purpose_denied = dispatcher.execute(
        'staff.claim.read',
        {'claim_id': 'clm_staff_tool'},
        call_id='call-purpose',
        correlation_id='turn-staff-tools',
        registry_version='v1.0',
        purpose='unrestricted_database_scan',
    )

    assert unknown.failure_code == 'UNKNOWN_TOOL'
    assert malformed_name.failure_code == 'UNKNOWN_TOOL'
    assert malformed_name.tool_name == 'staff.runtime.unknown'
    assert malformed.failure_code == 'INVALID_TOOL_ARGUMENTS'
    assert first.status == 'succeeded'
    assert duplicate.failure_code == 'DUPLICATE_CALL_ID'
    assert denied.status == 'denied'
    assert denied.failure_code == 'ACCESS_DENIED'
    assert unscoped.status == 'denied'
    assert unscoped.failure_code == 'ACCESS_DENIED'
    assert version_mismatch.failure_code == 'REGISTRY_VERSION_MISMATCH'
    assert purpose_denied.status == 'denied'
    assert purpose_denied.failure_code == 'PURPOSE_DENIED'


def test_cross_claim_identifiers_and_empty_collections_do_not_widen_scope() -> None:
    dispatcher = _dispatcher()
    wrong_session = _execute(
        dispatcher,
        'staff.session.read',
        {'claim_id': 'clm_staff_tool', 'session_id': 'ses_other_claim'},
        1,
    )
    wrong_evidence = _execute(
        dispatcher,
        'staff.evidence.read',
        {'claim_id': 'clm_staff_tool', 'evidence_id': 'evd_other_claim'},
        2,
    )
    no_policy = _execute(
        dispatcher,
        'staff.policy.history',
        {'claim_id': 'clm_staff_tool'},
        3,
    )

    assert wrong_session.status == 'no_result'
    assert wrong_session.output == {}
    assert wrong_evidence.status == 'no_result'
    assert wrong_evidence.output == {}
    assert no_policy.status == 'no_result'
    assert no_policy.output == {'items': []}
    assert no_policy.effective_filters == {'claim_id': 'clm_staff_tool', 'limit': 10}


def test_every_remaining_handler_is_bound_and_reports_truthful_availability() -> None:
    dispatcher = _dispatcher()
    empty_tools = (
        'staff.handoff.read',
        'staff.review_signal.read',
        'staff.work_item.list',
        'staff.customer_update.read',
    )
    for ordinal, tool_name in enumerate(empty_tools, start=1):
        result = _execute(dispatcher, tool_name, {'claim_id': 'clm_staff_tool'}, ordinal)
        assert result.status == 'no_result'
        assert result.query_scope

    knowledge = _execute(
        dispatcher,
        'staff.knowledge.search',
        {
            'question': 'What policy applies?',
            'jurisdiction': 'NZ',
            'visibility': 'customer_and_staff',
            'authority': 'approved',
            'version': '1.0',
            'insurer': 'Northwind',
            'product': 'motor',
            'effective_at': '2026-09-14T00:00:00Z',
        },
        5,
    )
    external = _execute(
        dispatcher,
        'staff.external_task.status',
        {'claim_id': 'clm_staff_tool'},
        6,
    )

    assert knowledge.status == 'unavailable'
    assert knowledge.failure_code == 'SOURCE_UNAVAILABLE'
    assert knowledge.retryable is True
    assert external.status == 'unavailable'
    assert external.failure_code == 'SOURCE_UNAVAILABLE'


def test_knowledge_tool_preserves_governed_citation_identity() -> None:
    dispatcher = StaffToolDispatcher(
        _repository(),
        Principal(
            subject='stf_tool_reader',
            actor_type='staff',
            scopes=frozenset({'workbench:read'}),
        ),
        knowledge_retriever=_KnowledgeRetriever(),
    )
    result = _execute(
        dispatcher,
        'staff.knowledge.search',
        {
            'question': 'What policy applies?',
            'jurisdiction': 'NZ',
            'visibility': 'customer_and_staff',
            'authority': 'approved',
            'version': '1.0',
            'insurer': 'Northwind',
            'product': 'motor',
            'effective_at': '2026-09-14T00:00:00Z',
        },
        1,
    )

    assert result.status == 'succeeded'
    assert result.record_ids == ['chunk_collision']
    assert result.source_refs == ['knowledge:doc_motor_wording:chunk_collision:1.0']
    assert result.output['items'][0]['checksum'] == 'sha256:synthetic'
