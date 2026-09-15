from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import mongomock
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.auth import Principal, require_staff
from backend.core.config import IdentityMode, Settings
from backend.domain.agent_tool_registry import STAFF_TOOL_REGISTRY
from backend.domain.knowledge import KnowledgeChunk, KnowledgeSearch
from backend.domain.models import (
    Channel,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    HandoffPacket,
    HandoffPriority,
    HandoffRecord,
    HandoffStatus,
    HandoffTrigger,
    HandoffType,
    MessageRecord,
    MessageVisibility,
    NeededFor,
    ResponsibleParty,
    SessionRecord,
    SupportNeed,
    WorkflowState,
    WorkingClaim,
)
from backend.domain.staff_agent_tools import (
    STAFF_SESSION_MAX_EXAMINED,
    STAFF_SESSION_MESSAGE_MAX_EXAMINED,
    StaffToolResult,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services.agent import ControlledAgent
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
            roles=frozenset({'claims_professional'}),
        ),
    )


def _staff_principal() -> Principal:
    return Principal(
        subject='stf_tool_reader',
        actor_type='staff',
        scopes=frozenset({'workbench:read'}),
        auth_source='test:verified',
        synthetic=True,
        roles=frozenset({'claims_professional'}),
    )


def _seed_bounded_search(repository: PersistenceRepository) -> None:
    base = datetime(2026, 9, 14, 2, 30, tzinfo=UTC)
    cases = (
        ('clm_older_match', 'cus_older_match', base, WorkflowState.AWAITING_EVIDENCE, 'stf_match'),
        (
            'clm_newer_non_match',
            'cus_newer_non_match',
            base + timedelta(hours=1),
            WorkflowState.COLLECTING,
            'stf_other',
        ),
    )
    for claim_id, customer_id, timestamp, workflow_state, assignee_id in cases:
        session_id = f'ses_{claim_id}'
        claim = WorkingClaim(
            claim_id=claim_id,
            customer_id=customer_id,
            channel=Channel.WEB_AGENT,
            locale='en-NZ',
            claim_state={'workflow_state': workflow_state},
            assignee_id=assignee_id,
            active_session_id=session_id,
            customer_next_step=CustomerNextStep(
                status='continue_claim',
                summary='Continue the claim.',
                responsible_party=ResponsibleParty.CLAIMANT,
            ),
            created_at=timestamp,
            updated_at=timestamp,
        )
        repository.create_claim(
            claim,
            SessionRecord(
                session_id=session_id,
                claim_id=claim_id,
                customer_id=customer_id,
                started_at=timestamp,
                last_active_at=timestamp,
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


def test_dispatch_rejects_staff_without_an_allowed_registry_role() -> None:
    dispatcher = StaffToolDispatcher(
        _repository(),
        Principal(
            subject='stf_restricted',
            actor_type='staff',
            scopes=frozenset({'workbench:read'}),
            roles=frozenset({'claims_observer'}),
            auth_source='test:verified',
        ),
    )
    result = _execute(dispatcher, 'staff.claim.read', {'claim_id': 'clm_staff_tool'}, 1)

    assert result.status == 'denied'
    assert result.failure_code == 'ACCESS_DENIED'


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
    assert wrong_session.output.model_dump(mode='json') == {}
    assert wrong_evidence.status == 'no_result'
    assert wrong_evidence.output.model_dump(mode='json') == {}
    assert no_policy.status == 'no_result'
    assert no_policy.output.model_dump(mode='json') == {'items': []}
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
            roles=frozenset({'claims_professional'}),
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
    assert result.output.model_dump(mode='json')['items'][0]['checksum'] == 'sha256:synthetic'


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb'])
@pytest.mark.parametrize(
    ('filters', 'matched_field'),
    [
        ({'queue': 'waiting_user', 'limit': 1}, 'queue'),
        ({'assignee_id': 'stf_match', 'limit': 1}, 'assignee_id'),
        ({'lifecycle_state': 'waiting_customer', 'limit': 1}, 'lifecycle_state'),
    ],
)
def test_claim_search_applies_derived_filters_before_limit(
    repository_kind: str,
    filters: dict[str, object],
    matched_field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository: PersistenceRepository
    if repository_kind == 'fixture':
        repository = FixtureRepository()
    else:
        mongo_repository = MongoDBRepository(
            mongomock.MongoClient(), f'staff_search_{matched_field}'
        )

        def without_transaction(operation: Callable[[Any], Any]) -> Any:
            return operation(None)

        monkeypatch.setattr(mongo_repository, '_atomic', without_transaction)
        repository = mongo_repository
    _seed_bounded_search(repository)
    dispatcher = StaffToolDispatcher(repository, _staff_principal())

    result = _execute(dispatcher, 'staff.claim.search', filters, 1)

    assert result.status == 'succeeded'
    assert result.record_ids == ['clm_older_match']
    assert result.output.model_dump(mode='json')['items'][0]['matched_fields'] == [matched_field]


def test_claim_search_does_not_build_workbench_projections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FixtureRepository()
    _seed_bounded_search(repository)

    def reject_full_projection(*_args: object, **_kwargs: object) -> None:
        raise AssertionError('Claim search must not build a full Workbench projection.')

    monkeypatch.setattr(
        'backend.services.staff_agent_tools.get_workbench_claim_detail',
        reject_full_projection,
    )
    result = _execute(
        StaffToolDispatcher(repository, _staff_principal()),
        'staff.claim.search',
        {'queue': 'waiting_user', 'limit': 1},
        1,
    )

    assert result.status == 'succeeded'
    assert result.record_ids == ['clm_older_match']


def test_mongodb_claim_search_uses_indexed_projection_and_database_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'bounded_staff_search')

    def without_transaction(operation: Callable[[Any], Any]) -> Any:
        return operation(None)

    monkeypatch.setattr(repository, '_atomic', without_transaction)
    _seed_bounded_search(repository)
    original_find = repository._collection.find
    observed: dict[str, Any] = {'child_reads': 0, 'limit': None, 'query': None}

    class _TrackedCursor:
        def __init__(self, cursor: Any) -> None:
            self._cursor = cursor

        def sort(self, *args: Any, **kwargs: Any) -> '_TrackedCursor':
            self._cursor = self._cursor.sort(*args, **kwargs)
            return self

        def limit(self, value: int) -> '_TrackedCursor':
            observed['limit'] = value
            self._cursor = self._cursor.limit(value)
            return self

        def __iter__(self) -> Any:
            return iter(self._cursor)

    def tracked_find(*args: Any, **kwargs: Any) -> Any:
        query = args[0] if args else kwargs.get('filter', {})
        if query.get('record_type') in {'evidence', 'handoff'}:
            observed['child_reads'] = int(observed['child_reads']) + 1
        cursor = original_find(*args, **kwargs)
        if query.get('record_type') == 'claim':
            observed['query'] = query
            return _TrackedCursor(cursor)
        return cursor

    monkeypatch.setattr(repository._collection, 'find', tracked_find)

    matches = repository.search_claims_internal({'queue': 'waiting_user'}, 1)

    assert [item.claim.claim_id for item in matches] == ['clm_older_match']
    assert observed == {
        'child_reads': 0,
        'limit': 1,
        'query': {'record_type': 'claim', 'staff_search.queue': 'waiting_user'},
    }


def test_mongodb_repository_backfills_legacy_staff_search_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'legacy_staff_search')

    def without_transaction(operation: Callable[[Any], Any]) -> Any:
        return operation(None)

    monkeypatch.setattr(repository, '_atomic', without_transaction)
    _seed_bounded_search(repository)
    repository._collection.update_many(
        {'record_type': 'claim'},
        {'$unset': {'staff_search': ''}},
    )

    repository._backfill_staff_search_projections()
    matches = repository.search_claims_internal({'queue': 'waiting_user'}, 1)

    assert [item.claim.claim_id for item in matches] == ['clm_older_match']
    assert (
        repository._collection.count_documents(
            {'record_type': 'claim', 'staff_search': {'$exists': True}}
        )
        == 2
    )


def test_mongodb_child_writes_refresh_staff_search_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'child_staff_search')

    def without_transaction(operation: Callable[[Any], Any]) -> Any:
        return operation(None)

    monkeypatch.setattr(repository, '_atomic', without_transaction)
    _seed_bounded_search(repository)
    claim_id = 'clm_older_match'
    customer_id = 'cus_older_match'
    timestamp = datetime(2026, 9, 14, 4, 0, tzinfo=UTC)
    repository.save_evidence(
        EvidenceRecord(
            evidence_id='evd_waiting_material',
            claim_id=claim_id,
            kind='incident_photo',
            status=EvidenceStatus.PENDING,
            file_status=EvidenceFileStatus.AWAITING_UPLOAD,
            source=EvidenceSource.CLAIMANT,
            needed_for=[NeededFor.CURRENT_ACTION],
            responsible_party=ResponsibleParty.CLAIMANT,
            created_at=timestamp,
            updated_at=timestamp,
        ),
        customer_id,
    )

    waiting = repository.search_claims_internal({'queue': 'waiting_material'}, 1)
    assert [item.claim.claim_id for item in waiting] == [claim_id]

    repository.save_handoff(
        HandoffRecord(
            handoff_id='hnd_staff_search',
            claim_id=claim_id,
            type=HandoffType.HUMAN_SUPPORT,
            status=HandoffStatus.REQUESTED,
            priority=HandoffPriority.STANDARD,
            queue='human_support',
            support_need=SupportNeed.HUMAN_REQUESTED,
            trigger=HandoffTrigger.CLAIMANT_SUPPORT_REQUEST,
            reason_codes=['HUMAN_SUPPORT_REQUESTED'],
            reason='The claimant requested staff support.',
            requested_action='Continue the report with staff support.',
            applied_rule='human_support_request',
            packet=HandoffPacket(
                form_revision=1,
                promised_next_step='Northwind staff will continue the report.',
            ),
            created_at=timestamp,
        ),
        customer_id,
    )

    supported = repository.search_claims_internal(
        {'lifecycle_state': 'staff_support', 'assignee_id': 'stf_match'}, 1
    )
    assert [item.claim.claim_id for item in supported] == [claim_id]


