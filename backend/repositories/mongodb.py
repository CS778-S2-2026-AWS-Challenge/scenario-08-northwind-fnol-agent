"""MongoDB persistence primitives for the provider-neutral repository contract.

The adapter is intentionally not selected by the runtime profile yet.  The
MongoDB bundle must implement the complete contract before ``DATA_RUNTIME_PROFILE``
can enable it.  This module provides the first durable slice and keeps provider
document details below the repository boundary.
"""

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from backend.domain.models import SessionRecord, WorkingClaim
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    RevisionConflict,
)

ModelT = TypeVar('ModelT', bound=BaseModel)


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
        self._collection.create_index([('kind', 1), ('claim_id', 1), ('created_at', 1)])
        self._collection.create_index([('kind', 1), ('customer_id', 1), ('updated_at', -1)])
        self._collection.create_index(
            [('kind', 1), ('actor_id', 1), ('route', 1), ('key', 1)],
            unique=True,
            partialFilterExpression={'kind': 'idempotency'},
        )

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
                'kind': kind,
                'customer_id': customer_id,
                'claim_id': claim_id,
            }
        )
        self._collection.replace_one(
            {'_id': document['_id']},
            document,
            upsert=True,
            session=session,
        )

    def _get(
        self,
        kind: str,
        identifier: str,
        model_type: type[ModelT],
        *,
        customer_id: str | None = None,
        session: Any = None,
    ) -> ModelT | None:
        query: dict[str, Any] = {'_id': self._record_id(kind, identifier), 'kind': kind}
        if customer_id is not None:
            query['customer_id'] = customer_id
        document = self._collection.find_one(query, session=session)
        if document is None:
            return None
        document.pop('_id', None)
        document.pop('kind', None)
        return model_type.model_validate(document)

    def create_claim(self, claim: WorkingClaim, session: SessionRecord) -> None:
        self._put(
            'claim', claim.claim_id, claim, customer_id=claim.customer_id, claim_id=claim.claim_id
        )
        self._put(
            'session',
            session.session_id,
            session,
            customer_id=session.customer_id,
            claim_id=session.claim_id,
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
                'kind': 'claim',
                'customer_id': claim.customer_id,
                'revision': expected_revision,
            },
            {
                **claim.model_dump(mode='json'),
                '_id': self._record_id('claim', claim.claim_id),
                'kind': 'claim',
                'customer_id': claim.customer_id,
                'claim_id': claim.claim_id,
            },
        )
        if result.matched_count == 0:
            current = self._collection.find_one(
                {'_id': self._record_id('claim', claim.claim_id), 'kind': 'claim'},
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
        self._put(
            'session',
            session.session_id,
            session,
            customer_id=session.customer_id,
            claim_id=session.claim_id,
        )

    def get_active_session(self, claim_id: str, customer_id: str) -> SessionRecord | None:
        claim = self.get_claim(claim_id, customer_id)
        if claim is None or claim.active_session_id is None:
            return None
        return self.get_session(claim_id, claim.active_session_id, customer_id)

    def list_sessions_for_claim(self, claim_id: str, customer_id: str) -> list[SessionRecord]:
        return self._list(
            'session',
            SessionRecord,
            {'claim_id': claim_id, 'customer_id': customer_id},
            'started_at',
        )

    def find_idempotency(self, actor_id: str, route: str, key: str) -> IdempotencyRecord | None:
        document = self._collection.find_one(
            {'kind': 'idempotency', 'actor_id': actor_id, 'route': route, 'key': key}
        )
        if document is None:
            return None
        return IdempotencyRecord(**document['payload'])

    def save_idempotency(self, record: IdempotencyRecord) -> None:
        query = {
            'kind': 'idempotency',
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
        self._atomic(
            lambda mongo_session: self._save_session_mutation(
                claim, expected_revision, session, idempotency, mongo_session
            )
        )

    def _save_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        mongo_session: Any,
    ) -> None:
        result = self._collection.replace_one(
            {
                '_id': self._record_id('claim', claim.claim_id),
                'kind': 'claim',
                'customer_id': claim.customer_id,
                'revision': expected_revision,
            },
            {
                **claim.model_dump(mode='json'),
                '_id': self._record_id('claim', claim.claim_id),
                'kind': 'claim',
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
            'kind': 'idempotency',
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
        query = {'kind': kind, **filters}
        descending = sort_field.startswith('-')
        field = sort_field.removeprefix('-')
        records: list[ModelT] = []
        for document in self._collection.find(query).sort(field, -1 if descending else 1):
            document.pop('_id', None)
            document.pop('kind', None)
            records.append(model_type.model_validate(document))
        return records

    def _atomic(self, operation: Callable[[Any], None]) -> None:
        """Run a multi-record write only where MongoDB transactions are available."""
        with self._client.start_session() as session:
            session.with_transaction(operation)

    # Remaining PersistenceRepository operations are deliberately explicit until
    # their mapping and transaction tests are added in follow-up commits.
    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f'MongoDB adapter capability is not implemented: {name}')
