"""MongoDB persistence primitives for the provider-neutral repository contract.

The adapter is intentionally not selected by the runtime profile yet.  The
MongoDB bundle must implement the complete contract before ``DATA_RUNTIME_PROFILE``
can enable it.  This module provides the first durable slice and keeps provider
document details below the repository boundary.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError, PyMongoError

from backend.domain.audit import AuditEventEnvelope, AuditSubject
from backend.domain.external_services import (
    ExternalTaskEvidenceLink,
    ExternalTaskRecord,
    ExternalTaskRequest,
    ExternalTaskResult,
    ExternalTaskResultVerification,
    assert_disclosure_within_consent,
    assert_request_matches_task,
    assert_result_advance_is_permitted,
    assert_result_evidence_is_linked,
    assert_result_matches_task,
)
from backend.domain.models import (
    ActorType,
    AgentDecisionRecord,
    AssessorRoutingOperation,
    AssessorRoutingOperationStatus,
    AuthorityOutcome,
    BranchEvaluationRecord,
    BranchEvaluationStatus,
    ClaimCollaborationRequest,
    ClaimCoworkerRecord,
    CustomerUpdateRecord,
    EvidenceRecord,
    HandoffRecord,
    MessageRecord,
    SessionRecord,
    SessionStatus,
    SignalDecisionRecord,
    StaffActionRecord,
    WorkingClaim,
)
from backend.domain.retrieval import (
    ClaimHistoryRetrievalRecord,
    PolicyRetrievalRecord,
    RetrievalKind,
    RetrievalRecord,
    ReviewSignalRecord,
)
from backend.domain.staff_agent import StaffAgentMessage, StaffAgentSession
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    RevisionConflict,
)

ModelT = TypeVar('ModelT', bound=BaseModel)
_DATETIME_ADAPTER = TypeAdapter(datetime)


class MongoDBConfigurationError(ValueError):
    """MongoDB configuration is missing, invalid, or cannot be verified."""


@dataclass(frozen=True, slots=True)
class MongoDBConnectionConfig:
    uri: str = field(repr=False)
    database_name: str
    collection_name: str = 'northwind_records'
    server_selection_timeout_ms: int = 5_000

    @classmethod
    def from_environment(cls) -> 'MongoDBConnectionConfig':
        uri = os.getenv('NORTHWIND_MONGODB_URI', '').strip()
        database_name = os.getenv('NORTHWIND_MONGODB_DATABASE', '').strip()
        collection_name = os.getenv('NORTHWIND_MONGODB_COLLECTION', 'northwind_records').strip()
        raw_timeout = os.getenv('NORTHWIND_MONGODB_SERVER_SELECTION_TIMEOUT_MS', '5000').strip()

        missing = [
            name
            for name, value in (
                ('NORTHWIND_MONGODB_URI', uri),
                ('NORTHWIND_MONGODB_DATABASE', database_name),
                ('NORTHWIND_MONGODB_COLLECTION', collection_name),
            )
            if not value
        ]
        if missing:
            raise MongoDBConfigurationError(
                f'Missing required MongoDB configuration: {", ".join(missing)}.'
            )
        try:
            timeout = int(raw_timeout)
        except ValueError as error:
            raise MongoDBConfigurationError(
                'NORTHWIND_MONGODB_SERVER_SELECTION_TIMEOUT_MS must be an integer.'
            ) from error
        if not 100 <= timeout <= 60_000:
            raise MongoDBConfigurationError(
                'NORTHWIND_MONGODB_SERVER_SELECTION_TIMEOUT_MS must be between 100 and 60000.'
            )
        if any(character in database_name for character in '/\\. "$'):
            raise MongoDBConfigurationError('NORTHWIND_MONGODB_DATABASE is invalid.')
        if collection_name.startswith('system.') or '\x00' in collection_name:
            raise MongoDBConfigurationError('NORTHWIND_MONGODB_COLLECTION is invalid.')
        return cls(
            uri=uri,
            database_name=database_name,
            collection_name=collection_name,
            server_selection_timeout_ms=timeout,
        )


def connect_mongodb_repository(config: MongoDBConnectionConfig) -> 'MongoDBRepository':
    """Connect and verify MongoDB before exposing the persistence adapter."""

    client: MongoClient[Any] | None = None
    try:
        client = MongoClient(
            config.uri,
            serverSelectionTimeoutMS=config.server_selection_timeout_ms,
        )
        client.admin.command('ping')
        return MongoDBRepository(
            client,
            config.database_name,
            collection_name=config.collection_name,
        )
    except (PyMongoError, ValueError):
        if client is not None:
            client.close()
        raise MongoDBConfigurationError(
            'MongoDB connection or repository initialisation failed.'
        ) from None


def probe_mongodb_connectivity(config: MongoDBConnectionConfig) -> str:
    """Ping MongoDB without constructing a repository or changing provider state."""

    client: MongoClient[Any] | None = None
    try:
        client = MongoClient(
            config.uri,
            serverSelectionTimeoutMS=config.server_selection_timeout_ms,
        )
        client.admin.command('ping')
        return 'verified'
    except (PyMongoError, ValueError):
        return 'unavailable'
    finally:
        if client is not None:
            client.close()


IMMUTABLE_CHILD_RECORD_KINDS = frozenset({'message', 'agent_decision', 'branch_evaluation'})
"""Child records whose identity may never be rebound or rewritten once persisted."""


class MongoDBRepository:
    """MongoDB implementation of the core Claim/Session/Message boundary.

    Records are stored as typed documents in one adapter-owned collection.  The
    public API only receives domain models; MongoDB ``_id`` and discriminator
    fields never leave this module.
    """

    def __init__(
        self,
        client: MongoClient[Any],
        database_name: str,
        *,
        collection_name: str = 'northwind_records',
    ) -> None:
        self._client = client
        self._collection: Collection[dict[str, Any]] = client[database_name][collection_name]
        self._collection.create_index([('record_type', 1), ('claim_id', 1), ('created_at', 1)])
        self._collection.create_index(
            [
                ('record_type', 1),
                ('subject.subject_type', 1),
                ('subject.subject_id', 1),
                ('subject.claim_id', 1),
                ('created_at', 1),
            ]
        )
        self._collection.create_index([('record_type', 1), ('customer_id', 1), ('updated_at', -1)])
        self._collection.create_index(
            [('record_type', 1), ('actor_id', 1), ('route', 1), ('key', 1)],
            unique=True,
            partialFilterExpression={'record_type': 'idempotency'},
        )
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1), ('client_message_id', 1)],
            unique=True,
            partialFilterExpression={
                'record_type': 'message',
                'client_message_id': {'$type': 'string'},
            },
        )
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1), ('created_at', 1)],
            name='branch_evaluation_claim_created',
        )
        # One task carries one canonical result. Without this, two concurrent first
        # writes can each observe no held record and both insert.
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1), ('task_id', 1)],
            unique=True,
            name='external_task_result_task_unique',
            partialFilterExpression={'record_type': 'external_task_result'},
        )

    def connection_status(self) -> str:
        try:
            self._client.admin.command('ping')
        except (PyMongoError, ValueError):
            return 'unavailable'
        return 'verified'

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _record_id(kind: str, identifier: str) -> str:
        return f'{kind}:{identifier}'

    def _put(
        self,
        kind: str,
        identifier: str,
        model: Any,
        *,
        customer_id: str | None = None,
        claim_id: str | None = None,
        session: Any = None,
    ) -> None:
        document = model.model_dump(mode='json')
        document.update(
            {
                '_id': self._record_id(kind, identifier),
                'record_type': kind,
                'customer_id': customer_id,
                'claim_id': claim_id,
            }
        )
        existing = self._collection.find_one(
            {'_id': document['_id'], 'record_type': kind},
            projection={'claim_id': 1, 'customer_id': 1},
            session=session,
        )
        if existing is not None and (
            existing.get('claim_id') != claim_id or existing.get('customer_id') != customer_id
        ):
            raise IdempotencyConflict(identifier)
        self._reject_client_message_conflict(document, session=session)
        ownership_filter = {
            '_id': document['_id'],
            'record_type': kind,
            'claim_id': claim_id,
            'customer_id': customer_id,
        }
        try:
            self._collection.replace_one(
                ownership_filter,
                document,
                upsert=True,
                session=session,
            )
        except DuplicateKeyError as error:
            conflict_key = document.get('client_message_id') or identifier
            raise IdempotencyConflict(str(conflict_key)) from error

    def _reject_client_message_conflict(
        self,
        document: dict[str, Any],
        *,
        session: Any = None,
    ) -> None:
        client_message_id = document.get('client_message_id')
        if document.get('record_type') != 'message' or not client_message_id:
            return
        existing = self._collection.find_one(
            {
                'record_type': 'message',
                'claim_id': document.get('claim_id'),
                'client_message_id': client_message_id,
            },
            projection={'_id': 1},
            session=session,
        )
        if existing is not None and existing.get('_id') != document.get('_id'):
            raise IdempotencyConflict(str(client_message_id))

    def _get(
        self,
        kind: str,
        identifier: str,
        model_type: type[ModelT],
        *,
        customer_id: str | None = None,
        session: Any = None,
    ) -> ModelT | None:
        query: dict[str, Any] = {
            '_id': self._record_id(kind, identifier),
            'record_type': kind,
        }
        if customer_id is not None:
            query['customer_id'] = customer_id
        document = self._collection.find_one(query, session=session)
        return self._model_from_document(document, model_type)

    @staticmethod
    def _model_from_document(
        document: dict[str, Any] | None,
        model_type: type[ModelT],
    ) -> ModelT | None:
        if document is None:
            return None
        payload = {key: value for key, value in document.items() if key in model_type.model_fields}
        return model_type.model_validate(payload)

    @staticmethod
    def _audit_timestamp(value: datetime) -> str:
        if value.tzinfo is not None and value.utcoffset() is not None:
            value = value.astimezone(UTC)
        return str(_DATETIME_ADAPTER.dump_python(value, mode='json'))

    def _audit_document(self, event: AuditEventEnvelope) -> dict[str, Any]:
        document = event.model_dump(mode='json')
        document.update(
            {
                '_id': self._record_id('audit_event', event.event_id),
                'record_type': 'audit_event',
                'created_at': self._audit_timestamp(event.created_at),
            }
        )
        return document

    def _prepare_audit_events(
        self,
        claim: WorkingClaim,
        audit_events: tuple[AuditEventEnvelope, ...],
        *,
        mongo_session: Any,
    ) -> tuple[AuditEventEnvelope, ...]:
        prepared: dict[str, AuditEventEnvelope] = {}
        for event in audit_events:
            if event.subject.claim_id != claim.claim_id:
                raise KeyError(claim.claim_id)
            if (
                event.subject.subject_type.value == 'claim'
                and event.claim_revision != claim.revision
            ):
                raise KeyError(claim.claim_id)
            incoming = prepared.get(event.event_id)
            if incoming is not None and incoming != event:
                raise IdempotencyConflict(event.event_id)
            existing = self._collection.find_one(
                {
                    '_id': self._record_id('audit_event', event.event_id),
                    'record_type': 'audit_event',
                },
                session=mongo_session,
            )
            stored = self._model_from_document(existing, AuditEventEnvelope)
            if stored is not None and stored != event:
                raise IdempotencyConflict(event.event_id)
            prepared[event.event_id] = event
        return tuple(prepared.values())

    def _insert_audit_event(self, event: AuditEventEnvelope, *, mongo_session: Any) -> None:
        record_id = self._record_id('audit_event', event.event_id)
        existing = self._collection.find_one(
            {'_id': record_id, 'record_type': 'audit_event'},
            session=mongo_session,
        )
        stored = self._model_from_document(existing, AuditEventEnvelope)
        if stored is not None:
            if stored != event:
                raise IdempotencyConflict(event.event_id)
            return
        try:
            self._collection.insert_one(
                self._audit_document(event),
                session=mongo_session,
            )
        except DuplicateKeyError as error:
            existing = self._collection.find_one(
                {'_id': record_id, 'record_type': 'audit_event'},
                session=mongo_session,
            )
            stored = self._model_from_document(existing, AuditEventEnvelope)
            if stored != event:
                raise IdempotencyConflict(event.event_id) from error

    def append_audit_event(self, event: AuditEventEnvelope) -> None:
        """Append one immutable audit event to MongoDB.

        Args:
            event: Audit event to persist.

        Returns:
            None.

        Raises:
            IdempotencyConflict: The event identity exists with different content.
        """
        self._insert_audit_event(event, mongo_session=None)

    def list_audit_events_internal(
        self,
        subject: AuditSubject,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[AuditEventEnvelope]:
        """Return audit events for an already-authorised subject read.

        Args:
            subject: Exact logical subject to match.
            start_at: Optional inclusive lower timestamp bound.
            end_at: Optional inclusive upper timestamp bound.

        Returns:
            Matching events in stable time and identity order.

        Raises:
            ValueError: The requested time range is invalid or incomparable.
        """
        if start_at is not None and end_at is not None:
            try:
                invalid_range = start_at > end_at
            except TypeError as error:
                raise ValueError(
                    'Audit event time bounds must use comparable timestamps.'
                ) from error
            if invalid_range:
                raise ValueError('Audit event start_at must not be after end_at.')

        query: dict[str, Any] = {
            'record_type': 'audit_event',
            'subject.subject_type': subject.subject_type.value,
            'subject.subject_id': subject.subject_id,
            'subject.claim_id': subject.claim_id,
        }
        time_range: dict[str, str] = {}
        if start_at is not None:
            time_range['$gte'] = self._audit_timestamp(start_at)
        if end_at is not None:
            time_range['$lte'] = self._audit_timestamp(end_at)
        if time_range:
            query['created_at'] = time_range

        events: list[AuditEventEnvelope] = []
        for document in self._collection.find(query).sort([('created_at', 1), ('_id', 1)]):
            event = self._model_from_document(document, AuditEventEnvelope)
            if event is not None:
                events.append(event)
        return sorted(events, key=lambda event: (event.created_at, event.event_id))

    def list_audit_events_admin(
        self,
        *,
        event_type: str | None = None,
        subject_type: str | None = None,
        actor_id: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[AuditEventEnvelope]:
        if start_at is not None and end_at is not None:
            try:
                invalid_range = start_at > end_at
            except TypeError as error:
                raise ValueError(
                    'Audit event time bounds must use comparable timestamps.'
                ) from error
            if invalid_range:
                raise ValueError('Audit event start_at must not be after end_at.')
        query: dict[str, Any] = {'record_type': 'audit_event'}
        if event_type is not None:
            query['event_type'] = event_type
        if subject_type is not None:
            query['subject.subject_type'] = subject_type
        if actor_id is not None:
            query['actor.actor_id'] = actor_id
        time_range: dict[str, str] = {}
        if start_at is not None:
            time_range['$gte'] = self._audit_timestamp(start_at)
        if end_at is not None:
            time_range['$lte'] = self._audit_timestamp(end_at)
        if time_range:
            query['created_at'] = time_range
        events: list[AuditEventEnvelope] = []
        for document in self._collection.find(query).sort([('created_at', 1), ('_id', 1)]):
            event = self._model_from_document(document, AuditEventEnvelope)
            if event is not None:
                events.append(event)
        return sorted(events, key=lambda event: (event.created_at, event.event_id))

    def create_claim(self, claim: WorkingClaim, session: SessionRecord) -> None:
        if (
            session.claim_id != claim.claim_id
            or session.customer_id != claim.customer_id
            or claim.active_session_id != session.session_id
            or session.status is not SessionStatus.ACTIVE
            or session.context_revision != claim.revision
        ):
            raise KeyError(claim.claim_id)
        self._atomic(lambda mongo_session: self._create_claim(claim, session, mongo_session))

    def _create_claim(
        self,
        claim: WorkingClaim,
        session: SessionRecord,
        mongo_session: Any,
    ) -> None:
        if self._get('claim', claim.claim_id, WorkingClaim, session=mongo_session) is not None:
            raise IdempotencyConflict(claim.claim_id)
        self._reject_session_identity_conflict(session, mongo_session=mongo_session)
        self._put(
            'claim',
            claim.claim_id,
            claim,
            customer_id=claim.customer_id,
            claim_id=claim.claim_id,
            session=mongo_session,
        )
        self._put(
            'session',
            session.session_id,
            session,
            customer_id=session.customer_id,
            claim_id=session.claim_id,
            session=mongo_session,
        )

    def get_claim(self, claim_id: str, customer_id: str) -> WorkingClaim | None:
        return self._get('claim', claim_id, WorkingClaim, customer_id=customer_id)

    def get_claim_internal(self, claim_id: str) -> WorkingClaim | None:
        return self._get('claim', claim_id, WorkingClaim)

    def list_claims_for_customer(self, customer_id: str) -> list[WorkingClaim]:
        return self._list('claim', WorkingClaim, {'customer_id': customer_id}, '-updated_at')

    def list_claims_internal(self) -> list[WorkingClaim]:
        return self._list('claim', WorkingClaim, {}, '-updated_at')

    def promote_claim_owner(
        self,
        claim_id: str,
        anonymous_customer_id: str,
        customer_id: str,
    ) -> WorkingClaim | None:
        """Move an anonymous claim projection to an authenticated customer."""
        claim = self.get_claim(claim_id, anonymous_customer_id)
        if claim is None:
            return None
        self._collection.update_many(
            {'claim_id': claim_id, 'customer_id': anonymous_customer_id},
            {'$set': {'customer_id': customer_id}},
        )
        self._collection.update_one(
            {'_id': self._record_id('claim', claim_id), 'record_type': 'claim'},
            {'$set': {'customer_id': customer_id}},
        )
        return self.get_claim(claim_id, customer_id)

    def save_claim(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        if branch_evaluation is not None:
            self._validate_branch_evaluation(claim, branch_evaluation)
            self._atomic(
                lambda mongo_session: self._save_claim_with_evaluation(
                    claim,
                    expected_revision,
                    branch_evaluation,
                    mongo_session,
                )
            )
            return
        self._ensure_claim_revision(claim, expected_revision, mongo_session=None)
        if claim.revision != expected_revision + 1:
            raise KeyError(claim.claim_id)
        result = self._collection.replace_one(
            {
                '_id': self._record_id('claim', claim.claim_id),
                'record_type': 'claim',
                'customer_id': claim.customer_id,
                'revision': expected_revision,
            },
            {
                **claim.model_dump(mode='json'),
                '_id': self._record_id('claim', claim.claim_id),
                'record_type': 'claim',
                'customer_id': claim.customer_id,
                'claim_id': claim.claim_id,
            },
        )
        if result.matched_count == 0:
            current = self._collection.find_one(
                {'_id': self._record_id('claim', claim.claim_id), 'record_type': 'claim'},
                projection={'revision': 1},
            )
            raise RevisionConflict(int(current['revision']) if current else 0)

    def _save_claim_with_evaluation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        branch_evaluation: BranchEvaluationRecord,
        mongo_session: Any,
    ) -> None:
        self._reject_branch_evaluation_identity_conflict(
            branch_evaluation,
            mongo_session=mongo_session,
        )
        self._ensure_claim_revision(claim, expected_revision, mongo_session=mongo_session)
        if claim.revision != expected_revision + 1:
            raise KeyError(claim.claim_id)
        if self._replace_claim_revision(claim, expected_revision, mongo_session=mongo_session) == 0:
            self._raise_revision_conflict(claim.claim_id, mongo_session=mongo_session)
        self._put(
            'branch_evaluation',
            branch_evaluation.evaluation_id,
            branch_evaluation,
            customer_id=claim.customer_id,
            claim_id=claim.claim_id,
            session=mongo_session,
        )

    def save_claim_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        if (
            claim.revision != expected_revision + 1
            or idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != (claim.active_session_id or '')
        ):
            raise KeyError(claim.claim_id)
        self._validate_branch_evaluation(claim, branch_evaluation)
        records: list[tuple[str, str, BaseModel]] = []
        if branch_evaluation is not None:
            records.append(
                ('branch_evaluation', branch_evaluation.evaluation_id, branch_evaluation)
            )
        self._atomic(
            lambda mongo_session: self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                records=records,
            )
        )

    def save_claim_mutation_with_audit(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        audit_events: tuple[AuditEventEnvelope, ...],
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        """Atomically persist a claim mutation and its audit events in MongoDB.

        Args:
            claim: Resulting authoritative Claim State.
            expected_revision: Revision that must still be current.
            idempotency: Retry metadata for the mutation.
            audit_events: Claim-scoped immutable facts produced by the mutation.
            branch_evaluation: Optional applied evaluation for the resulting Claim revision.

        Returns:
            None.

        Raises:
            RevisionConflict: The stored Claim revision changed first.
            IdempotencyConflict: Retry or audit identity conflicts with stored data.
            KeyError: Claim ownership, revision linkage, or audit scope is invalid.
        """
        if (
            claim.revision != expected_revision + 1
            or idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != (claim.active_session_id or '')
        ):
            raise KeyError(claim.claim_id)
        self._validate_branch_evaluation(claim, branch_evaluation)
        self._atomic(
            lambda mongo_session: self._save_claim_mutation_with_audit(
                claim,
                expected_revision,
                idempotency,
                audit_events,
                branch_evaluation,
                mongo_session,
            )
        )

    def _save_claim_mutation_with_audit(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        audit_events: tuple[AuditEventEnvelope, ...],
        branch_evaluation: BranchEvaluationRecord | None,
        mongo_session: Any,
    ) -> None:
        prepared = self._prepare_audit_events(
            claim,
            audit_events,
            mongo_session=mongo_session,
        )
        records: list[tuple[str, str, BaseModel]] = []
        if branch_evaluation is not None:
            records.append(
                ('branch_evaluation', branch_evaluation.evaluation_id, branch_evaluation)
            )
        self._save_child_mutation(
            claim,
            expected_revision,
            idempotency,
            mongo_session,
            records=records,
        )
        for event in prepared:
            self._insert_audit_event(event, mongo_session=mongo_session)

    def get_session(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> SessionRecord | None:
        record = self._get('session', session_id, SessionRecord, customer_id=customer_id)
        return record if record is not None and record.claim_id == claim_id else None

    def save_session(self, session: SessionRecord) -> None:
        if self.get_claim(session.claim_id, session.customer_id) is None:
            raise KeyError(session.claim_id)
        self._reject_session_identity_conflict(session, allow_existing=True)
        self._put(
            'session',
            session.session_id,
            session,
            customer_id=session.customer_id,
            claim_id=session.claim_id,
        )

    def _reject_session_identity_conflict(
        self,
        session: SessionRecord,
        *,
        mongo_session: Any = None,
        allow_existing: bool = False,
    ) -> None:
        """Protect the global session identity before an upsert can overwrite it."""
        existing = self._collection.find_one(
            {'_id': self._record_id('session', session.session_id), 'record_type': 'session'},
            projection={'claim_id': 1, 'customer_id': 1},
            session=mongo_session,
        )
        if existing is None:
            return
        if (
            existing.get('claim_id') != session.claim_id
            or existing.get('customer_id') != session.customer_id
        ):
            raise IdempotencyConflict(session.session_id)
        if not allow_existing:
            raise IdempotencyConflict(session.session_id)

    def get_active_session(
        self,
        claim_id: str,
        customer_id: str,
        *,
        mongo_session: Any = None,
    ) -> SessionRecord | None:
        claim = self._get(
            'claim', claim_id, WorkingClaim, customer_id=customer_id, session=mongo_session
        )
        if claim is None or claim.active_session_id is None:
            return None
        record = self._get(
            'session',
            claim.active_session_id,
            SessionRecord,
            customer_id=customer_id,
            session=mongo_session,
        )
        return record if record is not None and record.claim_id == claim_id else None

    def list_sessions_for_claim(self, claim_id: str, customer_id: str) -> list[SessionRecord]:
        return self._list(
            'session',
            SessionRecord,
            {'claim_id': claim_id, 'customer_id': customer_id},
            'started_at',
        )

    def _claim_owned(
        self,
        claim_id: str,
        customer_id: str,
        *,
        mongo_session: Any = None,
    ) -> bool:
        return (
            self._get(
                'claim', claim_id, WorkingClaim, customer_id=customer_id, session=mongo_session
            )
            is not None
        )

    def save_message(self, message: MessageRecord, customer_id: str) -> None:
        if (
            not self._claim_owned(message.claim_id, customer_id)
            or self.get_session(message.claim_id, message.session_id, customer_id) is None
        ):
            raise KeyError(message.claim_id)
        self._put(
            'message',
            message.message_id,
            message,
            customer_id=customer_id,
            claim_id=message.claim_id,
        )

    def get_message(
        self,
        claim_id: str,
        session_id: str,
        message_id: str,
        customer_id: str,
    ) -> MessageRecord | None:
        if not self._claim_owned(claim_id, customer_id):
            return None
        record = self._get('message', message_id, MessageRecord, customer_id=customer_id)
        if record is None or record.claim_id != claim_id or record.session_id != session_id:
            return None
        return record

    def find_message_by_client_id(
        self,
        claim_id: str,
        client_message_id: str,
        customer_id: str,
    ) -> MessageRecord | None:
        if not self._claim_owned(claim_id, customer_id):
            return None
        document = self._collection.find_one(
            {
                'record_type': 'message',
                'claim_id': claim_id,
                'customer_id': customer_id,
                'client_message_id': client_message_id,
            }
        )
        return self._model_from_document(document, MessageRecord)

    def list_messages(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> list[MessageRecord]:
        if not self._claim_owned(claim_id, customer_id):
            return []
        return self._list(
            'message',
            MessageRecord,
            {'claim_id': claim_id, 'session_id': session_id, 'customer_id': customer_id},
            'created_at',
        )

    def save_agent_decision(self, decision: AgentDecisionRecord, customer_id: str) -> None:
        if (
            not self._claim_owned(decision.claim_id, customer_id)
            or self.get_session(decision.claim_id, decision.session_id, customer_id) is None
        ):
            raise KeyError(decision.claim_id)
        self._put(
            'agent_decision',
            decision.decision_id,
            decision,
            customer_id=customer_id,
            claim_id=decision.claim_id,
        )

    def save_branch_evaluation(
        self,
        evaluation: BranchEvaluationRecord,
        customer_id: str,
    ) -> None:
        claim = self.get_claim(evaluation.claim_id, customer_id)
        if claim is None:
            raise KeyError(evaluation.claim_id)
        if evaluation.status is BranchEvaluationStatus.APPLIED:
            raise ValueError(
                'Applied branch evaluations must be persisted with their Claim mutation.'
            )
        if evaluation.evaluated_against_claim_revision != claim.revision:
            raise RevisionConflict(claim.revision)
        existing = self._get(
            'branch_evaluation',
            evaluation.evaluation_id,
            BranchEvaluationRecord,
            customer_id=customer_id,
        )
        if existing is not None:
            if existing == evaluation:
                return
            raise IdempotencyConflict(evaluation.evaluation_id)
        self._put(
            'branch_evaluation',
            evaluation.evaluation_id,
            evaluation,
            customer_id=customer_id,
            claim_id=evaluation.claim_id,
        )

    def list_branch_evaluations(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[BranchEvaluationRecord]:
        if not self._claim_owned(claim_id, customer_id):
            return []
        records = self._list(
            'branch_evaluation',
            BranchEvaluationRecord,
            {'claim_id': claim_id, 'customer_id': customer_id},
            'created_at',
        )
        return sorted(
            records,
            key=lambda record: (
                record.resulting_claim_revision or 0,
                record.created_at,
                record.evaluation_id,
            ),
        )

    def get_agent_decision(
        self,
        claim_id: str,
        decision_id: str,
        customer_id: str,
    ) -> AgentDecisionRecord | None:
        if not self._claim_owned(claim_id, customer_id):
            return None
        record = self._get(
            'agent_decision', decision_id, AgentDecisionRecord, customer_id=customer_id
        )
        return record if record is not None and record.claim_id == claim_id else None

    def get_agent_decision_internal(
        self,
        claim_id: str,
        decision_id: str,
    ) -> AgentDecisionRecord | None:
        record = self._get('agent_decision', decision_id, AgentDecisionRecord)
        return record if record is not None and record.claim_id == claim_id else None

    def find_agent_decision_for_trigger(
        self,
        claim_id: str,
        trigger_message_id: str,
        customer_id: str,
    ) -> AgentDecisionRecord | None:
        if not self._claim_owned(claim_id, customer_id):
            return None
        document = self._collection.find_one(
            {
                'record_type': 'agent_decision',
                'claim_id': claim_id,
                'customer_id': customer_id,
                'trigger_message_id': trigger_message_id,
            }
        )
        return self._model_from_document(document, AgentDecisionRecord)

    def list_agent_decisions(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[AgentDecisionRecord]:
        if not self._claim_owned(claim_id, customer_id):
            return []
        return self._list(
            'agent_decision',
            AgentDecisionRecord,
            {'claim_id': claim_id, 'customer_id': customer_id},
            'created_at',
        )

    def get_assessor_routing_operation(
        self,
        operation_id: str,
    ) -> AssessorRoutingOperation | None:
        return self._get('assessor_routing_operation', operation_id, AssessorRoutingOperation)

    def save_assessor_routing_operation(
        self,
        operation: AssessorRoutingOperation,
    ) -> None:
        claim = self.get_claim_internal(operation.claim_id)
        if (
            claim is None
            or claim.external_claim is None
            or claim.external_claim.external_claim_id != operation.external_claim_id
            or operation.authorised_revision > claim.revision
        ):
            raise KeyError(operation.claim_id)

        existing = self.get_assessor_routing_operation(operation.operation_id)
        if existing is None:
            if operation.status is not AssessorRoutingOperationStatus.PREPARED:
                raise IdempotencyConflict(operation.operation_id)
            self._put(
                'assessor_routing_operation',
                operation.operation_id,
                operation,
                claim_id=operation.claim_id,
            )
            return

        immutable_identity = (
            'claim_id',
            'external_claim_id',
            'authorisation_ref',
            'claimant_consent_ref',
            'requested_action',
            'authorised_revision',
            'request_fingerprint',
            'created_at',
        )
        if any(getattr(existing, name) != getattr(operation, name) for name in immutable_identity):
            raise IdempotencyConflict(operation.operation_id)
        if operation.updated_at < existing.updated_at:
            raise IdempotencyConflict(operation.operation_id)
        if existing.status in {
            AssessorRoutingOperationStatus.ACCEPTED,
            AssessorRoutingOperationStatus.TERMINAL_FAILURE,
        }:
            if existing != operation:
                raise IdempotencyConflict(operation.operation_id)
            return
        allowed_statuses = {
            AssessorRoutingOperationStatus.RETRYABLE_FAILURE,
            AssessorRoutingOperationStatus.TERMINAL_FAILURE,
            AssessorRoutingOperationStatus.ACCEPTED,
        }
        if operation.status not in allowed_statuses:
            if existing != operation:
                raise IdempotencyConflict(operation.operation_id)
            return
        self._put(
            'assessor_routing_operation',
            operation.operation_id,
            operation,
            claim_id=operation.claim_id,
        )

    def save_assessor_routing_preparation(
        self,
        operation: AssessorRoutingOperation,
        decision: AgentDecisionRecord,
        customer_id: str,
        audit_events: tuple[AuditEventEnvelope, ...] = (),
    ) -> None:
        claim = self.get_claim(operation.claim_id, customer_id)
        session = self.get_session(operation.claim_id, decision.session_id, customer_id)
        if (
            claim is None
            or session is None
            or claim.active_session_id != decision.session_id
            or claim.external_claim is None
            or claim.external_claim.external_claim_id != operation.external_claim_id
            or operation.status is not AssessorRoutingOperationStatus.PREPARED
            or operation.authorised_revision != claim.revision
            or decision.claim_id != claim.claim_id
            or decision.decision_id != operation.authorisation_ref
            or decision.resulting_revision != operation.authorised_revision
            or decision.authority.outcome is not AuthorityOutcome.AUTHORISED
            or 'ASSESSOR_RULE_AUTHORISED' not in decision.reason_codes
        ):
            raise KeyError(operation.claim_id)

        def persist(mongo_session: Any) -> None:
            prepared_audit = self._prepare_audit_events(
                claim,
                audit_events,
                mongo_session=mongo_session,
            )
            existing_operation = self._get(
                'assessor_routing_operation',
                operation.operation_id,
                AssessorRoutingOperation,
                session=mongo_session,
            )
            existing_decision = self._get(
                'agent_decision',
                decision.decision_id,
                AgentDecisionRecord,
                session=mongo_session,
            )
            if existing_operation is not None or existing_decision is not None:
                if existing_operation == operation and existing_decision == decision:
                    for event in prepared_audit:
                        self._insert_audit_event(event, mongo_session=mongo_session)
                    return
                raise IdempotencyConflict(operation.operation_id)
            self._put(
                'agent_decision',
                decision.decision_id,
                decision,
                customer_id=customer_id,
                claim_id=decision.claim_id,
                session=mongo_session,
            )
            self._put(
                'assessor_routing_operation',
                operation.operation_id,
                operation,
                claim_id=operation.claim_id,
                session=mongo_session,
            )
            for event in prepared_audit:
                self._insert_audit_event(event, mongo_session=mongo_session)

        self._atomic(persist)

    def save_evidence(self, evidence: EvidenceRecord, customer_id: str) -> None:
        if not self._claim_owned(evidence.claim_id, customer_id):
            raise KeyError(evidence.claim_id)
        self._put(
            'evidence',
            evidence.evidence_id,
            evidence,
            customer_id=customer_id,
            claim_id=evidence.claim_id,
        )

    def get_evidence(
        self,
        claim_id: str,
        evidence_id: str,
        customer_id: str,
    ) -> EvidenceRecord | None:
        if not self._claim_owned(claim_id, customer_id):
            return None
        record = self._get('evidence', evidence_id, EvidenceRecord, customer_id=customer_id)
        return record if record is not None and record.claim_id == claim_id else None

    def list_evidence(self, claim_id: str, customer_id: str) -> list[EvidenceRecord]:
        if not self._claim_owned(claim_id, customer_id):
            return []
        return self._list(
            'evidence',
            EvidenceRecord,
            {'claim_id': claim_id, 'customer_id': customer_id},
            'created_at',
        )

    def save_external_task(self, task: ExternalTaskRecord, customer_id: str) -> None:
        """Create or conditionally advance one claim-owned external task.

        Args:
            task: External task state to create or advance.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The claim is missing or not owned by the customer.
            IdempotencyConflict: The write changes immutable identity or is stale.
        """
        if not self._claim_owned(task.claim_id, customer_id):
            raise KeyError(task.claim_id)
        record_id = self._record_id('external_task', task.task_id)
        document = {
            **task.model_dump(mode='json'),
            '_id': record_id,
            'record_type': 'external_task',
            'customer_id': customer_id,
            'claim_id': task.claim_id,
        }
        stored = self._collection.find_one({'_id': record_id, 'record_type': 'external_task'})
        if stored is None:
            try:
                self._collection.insert_one(document)
                return
            except DuplicateKeyError:
                stored = self._collection.find_one(
                    {'_id': record_id, 'record_type': 'external_task'}
                )
        existing = self._model_from_document(stored, ExternalTaskRecord)
        if (
            stored is None
            or stored.get('customer_id') != customer_id
            or stored.get('claim_id') != task.claim_id
            or existing is None
        ):
            raise IdempotencyConflict(task.task_id)
        immutable_identity = (
            'claim_id',
            'service_identity',
            'requested_action',
            'integration_source',
            'created_at',
        )
        if existing == task:
            return
        if any(getattr(existing, name) != getattr(task, name) for name in immutable_identity):
            raise IdempotencyConflict(task.task_id)
        if task.updated_at <= existing.updated_at:
            raise IdempotencyConflict(task.task_id)
        result = self._collection.replace_one(
            {
                '_id': record_id,
                'record_type': 'external_task',
                'customer_id': customer_id,
                'claim_id': task.claim_id,
                'updated_at': stored.get('updated_at'),
            },
            document,
        )
        if result.matched_count == 0:
            current = self._collection.find_one({'_id': record_id, 'record_type': 'external_task'})
            same_owner = current is not None and (
                current.get('customer_id') == customer_id
                and current.get('claim_id') == task.claim_id
            )
            if not same_owner or self._model_from_document(current, ExternalTaskRecord) != task:
                raise IdempotencyConflict(task.task_id)

    def save_external_task_request(
        self,
        request: ExternalTaskRequest,
        customer_id: str,
    ) -> None:
        """Persist a claim-owned request preparation or its first send record.

        Args:
            request: Request state to create or advance from prepared to sent.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The claim, task, consent, or authority is unavailable.
            IdempotencyConflict: Identity changes, a send is rewritten, or the
                task already has another request.
        """
        claim = self.get_claim(request.claim_id, customer_id)
        task = self._get(
            'external_task',
            request.task_id,
            ExternalTaskRecord,
            customer_id=customer_id,
        )
        if claim is None or task is None or task.claim_id != request.claim_id:
            raise KeyError(request.claim_id)
        try:
            assert_request_matches_task(request, task)
        except ValueError as conflict:
            raise IdempotencyConflict(request.request_id) from conflict
        consent = next(
            (
                record
                for record in claim.external_service_consents
                if record.consent_ref == request.authorisation.claimant_consent_ref
            ),
            None,
        )
        decision = self._get(
            'agent_decision',
            request.authorisation.northwind_authority_ref,
            AgentDecisionRecord,
            customer_id=customer_id,
        )
        if (
            consent is None
            or decision is None
            or decision.claim_id != request.claim_id
            or decision.resulting_revision != request.authorisation.authorised_revision
            or decision.authority.outcome is not AuthorityOutcome.AUTHORISED
        ):
            raise KeyError(request.request_id)
        try:
            assert_disclosure_within_consent(
                request,
                consent,
                claim_customer_id=customer_id,
            )
        except ValueError as conflict:
            raise IdempotencyConflict(request.request_id) from conflict

        record_id = self._record_id('external_task_request', request.task_id)
        document = {
            **request.model_dump(mode='json'),
            '_id': record_id,
            'record_type': 'external_task_request',
            'customer_id': customer_id,
            'claim_id': request.claim_id,
        }
        stored = self._collection.find_one(
            {'_id': record_id, 'record_type': 'external_task_request'}
        )
        if stored is None:
            try:
                self._collection.insert_one(document)
                return
            except DuplicateKeyError:
                stored = self._collection.find_one(
                    {'_id': record_id, 'record_type': 'external_task_request'}
                )
        existing = self._model_from_document(stored, ExternalTaskRequest)
        if (
            stored is None
            or stored.get('customer_id') != customer_id
            or stored.get('claim_id') != request.claim_id
            or existing is None
        ):
            raise IdempotencyConflict(request.request_id)
        if existing == request:
            return
        immutable_identity = (
            'request_id',
            'task_id',
            'claim_id',
            'service_identity',
            'requested_action',
            'purpose',
            'disclosed_fields',
            'authorisation',
            'prepared_at',
        )
        changed_identity = any(
            getattr(existing, name) != getattr(request, name) for name in immutable_identity
        )
        first_send = (
            existing.sent_at is None
            and existing.operation_id is None
            and request.sent_at is not None
            and request.operation_id is not None
        )
        if changed_identity or not first_send:
            raise IdempotencyConflict(request.request_id)
        result = self._collection.replace_one(
            {
                '_id': record_id,
                'record_type': 'external_task_request',
                'customer_id': customer_id,
                'claim_id': request.claim_id,
                'sent_at': None,
                'operation_id': None,
            },
            document,
        )
        if result.matched_count == 0:
            current = self._collection.find_one(
                {'_id': record_id, 'record_type': 'external_task_request'}
            )
            same_owner = current is not None and (
                current.get('customer_id') == customer_id
                and current.get('claim_id') == request.claim_id
            )
            if not same_owner or self._model_from_document(current, ExternalTaskRequest) != request:
                raise IdempotencyConflict(request.request_id)

    def list_external_task_requests_internal(
        self,
        claim_id: str,
    ) -> list[ExternalTaskRequest]:
        """List request records for an authorised internal claim read.

        Args:
            claim_id: Working Claim whose requests are requested.

        Returns:
            Requests in stable preparation order.

        Raises:
            RuntimeError: MongoDB cannot complete the read.
        """
        return self._list(
            'external_task_request',
            ExternalTaskRequest,
            {'claim_id': claim_id},
            'prepared_at',
        )

    def save_external_task_evidence_link(
        self,
        link: ExternalTaskEvidenceLink,
        customer_id: str,
    ) -> None:
        """Save one claim-owned evidence origin after validating its task and record.

        Args:
            link: Task-to-evidence relationship to persist.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The claim, task, or evidence record is missing or not owned.
            IdempotencyConflict: The evidence already has a different origin.
        """
        if not self._claim_owned(link.claim_id, customer_id):
            raise KeyError(link.claim_id)
        task = self._get(
            'external_task',
            link.task_id,
            ExternalTaskRecord,
            customer_id=customer_id,
        )
        if task is None or task.claim_id != link.claim_id:
            raise KeyError(link.task_id)
        if self.get_evidence(link.claim_id, link.evidence_id, customer_id) is None:
            raise KeyError(link.evidence_id)

        identifier = f'{link.claim_id}:{link.evidence_id}'
        record_id = self._record_id('external_task_evidence_link', identifier)
        document = {
            **link.model_dump(mode='json'),
            '_id': record_id,
            'record_type': 'external_task_evidence_link',
            'customer_id': customer_id,
            'claim_id': link.claim_id,
        }
        try:
            self._collection.insert_one(document)
        except DuplicateKeyError as error:
            existing = self._collection.find_one(
                {'_id': record_id, 'record_type': 'external_task_evidence_link'}
            )
            same_owner = existing is not None and (
                existing.get('customer_id') == customer_id
                and existing.get('claim_id') == link.claim_id
            )
            if (
                not same_owner
                or self._model_from_document(existing, ExternalTaskEvidenceLink) != link
            ):
                raise IdempotencyConflict(link.evidence_id) from error

    def save_external_task_result(self, result: ExternalTaskResult, customer_id: str) -> None:
        """Ingest one returned result, or advance its verification, after validating it.

        Args:
            result: Returned-result state to ingest or advance to a checked verification.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The claim, the result-bearing task, or a named evidence link is
                unavailable.
            IdempotencyConflict: The write changes an ingestion fact, contradicts a
                recorded verification, or adds a second result to one task.
        """
        if not self._claim_owned(result.claim_id, customer_id):
            raise KeyError(result.claim_id)
        task = self._get(
            'external_task',
            result.task_id,
            ExternalTaskRecord,
            customer_id=customer_id,
        )
        if task is None:
            raise KeyError(result.task_id)
        # The domain already decides which task states can carry an answer and how a
        # result reaches its material. Re-deciding either here would be a second,
        # quietly different rule.
        links = [
            link
            for evidence_id in result.evidence_ids
            if (
                link := self._get(
                    'external_task_evidence_link',
                    f'{result.claim_id}:{evidence_id}',
                    ExternalTaskEvidenceLink,
                    customer_id=customer_id,
                )
            )
            is not None
        ]
        try:
            assert_result_matches_task(result, task)
            assert_result_evidence_is_linked(result, links)
        except ValueError as mismatch:
            raise KeyError(result.task_id) from mismatch
        for evidence_id in result.evidence_ids:
            if self.get_evidence(result.claim_id, evidence_id, customer_id) is None:
                raise KeyError(evidence_id)

        held = next(
            iter(
                self._list(
                    'external_task_result',
                    ExternalTaskResult,
                    {'claim_id': result.claim_id, 'task_id': result.task_id},
                    'received_at',
                )
            ),
            None,
        )
        by_identity = self._get(
            'external_task_result',
            result.result_id,
            ExternalTaskResult,
            customer_id=customer_id,
        )
        # A result identity belongs to one task for good, so a reused identifier is a
        # conflict even when the task it now names holds nothing.
        if by_identity is not None and by_identity.task_id != result.task_id:
            raise IdempotencyConflict(result.result_id)
        if held is None:
            # Only the verification operation may record a check, so an answer arrives
            # unverified or not at all.
            if result.verification is not ExternalTaskResultVerification.UNVERIFIED:
                raise IdempotencyConflict(result.result_id)
        else:
            try:
                assert_result_advance_is_permitted(held, result)
            except ValueError as conflict:
                raise IdempotencyConflict(result.result_id) from conflict
            if held == result:
                return

        record_id = self._record_id('external_task_result', result.result_id)
        document = {
            **result.model_dump(mode='json'),
            '_id': record_id,
            'record_type': 'external_task_result',
            'customer_id': customer_id,
            'claim_id': result.claim_id,
        }
        if held is None:
            try:
                self._collection.insert_one(document)
                return
            except DuplicateKeyError as error:
                # Another writer won the race. Whether that is a conflict depends on what
                # it stored: an identical document means this call's intended result is
                # the canonical one, and reporting failure would tell a retrying producer
                # that ingestion failed after it had actually succeeded.
                self._assert_race_winner_matches(result, customer_id, error)
                return
        replaced = self._collection.replace_one(
            {
                '_id': record_id,
                'record_type': 'external_task_result',
                'customer_id': customer_id,
                'claim_id': result.claim_id,
                'verification': held.verification.value,
            },
            document,
        )
        if replaced.matched_count == 0:
            # The stored verification moved between the read and the write. The same
            # question applies: an identical winner is this call's own outcome.
            self._assert_race_winner_matches(result, customer_id, None)

    def _assert_race_winner_matches(
        self,
        result: ExternalTaskResult,
        customer_id: str,
        cause: Exception | None,
    ) -> None:
        """Refuse only when a concurrent writer stored something else.

        Args:
            result: The result this call intended to store.
            customer_id: Customer who owns the parent claim.
            cause: The duplicate-key error that revealed the race, when there was one.

        Returns:
            None. The write is treated as already applied.

        Raises:
            IdempotencyConflict: The stored canonical result differs from the proposal.
        """
        stored = next(
            iter(
                self._list(
                    'external_task_result',
                    ExternalTaskResult,
                    {'claim_id': result.claim_id, 'task_id': result.task_id},
                    'received_at',
                )
            ),
            None,
        )
        if stored == result:
            return
        if cause is None:
            raise IdempotencyConflict(result.result_id)
        raise IdempotencyConflict(result.result_id) from cause

    def list_external_tasks_internal(self, claim_id: str) -> list[ExternalTaskRecord]:
        """List task records for an already-authorised internal claim read.

        Args:
            claim_id: Working Claim whose tasks are requested.

        Returns:
            Task records in stable creation order.

        Raises:
            RuntimeError: MongoDB cannot complete the read.
        """
        return self._list(
            'external_task',
            ExternalTaskRecord,
            {'claim_id': claim_id},
            'created_at',
        )

    def list_external_task_results_internal(self, claim_id: str) -> list[ExternalTaskResult]:
        """List returned results for an already-authorised internal claim read.

        Args:
            claim_id: Working Claim whose external task results are requested.

        Returns:
            Result records, oldest ingestion first.

        Raises:
            RuntimeError: MongoDB cannot complete the read.
        """
        return self._list(
            'external_task_result',
            ExternalTaskResult,
            {'claim_id': claim_id},
            'received_at',
        )

    def list_external_task_evidence_links_internal(
        self,
        claim_id: str,
    ) -> list[ExternalTaskEvidenceLink]:
        """List evidence-origin links for an authorised internal claim read.

        Args:
            claim_id: Working Claim whose evidence links are requested.

        Returns:
            Links in stable linkage order.

        Raises:
            RuntimeError: MongoDB cannot complete the read.
        """
        return self._list(
            'external_task_evidence_link',
            ExternalTaskEvidenceLink,
            {'claim_id': claim_id},
            'linked_at',
        )

    def save_handoff(self, handoff: HandoffRecord, customer_id: str) -> None:
        if not self._claim_owned(handoff.claim_id, customer_id):
            raise KeyError(handoff.claim_id)
        self._put(
            'handoff',
            handoff.handoff_id,
            handoff,
            customer_id=customer_id,
            claim_id=handoff.claim_id,
        )

    def get_handoff(
        self,
        claim_id: str,
        handoff_id: str,
        customer_id: str,
    ) -> HandoffRecord | None:
        if not self._claim_owned(claim_id, customer_id):
            return None
        record = self._get('handoff', handoff_id, HandoffRecord, customer_id=customer_id)
        return record if record is not None and record.claim_id == claim_id else None

    def list_handoffs(self, claim_id: str, customer_id: str) -> list[HandoffRecord]:
        if not self._claim_owned(claim_id, customer_id):
            return []
        return self._list(
            'handoff',
            HandoffRecord,
            {'claim_id': claim_id, 'customer_id': customer_id},
            'created_at',
        )

    def save_retrieval_bundle(
        self,
        record: RetrievalRecord,
        review_signals: list[ReviewSignalRecord],
        customer_id: str,
    ) -> None:
        if not self._claim_owned(record.claim_id, customer_id):
            raise KeyError(record.claim_id)
        if any(
            signal.claim_id != record.claim_id or record.retrieval_id not in signal.source_refs
            for signal in review_signals
        ):
            raise KeyError(record.claim_id)
        incoming: dict[str, ReviewSignalRecord] = {}
        for signal in review_signals:
            duplicate = incoming.get(signal.signal_id)
            if duplicate is not None and duplicate != signal:
                raise IdempotencyConflict(signal.signal_id)
            incoming[signal.signal_id] = signal
        self._atomic(
            lambda mongo_session: self._save_retrieval_records(
                record, list(incoming.values()), customer_id, mongo_session
            )
        )

    def _save_retrieval_records(
        self,
        record: RetrievalRecord,
        review_signals: list[ReviewSignalRecord],
        customer_id: str,
        mongo_session: Any,
    ) -> None:
        existing = self._get_retrieval(record.retrieval_id, mongo_session=mongo_session)
        if existing is not None and existing != record:
            raise IdempotencyConflict(record.retrieval_id)
        for signal in review_signals:
            stored = self._get(
                'review_signal',
                signal.signal_id,
                ReviewSignalRecord,
                session=mongo_session,
            )
            if stored is not None and stored != signal:
                raise IdempotencyConflict(signal.signal_id)
        self._put(
            'retrieval',
            record.retrieval_id,
            record,
            customer_id=customer_id,
            claim_id=record.claim_id,
            session=mongo_session,
        )
        for signal in review_signals:
            self._put(
                'review_signal',
                signal.signal_id,
                signal,
                customer_id=customer_id,
                claim_id=record.claim_id,
                session=mongo_session,
            )

    def _get_retrieval(
        self,
        retrieval_id: str,
        *,
        mongo_session: Any = None,
    ) -> RetrievalRecord | None:
        document = self._collection.find_one(
            {
                '_id': self._record_id('retrieval', retrieval_id),
                'record_type': 'retrieval',
            },
            session=mongo_session,
        )
        if document is None:
            return None
        if document.get('kind') == RetrievalKind.POLICY.value:
            return self._model_from_document(document, PolicyRetrievalRecord)
        return self._model_from_document(document, ClaimHistoryRetrievalRecord)

    def list_retrieval_records(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[RetrievalRecord]:
        if not self._claim_owned(claim_id, customer_id):
            return []
        records: list[RetrievalRecord] = []
        query = {
            'record_type': 'retrieval',
            'claim_id': claim_id,
            'customer_id': customer_id,
        }
        for document in self._collection.find(query).sort('source.retrieved_at', 1):
            if document.get('kind') == RetrievalKind.POLICY.value:
                record: RetrievalRecord | None = self._model_from_document(
                    document, PolicyRetrievalRecord
                )
            else:
                record = self._model_from_document(document, ClaimHistoryRetrievalRecord)
            if record is not None:
                records.append(record)
        return sorted(records, key=lambda item: (item.source.retrieved_at, item.retrieval_id))

    def list_review_signals(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[ReviewSignalRecord]:
        if not self._claim_owned(claim_id, customer_id):
            return []
        return self._list(
            'review_signal',
            ReviewSignalRecord,
            {'claim_id': claim_id, 'customer_id': customer_id},
            'created_at',
        )

    def list_staff_actions(self, claim_id: str) -> list[StaffActionRecord]:
        return self._list('staff_action', StaffActionRecord, {'claim_id': claim_id}, 'created_at')

    def get_staff_action(self, claim_id: str, action_id: str) -> StaffActionRecord | None:
        record = self._get('staff_action', action_id, StaffActionRecord)
        return record if record is not None and record.claim_id == claim_id else None

    def list_customer_updates(self, claim_id: str) -> list[CustomerUpdateRecord]:
        return self._list(
            'customer_update', CustomerUpdateRecord, {'claim_id': claim_id}, 'created_at'
        )

    def list_signal_decisions(self, claim_id: str) -> list[SignalDecisionRecord]:
        return self._list(
            'signal_decision', SignalDecisionRecord, {'claim_id': claim_id}, 'created_at'
        )

    def list_collaboration_requests(self, claim_id: str) -> list[ClaimCollaborationRequest]:
        return self._list(
            'collaboration_request',
            ClaimCollaborationRequest,
            {'claim_id': claim_id},
            'created_at',
        )

    def list_claim_coworkers(self, claim_id: str) -> list[ClaimCoworkerRecord]:
        return self._list(
            'claim_coworker',
            ClaimCoworkerRecord,
            {'claim_id': claim_id, 'active': True},
            'granted_at',
        )

    def save_ownership_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        collaboration_request: ClaimCollaborationRequest,
        coworkers: list[ClaimCoworkerRecord] | None = None,
        handoff: HandoffRecord | None = None,
    ) -> None:
        coworker_records = coworkers or []
        if (
            claim.revision != expected_revision + 1
            or collaboration_request.claim_id != claim.claim_id
            or any(item.claim_id != claim.claim_id for item in coworker_records)
            or (handoff is not None and handoff.claim_id != claim.claim_id)
            or idempotency.claim_id != claim.claim_id
        ):
            raise KeyError(claim.claim_id)
        records: list[tuple[str, str, BaseModel]] = [
            ('collaboration_request', collaboration_request.request_id, collaboration_request)
        ]
        for coworker in coworker_records:
            records.append(('claim_coworker', coworker.coworker_id, coworker))
        if handoff is not None:
            records.append(('handoff', handoff.handoff_id, handoff))
        self._atomic(
            lambda mongo_session: self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                records=records,
            )
        )

    def save_staff_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        *,
        staff_action: StaffActionRecord | None = None,
        customer_update: CustomerUpdateRecord | None = None,
        signal_decision: SignalDecisionRecord | None = None,
        handoff: HandoffRecord | None = None,
        message: MessageRecord | None = None,
    ) -> None:
        supplied = (staff_action, customer_update, signal_decision, handoff, message)
        if (
            claim.revision != expected_revision + 1
            or not any(item is not None for item in supplied)
            or any(item is not None and item.claim_id != claim.claim_id for item in supplied)
            or idempotency.claim_id != claim.claim_id
            or (
                message is not None
                and (
                    idempotency.session_id != message.session_id
                    or idempotency.message_id != message.message_id
                    or idempotency.agent_message_id is not None
                )
            )
        ):
            raise KeyError(claim.claim_id)
        records: list[tuple[str, str, BaseModel]] = []
        if staff_action is not None:
            records.append(('staff_action', staff_action.action_id, staff_action))
        if customer_update is not None:
            records.append(('customer_update', customer_update.update_id, customer_update))
        if signal_decision is not None:
            records.append(('signal_decision', signal_decision.signal_decision_id, signal_decision))
        if handoff is not None:
            records.append(('handoff', handoff.handoff_id, handoff))
        if message is not None:
            records.append(('message', message.message_id, message))
        self._atomic(
            lambda mongo_session: self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                records=records,
            )
        )

    def save_message_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        message: MessageRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        if (
            claim.revision != expected_revision + 1
            or claim.active_session_id != session.session_id
            or session.claim_id != claim.claim_id
            or session.customer_id != claim.customer_id
            or session.status is not SessionStatus.ACTIVE
            or session.context_revision != claim.revision
            or message.claim_id != claim.claim_id
            or message.session_id != session.session_id
            or message.actor is not ActorType.CLAIMANT
            or idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != session.session_id
            or idempotency.message_id != message.message_id
        ):
            raise KeyError(claim.claim_id)
        self._atomic(
            lambda mongo_session: self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                session=session,
                records=[('message', message.message_id, message)],
            )
        )

    def save_agent_turn(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        claimant_message: MessageRecord,
        agent_message: MessageRecord,
        decision: AgentDecisionRecord,
        idempotency: IdempotencyRecord,
        handoff: HandoffRecord | None = None,
        evidence: EvidenceRecord | None = None,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        records_match = (
            claim.revision == expected_revision + 1
            and session.claim_id == claim.claim_id
            and session.customer_id == claim.customer_id
            and claimant_message.claim_id == claim.claim_id
            and agent_message.claim_id == claim.claim_id
            and decision.claim_id == claim.claim_id
            and claimant_message.session_id == session.session_id
            and agent_message.session_id == session.session_id
            and decision.session_id == session.session_id
            and session.context_revision == claim.revision
            and decision.resulting_revision == claim.revision
            and claimant_message.actor is ActorType.CLAIMANT
            and agent_message.actor is ActorType.AGENT
            and decision.trigger_message_id == claimant_message.message_id
            and agent_message.in_reply_to == claimant_message.message_id
            and idempotency.actor_id == claim.customer_id
            and idempotency.claim_id == claim.claim_id
            and idempotency.session_id == session.session_id
            and idempotency.message_id == claimant_message.message_id
            and idempotency.agent_message_id == agent_message.message_id
            and idempotency.decision_id == decision.decision_id
            and (handoff is None or handoff.claim_id == claim.claim_id)
            and (handoff is None or idempotency.handoff_id == handoff.handoff_id)
            and decision.handoff_id == (handoff.handoff_id if handoff is not None else None)
            and (evidence is None or evidence.claim_id == claim.claim_id)
            and (
                branch_evaluation is None
                or (
                    branch_evaluation.claim_id == claim.claim_id
                    and branch_evaluation.evaluated_against_claim_revision == claim.revision
                    and branch_evaluation.resulting_claim_revision == claim.revision
                )
            )
        )
        if not records_match:
            raise KeyError(claim.claim_id)
        self._atomic(
            lambda mongo_session: self._save_agent_turn_records(
                claim,
                expected_revision,
                session,
                claimant_message,
                agent_message,
                decision,
                idempotency,
                handoff,
                evidence,
                branch_evaluation,
                mongo_session,
            )
        )

    def _save_agent_turn_records(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        claimant_message: MessageRecord,
        agent_message: MessageRecord,
        decision: AgentDecisionRecord,
        idempotency: IdempotencyRecord,
        handoff: HandoffRecord | None,
        evidence: EvidenceRecord | None,
        branch_evaluation: BranchEvaluationRecord | None,
        mongo_session: Any,
    ) -> None:
        if claimant_message.client_message_id is not None:
            duplicate = self._collection.find_one(
                {
                    'record_type': 'message',
                    'claim_id': claim.claim_id,
                    'client_message_id': claimant_message.client_message_id,
                },
                session=mongo_session,
            )
            if duplicate is not None:
                raise IdempotencyConflict(claimant_message.client_message_id)
        records: list[tuple[str, str, BaseModel]] = [
            ('message', claimant_message.message_id, claimant_message),
            ('message', agent_message.message_id, agent_message),
            ('agent_decision', decision.decision_id, decision),
        ]
        if handoff is not None:
            records.append(('handoff', handoff.handoff_id, handoff))
        if evidence is not None:
            records.append(('evidence', evidence.evidence_id, evidence))
        if branch_evaluation is not None:
            records.append(
                ('branch_evaluation', branch_evaluation.evaluation_id, branch_evaluation)
            )
        self._save_child_mutation(
            claim,
            expected_revision,
            idempotency,
            mongo_session,
            records=records,
            session=session,
        )

    def save_evidence_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        evidence: EvidenceRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        if (
            claim.revision != expected_revision + 1
            or evidence.claim_id != claim.claim_id
            or idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != (claim.active_session_id or '')
        ):
            raise KeyError(claim.claim_id)
        self._validate_branch_evaluation(claim, branch_evaluation)
        records: list[tuple[str, str, BaseModel]] = [('evidence', evidence.evidence_id, evidence)]
        if branch_evaluation is not None:
            records.append(
                ('branch_evaluation', branch_evaluation.evaluation_id, branch_evaluation)
            )
        self._atomic(
            lambda mongo_session: self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                records=records,
            )
        )

    def save_handoff_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        handoff: HandoffRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        if (
            claim.revision != expected_revision + 1
            or handoff.claim_id != claim.claim_id
            or idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != (claim.active_session_id or '')
            or idempotency.handoff_id != handoff.handoff_id
        ):
            raise KeyError(claim.claim_id)
        self._validate_branch_evaluation(claim, branch_evaluation)
        records: list[tuple[str, str, BaseModel]] = [('handoff', handoff.handoff_id, handoff)]
        if branch_evaluation is not None:
            records.append(
                ('branch_evaluation', branch_evaluation.evaluation_id, branch_evaluation)
            )
        self._atomic(
            lambda mongo_session: self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                records=records,
            )
        )

    def _save_child_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        mongo_session: Any,
        *,
        records: list[tuple[str, str, BaseModel]],
        session: SessionRecord | None = None,
    ) -> None:
        self._reject_existing_idempotency(idempotency, mongo_session=mongo_session)
        self._ensure_claim_revision(claim, expected_revision, mongo_session=mongo_session)
        stored_session: SessionRecord | None = None
        if session is not None:
            stored_session = self._get(
                'session',
                session.session_id,
                SessionRecord,
                customer_id=claim.customer_id,
                session=mongo_session,
            )
            if (
                stored_session is None
                or stored_session.claim_id != claim.claim_id
                or stored_session.status is not SessionStatus.ACTIVE
                or session.status is not SessionStatus.ACTIVE
                or claim.active_session_id != session.session_id
            ):
                raise KeyError(claim.claim_id)
        for kind, identifier, record in records:
            if kind == 'message':
                if not isinstance(record, MessageRecord):
                    raise KeyError(claim.claim_id)
                message_session = self._get(
                    'session',
                    record.session_id,
                    SessionRecord,
                    customer_id=claim.customer_id,
                    session=mongo_session,
                )
                if (
                    message_session is None
                    or message_session.claim_id != claim.claim_id
                    or message_session.status is not SessionStatus.ACTIVE
                    or claim.active_session_id != record.session_id
                    or idempotency.session_id != record.session_id
                    or record.message_id
                    not in {idempotency.message_id, idempotency.agent_message_id}
                ):
                    raise KeyError(claim.claim_id)
            document = record.model_dump(mode='json')
            document.update(
                {
                    '_id': self._record_id(kind, identifier),
                    'record_type': kind,
                    'customer_id': claim.customer_id,
                    'claim_id': claim.claim_id,
                }
            )
            existing = self._collection.find_one(
                {'_id': document['_id'], 'record_type': kind},
                projection={'claim_id': 1, 'customer_id': 1},
                session=mongo_session,
            )
            if existing is not None and (
                existing.get('claim_id') != claim.claim_id
                or existing.get('customer_id') != claim.customer_id
                or kind in IMMUTABLE_CHILD_RECORD_KINDS
            ):
                raise IdempotencyConflict(identifier)
            self._reject_client_message_conflict(document, session=mongo_session)
        result = self._replace_claim_revision(claim, expected_revision, mongo_session=mongo_session)
        if result == 0:
            self._raise_revision_conflict(claim.claim_id, mongo_session=mongo_session)
        if session is not None:
            self._put(
                'session',
                session.session_id,
                session,
                customer_id=claim.customer_id,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
        for kind, identifier, record in records:
            self._put(
                kind,
                identifier,
                record,
                customer_id=claim.customer_id,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
        self._save_idempotency(idempotency, mongo_session)

    def _ensure_claim_revision(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        *,
        mongo_session: Any,
    ) -> None:
        current = self._collection.find_one(
            {
                '_id': self._record_id('claim', claim.claim_id),
                'record_type': 'claim',
                'customer_id': claim.customer_id,
                'revision': expected_revision,
            },
            projection={'revision': 1, 'active_session_id': 1},
            session=mongo_session,
        )
        if current is None:
            self._raise_revision_conflict(claim.claim_id, mongo_session=mongo_session)
            return
        if current.get('active_session_id') != claim.active_session_id:
            raise KeyError(claim.claim_id)

    def _replace_claim_revision(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        *,
        mongo_session: Any,
    ) -> int:
        result = self._collection.replace_one(
            {
                '_id': self._record_id('claim', claim.claim_id),
                'record_type': 'claim',
                'customer_id': claim.customer_id,
                'revision': expected_revision,
            },
            {
                **claim.model_dump(mode='json'),
                '_id': self._record_id('claim', claim.claim_id),
                'record_type': 'claim',
                'customer_id': claim.customer_id,
                'claim_id': claim.claim_id,
            },
            session=mongo_session,
        )
        return result.matched_count

    def _raise_revision_conflict(self, claim_id: str, *, mongo_session: Any) -> None:
        current = self._collection.find_one(
            {'_id': self._record_id('claim', claim_id), 'record_type': 'claim'},
            projection={'revision': 1},
            session=mongo_session,
        )
        raise RevisionConflict(int(current['revision']) if current else 0)

    def _reject_existing_idempotency(
        self,
        record: IdempotencyRecord,
        *,
        mongo_session: Any,
    ) -> None:
        existing = self._collection.find_one(
            {
                'record_type': 'idempotency',
                'actor_id': record.actor_id,
                'route': record.route,
                'key': record.key,
            },
            session=mongo_session,
        )
        if existing is not None:
            raise IdempotencyConflict(record.key)

    def find_idempotency(self, actor_id: str, route: str, key: str) -> IdempotencyRecord | None:
        document = self._collection.find_one(
            {'record_type': 'idempotency', 'actor_id': actor_id, 'route': route, 'key': key}
        )
        if document is None:
            return None
        return IdempotencyRecord(**document['payload'])

    def save_idempotency(self, record: IdempotencyRecord) -> None:
        query = {
            'record_type': 'idempotency',
            'actor_id': record.actor_id,
            'route': record.route,
            'key': record.key,
        }
        document = {
            **query,
            '_id': self._record_id('idempotency', f'{record.actor_id}:{record.route}:{record.key}'),
            'payload': record.__dict__,
        }
        try:
            self._collection.insert_one(document)
        except DuplicateKeyError:
            existing = self._collection.find_one(query)
            if (
                existing is None
                or existing['payload']['request_fingerprint'] != record.request_fingerprint
            ):
                raise IdempotencyConflict(record.key) from None

    def save_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        self._validate_session_mutation(claim, expected_revision, session, idempotency)
        self._validate_branch_evaluation(claim, branch_evaluation)
        self._atomic(
            lambda mongo_session: self._save_session_mutation(
                claim,
                expected_revision,
                session,
                idempotency,
                branch_evaluation,
                mongo_session,
            )
        )

    def _validate_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        if (
            claim.revision != expected_revision + 1
            or claim.active_session_id != session.session_id
            or session.claim_id != claim.claim_id
            or session.customer_id != claim.customer_id
            or session.status is not SessionStatus.ACTIVE
            or session.context_revision != expected_revision
            or idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != session.session_id
        ):
            raise KeyError(claim.claim_id)

    def _save_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None,
        mongo_session: Any,
    ) -> None:
        if (
            self.get_active_session(claim.claim_id, claim.customer_id, mongo_session=mongo_session)
            is not None
        ):
            raise IdempotencyConflict(session.session_id)
        self._reject_session_identity_conflict(session, mongo_session=mongo_session)
        if branch_evaluation is not None:
            self._reject_branch_evaluation_identity_conflict(
                branch_evaluation,
                mongo_session=mongo_session,
            )
        result = self._collection.replace_one(
            {
                '_id': self._record_id('claim', claim.claim_id),
                'record_type': 'claim',
                'customer_id': claim.customer_id,
                'revision': expected_revision,
            },
            {
                **claim.model_dump(mode='json'),
                '_id': self._record_id('claim', claim.claim_id),
                'record_type': 'claim',
                'customer_id': claim.customer_id,
                'claim_id': claim.claim_id,
            },
            session=mongo_session,
        )
        if result.matched_count == 0:
            current = self._collection.find_one(
                {'_id': self._record_id('claim', claim.claim_id)},
                projection={'revision': 1},
                session=mongo_session,
            )
            raise RevisionConflict(int(current['revision']) if current else 0)
        self._put(
            'session',
            session.session_id,
            session,
            customer_id=session.customer_id,
            claim_id=session.claim_id,
            session=mongo_session,
        )
        if branch_evaluation is not None:
            self._put(
                'branch_evaluation',
                branch_evaluation.evaluation_id,
                branch_evaluation,
                customer_id=claim.customer_id,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
        self._save_idempotency(record=idempotency, session=mongo_session)

    @staticmethod
    def _validate_branch_evaluation(
        claim: WorkingClaim,
        branch_evaluation: BranchEvaluationRecord | None,
    ) -> None:
        if branch_evaluation is None:
            return
        if (
            branch_evaluation.claim_id != claim.claim_id
            or branch_evaluation.evaluated_against_claim_revision != claim.revision
            or branch_evaluation.resulting_claim_revision != claim.revision
        ):
            raise KeyError(claim.claim_id)

    def _reject_branch_evaluation_identity_conflict(
        self,
        branch_evaluation: BranchEvaluationRecord,
        *,
        mongo_session: Any,
    ) -> None:
        existing = self._collection.find_one(
            {
                '_id': self._record_id('branch_evaluation', branch_evaluation.evaluation_id),
                'record_type': 'branch_evaluation',
            },
            projection={'_id': 1},
            session=mongo_session,
        )
        if existing is not None:
            raise IdempotencyConflict(branch_evaluation.evaluation_id)

    def _save_idempotency(self, record: IdempotencyRecord, session: Any) -> None:
        query = {
            'record_type': 'idempotency',
            'actor_id': record.actor_id,
            'route': record.route,
            'key': record.key,
        }
        document = {
            **query,
            '_id': self._record_id('idempotency', f'{record.actor_id}:{record.route}:{record.key}'),
            'payload': record.__dict__,
        }
        try:
            self._collection.insert_one(document, session=session)
        except DuplicateKeyError as error:
            raise IdempotencyConflict(record.key) from error

    def save_staff_agent_session(self, staff_agent_session: StaffAgentSession) -> None:
        existing = self.get_staff_agent_session(
            staff_agent_session.session_id, staff_agent_session.staff_id
        )
        if existing is not None and existing != staff_agent_session:
            raise IdempotencyConflict(staff_agent_session.session_id)
        self._put(
            'staff_agent_session',
            staff_agent_session.session_id,
            staff_agent_session,
            customer_id=staff_agent_session.staff_id,
        )

    def get_staff_agent_session(self, session_id: str, staff_id: str) -> StaffAgentSession | None:
        return self._get(
            'staff_agent_session',
            session_id,
            StaffAgentSession,
            customer_id=staff_id,
        )

    def list_staff_agent_sessions(self, staff_id: str) -> list[StaffAgentSession]:
        return self._list(
            'staff_agent_session',
            StaffAgentSession,
            {'customer_id': staff_id},
            '-updated_at',
        )

    def list_staff_agent_messages(self, session_id: str, staff_id: str) -> list[StaffAgentMessage]:
        if self.get_staff_agent_session(session_id, staff_id) is None:
            return []
        return self._list(
            'staff_agent_message',
            StaffAgentMessage,
            {'customer_id': staff_id, 'session_id': session_id},
            'created_at',
        )

    def find_staff_agent_message_by_client_id(
        self, session_id: str, staff_id: str, client_message_id: str
    ) -> StaffAgentMessage | None:
        document = self._collection.find_one(
            {
                'record_type': 'staff_agent_message',
                'customer_id': staff_id,
                'session_id': session_id,
                'client_message_id': client_message_id,
            }
        )
        return self._model_from_document(document, StaffAgentMessage)

    def save_staff_agent_turn(
        self,
        staff_agent_session: StaffAgentSession,
        staff_message: StaffAgentMessage,
        assistant_message: StaffAgentMessage,
    ) -> None:
        stored = self.get_staff_agent_session(
            staff_agent_session.session_id, staff_agent_session.staff_id
        )
        if stored is None:
            raise KeyError(staff_agent_session.session_id)
        if (
            staff_message.session_id != staff_agent_session.session_id
            or assistant_message.session_id != staff_agent_session.session_id
            or staff_message.staff_id != staff_agent_session.staff_id
            or assistant_message.staff_id != staff_agent_session.staff_id
            or assistant_message.in_reply_to != staff_message.message_id
        ):
            raise KeyError(staff_agent_session.session_id)
        duplicate = self.find_staff_agent_message_by_client_id(
            staff_agent_session.session_id,
            staff_agent_session.staff_id,
            staff_message.client_message_id or '',
        )
        if duplicate is not None and duplicate.message_id != staff_message.message_id:
            raise IdempotencyConflict(staff_message.client_message_id or '')
        for message in (staff_message, assistant_message):
            existing = self._get(
                'staff_agent_message',
                message.message_id,
                StaffAgentMessage,
                customer_id=staff_agent_session.staff_id,
            )
            if existing is not None and existing != message:
                raise IdempotencyConflict(message.message_id)

        def save_turn(mongo_session: Any) -> None:
            self._put(
                'staff_agent_session',
                staff_agent_session.session_id,
                staff_agent_session,
                customer_id=staff_agent_session.staff_id,
                session=mongo_session,
            )
            for message in (staff_message, assistant_message):
                self._put(
                    'staff_agent_message',
                    message.message_id,
                    message,
                    customer_id=staff_agent_session.staff_id,
                    session=mongo_session,
                )

        self._atomic(save_turn)

    def _list(
        self,
        kind: str,
        model_type: type[ModelT],
        filters: dict[str, Any],
        sort_field: str,
    ) -> list[ModelT]:
        query = {'record_type': kind, **filters}
        descending = sort_field.startswith('-')
        field = sort_field.removeprefix('-')
        records: list[ModelT] = []
        direction = -1 if descending else 1
        for document in self._collection.find(query).sort([(field, direction), ('_id', direction)]):
            record = self._model_from_document(document, model_type)
            if record is not None:
                records.append(record)
        return records

    def _atomic(self, operation: Callable[[Any], None]) -> None:
        """Run a multi-record write only where MongoDB transactions are available."""
        with self._client.start_session() as session:
            session.with_transaction(operation)

    # Remaining PersistenceRepository operations are deliberately explicit until
    # their mapping and transaction tests are added in follow-up commits.
    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f'MongoDB adapter capability is not implemented: {name}')