def test_dispatch_rejects_handler_fields_outside_registered_output_schema() -> None:
    dispatcher = _dispatcher()

    def leaking_handler(
        _payload: object,
    ) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
        return (
            [
                {
                    'claim_id': 'clm_staff_tool',
                    'display_reference': 'clm_staff_tool',
                    'revision': 1,
                    'incident': {'family': None, 'summary': 'Claim details'},
                    'lifecycle_state': 'draft_active',
                    'workflow_state': 'collecting',
                    'ownership': {
                        'state': 'unassigned',
                        'coworkers': [],
                        'coworker_count': 0,
                        'current_staff_access': 'read_only',
                        'pending_cowork_requests': 0,
                        'pending_transfer_requests': 0,
                    },
                    'work_summary': {
                        'queue_key': 'processing',
                        'missing_information': [],
                        'risk_signals': [],
                    },
                    'integration_summary': {'waiting_external_services': []},
                    'customer_next_step': {
                        'status': 'describe_incident',
                        'summary': 'Describe the incident.',
                        'responsible_party': 'claimant',
                    },
                    'created_at': '2026-09-14T02:30:00Z',
                    'updated_at': '2026-09-14T02:30:00Z',
                    'storage_key': 'must-fail-closed',
                }
            ],
            [],
            [],
            [],
        )

    dispatcher._handlers['staff.claim.read'] = leaking_handler
    result = _execute(
        dispatcher,
        'staff.claim.read',
        {'claim_id': 'clm_staff_tool'},
        1,
    )

    assert result.status == 'failed'
    assert result.failure_code == 'INVALID_TOOL_OUTPUT'
    assert result.output.model_dump(mode='json') == {}


