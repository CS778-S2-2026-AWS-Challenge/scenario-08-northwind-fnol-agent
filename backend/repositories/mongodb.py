"""MongoDB persistence primitives for the provider-neutral repository contract.

The adapter is intentionally not selected by the runtime profile yet.  The
MongoDB bundle must implement the complete contract before ``DATA_RUNTIME_PROFILE``
can enable it.  This module provides the first durable slice and keeps provider
document details below the repository boundary.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError, PyMongoError

from backend.domain.models import (
    ActorType,
    AgentDecisionRecord,
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
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    RevisionConflict,
)

ModelT = TypeVar('ModelT', bound=BaseModel)


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
    except (PyMongoError, ValueError) as error:
        if client is not None:
            client.close()
        raise MongoDBConfigurationError(
            'MongoDB connection or repository initialisation failed.'
        ) from error


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

    def connection_status(self) -> str:
        try:
            self._client.admin.command('ping')
        except PyMongoError:
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

    def save_claim(self, claim: WorkingClaim, expected_revision: int) -> None:
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
            or session.claim_id != claim.claim_id
            or session.customer_id != claim.customer_id
            or session.context_revision != claim.revision
            or message.claim_id != claim.claim_id
            or message.session_id != session.session_id
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
    ) -> None:
        if (
            claim.revision != expected_revision + 1
            or evidence.claim_id != claim.claim_id
            or idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != (claim.active_session_id or '')
        ):
            raise KeyError(claim.claim_id)
        self._atomic(
            lambda mongo_session: self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                records=[('evidence', evidence.evidence_id, evidence)],
            )
        )

    def save_handoff_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        handoff: HandoffRecord,
        idempotency: IdempotencyRecord,
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
        self._atomic(
            lambda mongo_session: self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                records=[('handoff', handoff.handoff_id, handoff)],
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
            if stored_session is None or stored_session.claim_id != claim.claim_id:
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
            projection={'revision': 1},
            session=mongo_session,
        )
        if current is None:
            self._raise_revision_conflict(claim.claim_id, mongo_session=mongo_session)

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
    ) -> None:
        self._validate_session_mutation(claim, expected_revision, session, idempotency)
        self._atomic(
            lambda mongo_session: self._save_session_mutation(
                claim, expected_revision, session, idempotency, mongo_session
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
        mongo_session: Any,
    ) -> None:
        if (
            self.get_active_session(claim.claim_id, claim.customer_id, mongo_session=mongo_session)
            is not None
        ):
            raise IdempotencyConflict(session.session_id)
        self._reject_session_identity_conflict(session, mongo_session=mongo_session)
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
        self._save_idempotency(record=idempotency, session=mongo_session)

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
        for document in self._collection.find(query).sort(field, -1 if descending else 1):
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