def test_synthetic_credentials_enforce_staff_tool_role_boundary() -> None:
    repository = _repository()
    app = create_app(
        Settings(environment='test', identity_mode=IdentityMode.DEVELOPER),
        repository,
        ControlledAgent(),
    )

    @app.get('/__staff_tool_auth_test')
    def execute_claim_search(
        principal: Annotated[Principal, Depends(require_staff)],
    ) -> StaffToolResult:
        return _execute(
            StaffToolDispatcher(repository, principal),
            'staff.claim.search',
            {'created_date': '2026-09-14'},
            1,
        )

    with TestClient(app) as client:
        staff_response = client.get(
            '/__staff_tool_auth_test',
            headers={'Authorization': 'Bearer synthetic-staff'},
        )
        claimant_response = client.get(
            '/__staff_tool_auth_test',
            headers={'Authorization': 'Bearer synthetic-claimant'},
        )

    assert staff_response.status_code == 200
    assert staff_response.json()['status'] == 'succeeded'
    assert staff_response.json()['record_ids'] == ['clm_staff_tool']
    assert claimant_response.status_code == 403
    assert claimant_response.json()['error']['code'] == 'ACCESS_DENIED'


def test_session_read_projects_only_closed_text_content() -> None:
    repository = _repository()
    timestamp = datetime(2026, 9, 14, 2, 31, tzinfo=UTC)
    repository.save_message(
        MessageRecord(
            message_id='msg_nested_storage_data',
            claim_id='clm_staff_tool',
            session_id='ses_staff_tool',
            actor='agent',
            visibility=MessageVisibility.CLAIMANT_VISIBLE,
            content={
                'type': 'text',
                'text': 'This text is safe for the Staff Agent.',
                'model_internal': {'storage_key': 'must-not-leak'},
            },
            created_at=timestamp,
        ),
        'cus_staff_tool',
    )
    repository.save_message(
        MessageRecord(
            message_id='msg_unsupported_content',
            claim_id='clm_staff_tool',
            session_id='ses_staff_tool',
            actor='system',
            visibility=MessageVisibility.INTERNAL_ONLY,
            content={'type': 'internal_trace', 'text': 'unsupported-search-secret'},
            created_at=timestamp + timedelta(seconds=1),
        ),
        'cus_staff_tool',
    )
    dispatcher = StaffToolDispatcher(repository, _staff_principal())

    read_result = _execute(
        dispatcher,
        'staff.session.read',
        {'claim_id': 'clm_staff_tool', 'session_id': 'ses_staff_tool'},
        1,
    )
    hidden_search = _execute(
        dispatcher,
        'staff.session.search',
        {'claim_id': 'clm_staff_tool', 'message_contains': 'must-not-leak'},
        2,
    )
    unsupported_search = _execute(
        dispatcher,
        'staff.session.search',
        {'claim_id': 'clm_staff_tool', 'message_contains': 'unsupported-search-secret'},
        3,
    )

    output = read_result.output.model_dump(mode='json')
    assert output['items'][0]['messages'][-1]['content'] == {
        'type': 'text',
        'text': 'This text is safe for the Staff Agent.',
    }
    assert 'model_internal' not in str(output)
    assert 'customer_id' not in output['items'][0]['session']
    assert hidden_search.status == 'no_result'
    assert unsupported_search.status == 'no_result'


def test_fixture_session_search_stops_before_unrelated_session_messages() -> None:
    repository = _repository()
    timestamp = datetime(2026, 9, 14, 3, 30, tzinfo=UTC)
    newest = SessionRecord(
        session_id='ses_newest_match',
        claim_id='clm_staff_tool',
        customer_id='cus_staff_tool',
        started_at=timestamp,
        last_active_at=timestamp,
    )
    repository.save_session(newest)
    repository.save_message(
        MessageRecord(
            message_id='msg_newest_match',
            claim_id=newest.claim_id,
            session_id=newest.session_id,
            actor='claimant',
            visibility=MessageVisibility.CLAIMANT_VISIBLE,
            content={'type': 'text', 'text': 'The bounded match is here.'},
            created_at=timestamp,
        ),
        newest.customer_id,
    )
    repository._message_ids_by_session['ses_staff_tool'] = ['unrelated-message-must-not-load']

    result = _execute(
        StaffToolDispatcher(repository, _staff_principal()),
        'staff.session.search',
        {
            'claim_id': 'clm_staff_tool',
            'message_contains': 'bounded match',
            'limit': 1,
        },
        1,
    )

    assert result.status == 'succeeded'
    assert result.record_ids == ['ses_newest_match']


@pytest.mark.parametrize('repository_kind', ['fixture', 'mongodb'])
def test_session_search_filters_before_limit_with_repository_parity(
    repository_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository: PersistenceRepository
    if repository_kind == 'fixture':
        repository = FixtureRepository()
    else:
        mongo_repository = MongoDBRepository(
            mongomock.MongoClient(), f'bounded_session_search_{repository_kind}'
        )

        def without_transaction(operation: Callable[[Any], Any]) -> Any:
            return operation(None)

        monkeypatch.setattr(mongo_repository, '_atomic', without_transaction)
        repository = mongo_repository
    timestamp = datetime(2026, 9, 14, 2, 30, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id='clm_session_boundary',
        customer_id='cus_session_boundary',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id='ses_newer_non_match',
        customer_next_step=CustomerNextStep(
            status='continue_claim',
            summary='Continue the claim.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    older = SessionRecord(
        session_id='ses_older_match',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=timestamp,
        last_active_at=timestamp,
    )
    newer = SessionRecord(
        session_id='ses_newer_non_match',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=timestamp + timedelta(hours=1),
        last_active_at=timestamp + timedelta(hours=1),
    )
    repository.create_claim(claim, newer)
    repository.save_session(older)
    repository.save_message(
        MessageRecord(
            message_id='msg_older_match',
            claim_id=claim.claim_id,
            session_id=older.session_id,
            actor='staff',
            visibility=MessageVisibility.INTERNAL_ONLY,
            content={'type': 'text', 'text': 'The address was corrected.'},
            created_at=timestamp,
        ),
        claim.customer_id,
    )

    matches = repository.search_sessions_internal(
        claim.claim_id,
        claim.customer_id,
        {'actor': 'staff', 'message_contains': 'corrected'},
        1,
    )

    assert [candidate.session.session_id for candidate in matches] == ['ses_older_match']
    assert matches[0].message_count == 1


def test_session_search_fails_closed_above_examined_cap() -> None:
    repository = _repository()
    timestamp = datetime(2026, 9, 14, 4, 0, tzinfo=UTC)
    for ordinal in range(STAFF_SESSION_MAX_EXAMINED):
        repository.save_session(
            SessionRecord(
                session_id=f'ses_unmatched_{ordinal:03}',
                claim_id='clm_staff_tool',
                customer_id='cus_staff_tool',
                started_at=timestamp + timedelta(minutes=ordinal),
                last_active_at=timestamp + timedelta(minutes=ordinal),
            )
        )

    result = _execute(
        StaffToolDispatcher(repository, _staff_principal()),
        'staff.session.search',
        {'claim_id': 'clm_staff_tool', 'actor': 'staff', 'limit': 1},
        1,
    )

    assert result.status == 'unavailable'
    assert result.failure_code == 'SEARCH_SCOPE_EXCEEDED'


def test_session_message_search_fails_closed_above_examined_cap() -> None:
    repository = _repository()
    timestamp = datetime(2026, 9, 14, 4, 0, tzinfo=UTC)
    for ordinal in range(STAFF_SESSION_MESSAGE_MAX_EXAMINED):
        repository.save_message(
            MessageRecord(
                message_id=f'msg_unmatched_{ordinal:03}',
                claim_id='clm_staff_tool',
                session_id='ses_staff_tool',
                actor='claimant',
                visibility=MessageVisibility.CLAIMANT_VISIBLE,
                content={'type': 'text', 'text': 'No matching term.'},
                created_at=timestamp + timedelta(seconds=ordinal),
            ),
            'cus_staff_tool',
        )

    result = _execute(
        StaffToolDispatcher(repository, _staff_principal()),
        'staff.session.search',
        {'claim_id': 'clm_staff_tool', 'message_contains': 'absent term'},
        1,
    )

    assert result.status == 'unavailable'
    assert result.failure_code == 'SEARCH_SCOPE_EXCEEDED'


def test_mongodb_session_message_search_fails_closed_above_examined_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'session_message_examined_cap')

    def without_transaction(operation: Callable[[Any], Any]) -> Any:
        return operation(None)

    monkeypatch.setattr(repository, '_atomic', without_transaction)
    timestamp = datetime(2026, 9, 14, 4, 0, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id='clm_mongo_session_cap',
        customer_id='cus_mongo_session_cap',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id='ses_mongo_session_cap',
        customer_next_step=CustomerNextStep(
            status='continue_claim',
            summary='Continue the claim.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id=claim.active_session_id,
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        started_at=timestamp,
        last_active_at=timestamp,
    )
    repository.create_claim(claim, session)
    for ordinal in range(STAFF_SESSION_MESSAGE_MAX_EXAMINED + 1):
        repository.save_message(
            MessageRecord(
                message_id=f'msg_mongo_cap_{ordinal:03}',
                claim_id=claim.claim_id,
                session_id=session.session_id,
                actor='claimant',
                visibility=MessageVisibility.CLAIMANT_VISIBLE,
                content={'type': 'text', 'text': 'No matching term.'},
                created_at=timestamp + timedelta(seconds=ordinal),
            ),
            claim.customer_id,
        )

    result = _execute(
        StaffToolDispatcher(repository, _staff_principal()),
        'staff.session.search',
        {'claim_id': claim.claim_id, 'actor': 'claimant', 'limit': 1},
        1,
    )

    assert result.status == 'unavailable'
    assert result.failure_code == 'SEARCH_SCOPE_EXCEEDED'


def test_mongodb_session_search_stops_message_reads_after_small_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'session_search_read_bound')

    def without_transaction(operation: Callable[[Any], Any]) -> Any:
        return operation(None)

    monkeypatch.setattr(repository, '_atomic', without_transaction)
    timestamp = datetime(2026, 9, 14, 2, 30, tzinfo=UTC)
    claim = WorkingClaim(
        claim_id='clm_session_read_bound',
        customer_id='cus_session_read_bound',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        active_session_id='ses_newest_match',
        customer_next_step=CustomerNextStep(
            status='continue_claim',
            summary='Continue the claim.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    sessions = [
        SessionRecord(
            session_id=session_id,
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            started_at=timestamp + timedelta(hours=offset),
            last_active_at=timestamp + timedelta(hours=offset),
        )
        for session_id, offset in (('ses_older_unrelated', 0), ('ses_newest_match', 1))
    ]
    repository.create_claim(claim, sessions[1])
    repository.save_session(sessions[0])
    for session in sessions:
        repository.save_message(
            MessageRecord(
                message_id=f'msg_{session.session_id}',
                claim_id=claim.claim_id,
                session_id=session.session_id,
                actor='claimant',
                visibility=MessageVisibility.CLAIMANT_VISIBLE,
                content={'type': 'text', 'text': 'bounded target'},
                created_at=session.started_at,
            ),
            claim.customer_id,
        )
    original_find = repository._collection.find
    message_session_reads: list[str] = []
    session_limit: list[int] = []

    class _TrackedCursor:
        def __init__(self, cursor: Any) -> None:
            self._cursor = cursor

        def sort(self, *args: Any, **kwargs: Any) -> '_TrackedCursor':
            self._cursor = self._cursor.sort(*args, **kwargs)
            return self

        def limit(self, value: int) -> '_TrackedCursor':
            session_limit.append(value)
            self._cursor = self._cursor.limit(value)
            return self

        def __iter__(self) -> Any:
            return iter(self._cursor)

    def tracked_find(*args: Any, **kwargs: Any) -> Any:
        query = args[0] if args else kwargs.get('filter', {})
        cursor = original_find(*args, **kwargs)
        if query.get('record_type') == 'session':
            return _TrackedCursor(cursor)
        if query.get('record_type') == 'message':
            message_session_reads.append(str(query.get('session_id')))
        return cursor

    monkeypatch.setattr(repository._collection, 'find', tracked_find)

    matches = repository.search_sessions_internal(
        claim.claim_id,
        claim.customer_id,
        {'message_contains': 'bounded target'},
        1,
    )

    assert [candidate.session.session_id for candidate in matches] == ['ses_newest_match']
    assert session_limit == [STAFF_SESSION_MAX_EXAMINED + 1]
    assert set(message_session_reads) == {'ses_newest_match'}
