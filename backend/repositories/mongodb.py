"""MongoDB persistence primitives for the provider-neutral repository contract.

The adapter is intentionally not selected by the runtime profile yet.  The
MongoDB bundle must implement the complete contract before ``DATA_RUNTIME_PROFILE``
can enable it.  This module provides the first durable slice and keeps provider
document details below the repository boundary.
"""

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Any, NoReturn, TypeVar, cast

from pydantic import BaseModel, TypeAdapter, ValidationError

from backend.domain.account_data import (
    IdentityDocumentRecord,
    PaymentDestinationRecord,
    PolicyNumberRecord,
)
from backend.domain.agent_context_runtime import VerifiedConversationSummary
from backend.domain.assets import AssetRecord, AssetType, ClaimAssetSnapshot
from backend.domain.audit import AuditEventEnvelope, AuditSubject
from backend.domain.claim_creation import (
    ClaimCreationOperationRecord,
    ClaimCreationOperationStatus,
    assert_claim_creation_operation_transition,
    evidence_snapshot_fingerprint,
)
from backend.domain.evidence import (
    assert_material_history_is_append_only,
    validate_evidence_record,
)
from backend.domain.external_services import (
    ExternalTaskAttempt,
    ExternalTaskEvidenceLink,
    ExternalTaskRecord,
    ExternalTaskRequest,
    ExternalTaskResult,
    ExternalTaskResultVerification,
    assert_disclosure_within_consent,
    assert_external_task_registry_compatible,
    assert_request_matches_task,
    assert_result_advance_is_permitted,
    assert_result_evidence_is_linked,
    assert_result_matches_task,
    assert_task_transition_is_permitted,
)
from backend.domain.follow_up_execution import (
    FollowUpContactWithdrawalRejected,
    FollowUpDueExecutionRejected,
    FollowUpExpiryExecutionRejected,
    FollowUpStaffAbandonmentRejected,
    reduce_due_follow_up,
    reduce_expired_follow_up,
    reduce_follow_up_contact_withdrawal,
    reduce_follow_up_staff_abandonment,
)
from backend.domain.follow_up_migration import (
    backfill_legacy_follow_up_record,
)
from backend.domain.message import (
    DuplicateClientMessage,
    order_messages,
    validate_message_graph,
    validate_message_record,
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
    ContentsItemEvidenceAssociation,
    CustomerUpdateRecord,
    EvidenceClaimLink,
    EvidenceRecord,
    FollowUpOperation,
    FollowUpOperationStatus,
    FollowUpReasonCode,
    FollowUpRecord,
    FollowUpStatus,
    HandoffRecord,
    MessageRecord,
    MessageVisibility,
    MotorOtherDriverRecord,
    RuntimeTraceRecord,
    SessionRecord,
    SessionStatus,
    SignalDecisionRecord,
    StaffActionRecord,
    StaffActionStatus,
    WorkingClaim,
    assert_follow_up_operation_transition,
)
from backend.domain.realtime import (
    AgentTurnProgressPublication,
    MutationOutcome,
    RealtimeCursor,
    RealtimeEvent,
    RealtimeMutation,
    RealtimePublication,
    RealtimeResource,
    claimant_resources_for,
    realtime_event_from_publication,
    realtime_publication_for,
    realtime_resources_for_records,
)
from backend.domain.retention import (
    RETENTION_STORAGE_TARGETS,
    RETENTION_TARGET_STORAGE_TYPE,
    ResourceAccessClosed,
    RetentionClassification,
    RetentionCleanupTarget,
    RetentionDatabaseStepError,
    RetentionEligibilityReason,
    RetentionEligibilityRejected,
    RetentionHoldRecord,
    RetentionOperation,
    RetentionOperationStatus,
    RetentionRecordTombstone,
    RetentionStepEvidence,
    RetentionStepStatus,
    RetentionTargetFreezeReason,
    RetentionTargetFreezeRejected,
    RetentionTargetKind,
    build_retention_cleanup_target,
    retention_access_closed,
    retention_candidate_after_step,
    retention_next_attempt,
    retention_record_identity,
    retention_step_evidence_id,
    retention_target_statuses,
    retention_tombstone_authority,
    validate_retention_eligibility_source,
    validate_retention_hold_transition,
    validate_retention_operation_transition,
    validate_retention_source_authority,
)
from backend.domain.retrieval import (
    ClaimHistoryRetrievalRecord,
    PolicyRetrievalRecord,
    RetrievalKind,
    RetrievalRecord,
    ReviewSignalRecord,
)
from backend.domain.runtime import (
    ActionEnvelopeRecord,
    AgentProposalRecord,
    ExecutionPlanRecord,
    RuntimeTurnRecords,
    RuntimeWorkItemRecord,
    ToolResultRecord,
    TurnPlanRecord,
    TurnResultRecord,
    validate_runtime_turn_links,
)
from backend.domain.staff_agent import (
    StaffAgentExecutionRecord,
    StaffAgentMessage,
    StaffAgentSession,
)
from backend.domain.staff_agent_tools import (
    STAFF_SESSION_MAX_EXAMINED,
    STAFF_SESSION_MESSAGE_MAX_EXAMINED,
    StaffClaimSearchCandidate,
    StaffClaimSearchProjection,
    StaffSessionSearchCandidate,
    build_staff_claim_search_candidate,
    build_staff_claim_search_projection,
)
from backend.domain.staff_identity import StaffPresenceRecord
from backend.repositories.account_data import (
    AccountCursorKey,
    AccountRecord,
    CommonPaymentDestinationConflict,
    PaymentDestinationDesignationConflict,
    PaymentDestinationSelectionConflict,
    PolicySelectionConflict,
    account_record_audit_matches,
    account_record_identity,
    payment_destination_create_result,
    payment_destination_demotion,
    payout_contact_selection_audit_matches,
    policy_selection_audit_matches,
)
from backend.repositories.assets import (
    AssetSelectionRevisionConflictError,
    AssetSelectionSnapshotConflictError,
    AssetSelectionUnavailableError,
    asset_audit_matches,
    asset_matches_snapshot,
    asset_selection_audit_matches,
)
from backend.repositories.protocols import (
    DemoSeedConflict,
    IdempotencyConflict,
    IdempotencyRecord,
    RecoveryDeadlineConflict,
    RepositorySearchLimitExceeded,
    RevisionConflict,
    ValidationSeedGraph,
    validate_handoff_mutation_audit,
    validate_staff_agent_execution,
    validate_staff_agent_execution_source,
    validate_validation_seed_session,
)
from pymongo import MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError, PyMongoError

ModelT = TypeVar('ModelT', bound=BaseModel)
ResultT = TypeVar('ResultT')
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


IMMUTABLE_CHILD_RECORD_KINDS = frozenset(
    {
        'message',
        'conversation_summary',
        'agent_decision',
        'branch_evaluation',
        'runtime_trace',
        'turn_plan',
        'agent_proposal',
        'action_envelope',
        'execution_plan',
        'tool_result',
        'turn_result',
        'runtime_work_item',
        'staff_agent_execution',
        'claim_asset_snapshot',
        'motor_other_driver',
        'contents_item_evidence_association',
    }
)
"""Child records whose identity may never be rebound or rewritten once persisted.

Runtime records are execution evidence, not mutable Claim projections.  Treating
them as immutable prevents a retry or a later turn from rewriting the plan that
was actually authorised and executed.
"""


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
        account_record_types = ['identity_document', 'payment_destination', 'policy']
        self._collection.create_index(
            [('record_type', 1), ('customer_id', 1), ('created_at', -1), ('_id', -1)],
            name='account_record_customer_active_created',
            partialFilterExpression={
                'record_type': {'$in': account_record_types},
                'active': True,
            },
        )
        self._collection.create_index(
            [('record_type', 1), ('customer_id', 1), ('created_at', -1), ('_id', -1)],
            name='account_record_customer_all_created',
            partialFilterExpression={'record_type': {'$in': account_record_types}},
        )
        self._collection.create_index(
            [('record_type', 1), ('customer_id', 1), ('is_common', 1)],
            unique=True,
            name='payment_destination_active_common_unique',
            partialFilterExpression={
                'record_type': 'payment_destination',
                'active': True,
                'is_common': True,
            },
        )
        self._collection.create_index(
            [
                ('record_type', 1),
                ('customer_id', 1),
                ('active', 1),
                ('updated_at', -1),
                ('_id', -1),
            ],
            name='asset_customer_active_updated',
            partialFilterExpression={'record_type': 'asset'},
        )
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1), ('captured_at', 1), ('_id', 1)],
            name='claim_asset_snapshot_claim_captured',
            partialFilterExpression={'record_type': 'claim_asset_snapshot'},
        )
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1)],
            unique=True,
            name='motor_other_driver_claim_unique',
            partialFilterExpression={'record_type': 'motor_other_driver'},
        )
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1), ('item_id', 1), ('evidence_id', 1)],
            unique=True,
            name='contents_item_evidence_unique',
            partialFilterExpression={'record_type': 'contents_item_evidence_association'},
        )
        self._collection.create_index(
            [
                ('record_type', 1),
                ('claim_id', 1),
                ('customer_id', 1),
                ('item_id', 1),
                ('created_at', 1),
                ('association_id', 1),
            ],
            name='contents_item_evidence_page',
            partialFilterExpression={'record_type': 'contents_item_evidence_association'},
        )
        self._collection.create_index(
            [('record_type', 1), ('actor_id', 1), ('route', 1), ('key', 1)],
            unique=True,
            partialFilterExpression={'record_type': 'idempotency'},
        )
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1)],
            unique=True,
            name='claim_creation_operation_claim_unique',
            partialFilterExpression={'record_type': 'claim_creation_operation'},
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
            [
                ('record_type', 1),
                ('claim_id', 1),
                ('customer_id', 1),
                ('started_at', -1),
                ('_id', -1),
            ],
            name='staff_session_search_claim_started',
            partialFilterExpression={'record_type': 'session'},
        )
        self._collection.create_index(
            [
                ('record_type', 1),
                ('claim_id', 1),
                ('customer_id', 1),
                ('status', 1),
                ('started_at', -1),
                ('_id', -1),
            ],
            name='staff_session_search_claim_status_started',
            partialFilterExpression={'record_type': 'session'},
        )
        self._collection.create_index(
            [
                ('record_type', 1),
                ('claim_id', 1),
                ('session_id', 1),
                ('customer_id', 1),
                ('created_at', -1),
                ('_id', -1),
            ],
            name='staff_session_message_lookup',
            partialFilterExpression={'record_type': 'message'},
        )
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1), ('source_session_id', 1)],
            unique=True,
            name='follow_up_source_session_unique',
            partialFilterExpression={'record_type': 'follow_up'},
        )
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1), ('purpose', 1)],
            unique=True,
            name='follow_up_claim_purpose_open_unique',
            partialFilterExpression={
                'record_type': 'follow_up',
                'status': {'$in': [FollowUpStatus.PENDING.value, FollowUpStatus.BLOCKED.value]},
            },
        )
        self._collection.create_index(
            [('record_type', 1), ('operation_id', 1)],
            unique=True,
            name='follow_up_operation_id_unique',
            partialFilterExpression={'record_type': 'follow_up_operation'},
        )
        self._collection.create_index(
            [
                ('record_type', 1),
                ('follow_up_id', 1),
                ('sequence', 1),
            ],
            unique=True,
            name='follow_up_operation_sequence_unique',
            partialFilterExpression={'record_type': 'follow_up_operation'},
        )
        self._collection.create_index(
            [
                ('record_type', 1),
                ('due_at', 1),
                ('follow_up_id', 1),
            ],
            name='follow_up_due_order',
            partialFilterExpression={
                'record_type': 'follow_up',
                'status': FollowUpStatus.PENDING.value,
            },
        )
        self._collection.create_index(
            [
                ('record_type', 1),
                ('deadline_at', 1),
                ('follow_up_id', 1),
            ],
            name='follow_up_deadline_order',
            partialFilterExpression={
                'record_type': 'follow_up',
                'status': {
                    '$in': [
                        FollowUpStatus.PENDING.value,
                        FollowUpStatus.BLOCKED.value,
                    ]
                },
            },
        )
        self._collection.create_index(
            [('record_type', 1), ('status', 1), ('due_at', 1), ('_id', 1)],
            name='follow_up_due_ordered',
            partialFilterExpression={
                'record_type': 'follow_up',
                'status': FollowUpStatus.PENDING.value,
            },
        )
        self._collection.create_index(
            [('record_type', 1), ('status', 1), ('deadline_at', 1), ('_id', 1)],
            name='follow_up_deadline_ordered',
            partialFilterExpression={
                'record_type': 'follow_up',
                'status': {'$in': [FollowUpStatus.PENDING.value, FollowUpStatus.BLOCKED.value]},
            },
        )
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1), ('updated_at', 1), ('_id', 1)],
            name='retention_operation_claim_updated',
            partialFilterExpression={'record_type': 'retention_operation'},
        )
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1), ('created_at', 1)],
            name='branch_evaluation_claim_created',
        )
        self._collection.create_index(
            [('record_type', 1), ('realtime_order', 1)],
            unique=True,
            name='realtime_event_order_unique',
            partialFilterExpression={'record_type': 'realtime_event'},
        )
        # One task carries one canonical result. Without this, two concurrent first
        # writes can each observe no held record and both insert.
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1), ('task_id', 1)],
            unique=True,
            name='external_task_result_task_unique',
            partialFilterExpression={'record_type': 'external_task_result'},
        )
        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1), ('task_id', 1), ('attempt_number', 1)],
            unique=True,
            name='external_task_attempt_sequence_unique',
            partialFilterExpression={'record_type': 'external_task_attempt'},
        )
        for search_field in (
            'external_reference',
            'created_date',
            'incident_date',
            'product_family',
            'lifecycle_state',
            'assignee_id',
            'queue',
        ):
            self._collection.create_index(
                [('record_type', 1), (f'staff_search.{search_field}', 1), ('updated_at', -1)],
                name=f'staff_claim_search_{search_field}',
                partialFilterExpression={'record_type': 'claim'},
            )
        self._backfill_staff_search_projections()

        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1)],
            unique=True,
            name='retention_operation_claim_unique',
            partialFilterExpression={
                'record_type': 'retention_operation',
            },
        )
        self._collection.create_index(
            [
                ('record_type', 1),
                ('claim_id', 1),
                ('released_at', 1),
                ('applied_at', 1),
                ('_id', 1),
            ],
            name='retention_hold_claim_state',
            partialFilterExpression={
                'record_type': 'retention_hold',
            },
        )

    def connection_status(self) -> str:
        try:
            self._client.admin.command('ping')
        except (PyMongoError, ValueError):
            return 'unavailable'
        return 'verified'

    def close(self) -> None:
        self._client.close()

    def get_retention_operation(
        self,
        operation_id: str,
    ) -> RetentionOperation | None:
        return self._get(
            'retention_operation',
            operation_id,
            RetentionOperation,
        )

    def get_retention_operation_for_claim(
        self,
        claim_id: str,
    ) -> RetentionOperation | None:
        document = self._collection.find_one(
            {
                'record_type': 'retention_operation',
                'claim_id': claim_id,
            }
        )

        return self._model_from_document(
            document,
            RetentionOperation,
        )

    def list_pending_retention_operations(
        self,
        *,
        limit: int,
    ) -> list[RetentionOperation]:
        if not 1 <= limit <= 100:
            raise ValueError('Retention discovery limit must be between 1 and 100.')
        documents = (
            self._collection.find(
                {
                    'record_type': 'retention_operation',
                    'status': {'$ne': RetentionOperationStatus.COMPLETED.value},
                }
            )
            .sort([('updated_at', 1), ('_id', 1)])
            .limit(limit)
        )
        return [
            operation
            for document in documents
            if (operation := self._model_from_document(document, RetentionOperation)) is not None
        ]

    def reserve_eligible_retention_operation(
        self,
        operation: RetentionOperation,
    ) -> RetentionOperation:
        """Atomically validate P17 retention authority and close claimant access."""

        def reserve(
            mongo_session: Any,
        ) -> RetentionOperation:
            existing_document = self._collection.find_one(
                {
                    'record_type': ('retention_operation'),
                    'claim_id': operation.claim_id,
                },
                session=mongo_session,
            )

            existing = self._model_from_document(
                existing_document,
                RetentionOperation,
            )

            if existing is not None:
                same_logical_operation = (
                    existing.operation_id == operation.operation_id
                    and existing.claim_id == operation.claim_id
                    and existing.source_terminal_ref == operation.source_terminal_ref
                    and existing.source_claim_revision == operation.source_claim_revision
                    and existing.policy_id == operation.policy_id
                    and existing.policy_version == operation.policy_version
                    and existing.source_refs == operation.source_refs
                )

                if not same_logical_operation:
                    raise IdempotencyConflict(operation.operation_id)

                return existing

            claim = self._get(
                'claim',
                operation.claim_id,
                WorkingClaim,
                session=mongo_session,
            )

            if claim is None:
                raise RetentionEligibilityRejected(
                    RetentionEligibilityReason.CLAIM_NOT_FOUND,
                    operation.claim_id,
                )

            validate_retention_eligibility_source(
                claim,
                operation,
            )

            recovery_open = (
                self._collection.find_one(
                    {
                        'record_type': ('follow_up_operation'),
                        'claim_id': operation.claim_id,
                        'status': {
                            '$in': [
                                FollowUpOperationStatus.RESERVED.value,
                                FollowUpOperationStatus.COMMITTED.value,
                            ]
                        },
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            if recovery_open:
                raise RetentionEligibilityRejected(
                    RetentionEligibilityReason.RECOVERY_OPERATION_OPEN,
                    operation.claim_id,
                )

            external_unknown = (
                self._collection.find_one(
                    {
                        'record_type': 'external_task',
                        'claim_id': operation.claim_id,
                        'status': 'unknown_outcome',
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            if external_unknown:
                raise RetentionEligibilityRejected(
                    RetentionEligibilityReason.EXTERNAL_OUTCOME_UNKNOWN,
                    operation.claim_id,
                )

            open_runtime_work = (
                self._collection.find_one(
                    {
                        'record_type': ('runtime_work_item'),
                        'claim_id': operation.claim_id,
                        'status': {
                            '$in': [
                                'open',
                                'in_progress',
                            ]
                        },
                        'owner': {
                            '$in': [
                                'staff',
                                'system',
                                'external',
                            ]
                        },
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            open_handoff = (
                self._collection.find_one(
                    {
                        'record_type': 'handoff',
                        'claim_id': operation.claim_id,
                        'status': {
                            '$in': [
                                'requested',
                                'queued',
                                'accepted',
                                'in_progress',
                            ]
                        },
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            if open_runtime_work or open_handoff:
                raise RetentionEligibilityRejected(
                    RetentionEligibilityReason.STAFF_RESPONSIBILITY_OPEN,
                    operation.claim_id,
                )

            hold_documents = list(
                self._collection.find(
                    {
                        'record_type': 'retention_hold',
                        'claim_id': operation.claim_id,
                        'released_at': None,
                    },
                    session=mongo_session,
                )
            )

            active_hold_ids = sorted(str(document['hold_id']) for document in hold_documents)

            candidate = operation

            if active_hold_ids:
                payload = operation.model_dump(mode='python')
                payload.update(
                    {
                        'status': (RetentionOperationStatus.HELD),
                        'hold_refs': sorted(set(operation.hold_refs).union(active_hold_ids)),
                    }
                )
                candidate = RetentionOperation.model_validate(payload)

            winner = self._insert_retention_operation(candidate, mongo_session)
            if winner is not None:
                return winner

            self._collection.update_many(
                {
                    'record_type': 'idempotency',
                    'actor_id': claim.customer_id,
                    'payload.claim_id': candidate.claim_id,
                    'payload.retired': {
                        '$ne': True,
                    },
                },
                {
                    '$set': {
                        'payload.retired': True,
                    }
                },
                session=mongo_session,
            )

            return candidate

        return self._atomic(reserve)

    def _insert_retention_operation(
        self,
        operation: RetentionOperation,
        mongo_session: Any,
    ) -> RetentionOperation | None:
        """Insert-only creation; never replaces an existing operation.

        Returns ``None`` when this call created the operation, or the stored
        operation when an identical concurrent reservation already won.
        Any other stored operation for the same identity or Claim conflicts.
        """
        document = {
            **operation.model_dump(mode='json'),
            '_id': self._record_id('retention_operation', operation.operation_id),
            'record_type': 'retention_operation',
            'customer_id': None,
            'claim_id': operation.claim_id,
        }
        try:
            self._collection.insert_one(document, session=mongo_session)
        except DuplicateKeyError as error:
            stored = self._model_from_document(
                self._collection.find_one(
                    {'record_type': 'retention_operation', 'claim_id': operation.claim_id},
                    session=mongo_session,
                ),
                RetentionOperation,
            )
            if stored == operation:
                return stored
            raise IdempotencyConflict(operation.operation_id) from error
        return None

    def reserve_retention_operation(
        self,
        operation: RetentionOperation,
    ) -> bool:
        if operation.revision != 1 or operation.status is not RetentionOperationStatus.RESERVED:
            raise ValueError('Initial retention reservation must be revision 1 and reserved.')

        def persist(mongo_session: Any) -> bool:
            document = self._collection.find_one(
                {
                    'record_type': 'retention_operation',
                    'claim_id': operation.claim_id,
                },
                session=mongo_session,
            )

            existing = self._model_from_document(
                document,
                RetentionOperation,
            )

            if existing is not None:
                if existing.operation_id == operation.operation_id and existing == operation:
                    return False

                raise IdempotencyConflict(operation.operation_id)

            if self._insert_retention_operation(operation, mongo_session) is not None:
                return False

            claim = self._get(
                'claim',
                operation.claim_id,
                WorkingClaim,
                session=mongo_session,
            )

            if claim is not None:
                self._collection.update_many(
                    {
                        'record_type': 'idempotency',
                        'actor_id': claim.customer_id,
                        'payload.claim_id': operation.claim_id,
                        'payload.retired': {'$ne': True},
                    },
                    {
                        '$set': {
                            'payload.retired': True,
                        }
                    },
                    session=mongo_session,
                )

            return True

        return self._atomic(persist)

    def freeze_retention_targets(
        self,
        operation_id: str,
        expected_revision: int,
        *,
        frozen_at: datetime,
    ) -> RetentionOperation:
        """Freeze the exact selected Mongo/object inventory in one transaction."""

        def freeze(
            mongo_session: Any,
        ) -> RetentionOperation:
            operation = self._get(
                'retention_operation',
                operation_id,
                RetentionOperation,
                session=mongo_session,
            )

            if operation is None:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.OPERATION_NOT_FOUND,
                    operation_id,
                )

            if operation.revision != expected_revision:
                raise RevisionConflict(operation.revision)

            if operation.targets_frozen_at is not None:
                return operation

            claim = self._get(
                'claim',
                operation.claim_id,
                WorkingClaim,
                session=mongo_session,
            )

            if claim is None:
                raise RetentionEligibilityRejected(
                    RetentionEligibilityReason.CLAIM_NOT_FOUND,
                    operation.claim_id,
                )

            validate_retention_source_authority(
                claim,
                operation,
            )

            if (
                operation.status
                not in {
                    RetentionOperationStatus.RESERVED,
                    RetentionOperationStatus.HELD,
                }
                or operation.targets
                or operation.step_evidence
                or operation.completed_at is not None
            ):
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.INVALID_OPERATION_SHAPE,
                    operation.claim_id,
                )

            active_hold = (
                self._collection.find_one(
                    {
                        'record_type': 'retention_hold',
                        'claim_id': operation.claim_id,
                        'released_at': None,
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            if active_hold:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.ACTIVE_HOLD,
                    operation.claim_id,
                )

            recovery_open = (
                self._collection.find_one(
                    {
                        'record_type': 'follow_up_operation',
                        'claim_id': operation.claim_id,
                        'status': {
                            '$in': [
                                FollowUpOperationStatus.RESERVED.value,
                                'committed',
                            ]
                        },
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            if recovery_open:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.RECOVERY_OPERATION_OPEN,
                    operation.claim_id,
                )

            external_unknown = (
                self._collection.find_one(
                    {
                        'record_type': 'external_task',
                        'claim_id': operation.claim_id,
                        'status': 'unknown_outcome',
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            if external_unknown:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.EXTERNAL_OUTCOME_UNKNOWN,
                    operation.claim_id,
                )

            open_work = (
                self._collection.find_one(
                    {
                        'record_type': 'runtime_work_item',
                        'claim_id': operation.claim_id,
                        'status': {
                            '$in': [
                                'open',
                                'in_progress',
                            ]
                        },
                        'owner': {
                            '$in': [
                                'staff',
                                'system',
                                'external',
                            ]
                        },
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            open_handoff = (
                self._collection.find_one(
                    {
                        'record_type': 'handoff',
                        'claim_id': operation.claim_id,
                        'status': {
                            '$in': [
                                'requested',
                                'queued',
                                'accepted',
                                'in_progress',
                            ]
                        },
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            if open_work or open_handoff:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.STAFF_RESPONSIBILITY_OPEN,
                    operation.claim_id,
                )

            targets: dict[str, RetentionCleanupTarget] = {}

            identifier_fields = {
                'claim': 'claim_id',
                'session': 'session_id',
                'message': 'message_id',
                'follow_up': 'follow_up_id',
                'follow_up_operation': 'operation_id',
                'runtime_work_item': 'work_item_id',
                'handoff': 'handoff_id',
                'evidence': 'evidence_id',
                'external_task': 'task_id',
                'external_task_request': 'request_id',
                'external_task_attempt': 'attempt_id',
                'external_task_result': 'result_id',
                'retention_hold': 'hold_id',
                'audit_event': 'event_id',
            }

            def add_target(
                storage_type: str,
                record_id: str,
                *,
                source_refs: tuple[str, ...] = (),
            ) -> None:
                selected = RETENTION_STORAGE_TARGETS.get(storage_type)

                if selected is None:
                    raise RetentionTargetFreezeRejected(
                        RetentionTargetFreezeReason.INVALID_RECORD_IDENTITY,
                        operation.claim_id,
                    )

                logical_type, classification = selected

                target = build_retention_cleanup_target(
                    operation=operation,
                    record_type=logical_type,
                    record_id=record_id,
                    classification=classification,
                    source_refs=source_refs,
                )

                targets[target.target_id] = target

            regular_storage_types = [
                item
                for item in RETENTION_STORAGE_TARGETS
                if item
                not in {
                    'idempotency',
                    'audit_event',
                    'external_task_evidence_link',
                }
            ]

            for storage_type in regular_storage_types:
                field = identifier_fields.get(storage_type)

                if field is None:
                    continue

                documents = self._collection.find(
                    {
                        'record_type': storage_type,
                        'claim_id': operation.claim_id,
                    },
                    session=mongo_session,
                )

                for document in documents:
                    value = document.get(field)

                    if not isinstance(value, str) or not value:
                        raise RetentionTargetFreezeRejected(
                            RetentionTargetFreezeReason.INVALID_RECORD_IDENTITY,
                            operation.claim_id,
                        )

                    add_target(
                        storage_type,
                        value,
                        source_refs=(f'{storage_type}:{value}',),
                    )

                    if storage_type != 'evidence':
                        continue

                    provenance = document.get('provenance')

                    if not isinstance(provenance, dict):
                        continue

                    storage_key = provenance.get('storage_key')

                    if storage_key is None:
                        continue

                    if not isinstance(storage_key, str) or not storage_key.strip():
                        raise RetentionTargetFreezeRejected(
                            RetentionTargetFreezeReason.INVALID_STORAGE_REFERENCE,
                            operation.claim_id,
                        )

                    object_target = build_retention_cleanup_target(
                        operation=operation,
                        record_type='EvidenceObjectBytes',
                        record_id=value,
                        classification=RetentionClassification.DELETE,
                        kind=RetentionTargetKind.OBJECT_BYTES,
                        storage_key=storage_key,
                        source_refs=(f'evidence:{value}',),
                    )

                    targets[object_target.target_id] = object_target

            evidence_claim_links = self._collection.find(
                {
                    'record_type': 'evidence_claim_link',
                    '$or': [
                        {
                            'source_claim_id': operation.claim_id,
                        },
                        {
                            'target_claim_id': operation.claim_id,
                        },
                    ],
                },
                session=mongo_session,
            )

            for document in evidence_claim_links:
                link_id = document.get('link_id')
                evidence_id = document.get('evidence_id')
                source_claim_id = document.get('source_claim_id')
                target_claim_id = document.get('target_claim_id')

                if (
                    not isinstance(link_id, str)
                    or not link_id
                    or not isinstance(evidence_id, str)
                    or not evidence_id
                    or not isinstance(source_claim_id, str)
                    or not source_claim_id
                    or not isinstance(target_claim_id, str)
                    or not target_claim_id
                ):
                    raise RetentionTargetFreezeRejected(
                        RetentionTargetFreezeReason.INVALID_RECORD_IDENTITY,
                        operation.claim_id,
                    )

                add_target(
                    'evidence_claim_link',
                    link_id,
                    source_refs=(
                        f'evidence:{evidence_id}',
                        f'claim:{source_claim_id}',
                        f'claim:{target_claim_id}',
                    ),
                )

            external_links = self._collection.find(
                {
                    'record_type': 'external_task_evidence_link',
                    'claim_id': operation.claim_id,
                },
                session=mongo_session,
            )

            for document in external_links:
                task_id = document.get('task_id')
                evidence_id = document.get('evidence_id')

                if (
                    not isinstance(task_id, str)
                    or not task_id
                    or not isinstance(evidence_id, str)
                    or not evidence_id
                ):
                    raise RetentionTargetFreezeRejected(
                        RetentionTargetFreezeReason.INVALID_RECORD_IDENTITY,
                        operation.claim_id,
                    )

                link_id = retention_record_identity(
                    'external_link',
                    task_id,
                    evidence_id,
                )

                add_target(
                    'external_task_evidence_link',
                    link_id,
                    source_refs=(
                        f'external-task:{task_id}',
                        f'evidence:{evidence_id}',
                    ),
                )

            idempotency_documents = self._collection.find(
                {
                    'record_type': 'idempotency',
                    'actor_id': claim.customer_id,
                    'payload.claim_id': operation.claim_id,
                },
                session=mongo_session,
            )

            for document in idempotency_documents:
                actor_id = document.get('actor_id')
                route = document.get('route')
                key = document.get('key')

                if (
                    not isinstance(actor_id, str)
                    or not actor_id
                    or not isinstance(route, str)
                    or not route
                    or not isinstance(key, str)
                    or not key
                ):
                    raise RetentionTargetFreezeRejected(
                        RetentionTargetFreezeReason.INVALID_RECORD_IDENTITY,
                        operation.claim_id,
                    )

                record_id = retention_record_identity(
                    'idempotency',
                    actor_id,
                    route,
                    key,
                )

                add_target(
                    'idempotency',
                    record_id,
                    source_refs=(f'idempotency:{record_id}',),
                )

            audit_documents = self._collection.find(
                {
                    'record_type': 'audit_event',
                    'subject.claim_id': operation.claim_id,
                },
                session=mongo_session,
            )

            for document in audit_documents:
                event_id = document.get('event_id')

                if not isinstance(event_id, str) or not event_id:
                    raise RetentionTargetFreezeRejected(
                        RetentionTargetFreezeReason.INVALID_RECORD_IDENTITY,
                        operation.claim_id,
                    )

                add_target(
                    'audit_event',
                    event_id,
                    source_refs=(f'audit:{event_id}',),
                )

            selected_targets = sorted(
                targets.values(),
                key=lambda target: (
                    target.kind.value,
                    target.record_type,
                    target.record_id,
                    target.target_id,
                ),
            )

            if len(selected_targets) > 500:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.TARGET_LIMIT_EXCEEDED,
                    operation.claim_id,
                )

            payload = operation.model_dump(mode='python')
            payload.update(
                {
                    'revision': operation.revision + 1,
                    'status': RetentionOperationStatus.RESERVED,
                    'targets_frozen_at': frozen_at,
                    'targets': selected_targets,
                    'updated_at': frozen_at,
                    'completed_at': None,
                }
            )

            candidate = RetentionOperation.model_validate(payload)

            validate_retention_operation_transition(
                operation,
                candidate,
            )

            document = candidate.model_dump(mode='json')
            document.update(
                {
                    '_id': self._record_id(
                        'retention_operation',
                        candidate.operation_id,
                    ),
                    'record_type': 'retention_operation',
                    'customer_id': None,
                    'claim_id': candidate.claim_id,
                }
            )

            result = self._collection.replace_one(
                {
                    '_id': document['_id'],
                    'record_type': 'retention_operation',
                    'revision': expected_revision,
                },
                document,
                session=mongo_session,
            )

            if result.modified_count != 1:
                latest = self._get(
                    'retention_operation',
                    operation_id,
                    RetentionOperation,
                    session=mongo_session,
                )

                if latest is None:
                    raise KeyError(operation_id)

                raise RevisionConflict(latest.revision)

            return candidate

        return self._atomic(freeze)

    def get_retention_tombstone(
        self,
        target_id: str,
    ) -> RetentionRecordTombstone | None:
        return self._get(
            'retention_tombstone',
            target_id,
            RetentionRecordTombstone,
        )

    def record_retention_step_failure(
        self,
        operation_id: str,
        target_id: str,
        expected_revision: int,
        *,
        status: RetentionStepStatus,
        diagnostic_code: str,
        now: datetime,
    ) -> RetentionOperation:
        def record(
            mongo_session: Any,
        ) -> RetentionOperation:
            operation = self._get(
                'retention_operation',
                operation_id,
                RetentionOperation,
                session=mongo_session,
            )

            if operation is None:
                raise KeyError(operation_id)

            if operation.revision != expected_revision:
                raise RevisionConflict(operation.revision)

            if status not in {
                RetentionStepStatus.FAILED,
                RetentionStepStatus.UNKNOWN,
            }:
                raise ValueError('Retention failure evidence must be failed or unknown.')

            target = next(
                (item for item in operation.targets if item.target_id == target_id),
                None,
            )

            if target is None:
                raise KeyError(target_id)

            if target.kind is not RetentionTargetKind.MONGO_RECORD:
                raise ValueError('Database failure evidence requires a MONGO_RECORD target.')

            statuses = retention_target_statuses(
                operation.targets,
                operation.step_evidence,
            )

            if statuses[target_id] is RetentionStepStatus.SATISFIED:
                return operation

            attempt = retention_next_attempt(
                operation,
                target_id,
            )

            evidence = RetentionStepEvidence(
                evidence_id=retention_step_evidence_id(
                    operation.operation_id,
                    target_id,
                    attempt,
                ),
                target_id=target_id,
                attempt=attempt,
                status=status,
                diagnostic_code=diagnostic_code,
                source_refs=list(target.source_refs),
                recorded_at=now,
            )

            candidate = retention_candidate_after_step(
                operation,
                evidence,
                now=now,
            )

            validate_retention_operation_transition(
                operation,
                candidate,
            )

            document = candidate.model_dump(mode='json')

            document.update(
                {
                    '_id': self._record_id(
                        'retention_operation',
                        candidate.operation_id,
                    ),
                    'record_type': 'retention_operation',
                    'customer_id': None,
                    'claim_id': candidate.claim_id,
                }
            )

            result = self._collection.replace_one(
                {
                    '_id': document['_id'],
                    'record_type': 'retention_operation',
                    'revision': expected_revision,
                },
                document,
                session=mongo_session,
            )

            if result.modified_count != 1:
                latest = self._get(
                    'retention_operation',
                    operation_id,
                    RetentionOperation,
                    session=mongo_session,
                )

                if latest is None:
                    raise KeyError(operation_id)

                raise RevisionConflict(latest.revision)

            return candidate

        return self._atomic(record)

    def apply_retention_record_target(
        self,
        operation_id: str,
        target_id: str,
        expected_revision: int,
        *,
        now: datetime,
    ) -> RetentionOperation:
        """Mutate one database target and append evidence in the same transaction."""

        def apply(
            mongo_session: Any,
        ) -> RetentionOperation:
            operation = self._get(
                'retention_operation',
                operation_id,
                RetentionOperation,
                session=mongo_session,
            )

            if operation is None:
                raise KeyError(operation_id)

            if operation.revision != expected_revision:
                raise RevisionConflict(operation.revision)

            if operation.status is RetentionOperationStatus.COMPLETED:
                return operation

            active_hold = (
                self._collection.find_one(
                    {
                        'record_type': 'retention_hold',
                        'claim_id': operation.claim_id,
                        'released_at': None,
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            if active_hold:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.ACTIVE_HOLD,
                    operation.claim_id,
                )

            statuses = retention_target_statuses(
                operation.targets,
                operation.step_evidence,
            )

            target = next(
                (item for item in operation.targets if item.target_id == target_id),
                None,
            )

            if target is None:
                raise KeyError(target_id)

            if target.kind is not RetentionTargetKind.MONGO_RECORD:
                raise ValueError('Database cleanup may execute only frozen MONGO_RECORD targets.')

            if statuses[target.target_id] is RetentionStepStatus.SATISFIED:
                return operation

            object_incomplete = any(
                item.kind is RetentionTargetKind.OBJECT_BYTES
                and statuses[item.target_id] is not RetentionStepStatus.SATISFIED
                for item in operation.targets
            )

            if object_incomplete:
                raise ValueError(
                    'Database cleanup cannot begin before every object target is satisfied.'
                )

            recovery_open = (
                self._collection.find_one(
                    {
                        'record_type': 'follow_up_operation',
                        'claim_id': operation.claim_id,
                        'status': {
                            '$in': [
                                FollowUpOperationStatus.RESERVED.value,
                                'committed',
                            ]
                        },
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            external_unknown = (
                self._collection.find_one(
                    {
                        'record_type': 'external_task',
                        'claim_id': operation.claim_id,
                        'status': 'unknown_outcome',
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            staff_open = (
                self._collection.find_one(
                    {
                        'record_type': 'runtime_work_item',
                        'claim_id': operation.claim_id,
                        'status': {
                            '$in': [
                                'open',
                                'in_progress',
                            ]
                        },
                        'owner': {
                            '$in': [
                                'staff',
                                'system',
                                'external',
                            ]
                        },
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            handoff_open = (
                self._collection.find_one(
                    {
                        'record_type': 'handoff',
                        'claim_id': operation.claim_id,
                        'status': {
                            '$in': [
                                'requested',
                                'queued',
                                'accepted',
                                'in_progress',
                            ]
                        },
                    },
                    projection={'_id': 1},
                    session=mongo_session,
                )
                is not None
            )

            if recovery_open:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.RECOVERY_OPERATION_OPEN,
                    operation.claim_id,
                )

            if external_unknown:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.EXTERNAL_OUTCOME_UNKNOWN,
                    operation.claim_id,
                )

            if staff_open or handoff_open:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.STAFF_RESPONSIBILITY_OPEN,
                    operation.claim_id,
                )

            def source_query() -> dict[str, Any] | None:
                storage_type = RETENTION_TARGET_STORAGE_TYPE.get(target.record_type)

                if storage_type is None:
                    return None

                identifier_fields = {
                    'claim': 'claim_id',
                    'session': 'session_id',
                    'message': 'message_id',
                    'follow_up': 'follow_up_id',
                    'follow_up_operation': 'operation_id',
                    'runtime_work_item': 'work_item_id',
                    'handoff': 'handoff_id',
                    'evidence': 'evidence_id',
                    'external_task': 'task_id',
                    'external_task_request': 'request_id',
                    'external_task_attempt': 'attempt_id',
                    'external_task_result': 'result_id',
                    'retention_hold': 'hold_id',
                    'audit_event': 'event_id',
                }

                if storage_type == 'evidence_claim_link':
                    return {
                        'record_type': storage_type,
                        'link_id': target.record_id,
                        '$or': [
                            {
                                'source_claim_id': operation.claim_id,
                            },
                            {
                                'target_claim_id': operation.claim_id,
                            },
                        ],
                    }

                field = identifier_fields.get(storage_type)

                if field is None:
                    return None

                return {
                    'record_type': storage_type,
                    field: target.record_id,
                    'claim_id': operation.claim_id,
                }

            source_document = None
            idempotency_document = None
            tombstone = self._get(
                'retention_tombstone',
                target.target_id,
                RetentionRecordTombstone,
                session=mongo_session,
            )

            if target.record_type == 'IdempotencyRecord':
                documents = list(
                    self._collection.find(
                        {
                            'record_type': 'idempotency',
                            'payload.claim_id': operation.claim_id,
                        },
                        session=mongo_session,
                    )
                )

                for document in documents:
                    actor_id = document.get('actor_id')
                    route = document.get('route')
                    key = document.get('key')

                    if (
                        isinstance(actor_id, str)
                        and actor_id
                        and isinstance(route, str)
                        and route
                        and isinstance(key, str)
                        and key
                        and retention_record_identity(
                            'idempotency',
                            actor_id,
                            route,
                            key,
                        )
                        == target.record_id
                    ):
                        idempotency_document = document
                        break
            else:
                query = source_query()

                if query is not None:
                    source_document = self._collection.find_one(
                        query,
                        session=mongo_session,
                    )

            step_status = RetentionStepStatus.SATISFIED
            diagnostic_code = None
            tombstone_candidate = None
            sanitised_idempotency = None

            if target.classification is RetentionClassification.RETAIN:
                if source_document is None:
                    step_status = RetentionStepStatus.UNKNOWN
                    diagnostic_code = 'RETAINED_RECORD_MISSING'

            elif target.record_type == 'IdempotencyRecord':
                if idempotency_document is None:
                    step_status = RetentionStepStatus.UNKNOWN
                    diagnostic_code = 'IDEMPOTENCY_RECORD_MISSING'
                else:
                    record = IdempotencyRecord(**idempotency_document['payload'])

                    sanitised_idempotency = replace(
                        record,
                        message_id=None,
                        agent_message_id=None,
                        decision_id=None,
                        runtime_trace_id=None,
                        runtime_result_id=None,
                        handoff_id=None,
                        follow_up_id=None,
                        action_registry_version=None,
                        action_code=None,
                        target_ref=None,
                        staff_agent_session_id=None,
                        staff_agent_message_id=None,
                        staff_agent_draft_id=None,
                        staff_agent_execution_id=None,
                        message_turn_kind=None,
                        message_turn_revision=None,
                        response_payload=None,
                        revision_before_message=None,
                        confirmation_checkpoint=None,
                        inbound_checkpoint=False,
                        response_status=None,
                        retired=True,
                    )

            elif target.classification is RetentionClassification.DELETE:
                if source_document is None:
                    step_status = RetentionStepStatus.UNKNOWN
                    diagnostic_code = 'DELETE_SOURCE_RECORD_MISSING'

            elif target.classification in {
                RetentionClassification.ANONYMISE,
                RetentionClassification.TOMBSTONE,
            }:
                if tombstone is not None:
                    if (
                        tombstone.operation_id != operation.operation_id
                        or tombstone.target_id != target.target_id
                    ):
                        raise IdempotencyConflict(target.target_id)
                elif source_document is None:
                    step_status = RetentionStepStatus.UNKNOWN
                    diagnostic_code = 'ANONYMISE_SOURCE_RECORD_MISSING'
                else:
                    payload = {
                        key: value
                        for key, value in source_document.items()
                        if key
                        not in {
                            '_id',
                            'record_type',
                            'customer_id',
                            'claim_id',
                            'staff_search',
                        }
                    }

                    tombstone_candidate = RetentionRecordTombstone(
                        tombstone_id=('rts_' + target.target_id[4:]),
                        operation_id=operation.operation_id,
                        target_id=target.target_id,
                        claim_id=operation.claim_id,
                        source_record_type=target.record_type,
                        source_record_id=target.record_id,
                        classification=target.classification,
                        authority=retention_tombstone_authority(
                            target.record_type,
                            payload,
                        ),
                        source_refs=list(target.source_refs),
                        created_at=now,
                    )

            else:
                step_status = RetentionStepStatus.UNKNOWN
                diagnostic_code = 'UNSUPPORTED_RETENTION_CLASSIFICATION'

            attempt = retention_next_attempt(
                operation,
                target.target_id,
            )

            evidence = RetentionStepEvidence(
                evidence_id=retention_step_evidence_id(
                    operation.operation_id,
                    target.target_id,
                    attempt,
                ),
                target_id=target.target_id,
                attempt=attempt,
                status=step_status,
                diagnostic_code=diagnostic_code,
                source_refs=list(target.source_refs),
                recorded_at=now,
            )

            candidate = retention_candidate_after_step(
                operation,
                evidence,
                now=now,
            )

            validate_retention_operation_transition(
                operation,
                candidate,
            )

            if step_status is RetentionStepStatus.SATISFIED:
                if sanitised_idempotency is not None and idempotency_document is not None:
                    self._collection.update_one(
                        {
                            '_id': idempotency_document['_id'],
                            'record_type': 'idempotency',
                        },
                        {'$set': {'payload': (sanitised_idempotency.__dict__)}},
                        session=mongo_session,
                    )

                elif target.classification is RetentionClassification.DELETE:
                    assert source_document is not None

                    self._collection.delete_one(
                        {
                            '_id': source_document['_id'],
                        },
                        session=mongo_session,
                    )

                elif tombstone_candidate is not None:
                    self._put(
                        'retention_tombstone',
                        target.target_id,
                        tombstone_candidate,
                        claim_id=operation.claim_id,
                        session=mongo_session,
                    )

                    assert source_document is not None

                    self._collection.delete_one(
                        {
                            '_id': source_document['_id'],
                        },
                        session=mongo_session,
                    )

            document = candidate.model_dump(mode='json')

            document.update(
                {
                    '_id': self._record_id(
                        'retention_operation',
                        candidate.operation_id,
                    ),
                    'record_type': 'retention_operation',
                    'customer_id': None,
                    'claim_id': candidate.claim_id,
                }
            )

            result = self._collection.replace_one(
                {
                    '_id': document['_id'],
                    'record_type': 'retention_operation',
                    'revision': expected_revision,
                },
                document,
                session=mongo_session,
            )

            if result.modified_count != 1:
                latest = self._get(
                    'retention_operation',
                    operation_id,
                    RetentionOperation,
                    session=mongo_session,
                )

                if latest is None:
                    raise KeyError(operation_id)

                raise RevisionConflict(latest.revision)

            return candidate

        try:
            return self._atomic(apply)
        except PyMongoError as error:
            raise RetentionDatabaseStepError(
                target_id,
                commit_unknown=True,
                diagnostic_code='DATABASE_TRANSACTION_UNKNOWN',
            ) from error

    def save_retention_operation(
        self,
        operation: RetentionOperation,
        expected_revision: int,
    ) -> None:
        def persist(mongo_session: Any) -> None:
            current = self._get(
                'retention_operation',
                operation.operation_id,
                RetentionOperation,
                session=mongo_session,
            )

            if current is None:
                raise KeyError(operation.operation_id)

            if current == operation:
                return

            if current.revision != expected_revision:
                raise RevisionConflict(current.revision)

            validate_retention_operation_transition(
                current,
                operation,
            )

            document = operation.model_dump(mode='json')
            document.update(
                {
                    '_id': self._record_id(
                        'retention_operation',
                        operation.operation_id,
                    ),
                    'record_type': 'retention_operation',
                    'customer_id': None,
                    'claim_id': operation.claim_id,
                }
            )

            result = self._collection.replace_one(
                {
                    '_id': document['_id'],
                    'record_type': 'retention_operation',
                    'claim_id': operation.claim_id,
                    'revision': expected_revision,
                },
                document,
                session=mongo_session,
            )

            if result.matched_count != 1:
                latest = self._get(
                    'retention_operation',
                    operation.operation_id,
                    RetentionOperation,
                    session=mongo_session,
                )

                if latest is None:
                    raise KeyError(operation.operation_id)

                if latest == operation:
                    return

                raise RevisionConflict(latest.revision)

        self._atomic(persist)

    def save_retention_hold(
        self,
        hold: RetentionHoldRecord,
    ) -> None:
        def persist(mongo_session: Any) -> None:
            current = self._get(
                'retention_hold',
                hold.hold_id,
                RetentionHoldRecord,
                session=mongo_session,
            )

            if current is None:
                if hold.released_at is not None:
                    raise ValueError('A retention hold must be persisted before release.')

                # Insert-only: a concurrent creator of the same hold identity
                # either replays exactly or conflicts; it never overwrites.
                try:
                    self._collection.insert_one(
                        {
                            **hold.model_dump(mode='json'),
                            '_id': self._record_id('retention_hold', hold.hold_id),
                            'record_type': 'retention_hold',
                            'customer_id': None,
                            'claim_id': hold.claim_id,
                        },
                        session=mongo_session,
                    )
                except DuplicateKeyError as error:
                    winner = self._get(
                        'retention_hold',
                        hold.hold_id,
                        RetentionHoldRecord,
                        session=mongo_session,
                    )
                    if winner != hold:
                        raise IdempotencyConflict(hold.hold_id) from error
                return

            if current == hold:
                return

            validate_retention_hold_transition(
                current,
                hold,
            )

            document = hold.model_dump(mode='json')
            document.update(
                {
                    '_id': self._record_id(
                        'retention_hold',
                        hold.hold_id,
                    ),
                    'record_type': 'retention_hold',
                    'customer_id': None,
                    'claim_id': hold.claim_id,
                }
            )

            result = self._collection.replace_one(
                {
                    '_id': document['_id'],
                    'record_type': 'retention_hold',
                    'claim_id': hold.claim_id,
                    'released_at': (current.model_dump(mode='json')['released_at']),
                },
                document,
                session=mongo_session,
            )

            if result.matched_count != 1:
                latest = self._get(
                    'retention_hold',
                    hold.hold_id,
                    RetentionHoldRecord,
                    session=mongo_session,
                )

                if latest == hold:
                    return

                raise IdempotencyConflict(hold.hold_id)

        self._atomic(persist)

    def list_retention_holds(
        self,
        claim_id: str,
    ) -> list[RetentionHoldRecord]:
        documents = self._collection.find(
            {
                'record_type': 'retention_hold',
                'claim_id': claim_id,
            }
        ).sort(
            [
                ('applied_at', 1),
                ('_id', 1),
            ]
        )

        return [
            hold
            for hold in (
                self._model_from_document(
                    document,
                    RetentionHoldRecord,
                )
                for document in documents
            )
            if hold is not None
        ]

    def append_realtime_publication(
        self,
        publication: RealtimePublication | AgentTurnProgressPublication,
    ) -> RealtimeEvent:
        event = self._atomic(
            lambda mongo_session: self._persist_realtime_publication(
                publication,
                MutationOutcome.CHANGED,
                mongo_session=mongo_session,
            )
        )
        assert event is not None
        return event

    def _persist_realtime_publication(
        self,
        publication: RealtimePublication | AgentTurnProgressPublication,
        outcome: MutationOutcome,
        *,
        mongo_session: Any,
    ) -> RealtimeEvent | None:
        if outcome is not MutationOutcome.CHANGED:
            return None
        event = realtime_event_from_publication(
            publication,
            occurred_at=datetime.now(UTC),
            sequence=self._next_realtime_sequence(mongo_session),
        )
        document = event.model_dump(mode='json')
        document.update(
            {
                '_id': self._record_id('realtime_event', event.event_id),
                'record_type': 'realtime_event',
                'customer_id': event.customer_id,
                'claim_id': event.claim_id,
                'realtime_order': self._realtime_order(
                    event.occurred_at,
                    event.event_id,
                    event.sequence,
                ),
            }
        )
        self._collection.insert_one(document, session=mongo_session)
        return event

    def _next_realtime_sequence(self, session: Any = None) -> int:
        counter = self._collection.find_one_and_update(
            {'_id': 'realtime_sequence:global', 'record_type': 'realtime_sequence'},
            {
                '$inc': {'sequence': 1},
                '$setOnInsert': {'record_type': 'realtime_sequence'},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        sequence = counter.get('sequence') if counter is not None else None
        if not isinstance(sequence, int) or sequence < 1:
            raise RuntimeError('MongoDB did not return a realtime sequence.')
        return sequence

    def _append_realtime_mutation(
        self,
        mutation: RealtimeMutation,
        claim: WorkingClaim,
        *,
        mongo_session: Any,
        outcome: MutationOutcome = MutationOutcome.CHANGED,
        operation_correlation: str | None = None,
        claimant_visible: bool = True,
        resources: tuple[RealtimeResource, ...] | None = None,
        claimant_resources: tuple[RealtimeResource, ...] | None = None,
    ) -> RealtimeEvent | None:
        publication = realtime_publication_for(
            mutation=mutation,
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            claim_revision=claim.revision,
            operation_correlation=operation_correlation,
            claimant_visible=claimant_visible,
            resources=resources,
            claimant_resources=claimant_resources,
        )
        return self._persist_realtime_publication(
            publication,
            outcome,
            mongo_session=mongo_session,
        )

    def replay_realtime_events(
        self,
        after: RealtimeCursor | None,
        *,
        limit: int,
    ) -> list[RealtimeEvent]:
        if not 1 <= limit <= 1000:
            raise ValueError('Realtime replay limit must be between 1 and 1000.')
        query: dict[str, Any] = {'record_type': 'realtime_event'}
        if after is not None:
            anchor = self._collection.find_one(
                {
                    'record_type': 'realtime_event',
                    'event_id': after.event_id,
                },
            )
            anchor_event = self._model_from_document(anchor, RealtimeEvent)
            if (
                anchor_event is None
                or anchor_event.occurred_at != after.occurred_at
                or (after.sequence is not None and anchor_event.sequence != after.sequence)
            ):
                raise ValueError('The realtime cursor is outside the available replay window.')
            query['realtime_order'] = {
                '$gt': self._realtime_order(
                    anchor_event.occurred_at,
                    anchor_event.event_id,
                    anchor_event.sequence,
                )
            }
        cursor = self._collection.find(query).sort([('realtime_order', 1)]).limit(limit)
        return [
            event
            for document in cursor
            if (event := self._model_from_document(document, RealtimeEvent)) is not None
        ]

    def realtime_high_watermark(self) -> RealtimeEvent | None:
        document = self._collection.find_one(
            {'record_type': 'realtime_event'},
            sort=[('realtime_order', -1)],
        )
        return self._model_from_document(document, RealtimeEvent)

    def watch_realtime_events(self, stop: Event) -> Iterator[RealtimeEvent]:
        pipeline = [
            {
                '$match': {
                    'operationType': 'insert',
                    'fullDocument.record_type': 'realtime_event',
                }
            }
        ]
        with self._collection.watch(
            pipeline,
            full_document='updateLookup',
            max_await_time_ms=1000,
        ) as stream:
            while not stop.is_set():
                change = stream.try_next()
                if change is None:
                    continue
                event = self._model_from_document(change.get('fullDocument', {}), RealtimeEvent)
                if event is not None:
                    yield event

    def create_account_record(
        self,
        record: AccountRecord,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
    ) -> AccountRecord:
        kind, identifier, _ = account_record_identity(record)
        if (
            record.customer_id != idempotency.actor_id
            or identifier != idempotency.claim_id
            or not account_record_audit_matches(
                record, audit_event, idempotency_key=idempotency.key
            )
        ):
            raise KeyError(identifier)

        def persist(mongo_session: Any) -> AccountRecord:
            self._reject_existing_idempotency(idempotency, mongo_session=mongo_session)
            self._ensure_new_audit_event(audit_event, mongo_session=mongo_session)
            stored_record = record
            stored_idempotency = idempotency
            if isinstance(record, PaymentDestinationRecord) and record.active:
                active_documents = list(
                    self._collection.find(
                        {
                            'record_type': 'payment_destination',
                            'customer_id': record.customer_id,
                            'active': True,
                        },
                        session=mongo_session,
                    )
                )
                stored_record = record.model_copy(update={'is_common': not active_documents})
                stored_idempotency = payment_destination_create_result(stored_record, idempotency)
            try:
                self._put(
                    kind,
                    identifier,
                    stored_record,
                    customer_id=stored_record.customer_id,
                    session=mongo_session,
                )
            except IdempotencyConflict as error:
                # A concurrent first-create can win the partial common-marker index.
                if isinstance(stored_record, PaymentDestinationRecord) and stored_record.is_common:
                    raise CommonPaymentDestinationConflict(idempotency.key) from error
                raise
            self._save_idempotency(stored_idempotency, mongo_session)
            self._insert_audit_event(audit_event, mongo_session=mongo_session)
            return stored_record

        return self._atomic(persist)

    def get_policy(self, policy_id: str, customer_id: str) -> PolicyNumberRecord | None:
        return self._get('policy', policy_id, PolicyNumberRecord, customer_id=customer_id)

    def get_payment_destination(
        self, payment_destination_id: str, customer_id: str
    ) -> PaymentDestinationRecord | None:
        return self._get(
            'payment_destination',
            payment_destination_id,
            PaymentDestinationRecord,
            customer_id=customer_id,
        )

    def get_identity_document(
        self, identity_id: str, customer_id: str
    ) -> IdentityDocumentRecord | None:
        return self._get(
            'identity_document', identity_id, IdentityDocumentRecord, customer_id=customer_id
        )

    def _list_account_records(
        self,
        kind: str,
        model: type[ModelT],
        customer_id: str,
        *,
        include_inactive: bool,
        after: AccountCursorKey | None,
        limit: int,
    ) -> tuple[list[ModelT], bool]:
        filters: dict[str, Any] = {'record_type': kind, 'customer_id': customer_id}
        if not include_inactive:
            filters['active'] = True
        if after is not None:
            created_at, identifier = after
            stored_created_at = self._audit_timestamp(created_at)
            filters['$or'] = [
                {'created_at': {'$lt': stored_created_at}},
                {
                    'created_at': stored_created_at,
                    '_id': {'$lt': self._record_id(kind, identifier)},
                },
            ]
        documents = (
            self._collection.find(filters).sort([('created_at', -1), ('_id', -1)]).limit(limit + 1)
        )
        records = [
            record
            for document in documents
            if (record := self._model_from_document(document, model)) is not None
        ]
        return records[:limit], len(records) > limit

    def list_policies(
        self,
        customer_id: str,
        *,
        include_inactive: bool,
        after: AccountCursorKey | None,
        limit: int,
    ) -> tuple[list[PolicyNumberRecord], bool]:
        return self._list_account_records(
            'policy',
            PolicyNumberRecord,
            customer_id,
            include_inactive=include_inactive,
            after=after,
            limit=limit,
        )

    def list_payment_destinations(
        self,
        customer_id: str,
        *,
        include_inactive: bool,
        after: AccountCursorKey | None,
        limit: int,
    ) -> tuple[list[PaymentDestinationRecord], bool]:
        records, more = self._list_account_records(
            'payment_destination',
            PaymentDestinationRecord,
            customer_id,
            include_inactive=include_inactive,
            after=after,
            limit=limit,
        )
        return records, more

    def list_identity_documents(
        self,
        customer_id: str,
        *,
        include_inactive: bool,
        after: AccountCursorKey | None,
        limit: int,
    ) -> tuple[list[IdentityDocumentRecord], bool]:
        return self._list_account_records(
            'identity_document',
            IdentityDocumentRecord,
            customer_id,
            include_inactive=include_inactive,
            after=after,
            limit=limit,
        )

    def update_account_record(
        self,
        record: AccountRecord,
        expected_revision: int,
        audit_event: AuditEventEnvelope,
        related_audit_event_id: str | None = None,
    ) -> None:
        kind, identifier, _ = account_record_identity(record)
        if record.revision != expected_revision + 1 or not account_record_audit_matches(
            record, audit_event, idempotency_key=None
        ):
            raise KeyError(identifier)

        def persist(mongo_session: Any) -> None:
            self._ensure_new_audit_event(audit_event, mongo_session=mongo_session)
            if isinstance(record, PaymentDestinationRecord) and record.is_common:
                current_destination = self._get(
                    'payment_destination',
                    identifier,
                    PaymentDestinationRecord,
                    customer_id=record.customer_id,
                    session=mongo_session,
                )
                if current_destination is None:
                    raise KeyError(identifier)
                if current_destination.revision != expected_revision:
                    raise RevisionConflict(current_destination.revision)
                if not current_destination.active or not record.active:
                    raise PaymentDestinationDesignationConflict(identifier, reason='inactive')
                previous_documents = list(
                    self._collection.find(
                        {
                            'record_type': 'payment_destination',
                            'customer_id': record.customer_id,
                            'active': True,
                            'is_common': True,
                            '_id': {'$ne': self._record_id(kind, identifier)},
                        },
                        session=mongo_session,
                    )
                )
                if len(previous_documents) > 1 or (
                    previous_documents and related_audit_event_id is None
                ):
                    raise KeyError(identifier)
                if previous_documents:
                    assert related_audit_event_id is not None
                    previous = self._model_from_document(
                        previous_documents[0], PaymentDestinationRecord
                    )
                    if previous is None:
                        raise KeyError(identifier)
                    demoted, demotion_event = payment_destination_demotion(
                        previous, audit_event, related_audit_event_id
                    )
                    demoted_document = demoted.model_dump(mode='json')
                    demoted_document.update(
                        {
                            '_id': previous_documents[0]['_id'],
                            'record_type': 'payment_destination',
                            'customer_id': demoted.customer_id,
                            'claim_id': None,
                        }
                    )
                    demotion_result = self._collection.replace_one(
                        {
                            '_id': previous_documents[0]['_id'],
                            'record_type': 'payment_destination',
                            'customer_id': demoted.customer_id,
                            'revision': previous.revision,
                        },
                        demoted_document,
                        session=mongo_session,
                    )
                    if demotion_result.matched_count != 1:
                        raise RevisionConflict(previous.revision)
                    self._insert_audit_event(demotion_event, mongo_session=mongo_session)
            document = record.model_dump(mode='json')
            document.update(
                {
                    '_id': self._record_id(kind, identifier),
                    'record_type': kind,
                    'customer_id': record.customer_id,
                    'claim_id': None,
                }
            )
            result = self._collection.replace_one(
                {
                    '_id': document['_id'],
                    'record_type': kind,
                    'customer_id': record.customer_id,
                    'revision': expected_revision,
                },
                document,
                session=mongo_session,
            )
            if result.matched_count != 1:
                current = self._collection.find_one(
                    {
                        '_id': document['_id'],
                        'record_type': kind,
                        'customer_id': record.customer_id,
                    },
                    projection={'revision': 1},
                    session=mongo_session,
                )
                if current is None:
                    raise KeyError(identifier)
                raise RevisionConflict(int(current['revision']))
            self._insert_audit_event(audit_event, mongo_session=mongo_session)

        self._atomic(persist)

    def save_policy_selection(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        policy_id: str,
        policy_revision: int,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord,
        audit_event: AuditEventEnvelope,
    ) -> None:
        if (
            idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != (claim.active_session_id or '')
            or not policy_selection_audit_matches(
                claim, policy_id, policy_revision, idempotency, audit_event
            )
        ):
            raise KeyError(claim.claim_id)
        self._validate_branch_evaluation(claim, branch_evaluation)

        def persist(mongo_session: Any) -> None:
            policy = self._get(
                'policy',
                policy_id,
                PolicyNumberRecord,
                customer_id=claim.customer_id,
                session=mongo_session,
            )
            if policy is None or not policy.active:
                raise PolicySelectionConflict(policy_id, reason='unavailable')
            if policy.revision != policy_revision:
                raise PolicySelectionConflict(
                    policy_id, reason='changed', current_revision=policy.revision
                )
            prepared_audit = self._prepare_audit_events(
                claim, (audit_event,), mongo_session=mongo_session
            )
            self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                mutation=RealtimeMutation.CLAIM_CHANGED,
                records=[('branch_evaluation', branch_evaluation.evaluation_id, branch_evaluation)],
            )
            for event in prepared_audit:
                self._insert_audit_event(event, mongo_session=mongo_session)

        self._atomic(persist)

    def save_payout_contact_selection(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        payment_destination_id: str,
        payment_destination_revision: int,
        contact_authority_revision: int,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord,
        audit_event: AuditEventEnvelope,
    ) -> None:
        if (
            idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != (claim.active_session_id or '')
            or not payout_contact_selection_audit_matches(
                claim,
                payment_destination_id,
                payment_destination_revision,
                contact_authority_revision,
                idempotency,
                audit_event,
            )
        ):
            raise KeyError(claim.claim_id)
        self._validate_branch_evaluation(claim, branch_evaluation)

        def persist(mongo_session: Any) -> None:
            destination = self._get(
                'payment_destination',
                payment_destination_id,
                PaymentDestinationRecord,
                customer_id=claim.customer_id,
                session=mongo_session,
            )
            if destination is None or not destination.active:
                raise PaymentDestinationSelectionConflict(
                    payment_destination_id, reason='unavailable'
                )
            if destination.revision != payment_destination_revision:
                raise PaymentDestinationSelectionConflict(
                    payment_destination_id,
                    reason='changed',
                    current_revision=destination.revision,
                )
            prepared_audit = self._prepare_audit_events(
                claim, (audit_event,), mongo_session=mongo_session
            )
            self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                mutation=RealtimeMutation.CLAIM_CHANGED,
                records=[('branch_evaluation', branch_evaluation.evaluation_id, branch_evaluation)],
            )
            for event in prepared_audit:
                self._insert_audit_event(event, mongo_session=mongo_session)

        self._atomic(persist)

    def create_asset(
        self,
        asset: AssetRecord,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
    ) -> None:
        if (
            asset.customer_id != idempotency.actor_id
            or asset.asset_id != idempotency.claim_id
            or not asset_audit_matches(asset, audit_event)
            or audit_event.idempotency_key != idempotency.key
        ):
            raise KeyError(asset.asset_id)

        def persist(mongo_session: Any) -> None:
            self._reject_existing_idempotency(idempotency, mongo_session=mongo_session)
            self._ensure_new_audit_event(audit_event, mongo_session=mongo_session)
            self._put(
                'asset',
                asset.asset_id,
                asset,
                customer_id=asset.customer_id,
                session=mongo_session,
            )
            self._save_idempotency(idempotency, mongo_session)
            self._insert_audit_event(audit_event, mongo_session=mongo_session)

        self._atomic(persist)

    def get_asset(self, asset_id: str, customer_id: str) -> AssetRecord | None:
        return self._get('asset', asset_id, AssetRecord, customer_id=customer_id)

    def list_assets(
        self,
        customer_id: str,
        *,
        include_inactive: bool = False,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[AssetRecord], bool]:
        filters: dict[str, Any] = {'customer_id': customer_id}
        if not include_inactive:
            filters['active'] = True
        documents = (
            self._collection.find({'record_type': 'asset', **filters})
            .sort([('updated_at', -1), ('_id', -1)])
            .skip(offset)
            .limit(limit + 1)
        )
        records = [
            record
            for document in documents
            if (record := self._model_from_document(document, AssetRecord)) is not None
        ]
        return records[:limit], len(records) > limit

    def update_asset(
        self,
        asset: AssetRecord,
        expected_revision: int,
        audit_event: AuditEventEnvelope,
    ) -> None:
        if (
            asset.revision != expected_revision + 1
            or not asset_audit_matches(asset, audit_event)
            or audit_event.idempotency_key is not None
        ):
            raise KeyError(asset.asset_id)

        def persist(mongo_session: Any) -> None:
            self._ensure_new_audit_event(audit_event, mongo_session=mongo_session)
            document = asset.model_dump(mode='json')
            document.update(
                {
                    '_id': self._record_id('asset', asset.asset_id),
                    'record_type': 'asset',
                    'customer_id': asset.customer_id,
                    'claim_id': None,
                },
            )
            result = self._collection.replace_one(
                {
                    '_id': document['_id'],
                    'record_type': 'asset',
                    'customer_id': asset.customer_id,
                    'revision': expected_revision,
                },
                document,
                session=mongo_session,
            )
            if result.matched_count != 1:
                current = self._collection.find_one(
                    {
                        '_id': document['_id'],
                        'record_type': 'asset',
                        'customer_id': asset.customer_id,
                    },
                    projection={'revision': 1},
                    session=mongo_session,
                )
                if current is None:
                    raise KeyError(asset.asset_id)
                raise RevisionConflict(int(current['revision']))
            self._insert_audit_event(audit_event, mongo_session=mongo_session)

        self._atomic(persist)

    def save_asset_selection(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        snapshot: ClaimAssetSnapshot,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord,
        audit_event: AuditEventEnvelope,
    ) -> None:
        if (
            snapshot.customer_id != claim.customer_id
            or snapshot.claim_id != claim.claim_id
            or snapshot.resulting_claim_revision != claim.revision
            or idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != (claim.active_session_id or '')
            or not asset_selection_audit_matches(claim, snapshot, idempotency, audit_event)
        ):
            raise KeyError(claim.claim_id)
        self._validate_branch_evaluation(claim, branch_evaluation)

        def persist(mongo_session: Any) -> None:
            asset = self._get(
                'asset',
                snapshot.asset_id,
                AssetRecord,
                customer_id=claim.customer_id,
                session=mongo_session,
            )
            if asset is None or not asset.active:
                raise AssetSelectionUnavailableError(snapshot.asset_id)
            if asset.revision != snapshot.asset_revision:
                raise AssetSelectionRevisionConflictError(asset.revision)
            if not asset_matches_snapshot(asset, snapshot):
                raise AssetSelectionSnapshotConflictError(snapshot.asset_id)
            prepared_audit = self._prepare_audit_events(
                claim,
                (audit_event,),
                mongo_session=mongo_session,
            )
            self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                mutation=RealtimeMutation.CLAIM_CHANGED,
                records=[
                    ('claim_asset_snapshot', snapshot.snapshot_id, snapshot),
                    ('branch_evaluation', branch_evaluation.evaluation_id, branch_evaluation),
                ],
            )
            for event in prepared_audit:
                self._insert_audit_event(event, mongo_session=mongo_session)

        self._atomic(persist)

    def list_claim_asset_snapshots(
        self,
        claim_id: str,
        customer_id: str,
        *,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[ClaimAssetSnapshot], bool]:
        documents = (
            self._collection.find(
                {
                    'record_type': 'claim_asset_snapshot',
                    'claim_id': claim_id,
                    'customer_id': customer_id,
                }
            )
            .sort([('captured_at', 1), ('_id', 1)])
            .skip(offset)
            .limit(limit + 1)
        )
        records = [
            record
            for document in documents
            if (record := self._model_from_document(document, ClaimAssetSnapshot)) is not None
        ]
        return records[:limit], len(records) > limit

    @staticmethod
    def _record_id(kind: str, identifier: str) -> str:
        return f'{kind}:{identifier}'

    @staticmethod
    def _realtime_order(
        occurred_at: datetime,
        event_id: str,
        sequence: int | None = None,
    ) -> str:
        if sequence is not None:
            return f'z|{sequence:020d}|{event_id}'
        timestamp = occurred_at.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        return f'{timestamp}|{event_id}'

    def _staff_search_projection(
        self,
        claim: WorkingClaim,
        *,
        session: Any = None,
    ) -> StaffClaimSearchProjection:
        evidence = [
            record
            for record in (
                self._model_from_document(document, EvidenceRecord)
                for document in self._collection.find(
                    {
                        'record_type': 'evidence',
                        'claim_id': claim.claim_id,
                        'customer_id': claim.customer_id,
                    },
                    session=session,
                )
            )
            if record is not None
        ]
        handoffs = [
            record
            for record in (
                self._model_from_document(document, HandoffRecord)
                for document in self._collection.find(
                    {
                        'record_type': 'handoff',
                        'claim_id': claim.claim_id,
                        'customer_id': claim.customer_id,
                    },
                    session=session,
                )
            )
            if record is not None
        ]
        return build_staff_claim_search_projection(
            build_staff_claim_search_candidate(claim, evidence, handoffs)
        )

    def _refresh_staff_search_projection(
        self,
        claim_id: str,
        customer_id: str,
        *,
        session: Any = None,
    ) -> None:
        document = self._collection.find_one(
            {
                '_id': self._record_id('claim', claim_id),
                'record_type': 'claim',
                'customer_id': customer_id,
            },
            session=session,
        )
        claim = self._model_from_document(document, WorkingClaim)
        if claim is None:
            raise KeyError(claim_id)
        projection = self._staff_search_projection(claim, session=session)
        result = self._collection.update_one(
            {
                '_id': self._record_id('claim', claim_id),
                'record_type': 'claim',
                'customer_id': customer_id,
                'revision': claim.revision,
            },
            {'$set': {'staff_search': projection.model_dump(mode='json')}},
            session=session,
        )
        if result.matched_count != 1:
            raise RevisionConflict(claim.revision)

    def _backfill_staff_search_projections(self) -> None:
        """Populate the adapter-owned projection for pre-contract Claim documents."""

        documents = self._collection.find(
            {'record_type': 'claim', 'staff_search': {'$exists': False}},
            projection={'claim_id': 1, 'customer_id': 1},
        )
        for document in documents:
            claim_id = document.get('claim_id')
            customer_id = document.get('customer_id')
            if isinstance(claim_id, str) and isinstance(customer_id, str):
                self._refresh_staff_search_projection(claim_id, customer_id)

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
        if kind == 'realtime_event':
            raise TypeError('Realtime events must use the immutable append path.')
        document = model.model_dump(mode='json')
        if kind == 'claim':
            if not isinstance(model, WorkingClaim):
                raise TypeError('Claim records require WorkingClaim.')
            document['staff_search'] = self._staff_search_projection(
                model, session=session
            ).model_dump(mode='json')
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
        if kind in {'evidence', 'handoff'}:
            if claim_id is None or customer_id is None:
                raise KeyError(identifier)
            self._refresh_staff_search_projection(
                claim_id,
                customer_id,
                session=session,
            )

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
        if model_type in {AssetRecord, ClaimAssetSnapshot}:
            details = payload.get('details')
            if payload.get('asset_type') == AssetType.CONTENTS.value and isinstance(details, dict):
                payload['details'] = {
                    key: value for key, value in details.items() if key != 'serial_number'
                }
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

    def _ensure_new_audit_event(
        self,
        event: AuditEventEnvelope,
        *,
        mongo_session: Any,
    ) -> None:
        existing = self._collection.find_one(
            {
                '_id': self._record_id('audit_event', event.event_id),
                'record_type': 'audit_event',
            },
            projection={'_id': 1},
            session=mongo_session,
        )
        if existing is not None:
            raise IdempotencyConflict(event.event_id)

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

    def seed_validation_graph(self, graph: ValidationSeedGraph) -> IdempotencyRecord | None:
        """Persist validation records in one MongoDB transaction."""
        return self._atomic(lambda mongo_session: self._seed_validation_graph(graph, mongo_session))

    def _seed_validation_graph(
        self, graph: ValidationSeedGraph, mongo_session: Any
    ) -> IdempotencyRecord | None:
        idempotency_query = {
            'record_type': 'idempotency',
            'actor_id': graph.idempotency.actor_id,
            'route': graph.idempotency.route,
            'key': graph.idempotency.key,
        }
        existing_idempotency = self._collection.find_one(idempotency_query, session=mongo_session)
        if existing_idempotency is not None:
            payload = existing_idempotency.get('payload', {})
            if payload.get('request_fingerprint') != graph.idempotency.request_fingerprint:
                raise IdempotencyConflict(graph.idempotency.key)
            return IdempotencyRecord(**payload)
        if self._collection.find_one(
            {'record_type': 'claim'},
            projection={'_id': 1},
            session=mongo_session,
        ):
            raise DemoSeedConflict('The validation seed requires an empty claim queue.')

        claims_by_id = {claim.claim_id: claim for claim in graph.claims}
        sessions_by_id = {session.session_id: session for session in graph.sessions}
        messages_by_id = {message.message_id: message for message in graph.messages}
        evidence_by_id = {item.evidence_id: item for item in graph.evidence}
        if (
            not claims_by_id
            or len(claims_by_id) != len(graph.claims)
            or len(sessions_by_id) != len(graph.sessions)
            or len(messages_by_id) != len(graph.messages)
            or len(evidence_by_id) != len(graph.evidence)
        ):
            raise ValueError('Validation seed record identifiers must be unique and non-empty.')
        validate_message_graph(graph.messages)
        for evidence in graph.evidence:
            validate_evidence_record(evidence)
        for message in graph.messages:
            seed_session = sessions_by_id.get(message.session_id)
            if seed_session is None:
                raise ValueError('Every validation seed Message needs a known Session.')
            validate_message_record(
                message,
                session=seed_session,
                evidence=[
                    evidence_by_id[evidence_id]
                    for evidence_id in message.evidence_refs
                    if evidence_id in evidence_by_id
                ],
                reply=messages_by_id.get(message.in_reply_to or ''),
                duplicate_client_message=next(
                    (
                        item
                        for item in graph.messages
                        if message.client_message_id is not None
                        and item.message_id != message.message_id
                        and item.claim_id == message.claim_id
                        and item.client_message_id == message.client_message_id
                    ),
                    None,
                ),
            )

        presence_id = self._record_id('staff_presence', graph.staff_presence.staff_id)
        current_presence = self._collection.find_one(
            {'_id': presence_id, 'record_type': 'staff_presence'},
            session=mongo_session,
        )
        current_presence_revision = int(current_presence['revision']) if current_presence else 0
        if (
            graph.expected_presence_revision is not None
            and current_presence_revision != graph.expected_presence_revision
        ):
            raise RevisionConflict(current_presence_revision)
        presence_document = {
            **graph.staff_presence.model_dump(mode='json'),
            '_id': presence_id,
            'record_type': 'staff_presence',
        }
        if current_presence is None:
            if graph.staff_presence.revision != 1:
                raise RevisionConflict(0)
            try:
                self._collection.insert_one(presence_document, session=mongo_session)
            except DuplicateKeyError as error:
                raise RevisionConflict(1) from error
        else:
            if graph.staff_presence.revision != current_presence_revision + 1:
                raise RevisionConflict(current_presence_revision)
            result = self._collection.replace_one(
                {
                    '_id': presence_id,
                    'record_type': 'staff_presence',
                    'revision': current_presence_revision,
                },
                presence_document,
                session=mongo_session,
            )
            if result.matched_count != 1:
                raise RevisionConflict(current_presence_revision)

        sessions_by_claim: dict[str, list[SessionRecord]] = {
            claim_id: [] for claim_id in claims_by_id
        }
        for session in graph.sessions:
            sessions_by_claim.setdefault(session.claim_id, []).append(session)
        for claim in graph.claims:
            active = [
                session
                for session in sessions_by_claim.get(claim.claim_id, [])
                if session.session_id == claim.active_session_id
            ]
            if len(active) != 1:
                raise ValueError('Every validation seed claim needs one active session.')
            validate_validation_seed_session(claim, active[0])
            self._create_claim(claim, active[0], mongo_session)
        for session in graph.sessions:
            if session.session_id != claims_by_id[session.claim_id].active_session_id:
                self._reject_session_identity_conflict(session, mongo_session=mongo_session)
                self._put(
                    'session',
                    session.session_id,
                    session,
                    customer_id=session.customer_id,
                    claim_id=session.claim_id,
                    session=mongo_session,
                )
        for evidence in graph.evidence:
            self._put(
                'evidence',
                evidence.evidence_id,
                evidence,
                customer_id=claims_by_id[evidence.claim_id].customer_id,
                claim_id=evidence.claim_id,
                session=mongo_session,
            )
        for message in graph.messages:
            self._put(
                'message',
                message.message_id,
                message,
                customer_id=claims_by_id[message.claim_id].customer_id,
                claim_id=message.claim_id,
                session=mongo_session,
            )
        self._save_idempotency(graph.idempotency, session=mongo_session)
        return None

    def _create_claim(
        self,
        claim: WorkingClaim,
        session: SessionRecord,
        mongo_session: Any,
    ) -> None:
        existing_claim = self._get('claim', claim.claim_id, WorkingClaim, session=mongo_session)
        existing_session = self._get(
            'session', session.session_id, SessionRecord, session=mongo_session
        )
        if existing_claim is not None or existing_session is not None:
            if existing_claim == claim and existing_session == session:
                self._append_realtime_mutation(
                    RealtimeMutation.CLAIM_CREATED,
                    claim,
                    mongo_session=mongo_session,
                    outcome=MutationOutcome.EXACT_NOOP,
                )
                return
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
        self._append_realtime_mutation(
            RealtimeMutation.CLAIM_CREATED,
            claim,
            mongo_session=mongo_session,
        )

    def _claim_access_closed(
        self,
        claim_id: str,
        *,
        mongo_session: Any = None,
    ) -> bool:
        document = self._collection.find_one(
            {
                'record_type': 'retention_operation',
                'claim_id': claim_id,
            },
            projection={'_id': 1},
            session=mongo_session,
        )

        return document is not None

    def claimant_resource_access_open(
        self,
        claim_id: str,
        customer_id: str,
    ) -> bool:
        claim = self._get(
            'claim',
            claim_id,
            WorkingClaim,
            customer_id=customer_id,
        )

        return claim is not None and not self._claim_access_closed(claim_id)

    def _ensure_claim_access_open(
        self,
        claim_id: str,
        *,
        mongo_session: Any,
    ) -> None:
        if self._claim_access_closed(
            claim_id,
            mongo_session=mongo_session,
        ):
            raise ResourceAccessClosed(claim_id)

    def _claimant_actor_access_closed(
        self,
        claim_id: str,
        actor_id: str,
        *,
        mongo_session: Any = None,
    ) -> bool:
        claim = self._get(
            'claim',
            claim_id,
            WorkingClaim,
            session=mongo_session,
        )

        return (
            claim is not None
            and claim.customer_id == actor_id
            and self._claim_access_closed(
                claim_id,
                mongo_session=mongo_session,
            )
        )

    def get_claim(
        self,
        claim_id: str,
        customer_id: str,
    ) -> WorkingClaim | None:
        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return None

        return self._get(
            'claim',
            claim_id,
            WorkingClaim,
            customer_id=customer_id,
        )

    def get_claim_internal(self, claim_id: str) -> WorkingClaim | None:
        return self._get('claim', claim_id, WorkingClaim)

    def list_claims_for_customer(
        self,
        customer_id: str,
    ) -> list[WorkingClaim]:
        claims = self._list(
            'claim',
            WorkingClaim,
            {'customer_id': customer_id},
            '-updated_at',
        )

        return [claim for claim in claims if not self._claim_access_closed(claim.claim_id)]

    def list_claims_internal(self) -> list[WorkingClaim]:
        return self._list('claim', WorkingClaim, {}, '-updated_at')

    def search_claims_internal(
        self, filters: dict[str, object], limit: int
    ) -> list[StaffClaimSearchCandidate]:
        """Query registered Claim keys at MongoDB and return only bounded candidates."""
        query: dict[str, Any] = {'record_type': 'claim'}
        claim_reference = filters.get('claim_reference')
        if claim_reference:
            query['$or'] = [
                {'claim_id': claim_reference},
                {'staff_search.external_reference': claim_reference},
            ]
        if filters.get('customer_reference'):
            query['customer_id'] = filters['customer_reference']
        if filters.get('external_reference'):
            query['staff_search.external_reference'] = filters['external_reference']
        if filters.get('created_date'):
            query['staff_search.created_date'] = str(filters['created_date'])
        for search_field in (
            'incident_date',
            'product_family',
            'lifecycle_state',
            'assignee_id',
            'queue',
        ):
            value = filters.get(search_field)
            if value:
                query[f'staff_search.{search_field}'] = str(value)
        cursor = self._collection.find(query).sort([('updated_at', -1), ('_id', -1)]).limit(limit)
        records: list[StaffClaimSearchCandidate] = []
        for document in cursor:
            claim = self._model_from_document(document, WorkingClaim)
            projection_payload = document.get('staff_search')
            if claim is None or not isinstance(projection_payload, dict):
                continue
            projection = StaffClaimSearchProjection.model_validate(projection_payload)
            records.append(
                StaffClaimSearchCandidate(
                    claim=claim,
                    lifecycle_state=projection.lifecycle_state,
                    assignee_id=projection.assignee_id,
                    queue=projection.queue,
                )
            )
        return records

    def promote_claim_owner(
        self,
        claim_id: str,
        anonymous_customer_id: str,
        customer_id: str,
    ) -> WorkingClaim | None:
        """Move an anonymous claim projection to an authenticated customer."""
        return self._atomic(
            lambda mongo_session: self._promote_claim_owner(
                claim_id,
                anonymous_customer_id,
                customer_id,
                mongo_session,
            )
        )

    def _promote_claim_owner(
        self,
        claim_id: str,
        anonymous_customer_id: str,
        customer_id: str,
        mongo_session: Any,
    ) -> WorkingClaim | None:
        self._ensure_claim_access_open(
            claim_id,
            mongo_session=mongo_session,
        )
        claim = self._get(
            'claim',
            claim_id,
            WorkingClaim,
            customer_id=anonymous_customer_id,
            session=mongo_session,
        )
        if claim is None:
            return None
        idempotency_documents = list(
            self._collection.find(
                {
                    'record_type': 'idempotency',
                    'actor_id': anonymous_customer_id,
                    'payload.claim_id': claim_id,
                    'payload.retired': {'$ne': True},
                },
                session=mongo_session,
            )
        )
        promoted_idempotency: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
        for document in idempotency_documents:
            record = IdempotencyRecord(**document['payload'])
            promoted_record = replace(record, actor_id=customer_id, retired=False)
            target_id = self._record_id(
                'idempotency',
                f'{customer_id}:{record.route}:{record.key}',
            )
            existing = self._collection.find_one({'_id': target_id}, session=mongo_session)
            target = {
                **document,
                '_id': target_id,
                'actor_id': customer_id,
                'payload': promoted_record.__dict__,
            }
            if existing is not None and existing != target:
                raise IdempotencyConflict(record.key)
            promoted_idempotency.append((document, target, existing is None))
        self._collection.update_many(
            {'claim_id': claim_id, 'customer_id': anonymous_customer_id},
            {'$set': {'customer_id': customer_id}},
            session=mongo_session,
        )
        self._collection.update_one(
            {'_id': self._record_id('claim', claim_id), 'record_type': 'claim'},
            {
                '$set': {
                    'customer_id': customer_id,
                    'staff_search.customer_reference': customer_id,
                }
            },
            session=mongo_session,
        )
        for original, target, should_insert in promoted_idempotency:
            if original['_id'] != target['_id']:
                if should_insert:
                    self._collection.insert_one(target, session=mongo_session)
                retired = replace(
                    IdempotencyRecord(**original['payload']),
                    retired=True,
                )
                self._collection.update_one(
                    {'_id': original['_id'], 'record_type': 'idempotency'},
                    {'$set': {'payload': retired.__dict__}},
                    session=mongo_session,
                )
        promoted = self._get(
            'claim',
            claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        if promoted is None:
            raise KeyError(claim_id)
        self._append_realtime_mutation(
            RealtimeMutation.CLAIM_OWNER_CHANGED,
            promoted,
            mongo_session=mongo_session,
        )
        return promoted

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
        self._atomic(
            lambda mongo_session: self._save_claim_only(
                claim,
                expected_revision,
                mongo_session,
            )
        )

    def _save_claim_only(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        mongo_session: Any,
    ) -> None:
        self._ensure_claim_revision(claim, expected_revision, mongo_session=mongo_session)
        if claim.revision != expected_revision + 1:
            raise KeyError(claim.claim_id)
        if self._replace_claim_revision(claim, expected_revision, mongo_session=mongo_session) == 0:
            self._raise_revision_conflict(claim.claim_id, mongo_session=mongo_session)
        self._append_realtime_mutation(
            RealtimeMutation.CLAIM_CHANGED,
            claim,
            mongo_session=mongo_session,
        )

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
        self._append_realtime_mutation(
            RealtimeMutation.CLAIM_CHANGED,
            claim,
            mongo_session=mongo_session,
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
                mutation=RealtimeMutation.CLAIM_CHANGED,
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
            mutation=RealtimeMutation.CLAIM_CHANGED,
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
        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return None

        record = self._get(
            'session',
            session_id,
            SessionRecord,
            customer_id=customer_id,
        )

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

    def get_follow_up(
        self,
        claim_id: str,
        follow_up_id: str,
        customer_id: str,
    ) -> FollowUpRecord | None:
        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return None

        record = self._get(
            'follow_up',
            follow_up_id,
            FollowUpRecord,
            customer_id=customer_id,
        )

        if record is None or record.claim_id != claim_id:
            return None

        return record

    def list_follow_ups(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[FollowUpRecord]:
        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return []

        return self._list(
            'follow_up',
            FollowUpRecord,
            {
                'claim_id': claim_id,
                'customer_id': customer_id,
            },
            'created_at',
        )

    def _follow_up_backfill_candidate_ids(self) -> list[str]:
        candidates = self._collection.find(
            {
                'record_type': 'follow_up',
                'status': {
                    '$in': [
                        FollowUpStatus.PENDING.value,
                        FollowUpStatus.BLOCKED.value,
                    ]
                },
                # ``None`` matches both an absent field and an explicit null;
                # the two encodings are equally unbound for migration.
                '$or': [
                    {'policy_id': None},
                    {'policy_version': None},
                    {'deadline_at': None},
                    {
                        'status': FollowUpStatus.BLOCKED.value,
                        'blocked_reason': None,
                    },
                ],
            },
            projection={'_id': 1},
        ).sort('_id', 1)
        return [item['_id'] for item in candidates if isinstance(item.get('_id'), str)]

    def plan_incomplete_claim_recovery_backfill(
        self,
        *,
        recorded_at: datetime,
    ) -> dict[str, str]:
        """Report the backfill decision per candidate without writing.

        Args:
            recorded_at: Timezone-aware audit time the apply run would use.

        Returns:
            Follow-up identifier mapped to ``noop``, ``bound``, ``failed`` or
            ``unreadable`` (stored shape cannot be validated; never written).

        Raises:
            ValueError: ``recorded_at`` is naive.
        """
        if recorded_at.tzinfo is None:
            raise ValueError('Backfill audit time must be timezone-aware.')
        plan: dict[str, str] = {}
        for record_id in self._follow_up_backfill_candidate_ids():
            try:
                plan[record_id] = self._backfill_incomplete_claim_recovery_record(
                    record_id, recorded_at, None, dry_run=True
                )
            except ValidationError:
                plan[record_id] = 'unreadable'
        return plan

    def backfill_incomplete_claim_recovery(
        self,
        *,
        recorded_at: datetime | None = None,
    ) -> tuple[int, int]:
        migration_time = recorded_at or datetime.now(UTC)

        if migration_time.tzinfo is None:
            raise ValueError('Backfill audit time must be timezone-aware.')

        bound_count = 0
        failed_count = 0

        for record_id in self._follow_up_backfill_candidate_ids():

            def persist_record(
                mongo_session: Any,
                *,
                target_record_id: str = record_id,
            ) -> str:
                return self._backfill_incomplete_claim_recovery_record(
                    target_record_id,
                    migration_time,
                    mongo_session,
                )

            try:
                outcome = self._atomic(persist_record)
            except ValidationError:
                # An unreadable stored shape has no typed fail-closed encoding;
                # it is left untouched and reported by the planning pass.
                continue

            if outcome == 'bound':
                bound_count += 1
            elif outcome == 'failed':
                failed_count += 1

        return bound_count, failed_count

    def _backfill_incomplete_claim_recovery_record(
        self,
        record_id: str,
        recorded_at: datetime,
        mongo_session: Any,
        *,
        dry_run: bool = False,
    ) -> str:
        document = self._collection.find_one(
            {
                '_id': record_id,
                'record_type': 'follow_up',
            },
            session=mongo_session,
        )

        follow_up = self._model_from_document(
            document,
            FollowUpRecord,
        )

        if follow_up is None or document is None:
            return 'noop'

        customer_id = document.get('customer_id')
        source_document: dict[str, Any] | None = None

        if isinstance(customer_id, str):
            source_document = self._collection.find_one(
                {
                    '_id': self._record_id('session', follow_up.source_session_id),
                    'record_type': 'session',
                    'customer_id': customer_id,
                },
                session=mongo_session,
            )

        source_session = self._model_from_document(source_document, SessionRecord)

        decision = backfill_legacy_follow_up_record(
            follow_up,
            source_session,
            recorded_at=recorded_at,
        )

        if decision.outcome == 'noop' or dry_run:
            return decision.outcome

        assert decision.audit_event is not None

        migrated = {
            **decision.record.model_dump(mode='json'),
            '_id': record_id,
            'record_type': 'follow_up',
            'customer_id': document.get('customer_id'),
            'claim_id': follow_up.claim_id,
        }

        # The interruption source is read, not written, so a transaction alone
        # would not conflict with a concurrent Session change.  The fence write
        # matches the exact Session snapshot that produced the decision; the
        # fence field is adapter metadata that no domain model reads.
        if source_document is not None:
            source_predicate: dict[str, Any] = dict(source_document)
            for field in SessionRecord.model_fields:
                if field not in source_document:
                    source_predicate[field] = {'$exists': False}
            fence = self._collection.update_one(
                source_predicate,
                {'$inc': {'recovery_backfill_fence': 1}},
                session=mongo_session,
            )
            if fence.matched_count != 1:
                raise IdempotencyConflict(follow_up.follow_up_id)

        # Exact-document CAS: any concurrent Follow-up write since discovery,
        # including a competing policy binding, makes this migration a no-op.
        predicate: dict[str, Any] = dict(document)
        for field in FollowUpRecord.model_fields:
            if field not in document:
                predicate[field] = {'$exists': False}
        result = self._collection.replace_one(
            predicate,
            migrated,
            session=mongo_session,
        )

        if result.matched_count != 1:
            raise IdempotencyConflict(follow_up.follow_up_id)

        self._insert_audit_event(
            decision.audit_event,
            mongo_session=mongo_session,
        )

        return decision.outcome

    def commit_recovery_staff_abandonment(
        self,
        expected_claim_revision: int,
        expected_follow_up: FollowUpRecord,
        updated_claim: WorkingClaim,
        updated_follow_up: FollowUpRecord,
        reconciled_operation: FollowUpOperation | None,
        customer_id: str,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
    ) -> None:
        self._atomic(
            lambda mongo_session: self._commit_recovery_staff_abandonment(
                expected_claim_revision,
                expected_follow_up,
                updated_claim,
                updated_follow_up,
                reconciled_operation,
                customer_id,
                idempotency,
                audit_event,
                mongo_session,
            )
        )

    def _commit_recovery_staff_abandonment(
        self,
        expected_claim_revision: int,
        expected_follow_up: FollowUpRecord,
        updated_claim: WorkingClaim,
        updated_follow_up: FollowUpRecord,
        reconciled_operation: FollowUpOperation | None,
        customer_id: str,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
        mongo_session: Any,
    ) -> None:
        claim = self._get(
            'claim',
            expected_follow_up.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        current_follow_up = self._get(
            'follow_up',
            expected_follow_up.follow_up_id,
            FollowUpRecord,
            customer_id=customer_id,
            session=mongo_session,
        )
        source_session = self._get(
            'session',
            expected_follow_up.source_session_id,
            SessionRecord,
            customer_id=customer_id,
            session=mongo_session,
        )

        if claim is None or current_follow_up is None or source_session is None:
            raise KeyError(expected_follow_up.follow_up_id)

        if claim.revision != expected_claim_revision:
            raise RevisionConflict(claim.revision)

        if current_follow_up != expected_follow_up:
            raise IdempotencyConflict(current_follow_up.follow_up_id)

        self._reject_existing_idempotency(
            idempotency,
            mongo_session=mongo_session,
        )

        documents = self._collection.find(
            {
                'record_type': 'follow_up_operation',
                'claim_id': claim.claim_id,
                'follow_up_id': current_follow_up.follow_up_id,
                'customer_id': customer_id,
            },
            session=mongo_session,
        )

        operations = sorted(
            (
                operation
                for document in documents
                if (
                    operation := self._model_from_document(
                        document,
                        FollowUpOperation,
                    )
                )
                is not None
            ),
            key=lambda operation: (
                operation.sequence,
                operation.operation_id,
            ),
        )

        terminal = updated_claim.terminal_disposition
        if terminal is None:
            raise KeyError(claim.claim_id)

        try:
            transition = reduce_follow_up_staff_abandonment(
                claim,
                source_session,
                current_follow_up,
                operations,
                terminal.recorded_at,
                terminal.recorded_by,
            )
        except FollowUpStaffAbandonmentRejected as error:
            raise IdempotencyConflict(current_follow_up.follow_up_id) from error

        if (
            transition.claim != updated_claim
            or transition.follow_up != updated_follow_up
            or transition.reconciled_operation != reconciled_operation
        ):
            raise IdempotencyConflict(current_follow_up.follow_up_id)

        prepared_audit = self._prepare_audit_events(
            updated_claim,
            (audit_event,),
            mongo_session=mongo_session,
        )

        if reconciled_operation is not None:
            stored_operation = next(
                (
                    operation
                    for operation in operations
                    if operation.operation_id == reconciled_operation.operation_id
                ),
                None,
            )

            if stored_operation is None:
                raise IdempotencyConflict(reconciled_operation.operation_id)

            try:
                assert_follow_up_operation_transition(
                    stored_operation,
                    reconciled_operation,
                )
            except ValueError as error:
                raise IdempotencyConflict(reconciled_operation.operation_id) from error

            operation_result = self._collection.replace_one(
                {
                    '_id': self._record_id(
                        'follow_up_operation',
                        stored_operation.operation_id,
                    ),
                    'record_type': 'follow_up_operation',
                    'customer_id': customer_id,
                    'claim_id': claim.claim_id,
                    'status': stored_operation.status.value,
                },
                {
                    **reconciled_operation.model_dump(mode='json'),
                    '_id': self._record_id(
                        'follow_up_operation',
                        reconciled_operation.operation_id,
                    ),
                    'record_type': 'follow_up_operation',
                    'customer_id': customer_id,
                    'claim_id': claim.claim_id,
                },
                session=mongo_session,
            )

            if operation_result.matched_count != 1:
                raise IdempotencyConflict(reconciled_operation.operation_id)

        claim_result = self._collection.replace_one(
            {
                '_id': self._record_id('claim', claim.claim_id),
                'record_type': 'claim',
                'customer_id': customer_id,
                'revision': expected_claim_revision,
            },
            {
                **updated_claim.model_dump(mode='json'),
                '_id': self._record_id('claim', updated_claim.claim_id),
                'record_type': 'claim',
                'customer_id': customer_id,
                'claim_id': updated_claim.claim_id,
            },
            session=mongo_session,
        )

        if claim_result.matched_count != 1:
            raise RevisionConflict(expected_claim_revision)

        follow_up_result = self._collection.replace_one(
            {
                '_id': self._record_id(
                    'follow_up',
                    current_follow_up.follow_up_id,
                ),
                'record_type': 'follow_up',
                'customer_id': customer_id,
                'claim_id': claim.claim_id,
                'status': current_follow_up.status.value,
                'attempt_count': current_follow_up.attempt_count,
            },
            {
                **updated_follow_up.model_dump(mode='json'),
                '_id': self._record_id(
                    'follow_up',
                    updated_follow_up.follow_up_id,
                ),
                'record_type': 'follow_up',
                'customer_id': customer_id,
                'claim_id': claim.claim_id,
            },
            session=mongo_session,
        )

        if follow_up_result.matched_count != 1:
            raise IdempotencyConflict(current_follow_up.follow_up_id)

        self._save_idempotency(
            idempotency,
            mongo_session,
        )

        for event in prepared_audit:
            self._insert_audit_event(
                event,
                mongo_session=mongo_session,
            )

        self._append_realtime_mutation(
            RealtimeMutation.CLAIM_CHANGED,
            updated_claim,
            mongo_session=mongo_session,
            operation_correlation=idempotency.key,
        )

    def commit_follow_up_contact_withdrawal(
        self,
        expected_claim_revision: int,
        expected_follow_up: FollowUpRecord,
        updated_follow_up: FollowUpRecord,
        reconciled_operation: FollowUpOperation | None,
        customer_id: str,
        audit_event: AuditEventEnvelope,
    ) -> None:
        self._atomic(
            lambda mongo_session: self._commit_follow_up_contact_withdrawal(
                expected_claim_revision,
                expected_follow_up,
                updated_follow_up,
                reconciled_operation,
                customer_id,
                audit_event,
                mongo_session,
            )
        )

    def _commit_follow_up_contact_withdrawal(
        self,
        expected_claim_revision: int,
        expected_follow_up: FollowUpRecord,
        updated_follow_up: FollowUpRecord,
        reconciled_operation: FollowUpOperation | None,
        customer_id: str,
        audit_event: AuditEventEnvelope,
        mongo_session: Any,
    ) -> None:
        claim = self._get(
            'claim',
            expected_follow_up.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        current_follow_up = self._get(
            'follow_up',
            expected_follow_up.follow_up_id,
            FollowUpRecord,
            customer_id=customer_id,
            session=mongo_session,
        )
        source_session = self._get(
            'session',
            expected_follow_up.source_session_id,
            SessionRecord,
            customer_id=customer_id,
            session=mongo_session,
        )

        if claim is None or current_follow_up is None or source_session is None:
            raise KeyError(expected_follow_up.follow_up_id)

        if claim.revision != expected_claim_revision:
            raise RevisionConflict(claim.revision)

        if current_follow_up != expected_follow_up:
            raise IdempotencyConflict(expected_follow_up.follow_up_id)

        documents = self._collection.find(
            {
                'record_type': 'follow_up_operation',
                'claim_id': claim.claim_id,
                'follow_up_id': current_follow_up.follow_up_id,
                'customer_id': customer_id,
            },
            session=mongo_session,
        )

        operations = sorted(
            (
                operation
                for document in documents
                if (
                    operation := self._model_from_document(
                        document,
                        FollowUpOperation,
                    )
                )
                is not None
            ),
            key=lambda operation: (
                operation.sequence,
                operation.operation_id,
            ),
        )

        try:
            transition = reduce_follow_up_contact_withdrawal(
                claim,
                source_session,
                current_follow_up,
                operations,
                updated_follow_up.updated_at,
            )
        except FollowUpContactWithdrawalRejected as error:
            raise IdempotencyConflict(current_follow_up.follow_up_id) from error

        if (
            transition.follow_up != updated_follow_up
            or transition.reconciled_operation != reconciled_operation
        ):
            raise IdempotencyConflict(current_follow_up.follow_up_id)

        self._ensure_new_audit_event(
            audit_event,
            mongo_session=mongo_session,
        )

        if reconciled_operation is not None:
            stored_operation = next(
                (
                    operation
                    for operation in operations
                    if operation.operation_id == reconciled_operation.operation_id
                ),
                None,
            )
            if stored_operation is None:
                raise IdempotencyConflict(reconciled_operation.operation_id)

            try:
                assert_follow_up_operation_transition(
                    stored_operation,
                    reconciled_operation,
                )
            except ValueError as error:
                raise IdempotencyConflict(reconciled_operation.operation_id) from error

            result = self._collection.replace_one(
                {
                    '_id': self._record_id(
                        'follow_up_operation',
                        stored_operation.operation_id,
                    ),
                    'record_type': 'follow_up_operation',
                    'customer_id': customer_id,
                    'claim_id': claim.claim_id,
                    'status': stored_operation.status.value,
                },
                {
                    **reconciled_operation.model_dump(mode='json'),
                    '_id': self._record_id(
                        'follow_up_operation',
                        reconciled_operation.operation_id,
                    ),
                    'record_type': 'follow_up_operation',
                    'customer_id': customer_id,
                    'claim_id': claim.claim_id,
                },
                session=mongo_session,
            )
            if result.matched_count != 1:
                raise IdempotencyConflict(reconciled_operation.operation_id)

        result = self._collection.replace_one(
            {
                '_id': self._record_id(
                    'follow_up',
                    current_follow_up.follow_up_id,
                ),
                'record_type': 'follow_up',
                'customer_id': customer_id,
                'claim_id': claim.claim_id,
                'status': current_follow_up.status.value,
                'attempt_count': current_follow_up.attempt_count,
            },
            {
                **updated_follow_up.model_dump(mode='json'),
                '_id': self._record_id(
                    'follow_up',
                    updated_follow_up.follow_up_id,
                ),
                'record_type': 'follow_up',
                'customer_id': customer_id,
                'claim_id': claim.claim_id,
            },
            session=mongo_session,
        )

        if result.matched_count != 1:
            raise IdempotencyConflict(current_follow_up.follow_up_id)

        self._insert_audit_event(
            audit_event,
            mongo_session=mongo_session,
        )

        self._append_realtime_mutation(
            RealtimeMutation.CLAIM_CHANGED,
            claim,
            mongo_session=mongo_session,
            operation_correlation=(f'follow-up-contact:{updated_follow_up.follow_up_id}'),
        )

    def commit_recovery_expiry(
        self,
        expected_claim_revision: int,
        expected_follow_up: FollowUpRecord,
        updated_claim: WorkingClaim,
        updated_follow_up: FollowUpRecord,
        reconciled_operation: FollowUpOperation | None,
        customer_id: str,
        audit_event: AuditEventEnvelope,
    ) -> None:
        self._atomic(
            lambda mongo_session: self._commit_recovery_expiry(
                expected_claim_revision,
                expected_follow_up,
                updated_claim,
                updated_follow_up,
                reconciled_operation,
                customer_id,
                audit_event,
                mongo_session,
            )
        )

    def _commit_recovery_expiry(
        self,
        expected_claim_revision: int,
        expected_follow_up: FollowUpRecord,
        updated_claim: WorkingClaim,
        updated_follow_up: FollowUpRecord,
        reconciled_operation: FollowUpOperation | None,
        customer_id: str,
        audit_event: AuditEventEnvelope,
        mongo_session: Any,
    ) -> None:
        claim = self._get(
            'claim',
            expected_follow_up.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        current_follow_up = self._get(
            'follow_up',
            expected_follow_up.follow_up_id,
            FollowUpRecord,
            customer_id=customer_id,
            session=mongo_session,
        )
        source_session = self._get(
            'session',
            expected_follow_up.source_session_id,
            SessionRecord,
            customer_id=customer_id,
            session=mongo_session,
        )

        if claim is None or current_follow_up is None or source_session is None:
            raise KeyError(expected_follow_up.follow_up_id)

        if claim.revision != expected_claim_revision:
            raise RevisionConflict(claim.revision)

        if current_follow_up != expected_follow_up:
            raise IdempotencyConflict(expected_follow_up.follow_up_id)

        documents = self._collection.find(
            {
                'record_type': 'follow_up_operation',
                'claim_id': claim.claim_id,
                'follow_up_id': current_follow_up.follow_up_id,
                'customer_id': customer_id,
            },
            session=mongo_session,
        )
        operations = sorted(
            (
                operation
                for document in documents
                if (
                    operation := self._model_from_document(
                        document,
                        FollowUpOperation,
                    )
                )
                is not None
            ),
            key=lambda operation: (
                operation.sequence,
                operation.operation_id,
            ),
        )

        terminal = updated_claim.terminal_disposition
        if terminal is None:
            raise KeyError(claim.claim_id)

        try:
            transition = reduce_expired_follow_up(
                claim,
                source_session,
                current_follow_up,
                operations,
                terminal.recorded_at,
            )
        except FollowUpExpiryExecutionRejected as error:
            raise IdempotencyConflict(current_follow_up.follow_up_id) from error

        if (
            transition.claim != updated_claim
            or transition.follow_up != updated_follow_up
            or transition.reconciled_operation != reconciled_operation
        ):
            raise IdempotencyConflict(current_follow_up.follow_up_id)

        self._ensure_new_audit_event(
            audit_event,
            mongo_session=mongo_session,
        )

        if reconciled_operation is not None:
            stored_operation = next(
                (
                    operation
                    for operation in operations
                    if operation.operation_id == reconciled_operation.operation_id
                ),
                None,
            )
            if stored_operation is None:
                raise IdempotencyConflict(reconciled_operation.operation_id)

            try:
                assert_follow_up_operation_transition(
                    stored_operation,
                    reconciled_operation,
                )
            except ValueError as error:
                raise IdempotencyConflict(reconciled_operation.operation_id) from error

            result = self._collection.replace_one(
                {
                    '_id': self._record_id(
                        'follow_up_operation',
                        stored_operation.operation_id,
                    ),
                    'record_type': 'follow_up_operation',
                    'customer_id': customer_id,
                    'claim_id': claim.claim_id,
                    'status': stored_operation.status.value,
                },
                {
                    **reconciled_operation.model_dump(mode='json'),
                    '_id': self._record_id(
                        'follow_up_operation',
                        reconciled_operation.operation_id,
                    ),
                    'record_type': 'follow_up_operation',
                    'customer_id': customer_id,
                    'claim_id': claim.claim_id,
                },
                session=mongo_session,
            )
            if result.matched_count != 1:
                raise IdempotencyConflict(reconciled_operation.operation_id)

        claim_result = self._collection.replace_one(
            {
                '_id': self._record_id(
                    'claim',
                    claim.claim_id,
                ),
                'record_type': 'claim',
                'customer_id': customer_id,
                'revision': expected_claim_revision,
            },
            {
                **updated_claim.model_dump(mode='json'),
                '_id': self._record_id(
                    'claim',
                    updated_claim.claim_id,
                ),
                'record_type': 'claim',
                'customer_id': customer_id,
                'claim_id': updated_claim.claim_id,
            },
            session=mongo_session,
        )

        if claim_result.matched_count != 1:
            raise RevisionConflict(expected_claim_revision)

        follow_up_result = self._collection.replace_one(
            {
                '_id': self._record_id(
                    'follow_up',
                    current_follow_up.follow_up_id,
                ),
                'record_type': 'follow_up',
                'customer_id': customer_id,
                'claim_id': claim.claim_id,
                'status': current_follow_up.status.value,
                'attempt_count': current_follow_up.attempt_count,
            },
            {
                **updated_follow_up.model_dump(mode='json'),
                '_id': self._record_id(
                    'follow_up',
                    updated_follow_up.follow_up_id,
                ),
                'record_type': 'follow_up',
                'customer_id': customer_id,
                'claim_id': claim.claim_id,
            },
            session=mongo_session,
        )

        if follow_up_result.matched_count != 1:
            raise IdempotencyConflict(current_follow_up.follow_up_id)

        self._insert_audit_event(
            audit_event,
            mongo_session=mongo_session,
        )

        self._append_realtime_mutation(
            RealtimeMutation.CLAIM_CHANGED,
            updated_claim,
            mongo_session=mongo_session,
            operation_correlation=(f'recovery-expiry:{updated_follow_up.follow_up_id}'),
        )

    def commit_due_follow_up_attempt(
        self,
        expected_follow_up: FollowUpRecord,
        updated_follow_up: FollowUpRecord,
        operation: FollowUpOperation,
        settled_previous_operation: FollowUpOperation | None,
        in_app_message: MessageRecord,
        customer_id: str,
        audit_event: AuditEventEnvelope,
    ) -> None:
        self._atomic(
            lambda mongo_session: self._commit_due_follow_up_attempt(
                expected_follow_up,
                updated_follow_up,
                operation,
                settled_previous_operation,
                in_app_message,
                customer_id,
                audit_event,
                mongo_session,
            )
        )

    def _commit_due_follow_up_attempt(
        self,
        expected_follow_up: FollowUpRecord,
        updated_follow_up: FollowUpRecord,
        operation: FollowUpOperation,
        settled_previous_operation: FollowUpOperation | None,
        in_app_message: MessageRecord,
        customer_id: str,
        audit_event: AuditEventEnvelope,
        mongo_session: Any,
    ) -> None:
        claim = self._get(
            'claim',
            expected_follow_up.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        current_follow_up = self._get(
            'follow_up',
            expected_follow_up.follow_up_id,
            FollowUpRecord,
            customer_id=customer_id,
            session=mongo_session,
        )
        source_session = self._get(
            'session',
            expected_follow_up.source_session_id,
            SessionRecord,
            customer_id=customer_id,
            session=mongo_session,
        )

        if claim is None or current_follow_up is None or source_session is None:
            raise KeyError(expected_follow_up.follow_up_id)

        existing_operation = self._get(
            'follow_up_operation',
            operation.operation_id,
            FollowUpOperation,
            customer_id=customer_id,
            session=mongo_session,
        )

        if existing_operation is not None:
            stored_message = self._get(
                'message',
                in_app_message.message_id,
                MessageRecord,
                customer_id=customer_id,
                session=mongo_session,
            )
            if (
                existing_operation == operation
                and stored_message == in_app_message
                and current_follow_up.attempt_count >= updated_follow_up.attempt_count
                and current_follow_up.updated_at >= updated_follow_up.updated_at
            ):
                return
            raise IdempotencyConflict(operation.operation_id)

        if current_follow_up != expected_follow_up:
            raise IdempotencyConflict(expected_follow_up.follow_up_id)

        prior_documents = self._collection.find(
            {
                'record_type': 'follow_up_operation',
                'claim_id': expected_follow_up.claim_id,
                'follow_up_id': expected_follow_up.follow_up_id,
                'customer_id': customer_id,
            },
            session=mongo_session,
        )
        prior_operations = sorted(
            (
                stored
                for document in prior_documents
                if (
                    stored := self._model_from_document(
                        document,
                        FollowUpOperation,
                    )
                )
                is not None
            ),
            key=lambda stored: (
                stored.sequence,
                stored.operation_id,
            ),
        )

        committed_at = operation.committed_at
        if committed_at is None:
            raise IdempotencyConflict(operation.operation_id)

        try:
            transition = reduce_due_follow_up(
                claim,
                source_session,
                current_follow_up,
                prior_operations,
                committed_at,
            )
        except FollowUpDueExecutionRejected as error:
            raise IdempotencyConflict(operation.operation_id) from error

        if (
            transition.operation != operation
            or transition.follow_up != updated_follow_up
            or transition.settled_previous_operation != settled_previous_operation
        ):
            raise IdempotencyConflict(operation.operation_id)

        if (
            in_app_message.claim_id != claim.claim_id
            or in_app_message.session_id != source_session.session_id
            or in_app_message.actor is not ActorType.AGENT
            or in_app_message.visibility is not MessageVisibility.CLAIMANT_VISIBLE
            or in_app_message.created_at != operation.committed_at
        ):
            raise IdempotencyConflict(in_app_message.message_id)
        validate_message_record(
            in_app_message,
            session=source_session,
            evidence=[],
            reply=None,
            duplicate_client_message=None,
        )

        self._ensure_new_audit_event(
            audit_event,
            mongo_session=mongo_session,
        )

        if settled_previous_operation is not None:
            stored_previous = next(
                (
                    stored
                    for stored in prior_operations
                    if stored.operation_id == settled_previous_operation.operation_id
                ),
                None,
            )
            if stored_previous is None:
                raise IdempotencyConflict(settled_previous_operation.operation_id)

            try:
                assert_follow_up_operation_transition(
                    stored_previous,
                    settled_previous_operation,
                )
            except ValueError as error:
                raise IdempotencyConflict(settled_previous_operation.operation_id) from error

            previous_document = {
                **settled_previous_operation.model_dump(mode='json'),
                '_id': self._record_id(
                    'follow_up_operation',
                    settled_previous_operation.operation_id,
                ),
                'record_type': 'follow_up_operation',
                'customer_id': customer_id,
                'claim_id': settled_previous_operation.claim_id,
            }

            previous_result = self._collection.replace_one(
                {
                    '_id': self._record_id(
                        'follow_up_operation',
                        stored_previous.operation_id,
                    ),
                    'record_type': 'follow_up_operation',
                    'customer_id': customer_id,
                    'claim_id': stored_previous.claim_id,
                    'status': stored_previous.status.value,
                },
                previous_document,
                session=mongo_session,
            )
            if previous_result.matched_count != 1:
                raise IdempotencyConflict(settled_previous_operation.operation_id)

        operation_document = {
            **operation.model_dump(mode='json'),
            '_id': self._record_id(
                'follow_up_operation',
                operation.operation_id,
            ),
            'record_type': 'follow_up_operation',
            'customer_id': customer_id,
            'claim_id': operation.claim_id,
        }

        try:
            self._collection.insert_one(
                operation_document,
                session=mongo_session,
            )
        except DuplicateKeyError as error:
            raise IdempotencyConflict(operation.operation_id) from error

        expected_payload = expected_follow_up.model_dump(mode='json')
        updated_document = {
            **updated_follow_up.model_dump(mode='json'),
            '_id': self._record_id(
                'follow_up',
                updated_follow_up.follow_up_id,
            ),
            'record_type': 'follow_up',
            'customer_id': customer_id,
            'claim_id': updated_follow_up.claim_id,
        }

        follow_up_result = self._collection.replace_one(
            {
                '_id': self._record_id(
                    'follow_up',
                    expected_follow_up.follow_up_id,
                ),
                'record_type': 'follow_up',
                'customer_id': customer_id,
                'claim_id': expected_follow_up.claim_id,
                'status': expected_follow_up.status.value,
                'attempt_count': expected_follow_up.attempt_count,
                'updated_at': expected_payload['updated_at'],
            },
            updated_document,
            session=mongo_session,
        )

        if follow_up_result.matched_count != 1:
            raise IdempotencyConflict(expected_follow_up.follow_up_id)

        self._put(
            'message',
            in_app_message.message_id,
            in_app_message,
            customer_id=customer_id,
            claim_id=claim.claim_id,
            session=mongo_session,
        )

        self._insert_audit_event(
            audit_event,
            mongo_session=mongo_session,
        )

    def list_due_follow_ups(
        self,
        due_before: datetime,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[FollowUpRecord], str | None]:
        from backend.repositories.pagination import (
            FOLLOW_UP_DISCOVERY_MAX_LIMIT,
            FollowUpDiscoveryCursor,
            decode_follow_up_discovery_cursor,
            encode_follow_up_discovery_cursor,
            repository_datetime_value,
        )

        if due_before.tzinfo is None:
            raise ValueError('Follow-up discovery boundary must be timezone-aware.')
        if not 1 <= limit <= FOLLOW_UP_DISCOVERY_MAX_LIMIT:
            raise ValueError(
                f'Follow-up discovery limit must be between 1 and {FOLLOW_UP_DISCOVERY_MAX_LIMIT}.'
            )

        after = (
            decode_follow_up_discovery_cursor(
                cursor,
                scope='due',
                boundary=due_before,
            )
            if cursor is not None
            else None
        )

        boundary = repository_datetime_value(due_before)

        query: dict[str, Any] = {
            'record_type': 'follow_up',
            'status': FollowUpStatus.PENDING.value,
            'due_at': {'$lte': boundary},
            'deadline_at': {'$gt': boundary},
        }

        if after is not None:
            ordered_at = repository_datetime_value(after.ordered_at)
            query['$or'] = [
                {
                    'due_at': {
                        '$gt': ordered_at,
                        '$lte': boundary,
                    }
                },
                {
                    'due_at': ordered_at,
                    'follow_up_id': {
                        '$gt': after.follow_up_id,
                    },
                },
            ]

        documents = (
            self._collection.find(query)
            .sort(
                [
                    ('due_at', 1),
                    ('follow_up_id', 1),
                ]
            )
            .limit(limit + 1)
        )

        records = [
            record
            for document in documents
            if (
                record := self._model_from_document(
                    document,
                    FollowUpRecord,
                )
            )
            is not None
        ]

        selected = records[:limit]
        next_cursor = None

        if len(records) > limit:
            final = selected[-1]
            assert final.due_at is not None

            next_cursor = encode_follow_up_discovery_cursor(
                FollowUpDiscoveryCursor(
                    scope='due',
                    boundary=due_before,
                    ordered_at=final.due_at,
                    follow_up_id=final.follow_up_id,
                )
            )

        return selected, next_cursor

    def list_expiring_follow_ups(
        self,
        deadline_before: datetime,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> tuple[list[FollowUpRecord], str | None]:
        from backend.repositories.pagination import (
            FOLLOW_UP_DISCOVERY_MAX_LIMIT,
            FollowUpDiscoveryCursor,
            decode_follow_up_discovery_cursor,
            encode_follow_up_discovery_cursor,
            repository_datetime_value,
        )

        if deadline_before.tzinfo is None:
            raise ValueError('Follow-up discovery boundary must be timezone-aware.')
        if not 1 <= limit <= FOLLOW_UP_DISCOVERY_MAX_LIMIT:
            raise ValueError(
                f'Follow-up discovery limit must be between 1 and {FOLLOW_UP_DISCOVERY_MAX_LIMIT}.'
            )

        after = (
            decode_follow_up_discovery_cursor(
                cursor,
                scope='deadline',
                boundary=deadline_before,
            )
            if cursor is not None
            else None
        )

        boundary = repository_datetime_value(deadline_before)

        query: dict[str, Any] = {
            'record_type': 'follow_up',
            'status': {
                '$in': [
                    FollowUpStatus.PENDING.value,
                    FollowUpStatus.BLOCKED.value,
                ]
            },
            'deadline_at': {'$lte': boundary},
        }

        if after is not None:
            ordered_at = repository_datetime_value(after.ordered_at)
            query['$or'] = [
                {
                    'deadline_at': {
                        '$gt': ordered_at,
                        '$lte': boundary,
                    }
                },
                {
                    'deadline_at': ordered_at,
                    'follow_up_id': {
                        '$gt': after.follow_up_id,
                    },
                },
            ]

        documents = (
            self._collection.find(query)
            .sort(
                [
                    ('deadline_at', 1),
                    ('follow_up_id', 1),
                ]
            )
            .limit(limit + 1)
        )

        records = [
            record
            for document in documents
            if (
                record := self._model_from_document(
                    document,
                    FollowUpRecord,
                )
            )
            is not None
        ]

        selected = records[:limit]
        next_cursor = None

        if len(records) > limit:
            final = selected[-1]
            assert final.deadline_at is not None

            next_cursor = encode_follow_up_discovery_cursor(
                FollowUpDiscoveryCursor(
                    scope='deadline',
                    boundary=deadline_before,
                    ordered_at=final.deadline_at,
                    follow_up_id=final.follow_up_id,
                )
            )

        return selected, next_cursor

    def get_follow_up_operation(
        self,
        claim_id: str,
        operation_id: str,
        customer_id: str,
    ) -> FollowUpOperation | None:
        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return None

        operation = self._get(
            'follow_up_operation',
            operation_id,
            FollowUpOperation,
            customer_id=customer_id,
        )

        if operation is None or operation.claim_id != claim_id:
            return None

        return operation

    def list_follow_up_operations(
        self,
        claim_id: str,
        follow_up_id: str,
        customer_id: str,
    ) -> list[FollowUpOperation]:
        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return []

        follow_up = self._get(
            'follow_up',
            follow_up_id,
            FollowUpRecord,
            customer_id=customer_id,
        )

        if follow_up is None or follow_up.claim_id != claim_id:
            return []

        return self._list(
            'follow_up_operation',
            FollowUpOperation,
            {
                'claim_id': claim_id,
                'customer_id': customer_id,
                'follow_up_id': follow_up_id,
            },
            'sequence',
        )

    def save_follow_up_operation(
        self,
        operation: FollowUpOperation,
        customer_id: str,
    ) -> None:
        self._atomic(
            lambda mongo_session: self._save_follow_up_operation(
                operation,
                customer_id,
                mongo_session,
            )
        )

    def _save_follow_up_operation(
        self,
        operation: FollowUpOperation,
        customer_id: str,
        mongo_session: Any,
    ) -> None:
        claim = self._get(
            'claim',
            operation.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )

        follow_up = self._get(
            'follow_up',
            operation.follow_up_id,
            FollowUpRecord,
            customer_id=customer_id,
            session=mongo_session,
        )

        if (
            claim is None
            or follow_up is None
            or follow_up.claim_id != operation.claim_id
            or follow_up.policy_id is None
            or follow_up.policy_version is None
            or follow_up.deadline_at is None
            or operation.policy_id != follow_up.policy_id
            or operation.policy_version != follow_up.policy_version
            or operation.scheduled_at < follow_up.created_at
            or operation.scheduled_at >= follow_up.deadline_at
            or operation.based_on_claim_revision > claim.revision
        ):
            raise KeyError(operation.operation_id)

        existing = self._get(
            'follow_up_operation',
            operation.operation_id,
            FollowUpOperation,
            customer_id=customer_id,
            session=mongo_session,
        )

        document = {
            **operation.model_dump(mode='json'),
            '_id': self._record_id(
                'follow_up_operation',
                operation.operation_id,
            ),
            'record_type': 'follow_up_operation',
            'customer_id': customer_id,
            'claim_id': operation.claim_id,
        }

        if existing is not None:
            if existing == operation:
                return

            if (
                operation.status is FollowUpOperationStatus.COMMITTED
                and operation.based_on_claim_revision != claim.revision
            ):
                raise IdempotencyConflict(operation.operation_id)

            try:
                assert_follow_up_operation_transition(
                    existing,
                    operation,
                )
            except ValueError as error:
                raise IdempotencyConflict(operation.operation_id) from error

            result = self._collection.replace_one(
                {
                    '_id': self._record_id(
                        'follow_up_operation',
                        operation.operation_id,
                    ),
                    'record_type': 'follow_up_operation',
                    'customer_id': customer_id,
                    'claim_id': operation.claim_id,
                    'status': existing.status.value,
                },
                document,
                session=mongo_session,
            )

            if result.matched_count == 1:
                return

            winner = self._get(
                'follow_up_operation',
                operation.operation_id,
                FollowUpOperation,
                customer_id=customer_id,
                session=mongo_session,
            )

            if winner == operation:
                return

            raise IdempotencyConflict(operation.operation_id)

        if operation.status is not FollowUpOperationStatus.SCHEDULED:
            raise IdempotencyConflict(operation.operation_id)

        if operation.based_on_claim_revision != claim.revision:
            raise IdempotencyConflict(operation.operation_id)

        latest = self._collection.find_one(
            {
                'record_type': 'follow_up_operation',
                'follow_up_id': operation.follow_up_id,
            },
            projection={'sequence': 1},
            sort=[('sequence', -1), ('_id', -1)],
            session=mongo_session,
        )

        expected_sequence = int(latest['sequence']) + 1 if latest is not None else 1

        if operation.sequence != expected_sequence:
            raise IdempotencyConflict(operation.operation_id)

        try:
            self._collection.insert_one(
                document,
                session=mongo_session,
            )
        except DuplicateKeyError as error:
            winner = self._get(
                'follow_up_operation',
                operation.operation_id,
                FollowUpOperation,
                customer_id=customer_id,
                session=mongo_session,
            )

            if winner == operation:
                return

            raise IdempotencyConflict(operation.operation_id) from error

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
            'claim',
            claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )

        if (
            claim is None
            or claim.active_session_id is None
            or self._claim_access_closed(
                claim_id,
                mongo_session=mongo_session,
            )
        ):
            return None

        record = self._get(
            'session',
            claim.active_session_id,
            SessionRecord,
            customer_id=customer_id,
            session=mongo_session,
        )

        return record if record is not None and record.claim_id == claim_id else None

    def list_sessions_for_claim(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[SessionRecord]:
        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return []

        return self._list(
            'session',
            SessionRecord,
            {
                'claim_id': claim_id,
                'customer_id': customer_id,
            },
            'started_at',
        )

    def search_sessions_internal(
        self,
        claim_id: str,
        customer_id: str,
        filters: dict[str, object],
        limit: int,
    ) -> list[StaffSessionSearchCandidate]:
        """Search a bounded Claim-scoped Session set without loading message bodies wholesale."""

        query: dict[str, Any] = {
            'record_type': 'session',
            'claim_id': claim_id,
            'customer_id': customer_id,
        }
        if filters.get('session_id'):
            query['_id'] = self._record_id('session', str(filters['session_id']))
        if filters.get('started_date'):
            day = str(filters['started_date'])
            next_day = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
            query['started_at'] = {
                '$gte': f'{day}T00:00:00Z',
                '$lt': f'{next_day}T00:00:00Z',
            }
        if filters.get('status'):
            query['status'] = filters['status']
        cursor = (
            self._collection.find(query)
            .sort([('started_at', -1), ('_id', -1)])
            .limit(STAFF_SESSION_MAX_EXAMINED + 1)
        )
        matches: list[StaffSessionSearchCandidate] = []
        for examined, document in enumerate(cursor, start=1):
            if examined > STAFF_SESSION_MAX_EXAMINED:
                raise RepositorySearchLimitExceeded(
                    'The Session search exceeded its maximum examined set; narrow the filters.'
                )
            session = self._model_from_document(document, SessionRecord)
            if session is None:
                continue
            message_query: dict[str, Any] = {
                'record_type': 'message',
                'claim_id': claim_id,
                'session_id': session.session_id,
                'customer_id': customer_id,
            }
            message_documents = list(
                self._collection.find(
                    message_query,
                    projection={'actor': 1, 'content.type': 1, 'content.text': 1},
                )
                .sort([('created_at', 1), ('_id', 1)])
                .limit(STAFF_SESSION_MESSAGE_MAX_EXAMINED + 1)
            )
            if len(message_documents) > STAFF_SESSION_MESSAGE_MAX_EXAMINED:
                raise RepositorySearchLimitExceeded(
                    'The Session message search exceeded its maximum examined set; '
                    'narrow the filters.'
                )
            actor = filters.get('actor')
            if actor and not any(document.get('actor') == actor for document in message_documents):
                continue
            message_contains = filters.get('message_contains')
            if message_contains:
                expected = str(message_contains).casefold()
                if not any(
                    isinstance(content := document.get('content'), dict)
                    and content.get('type') == 'text'
                    and isinstance(text := content.get('text'), str)
                    and expected in text.casefold()
                    for document in message_documents
                ):
                    continue
            matches.append(
                StaffSessionSearchCandidate(session=session, message_count=len(message_documents))
            )
            if len(matches) >= limit:
                break
        return matches

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
        self._atomic(lambda mongo_session: self._save_message(message, customer_id, mongo_session))

    def _save_message(
        self,
        message: MessageRecord,
        customer_id: str,
        mongo_session: Any,
    ) -> None:
        self._ensure_claim_access_open(
            message.claim_id,
            mongo_session=mongo_session,
        )
        claim = self._get(
            'claim',
            message.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        session = self._get(
            'session',
            message.session_id,
            SessionRecord,
            customer_id=customer_id,
            session=mongo_session,
        )
        if claim is None or session is None or session.claim_id != message.claim_id:
            raise KeyError(message.claim_id)
        evidence = [
            item
            for evidence_id in message.evidence_refs
            if (
                item := self._get(
                    'evidence',
                    evidence_id,
                    EvidenceRecord,
                    customer_id=customer_id,
                    session=mongo_session,
                )
            )
            is not None
        ]
        reply = (
            self._get(
                'message',
                message.in_reply_to,
                MessageRecord,
                customer_id=customer_id,
                session=mongo_session,
            )
            if message.in_reply_to is not None
            else None
        )
        duplicate_client_message = None
        if message.client_message_id is not None:
            duplicate_client_message = self._model_from_document(
                self._collection.find_one(
                    {
                        'record_type': 'message',
                        'claim_id': message.claim_id,
                        'customer_id': customer_id,
                        'client_message_id': message.client_message_id,
                    },
                    session=mongo_session,
                ),
                MessageRecord,
            )
        try:
            validate_message_record(
                message,
                session=session,
                evidence=evidence,
                reply=reply,
                duplicate_client_message=duplicate_client_message,
            )
        except DuplicateClientMessage as conflict:
            raise IdempotencyConflict(message.client_message_id or message.message_id) from conflict
        existing = self._get(
            'message',
            message.message_id,
            MessageRecord,
            customer_id=customer_id,
            session=mongo_session,
        )
        if existing is not None:
            if existing == message:
                self._append_realtime_mutation(
                    RealtimeMutation.MESSAGE_CHANGED,
                    claim,
                    mongo_session=mongo_session,
                    outcome=MutationOutcome.EXACT_NOOP,
                    claimant_visible=message.visibility is not MessageVisibility.INTERNAL_ONLY,
                )
                return
            raise IdempotencyConflict(message.message_id)
        self._put(
            'message',
            message.message_id,
            message,
            customer_id=customer_id,
            claim_id=message.claim_id,
            session=mongo_session,
        )
        self._append_realtime_mutation(
            RealtimeMutation.MESSAGE_CHANGED,
            claim,
            mongo_session=mongo_session,
            claimant_visible=message.visibility is not MessageVisibility.INTERNAL_ONLY,
        )

    def get_message(
        self,
        claim_id: str,
        session_id: str,
        message_id: str,
        customer_id: str,
    ) -> MessageRecord | None:
        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return None

        record = self._get(
            'message',
            message_id,
            MessageRecord,
            customer_id=customer_id,
        )

        if record is None or record.claim_id != claim_id or record.session_id != session_id:
            return None

        return record

    def find_message_by_client_id(
        self,
        claim_id: str,
        client_message_id: str,
        customer_id: str,
    ) -> MessageRecord | None:
        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return None

        document = self._collection.find_one(
            {
                'record_type': 'message',
                'claim_id': claim_id,
                'customer_id': customer_id,
                'client_message_id': client_message_id,
            }
        )

        return self._model_from_document(
            document,
            MessageRecord,
        )

    def list_messages(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> list[MessageRecord]:
        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return []

        return order_messages(
            self._list(
                'message',
                MessageRecord,
                {
                    'claim_id': claim_id,
                    'session_id': session_id,
                    'customer_id': customer_id,
                },
                'created_at',
            )
        )

    def list_recent_messages(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
        limit: int,
    ) -> list[MessageRecord]:
        return self.list_messages(claim_id, session_id, customer_id)[-limit:]

    def save_conversation_summary(
        self,
        summary: VerifiedConversationSummary,
        customer_id: str,
    ) -> None:
        if self.get_session(summary.claim_id, summary.session_id, customer_id) is None:
            raise KeyError(summary.session_id)
        document = summary.model_dump(mode='json')
        document.update(
            {
                '_id': self._record_id('conversation_summary', summary.summary_id),
                'record_type': 'conversation_summary',
                'customer_id': customer_id,
                'claim_id': summary.claim_id,
            }
        )
        try:
            self._collection.insert_one(document)
        except DuplicateKeyError as error:
            existing_document = self._collection.find_one(
                {
                    '_id': document['_id'],
                    'record_type': 'conversation_summary',
                    'customer_id': customer_id,
                    'claim_id': summary.claim_id,
                }
            )
            existing = self._model_from_document(
                existing_document,
                VerifiedConversationSummary,
            )
            if existing != summary:
                raise IdempotencyConflict(summary.summary_id) from error

    def get_latest_conversation_summary(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> VerifiedConversationSummary | None:
        if self.get_session(claim_id, session_id, customer_id) is None:
            return None
        summaries = self._list(
            'conversation_summary',
            VerifiedConversationSummary,
            {
                'claim_id': claim_id,
                'session_id': session_id,
                'customer_id': customer_id,
            },
            'created_at',
        )
        return summaries[-1] if summaries else None

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

    def get_claim_creation_operation(
        self,
        operation_id: str,
    ) -> ClaimCreationOperationRecord | None:
        return self._get(
            'claim_creation_operation',
            operation_id,
            ClaimCreationOperationRecord,
        )

    def reserve_claim_creation_operation(
        self,
        operation: ClaimCreationOperationRecord,
    ) -> bool:
        def reserve(mongo_session: Any) -> bool:
            claim = self._get(
                'claim',
                operation.claim_id,
                WorkingClaim,
                customer_id=operation.customer_id,
                session=mongo_session,
            )
            decision = self._get(
                'agent_decision',
                operation.authorised_decision_id,
                AgentDecisionRecord,
                customer_id=operation.customer_id,
                session=mongo_session,
            )
            evidence = self._list(
                'evidence',
                EvidenceRecord,
                {
                    'claim_id': operation.claim_id,
                    'customer_id': operation.customer_id,
                },
                'created_at',
                session=mongo_session,
            )
            if (
                operation.status is not ClaimCreationOperationStatus.PREPARED
                or claim is None
                or claim.revision != operation.authorised_revision
                or claim.external_claim is not None
                or claim.terminal_disposition is not None
                or decision is None
                or decision.claim_id != operation.claim_id
                or decision.resulting_revision != operation.authorised_revision
                or evidence_snapshot_fingerprint(evidence)
                != operation.evidence_snapshot_fingerprint
            ):
                raise KeyError(operation.claim_id)

            document = self._collection.find_one(
                {
                    'record_type': 'claim_creation_operation',
                    'claim_id': operation.claim_id,
                },
                session=mongo_session,
            )
            current = self._model_from_document(document, ClaimCreationOperationRecord)
            if current is None:
                try:
                    self._put(
                        'claim_creation_operation',
                        operation.operation_id,
                        operation,
                        customer_id=operation.customer_id,
                        claim_id=operation.claim_id,
                        session=mongo_session,
                    )
                except DuplicateKeyError as conflict:
                    raise IdempotencyConflict(operation.operation_id) from conflict
                return True
            if current.operation_id != operation.operation_id:
                raise IdempotencyConflict(operation.operation_id)
            if current.status is ClaimCreationOperationStatus.RETRYABLE_FAILURE:
                try:
                    assert_claim_creation_operation_transition(current, operation)
                except ValueError as conflict:
                    raise IdempotencyConflict(operation.operation_id) from conflict
                result = self._collection.replace_one(
                    {
                        '_id': self._record_id('claim_creation_operation', operation.operation_id),
                        'record_type': 'claim_creation_operation',
                        'status': ClaimCreationOperationStatus.RETRYABLE_FAILURE.value,
                        'request_fingerprint': operation.request_fingerprint,
                    },
                    {
                        **operation.model_dump(mode='json'),
                        '_id': self._record_id('claim_creation_operation', operation.operation_id),
                        'record_type': 'claim_creation_operation',
                        'customer_id': operation.customer_id,
                        'claim_id': operation.claim_id,
                    },
                    session=mongo_session,
                )
                if result.modified_count != 1:
                    raise IdempotencyConflict(operation.operation_id)
                return True
            if (
                current.request_fingerprint != operation.request_fingerprint
                or current.evidence_snapshot_fingerprint != operation.evidence_snapshot_fingerprint
                or current.route != operation.route
                or current.integration_source is not operation.integration_source
            ):
                raise IdempotencyConflict(operation.operation_id)
            return False

        return self._atomic(reserve)

    def save_claim_creation_operation(
        self,
        operation: ClaimCreationOperationRecord,
    ) -> None:
        def persist(mongo_session: Any) -> None:
            current = self._get(
                'claim_creation_operation',
                operation.operation_id,
                ClaimCreationOperationRecord,
                customer_id=operation.customer_id,
                session=mongo_session,
            )
            if current is None:
                raise KeyError(operation.operation_id)
            try:
                assert_claim_creation_operation_transition(current, operation)
            except ValueError as conflict:
                raise IdempotencyConflict(operation.operation_id) from conflict
            result = self._collection.replace_one(
                {
                    '_id': self._record_id('claim_creation_operation', operation.operation_id),
                    'record_type': 'claim_creation_operation',
                    'status': current.status.value,
                    'updated_at': current.model_dump(mode='json')['updated_at'],
                },
                {
                    **operation.model_dump(mode='json'),
                    '_id': self._record_id('claim_creation_operation', operation.operation_id),
                    'record_type': 'claim_creation_operation',
                    'customer_id': operation.customer_id,
                    'claim_id': operation.claim_id,
                },
                session=mongo_session,
            )
            if result.matched_count != 1:
                raise IdempotencyConflict(operation.operation_id)

        self._atomic(persist)

    def save_claim_creation_outcome(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        operation: ClaimCreationOperationRecord,
        branch_evaluation: BranchEvaluationRecord,
    ) -> None:
        def persist(mongo_session: Any) -> None:
            self._ensure_claim_revision(claim, expected_revision, mongo_session=mongo_session)
            self._validate_branch_evaluation(claim, branch_evaluation)
            self._reject_branch_evaluation_identity_conflict(
                branch_evaluation,
                mongo_session=mongo_session,
            )
            current = self._get(
                'claim_creation_operation',
                operation.operation_id,
                ClaimCreationOperationRecord,
                customer_id=claim.customer_id,
                session=mongo_session,
            )
            evidence = self._list(
                'evidence',
                EvidenceRecord,
                {'claim_id': claim.claim_id, 'customer_id': claim.customer_id},
                'created_at',
                session=mongo_session,
            )
            if (
                current is None
                or operation.status is not ClaimCreationOperationStatus.ACCEPTED
                or operation.result is None
                or claim.external_claim != operation.result
                or claim.external_claim_source_revision != operation.authorised_revision
                or claim.external_claim_fingerprint != operation.request_fingerprint
                or evidence_snapshot_fingerprint(evidence)
                != operation.evidence_snapshot_fingerprint
            ):
                raise KeyError(claim.claim_id)
            try:
                assert_claim_creation_operation_transition(current, operation)
            except ValueError as conflict:
                raise IdempotencyConflict(operation.operation_id) from conflict
            if (
                self._replace_claim_revision(claim, expected_revision, mongo_session=mongo_session)
                == 0
            ):
                self._raise_revision_conflict(claim.claim_id, mongo_session=mongo_session)
            self._put(
                'claim_creation_operation',
                operation.operation_id,
                operation,
                customer_id=claim.customer_id,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
            self._put(
                'branch_evaluation',
                branch_evaluation.evaluation_id,
                branch_evaluation,
                customer_id=claim.customer_id,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
            self._append_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                claim,
                mongo_session=mongo_session,
                operation_correlation=operation.operation_id,
            )

        self._atomic(persist)

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
        self._atomic(
            lambda mongo_session: self._save_assessor_routing_operation(operation, mongo_session)
        )

    def _save_assessor_routing_operation(
        self,
        operation: AssessorRoutingOperation,
        mongo_session: Any,
    ) -> None:
        claim = self._get(
            'claim',
            operation.claim_id,
            WorkingClaim,
            session=mongo_session,
        )
        external_claim_id = (
            claim.external_claim.external_claim_id
            if claim is not None
            and claim.external_claim is not None
            and claim.external_claim.external_claim_id is not None
            else operation.claim_id
        )
        if (
            claim is None
            or external_claim_id != operation.external_claim_id
            or operation.authorised_revision > claim.revision
        ):
            raise KeyError(operation.claim_id)

        existing = self._get(
            'assessor_routing_operation',
            operation.operation_id,
            AssessorRoutingOperation,
            session=mongo_session,
        )
        if existing is None:
            if operation.status is not AssessorRoutingOperationStatus.PREPARED:
                raise IdempotencyConflict(operation.operation_id)
            self._put(
                'assessor_routing_operation',
                operation.operation_id,
                operation,
                claim_id=operation.claim_id,
                session=mongo_session,
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
        # `UNKNOWN_OUTCOME` is an outcome the operation may take on, not a settled one:
        # it is written when an attempt may already have reached the provider, and
        # reconciliation is what moves it afterwards.
        allowed_statuses = {
            AssessorRoutingOperationStatus.RETRYABLE_FAILURE,
            AssessorRoutingOperationStatus.TERMINAL_FAILURE,
            AssessorRoutingOperationStatus.UNKNOWN_OUTCOME,
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
            session=mongo_session,
        )

    def save_assessor_routing_settlement(
        self,
        operation: AssessorRoutingOperation,
        task: ExternalTaskRecord,
        attempt: ExternalTaskAttempt,
        customer_id: str,
    ) -> None:
        """Atomically persist an assessor outcome and its task attempt in MongoDB."""

        def persist(mongo_session: Any) -> None:
            self._save_assessor_routing_operation(operation, mongo_session)
            self._save_external_task(task, customer_id, mongo_session)
            self._save_external_task_attempt(attempt, customer_id, mongo_session)

        self._atomic(persist)

    def save_assessor_reconciliation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        task: ExternalTaskRecord,
        operation: AssessorRoutingOperation,
        request: ExternalTaskRequest,
        evidence: EvidenceRecord,
        link: ExternalTaskEvidenceLink,
        branch_evaluation: BranchEvaluationRecord,
        customer_id: str,
        *,
        staff_action: StaffActionRecord | None = None,
        idempotency: IdempotencyRecord | None = None,
        required_staff_id: str | None = None,
        required_staff_revision: int | None = None,
    ) -> None:
        """Atomically settle one unknown assessor operation in MongoDB.

        Args:
            claim: Resulting Claim carrying the reconciled routing result.
            expected_revision: Claim revision that must still be current.
            task: External task advanced from unknown to accepted.
            operation: Assessor operation advanced from unknown to accepted.
            request: Request record carrying the send this settlement establishes.
            evidence: Pending assessment material owed by the task.
            link: Immutable relationship between the task and material.
            branch_evaluation: Applied branch projection for the new Claim revision.
            customer_id: Customer who owns every record.
            staff_action: Optional completed reconciliation action persisted atomically.
            idempotency: Optional staff mutation replay record persisted atomically.
            required_staff_id: Staff identity that must remain claimable through the write.
            required_staff_revision: Exact presence revision guarded by the transaction.

        Returns:
            None.

        Raises:
            RevisionConflict: The stored Claim revision changed first.
            IdempotencyConflict: Stored identity or lifecycle state conflicts.
            KeyError: A record is missing, belongs elsewhere, or is malformed.
        """

        def persist(mongo_session: Any) -> None:
            self._ensure_claim_revision(claim, expected_revision, mongo_session=mongo_session)
            if claim.revision != expected_revision + 1 or claim.customer_id != customer_id:
                raise KeyError(claim.claim_id)
            if (staff_action is None) is not (idempotency is None):
                raise KeyError(claim.claim_id)
            if staff_action is not None and idempotency is not None:
                if (
                    required_staff_id is None
                    or claim.assignee_id != required_staff_id
                    or staff_action.claim_id != claim.claim_id
                    or staff_action.assigned_to != required_staff_id
                    or staff_action.completed_by != required_staff_id
                    or staff_action.status is not StaffActionStatus.COMPLETED
                    or task.task_id not in staff_action.source_refs
                    or idempotency.actor_id != required_staff_id
                    or idempotency.claim_id != claim.claim_id
                    or idempotency.action_code != 'external.reconcile_response'
                    or idempotency.target_ref != task.task_id
                ):
                    raise KeyError(claim.claim_id)
                self._reject_existing_idempotency(idempotency, mongo_session=mongo_session)
                presence_query = {
                    '_id': self._record_id('staff_presence', required_staff_id),
                    'record_type': 'staff_presence',
                    'online': True,
                    'available': True,
                    'expires_at': {'$gt': datetime.now(UTC).isoformat()},
                }
                if required_staff_revision is not None:
                    presence_query['revision'] = required_staff_revision
                presence = self._collection.find_one(presence_query, session=mongo_session)
                if presence is None:
                    raise KeyError('staff_not_available')
                guard = self._collection.update_one(
                    {
                        '_id': presence['_id'],
                        'record_type': 'staff_presence',
                        'revision': presence['revision'],
                    },
                    {'$inc': {'revision': 1}},
                    session=mongo_session,
                )
                if guard.modified_count != 1:
                    raise KeyError('staff_not_available')
            current_task = self._get(
                'external_task',
                task.task_id,
                ExternalTaskRecord,
                customer_id=customer_id,
                session=mongo_session,
            )
            current_operation = self._get(
                'assessor_routing_operation',
                operation.operation_id,
                AssessorRoutingOperation,
                session=mongo_session,
            )
            if (
                current_task is None
                or current_task.claim_id != claim.claim_id
                or current_operation is None
                or current_operation.claim_id != claim.claim_id
                or evidence.claim_id != claim.claim_id
                or link.claim_id != claim.claim_id
                or link.task_id != task.task_id
                or link.evidence_id != evidence.evidence_id
                or claim.assessor_routing != operation.result
                or claim.assessor_routing_fingerprint != operation.request_fingerprint
            ):
                raise KeyError(claim.claim_id)
            validate_evidence_record(evidence)
            try:
                assert_task_transition_is_permitted(current_task, task)
            except ValueError as conflict:
                raise IdempotencyConflict(task.task_id) from conflict
            immutable_operation = (
                'claim_id',
                'external_claim_id',
                'authorisation_ref',
                'claimant_consent_ref',
                'requested_action',
                'authorised_revision',
                'request_fingerprint',
                'created_at',
            )
            if (
                current_operation.status
                not in {
                    AssessorRoutingOperationStatus.UNKNOWN_OUTCOME,
                    AssessorRoutingOperationStatus.PREPARED,
                }
                or operation.status is not AssessorRoutingOperationStatus.ACCEPTED
                or operation.updated_at <= current_operation.updated_at
                or any(
                    getattr(current_operation, name) != getattr(operation, name)
                    for name in immutable_operation
                )
            ):
                raise IdempotencyConflict(operation.operation_id)

            held_evidence = self._get(
                'evidence',
                evidence.evidence_id,
                EvidenceRecord,
                customer_id=customer_id,
                session=mongo_session,
            )
            held_link = self._get(
                'external_task_evidence_link',
                f'{link.claim_id}:{link.evidence_id}',
                ExternalTaskEvidenceLink,
                customer_id=customer_id,
                session=mongo_session,
            )
            if (held_evidence is not None and held_evidence != evidence) or (
                held_link is not None and held_link != link
            ):
                raise IdempotencyConflict(evidence.evidence_id)
            self._validate_branch_evaluation(claim, branch_evaluation)

            self._append_realtime_mutation(
                RealtimeMutation.ASSESSOR_RECONCILED,
                claim,
                mongo_session=mongo_session,
                operation_correlation=(idempotency.key if idempotency is not None else None),
                resources=realtime_resources_for_records(
                    RealtimeMutation.ASSESSOR_RECONCILED,
                    ('staff_action',) if staff_action is not None else (),
                ),
            )

            if (
                self._replace_claim_revision(claim, expected_revision, mongo_session=mongo_session)
                == 0
            ):
                self._raise_revision_conflict(claim.claim_id, mongo_session=mongo_session)
            self._put(
                'external_task',
                task.task_id,
                task,
                customer_id=customer_id,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
            self._put(
                'assessor_routing_operation',
                operation.operation_id,
                operation,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
            self._put(
                'external_task_request',
                request.task_id,
                request,
                customer_id=customer_id,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
            self._put(
                'evidence',
                evidence.evidence_id,
                evidence,
                customer_id=customer_id,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
            self._put(
                'external_task_evidence_link',
                f'{link.claim_id}:{link.evidence_id}',
                link,
                customer_id=customer_id,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
            self._put(
                'branch_evaluation',
                branch_evaluation.evaluation_id,
                branch_evaluation,
                customer_id=customer_id,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
            if staff_action is not None and idempotency is not None:
                self._put(
                    'staff_action',
                    staff_action.action_id,
                    staff_action,
                    customer_id=customer_id,
                    claim_id=claim.claim_id,
                    session=mongo_session,
                )
                self._save_idempotency(idempotency, mongo_session)

        self._atomic(persist)

    def save_assessor_routing_preparation(
        self,
        operation: AssessorRoutingOperation,
        decision: AgentDecisionRecord,
        customer_id: str,
        audit_events: tuple[AuditEventEnvelope, ...] = (),
    ) -> None:
        claim = self.get_claim(operation.claim_id, customer_id)
        session = self.get_session(operation.claim_id, decision.session_id, customer_id)
        external_claim_id = (
            claim.external_claim.external_claim_id
            if claim is not None
            and claim.external_claim is not None
            and claim.external_claim.external_claim_id is not None
            else operation.claim_id
        )
        if (
            claim is None
            or session is None
            or claim.active_session_id != decision.session_id
            or external_claim_id != operation.external_claim_id
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
        self._atomic(
            lambda mongo_session: self._save_evidence(evidence, customer_id, mongo_session)
        )

    def _save_evidence(
        self,
        evidence: EvidenceRecord,
        customer_id: str,
        mongo_session: Any,
    ) -> None:
        validate_evidence_record(evidence)
        claim = self._get(
            'claim',
            evidence.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        if claim is None:
            raise KeyError(evidence.claim_id)
        current = self._get(
            'evidence',
            evidence.evidence_id,
            EvidenceRecord,
            customer_id=customer_id,
            session=mongo_session,
        )
        try:
            assert_material_history_is_append_only(current, evidence)
        except ValueError as conflict:
            raise IdempotencyConflict(evidence.evidence_id) from conflict
        if current == evidence:
            self._append_realtime_mutation(
                RealtimeMutation.EVIDENCE_CHANGED,
                claim,
                mongo_session=mongo_session,
                outcome=MutationOutcome.EXACT_NOOP,
            )
            return
        self._put(
            'evidence',
            evidence.evidence_id,
            evidence,
            customer_id=customer_id,
            claim_id=evidence.claim_id,
            session=mongo_session,
        )
        self._append_realtime_mutation(
            RealtimeMutation.EVIDENCE_CHANGED,
            claim,
            mongo_session=mongo_session,
        )

    def get_evidence(
        self,
        claim_id: str,
        evidence_id: str,
        customer_id: str,
    ) -> EvidenceRecord | None:
        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return None

        record = self._get(
            'evidence',
            evidence_id,
            EvidenceRecord,
            customer_id=customer_id,
        )

        return record if record is not None and record.claim_id == claim_id else None

    def list_evidence(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[EvidenceRecord]:
        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return []

        return self._list(
            'evidence',
            EvidenceRecord,
            {
                'claim_id': claim_id,
                'customer_id': customer_id,
            },
            'created_at',
        )

    def list_evidence_for_customer(self, customer_id: str) -> list[EvidenceRecord]:
        documents = self._collection.find(
            {'record_type': 'evidence', 'customer_id': customer_id, 'source': 'claimant'}
        ).sort([('created_at', 1), ('_id', 1)])
        return [
            evidence
            for evidence in (
                self._model_from_document(
                    document,
                    EvidenceRecord,
                )
                for document in documents
            )
            if evidence is not None
            and self.claimant_resource_access_open(
                evidence.claim_id,
                customer_id,
            )
        ]

    def get_motor_other_driver(
        self, claim_id: str, customer_id: str
    ) -> MotorOtherDriverRecord | None:
        if not self._claim_owned(claim_id, customer_id):
            return None
        records = self._list(
            'motor_other_driver',
            MotorOtherDriverRecord,
            {'claim_id': claim_id, 'customer_id': customer_id},
            'created_at',
        )
        return records[0] if records else None

    def save_motor_other_driver_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        participant: MotorOtherDriverRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        if (
            claim.incident_type != 'motor'
            or participant.claim_id != claim.claim_id
            or participant.customer_id != claim.customer_id
            or idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != (claim.active_session_id or '')
        ):
            raise KeyError(claim.claim_id)

        def persist(mongo_session: Any) -> None:
            existing = self._collection.find_one(
                {'record_type': 'motor_other_driver', 'claim_id': claim.claim_id},
                projection={'_id': 1},
                session=mongo_session,
            )
            if existing is not None:
                raise IdempotencyConflict(participant.participant_id)
            self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                mutation=RealtimeMutation.CLAIM_CHANGED,
                records=[('motor_other_driver', participant.participant_id, participant)],
            )

        try:
            self._atomic(persist)
        except DuplicateKeyError as error:
            raise IdempotencyConflict(participant.participant_id) from error

    def list_contents_item_evidence_associations(
        self, claim_id: str, customer_id: str
    ) -> list[ContentsItemEvidenceAssociation]:
        if not self._claim_owned(claim_id, customer_id):
            return []
        return self._list(
            'contents_item_evidence_association',
            ContentsItemEvidenceAssociation,
            {'claim_id': claim_id, 'customer_id': customer_id},
            'created_at',
        )

    def list_contents_item_evidence_association_page(
        self,
        claim_id: str,
        customer_id: str,
        item_id: str,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[ContentsItemEvidenceAssociation], str | None]:
        from backend.repositories.pagination import (
            ContentsEvidenceAssociationCursor,
            decode_contents_evidence_association_cursor,
            encode_contents_evidence_association_cursor,
            repository_datetime_value,
        )

        if not self._claim_owned(claim_id, customer_id):
            return [], None
        after = (
            decode_contents_evidence_association_cursor(
                cursor,
                claim_id=claim_id,
                customer_id=customer_id,
                item_id=item_id,
            )
            if cursor is not None
            else None
        )
        query: dict[str, Any] = {
            'record_type': 'contents_item_evidence_association',
            'claim_id': claim_id,
            'customer_id': customer_id,
            'item_id': item_id,
        }
        if after is not None:
            timestamp = repository_datetime_value(after.created_at)
            query['$or'] = [
                {'created_at': {'$gt': timestamp}},
                {'created_at': timestamp, 'association_id': {'$gt': after.association_id}},
            ]
        documents = (
            self._collection.find(query)
            .sort([('created_at', 1), ('association_id', 1)])
            .limit(limit + 1)
        )
        records = [
            record
            for document in documents
            if (record := self._model_from_document(document, ContentsItemEvidenceAssociation))
            is not None
        ]
        selected = records[:limit]
        next_cursor = None
        if len(records) > limit:
            final = selected[-1]
            next_cursor = encode_contents_evidence_association_cursor(
                ContentsEvidenceAssociationCursor(
                    claim_id=claim_id,
                    customer_id=customer_id,
                    item_id=item_id,
                    created_at=final.created_at,
                    association_id=final.association_id,
                )
            )
        return selected, next_cursor

    def save_contents_item_evidence_association_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        association: ContentsItemEvidenceAssociation,
        idempotency: IdempotencyRecord,
    ) -> None:
        if (
            association.claim_id != claim.claim_id
            or association.customer_id != claim.customer_id
            or not any(item.item_id == association.item_id for item in claim.contents_items)
            or idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != (claim.active_session_id or '')
        ):
            raise KeyError(claim.claim_id)

        def persist(mongo_session: Any) -> None:
            evidence = self._get(
                'evidence',
                association.evidence_id,
                EvidenceRecord,
                customer_id=claim.customer_id,
                session=mongo_session,
            )
            if evidence is None or evidence.claim_id != claim.claim_id:
                raise KeyError(association.evidence_id)
            duplicate = self._collection.find_one(
                {
                    'record_type': 'contents_item_evidence_association',
                    'claim_id': claim.claim_id,
                    'item_id': association.item_id,
                    'evidence_id': association.evidence_id,
                },
                projection={'_id': 1},
                session=mongo_session,
            )
            if duplicate is not None:
                raise IdempotencyConflict(association.association_id)
            self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                mutation=RealtimeMutation.CLAIM_CHANGED,
                records=[
                    (
                        'contents_item_evidence_association',
                        association.association_id,
                        association,
                    )
                ],
            )

        try:
            self._atomic(persist)
        except DuplicateKeyError as error:
            raise IdempotencyConflict(association.association_id) from error

    def get_evidence_claim_link(
        self,
        target_claim_id: str,
        evidence_id: str,
        customer_id: str,
    ) -> EvidenceClaimLink | None:
        if not self.claimant_resource_access_open(
            target_claim_id,
            customer_id,
        ):
            return None

        link = self._get(
            'evidence_claim_link',
            f'{target_claim_id}:{evidence_id}',
            EvidenceClaimLink,
            customer_id=customer_id,
        )

        if link is None or not self.claimant_resource_access_open(
            link.source_claim_id,
            customer_id,
        ):
            return None

        return link

    def list_evidence_claim_links(
        self,
        customer_id: str,
        target_claim_id: str | None = None,
    ) -> list[EvidenceClaimLink]:
        if target_claim_id is not None and not self.claimant_resource_access_open(
            target_claim_id,
            customer_id,
        ):
            return []

        filters: dict[str, Any] = {
            'customer_id': customer_id,
        }

        if target_claim_id is not None:
            filters['target_claim_id'] = target_claim_id

        links = self._list(
            'evidence_claim_link',
            EvidenceClaimLink,
            filters,
            'created_at',
        )

        return [
            link
            for link in links
            if self.claimant_resource_access_open(
                link.source_claim_id,
                customer_id,
            )
            and self.claimant_resource_access_open(
                link.target_claim_id,
                customer_id,
            )
        ]

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
        self._atomic(
            lambda mongo_session: self._save_external_task(task, customer_id, mongo_session)
        )

    def _save_external_task(
        self,
        task: ExternalTaskRecord,
        customer_id: str,
        mongo_session: Any,
    ) -> None:
        claim = self._get(
            'claim',
            task.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        if claim is None:
            raise KeyError(task.claim_id)
        record_id = self._record_id('external_task', task.task_id)
        document = {
            **task.model_dump(mode='json'),
            '_id': record_id,
            'record_type': 'external_task',
            'customer_id': customer_id,
            'claim_id': task.claim_id,
        }
        stored = self._collection.find_one(
            {'_id': record_id, 'record_type': 'external_task'},
            session=mongo_session,
        )
        if stored is None:
            assert_external_task_registry_compatible(task)
            try:
                self._collection.insert_one(document, session=mongo_session)
                self._append_realtime_mutation(
                    RealtimeMutation.EXTERNAL_TASK_CHANGED,
                    claim,
                    mongo_session=mongo_session,
                )
                return
            except DuplicateKeyError:
                stored = self._collection.find_one(
                    {'_id': record_id, 'record_type': 'external_task'},
                    session=mongo_session,
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
            self._append_realtime_mutation(
                RealtimeMutation.EXTERNAL_TASK_CHANGED,
                claim,
                mongo_session=mongo_session,
                outcome=MutationOutcome.EXACT_NOOP,
            )
            return
        if any(getattr(existing, name) != getattr(task, name) for name in immutable_identity):
            raise IdempotencyConflict(task.task_id)
        assert_external_task_registry_compatible(task)
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
            session=mongo_session,
        )
        if result.matched_count == 0:
            current = self._collection.find_one(
                {'_id': record_id, 'record_type': 'external_task'},
                session=mongo_session,
            )
            same_owner = current is not None and (
                current.get('customer_id') == customer_id
                and current.get('claim_id') == task.claim_id
            )
            if not same_owner or self._model_from_document(current, ExternalTaskRecord) != task:
                raise IdempotencyConflict(task.task_id)
            self._append_realtime_mutation(
                RealtimeMutation.EXTERNAL_TASK_CHANGED,
                claim,
                mongo_session=mongo_session,
                outcome=MutationOutcome.EXACT_NOOP,
            )
            return
        self._append_realtime_mutation(
            RealtimeMutation.EXTERNAL_TASK_CHANGED,
            claim,
            mongo_session=mongo_session,
        )

    def save_external_task_attempt(
        self,
        attempt: ExternalTaskAttempt,
        customer_id: str,
    ) -> None:
        """Append one immutable claim-owned external-task attempt."""
        self._atomic(
            lambda mongo_session: self._save_external_task_attempt(
                attempt,
                customer_id,
                mongo_session,
            )
        )

    def save_external_task_settlement(
        self,
        task: ExternalTaskRecord,
        attempt: ExternalTaskAttempt,
        customer_id: str,
    ) -> None:
        """Atomically persist a generic task outcome and its attempt in MongoDB."""

        def persist(mongo_session: Any) -> None:
            self._save_external_task(task, customer_id, mongo_session)
            self._save_external_task_attempt(attempt, customer_id, mongo_session)

        self._atomic(persist)

    def _save_external_task_attempt(
        self,
        attempt: ExternalTaskAttempt,
        customer_id: str,
        mongo_session: Any,
    ) -> None:
        claim = self._get(
            'claim',
            attempt.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        task = self._get(
            'external_task',
            attempt.task_id,
            ExternalTaskRecord,
            customer_id=customer_id,
            session=mongo_session,
        )
        request = self._get(
            'external_task_request',
            attempt.task_id,
            ExternalTaskRequest,
            customer_id=customer_id,
            session=mongo_session,
        )
        if (
            claim is None
            or task is None
            or task.claim_id != attempt.claim_id
            or request is None
            or request.operation_id != attempt.operation_id
        ):
            raise KeyError(attempt.operation_id)
        existing = self._get(
            'external_task_attempt',
            attempt.attempt_id,
            ExternalTaskAttempt,
            customer_id=customer_id,
            session=mongo_session,
        )
        if existing is not None:
            if existing != attempt:
                raise IdempotencyConflict(attempt.attempt_id)
            return
        prior = self._list(
            'external_task_attempt',
            ExternalTaskAttempt,
            {'claim_id': attempt.claim_id, 'task_id': attempt.task_id},
            'attempt_number',
            session=mongo_session,
        )
        expected_number = max((item.attempt_number for item in prior), default=0) + 1
        if attempt.attempt_number != expected_number:
            raise IdempotencyConflict(attempt.attempt_id)
        document = {
            **attempt.model_dump(mode='json'),
            '_id': self._record_id('external_task_attempt', attempt.attempt_id),
            'record_type': 'external_task_attempt',
            'customer_id': customer_id,
            'claim_id': attempt.claim_id,
        }
        try:
            self._collection.insert_one(document, session=mongo_session)
        except DuplicateKeyError as error:
            winner = self._get(
                'external_task_attempt',
                attempt.attempt_id,
                ExternalTaskAttempt,
                customer_id=customer_id,
                session=mongo_session,
            )
            if winner == attempt:
                return
            raise IdempotencyConflict(attempt.attempt_id) from error

    def reserve_external_dispatch(
        self,
        claim_id: str,
        request_id: str,
        customer_id: str,
        reserved_at: datetime,
        operation_id: str,
    ) -> ExternalTaskRequest | None:
        """Atomically claim the sole right to dispatch one prepared request.

        The filter carries `dispatch_reserved_at: None`, so the reservation is taken by
        the update itself rather than by a decision made after a read. A second caller
        matches nothing and is told it did not win.

        Args:
            claim_id: Claim that owns the request.
            request_id: Request whose dispatch is being reserved.
            customer_id: Customer who owns the parent claim.
            reserved_at: Moment the reservation is taken.
            operation_id: Operation this attempt dispatches under, recorded with the
                reservation so an interrupted attempt still names its own identity.

        Returns:
            The reserved request, or None when another attempt already holds it.

        Raises:
            KeyError: The claim or request is missing or belongs to another customer.
        """

        record_id = self._dispatch_record_id(claim_id, request_id, customer_id)
        updated = self._collection.find_one_and_update(
            {
                '_id': record_id,
                'record_type': 'external_task_request',
                'customer_id': customer_id,
                'claim_id': claim_id,
                'dispatch_reserved_at': None,
            },
            {
                '$set': {
                    'dispatch_reserved_at': reserved_at.isoformat(),
                    'operation_id': operation_id,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            return None
        return self._model_from_document(updated, ExternalTaskRequest)

    def release_external_dispatch(
        self,
        claim_id: str,
        request_id: str,
        customer_id: str,
    ) -> None:
        """Release a reservation whose attempt established that nothing was sent.

        Args:
            claim_id: Claim that owns the request.
            request_id: Request whose reservation is being released.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The claim or request is missing or belongs to another customer.
        """

        record_id = self._dispatch_record_id(claim_id, request_id, customer_id)
        self._collection.update_one(
            {
                '_id': record_id,
                'record_type': 'external_task_request',
                'customer_id': customer_id,
                'claim_id': claim_id,
            },
            {'$set': {'dispatch_reserved_at': None}},
        )

    def _dispatch_record_id(self, claim_id: str, request_id: str, customer_id: str) -> str:
        """Resolve the stored request document id, refusing an unknown or foreign one."""

        if self.get_claim(claim_id, customer_id) is None:
            raise KeyError(claim_id)
        stored = self._collection.find_one(
            {
                'record_type': 'external_task_request',
                'request_id': request_id,
                'claim_id': claim_id,
                'customer_id': customer_id,
            }
        )
        if stored is None:
            raise KeyError(request_id)
        return str(stored['_id'])

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
        self._atomic(
            lambda mongo_session: self._save_external_task_request(
                request, customer_id, mongo_session
            )
        )

    def _save_external_task_request(
        self,
        request: ExternalTaskRequest,
        customer_id: str,
        mongo_session: Any,
    ) -> None:
        claim = self._get(
            'claim',
            request.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        task = self._get(
            'external_task',
            request.task_id,
            ExternalTaskRecord,
            customer_id=customer_id,
            session=mongo_session,
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
            session=mongo_session,
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
            {'_id': record_id, 'record_type': 'external_task_request'},
            session=mongo_session,
        )
        if stored is None:
            try:
                self._collection.insert_one(document, session=mongo_session)
                self._append_realtime_mutation(
                    RealtimeMutation.EXTERNAL_REQUEST_CHANGED,
                    claim,
                    mongo_session=mongo_session,
                    operation_correlation=request.operation_id,
                )
                return
            except DuplicateKeyError:
                stored = self._collection.find_one(
                    {'_id': record_id, 'record_type': 'external_task_request'},
                    session=mongo_session,
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
            self._append_realtime_mutation(
                RealtimeMutation.EXTERNAL_REQUEST_CHANGED,
                claim,
                mongo_session=mongo_session,
                outcome=MutationOutcome.EXACT_NOOP,
                operation_correlation=request.operation_id,
            )
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
        # The reservation records the operation identity before the send, so a first
        # send now advances a record that may already carry it. What must not change is
        # which operation it names.
        first_send = (
            existing.sent_at is None
            and request.sent_at is not None
            and request.operation_id is not None
            and existing.operation_id in {None, request.operation_id}
        )
        if changed_identity or not first_send:
            raise IdempotencyConflict(request.request_id)
        # The conditional write still refuses to rewrite a send, but the operation
        # identity may already be present: the dispatch reservation records it before
        # the send, so filtering on a null one would refuse every reserved request.
        result = self._collection.replace_one(
            {
                '_id': record_id,
                'record_type': 'external_task_request',
                'customer_id': customer_id,
                'claim_id': request.claim_id,
                'sent_at': None,
                'operation_id': {'$in': [None, request.operation_id]},
            },
            document,
            session=mongo_session,
        )
        if result.matched_count == 0:
            current = self._collection.find_one(
                {'_id': record_id, 'record_type': 'external_task_request'},
                session=mongo_session,
            )
            same_owner = current is not None and (
                current.get('customer_id') == customer_id
                and current.get('claim_id') == request.claim_id
            )
            if not same_owner or self._model_from_document(current, ExternalTaskRequest) != request:
                raise IdempotencyConflict(request.request_id)
            self._append_realtime_mutation(
                RealtimeMutation.EXTERNAL_REQUEST_CHANGED,
                claim,
                mongo_session=mongo_session,
                outcome=MutationOutcome.EXACT_NOOP,
                operation_correlation=request.operation_id,
            )
            return
        self._append_realtime_mutation(
            RealtimeMutation.EXTERNAL_REQUEST_CHANGED,
            claim,
            mongo_session=mongo_session,
            operation_correlation=request.operation_id,
        )

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
        self._atomic(
            lambda mongo_session: self._save_external_task_evidence_link(
                link, customer_id, mongo_session
            )
        )

    def _save_external_task_evidence_link(
        self,
        link: ExternalTaskEvidenceLink,
        customer_id: str,
        mongo_session: Any,
    ) -> None:
        claim = self._get(
            'claim',
            link.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        if claim is None:
            raise KeyError(link.claim_id)
        task = self._get(
            'external_task',
            link.task_id,
            ExternalTaskRecord,
            customer_id=customer_id,
            session=mongo_session,
        )
        if task is None or task.claim_id != link.claim_id:
            raise KeyError(link.task_id)
        evidence = self._get(
            'evidence',
            link.evidence_id,
            EvidenceRecord,
            customer_id=customer_id,
            session=mongo_session,
        )
        if evidence is None or evidence.claim_id != link.claim_id:
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
            self._collection.insert_one(document, session=mongo_session)
        except DuplicateKeyError as error:
            existing = self._collection.find_one(
                {'_id': record_id, 'record_type': 'external_task_evidence_link'},
                session=mongo_session,
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
            self._append_realtime_mutation(
                RealtimeMutation.EXTERNAL_EVIDENCE_LINKED,
                claim,
                mongo_session=mongo_session,
                outcome=MutationOutcome.EXACT_NOOP,
            )
            return
        self._append_realtime_mutation(
            RealtimeMutation.EXTERNAL_EVIDENCE_LINKED,
            claim,
            mongo_session=mongo_session,
        )

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
        self._atomic(
            lambda mongo_session: self._save_external_task_result(
                result, customer_id, mongo_session
            )
        )

    def _save_external_task_result(
        self,
        result: ExternalTaskResult,
        customer_id: str,
        mongo_session: Any,
    ) -> None:
        claim = self._get(
            'claim',
            result.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        if claim is None:
            raise KeyError(result.claim_id)
        task = self._get(
            'external_task',
            result.task_id,
            ExternalTaskRecord,
            customer_id=customer_id,
            session=mongo_session,
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
                    session=mongo_session,
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
            evidence = self._get(
                'evidence',
                evidence_id,
                EvidenceRecord,
                customer_id=customer_id,
                session=mongo_session,
            )
            if evidence is None or evidence.claim_id != result.claim_id:
                raise KeyError(evidence_id)

        held = next(
            iter(
                self._list(
                    'external_task_result',
                    ExternalTaskResult,
                    {'claim_id': result.claim_id, 'task_id': result.task_id},
                    'received_at',
                    session=mongo_session,
                )
            ),
            None,
        )
        by_identity = self._get(
            'external_task_result',
            result.result_id,
            ExternalTaskResult,
            customer_id=customer_id,
            session=mongo_session,
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
                self._append_realtime_mutation(
                    RealtimeMutation.EXTERNAL_RESULT_CHANGED,
                    claim,
                    mongo_session=mongo_session,
                    outcome=MutationOutcome.EXACT_NOOP,
                )
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
                self._collection.insert_one(document, session=mongo_session)
                self._append_realtime_mutation(
                    RealtimeMutation.EXTERNAL_RESULT_CHANGED,
                    claim,
                    mongo_session=mongo_session,
                )
                return
            except DuplicateKeyError as error:
                # Another writer won the race. Whether that is a conflict depends on what
                # it stored: an identical document means this call's intended result is
                # the canonical one, and reporting failure would tell a retrying producer
                # that ingestion failed after it had actually succeeded.
                self._assert_race_winner_matches(
                    result, customer_id, error, mongo_session=mongo_session
                )
                self._append_realtime_mutation(
                    RealtimeMutation.EXTERNAL_RESULT_CHANGED,
                    claim,
                    mongo_session=mongo_session,
                    outcome=MutationOutcome.EXACT_NOOP,
                )
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
            session=mongo_session,
        )
        if replaced.matched_count == 0:
            # The stored verification moved between the read and the write. The same
            # question applies: an identical winner is this call's own outcome.
            self._assert_race_winner_matches(result, customer_id, None, mongo_session=mongo_session)
            self._append_realtime_mutation(
                RealtimeMutation.EXTERNAL_RESULT_CHANGED,
                claim,
                mongo_session=mongo_session,
                outcome=MutationOutcome.EXACT_NOOP,
            )
            return
        self._append_realtime_mutation(
            RealtimeMutation.EXTERNAL_RESULT_CHANGED,
            claim,
            mongo_session=mongo_session,
        )

    def _assert_race_winner_matches(
        self,
        result: ExternalTaskResult,
        customer_id: str,
        cause: Exception | None,
        *,
        mongo_session: Any = None,
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
                    session=mongo_session,
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

    def list_external_task_attempts_internal(
        self,
        claim_id: str,
    ) -> list[ExternalTaskAttempt]:
        """List immutable task attempts in stable sequence order."""
        return self._list(
            'external_task_attempt',
            ExternalTaskAttempt,
            {'claim_id': claim_id},
            'attempt_number',
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
        self._atomic(lambda mongo_session: self._save_handoff(handoff, customer_id, mongo_session))

    def _save_handoff(
        self,
        handoff: HandoffRecord,
        customer_id: str,
        mongo_session: Any,
    ) -> None:
        claim = self._get(
            'claim',
            handoff.claim_id,
            WorkingClaim,
            customer_id=customer_id,
            session=mongo_session,
        )
        if claim is None:
            raise KeyError(handoff.claim_id)
        existing = self._get(
            'handoff',
            handoff.handoff_id,
            HandoffRecord,
            customer_id=customer_id,
            session=mongo_session,
        )
        if existing == handoff:
            self._append_realtime_mutation(
                RealtimeMutation.HANDOFF_CHANGED,
                claim,
                mongo_session=mongo_session,
                outcome=MutationOutcome.EXACT_NOOP,
            )
            return
        self._put(
            'handoff',
            handoff.handoff_id,
            handoff,
            customer_id=customer_id,
            claim_id=handoff.claim_id,
            session=mongo_session,
        )
        self._append_realtime_mutation(
            RealtimeMutation.HANDOFF_CHANGED,
            claim,
            mongo_session=mongo_session,
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

    def get_staff_presence(self, staff_id: str) -> StaffPresenceRecord | None:
        return self._get('staff_presence', staff_id, StaffPresenceRecord)

    def list_staff_presence(self) -> list[StaffPresenceRecord]:
        return self._list('staff_presence', StaffPresenceRecord, {}, 'staff_id')

    def save_staff_presence(
        self, presence: StaffPresenceRecord, expected_revision: int | None = None
    ) -> None:
        record_id = self._record_id('staff_presence', presence.staff_id)
        current = self._collection.find_one({'_id': record_id, 'record_type': 'staff_presence'})
        current_revision = int(current['revision']) if current is not None else 0
        if expected_revision is not None and current_revision != expected_revision:
            raise RevisionConflict(current_revision)
        if current is None:
            if presence.revision != 1:
                raise RevisionConflict(0)
            document = {
                **presence.model_dump(mode='json'),
                '_id': record_id,
                'record_type': 'staff_presence',
            }
            try:
                self._collection.insert_one(document)
            except DuplicateKeyError as error:
                raise RevisionConflict(1) from error
            return
        if presence.revision != current_revision + 1:
            raise RevisionConflict(current_revision)
        document = {
            **presence.model_dump(mode='json'),
            '_id': record_id,
            'record_type': 'staff_presence',
        }
        result = self._collection.replace_one(
            {'_id': record_id, 'record_type': 'staff_presence', 'revision': current_revision},
            document,
        )
        if result.modified_count != 1:
            latest = self._collection.find_one({'_id': record_id})
            raise RevisionConflict(int(latest['revision']) if latest else 0)

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
        audit_event: AuditEventEnvelope | None = None,
        staff_agent_execution: StaffAgentExecutionRecord | None = None,
    ) -> None:
        try:
            validate_staff_agent_execution(
                staff_agent_execution, claim, expected_revision, idempotency
            )
        except ValueError as error:
            raise KeyError(claim.claim_id) from error
        coworker_records = coworkers or []
        try:
            validate_handoff_mutation_audit(claim, handoff, idempotency, audit_event)
        except ValueError as error:
            raise KeyError(claim.claim_id) from error
        if (
            claim.revision != expected_revision + 1
            or collaboration_request.claim_id != claim.claim_id
            or any(item.claim_id != claim.claim_id for item in coworker_records)
            or (handoff is not None and handoff.claim_id != claim.claim_id)
            or (handoff is not None and idempotency.handoff_id != handoff.handoff_id)
            or (handoff is None and idempotency.handoff_id is not None)
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
        if staff_agent_execution is not None:
            records.append(
                ('staff_agent_execution', staff_agent_execution.execution_id, staff_agent_execution)
            )

        def persist(mongo_session: Any) -> None:
            prepared_audit = (
                self._prepare_audit_events(claim, (audit_event,), mongo_session=mongo_session)
                if audit_event is not None
                else ()
            )
            self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                mutation=RealtimeMutation.OWNERSHIP_CHANGED,
                records=records,
            )
            for event in prepared_audit:
                self._insert_audit_event(event, mongo_session=mongo_session)

        self._atomic(persist)

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
        required_staff_id: str | None = None,
        required_staff_revision: int | None = None,
        audit_event: AuditEventEnvelope | None = None,
        staff_agent_execution: StaffAgentExecutionRecord | None = None,
    ) -> None:
        try:
            validate_staff_agent_execution(
                staff_agent_execution, claim, expected_revision, idempotency
            )
        except ValueError as error:
            raise KeyError(claim.claim_id) from error
        supplied = (staff_action, customer_update, signal_decision, handoff, message)
        try:
            validate_handoff_mutation_audit(claim, handoff, idempotency, audit_event)
        except ValueError as error:
            raise KeyError(claim.claim_id) from error
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
        if staff_agent_execution is not None:
            records.append(
                ('staff_agent_execution', staff_agent_execution.execution_id, staff_agent_execution)
            )

        def persist(mongo_session: Any) -> None:
            prepared_audit = (
                self._prepare_audit_events(claim, (audit_event,), mongo_session=mongo_session)
                if audit_event is not None
                else ()
            )
            self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                mutation=RealtimeMutation.STAFF_MUTATION_COMMITTED,
                records=records,
                required_staff_id=required_staff_id,
                required_staff_revision=required_staff_revision,
            )
            for event in prepared_audit:
                self._insert_audit_event(event, mongo_session=mongo_session)

        self._atomic(persist)

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
                mutation=RealtimeMutation.MESSAGE_MUTATION_COMMITTED,
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
        runtime_trace: RuntimeTraceRecord | None = None,
        runtime_records: RuntimeTurnRecords | None = None,
        *,
        checkpointed: bool = False,
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
            and (
                (runtime_records is None and idempotency.runtime_result_id is None)
                or (
                    runtime_records is not None
                    and idempotency.runtime_result_id == runtime_records.result.result_id
                )
            )
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
        if runtime_records is not None:
            try:
                validate_runtime_turn_links(
                    runtime_records,
                    claim_id=claim.claim_id,
                    session_id=session.session_id,
                    trigger_message_id=claimant_message.message_id,
                    agent_message_id=agent_message.message_id,
                    expected_revision=expected_revision,
                    resulting_revision=claim.revision,
                )
            except ValueError as error:
                raise KeyError(claim.claim_id) from error
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
                runtime_trace,
                runtime_records,
                checkpointed,
                mongo_session,
            )
        )

    def save_runtime_turn(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        claimant_message: MessageRecord,
        agent_message: MessageRecord,
        runtime_trace: RuntimeTraceRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        """Persist a read-only namespaced Runtime turn without a Claim rewrite."""
        if (
            claim.revision != expected_revision
            or session.claim_id != claim.claim_id
            or session.customer_id != claim.customer_id
            or session.status is not SessionStatus.ACTIVE
            or session.context_revision != claim.revision
            or claim.active_session_id != session.session_id
            or claimant_message.claim_id != claim.claim_id
            or agent_message.claim_id != claim.claim_id
            or claimant_message.session_id != session.session_id
            or agent_message.session_id != session.session_id
            or claimant_message.actor is not ActorType.CLAIMANT
            or agent_message.actor is not ActorType.AGENT
            or agent_message.in_reply_to != claimant_message.message_id
            or runtime_trace.claim_id != claim.claim_id
            or runtime_trace.session_id != session.session_id
            or runtime_trace.trigger_message_id != claimant_message.message_id
            or idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != session.session_id
            or idempotency.message_id != claimant_message.message_id
            or idempotency.agent_message_id != agent_message.message_id
            or idempotency.runtime_trace_id != runtime_trace.trace_id
            or idempotency.decision_id is not None
        ):
            raise KeyError(claim.claim_id)
        self._atomic(
            lambda mongo_session: self._save_runtime_turn_records(
                claim,
                expected_revision,
                session,
                claimant_message,
                agent_message,
                runtime_trace,
                idempotency,
                mongo_session,
            )
        )

    def _save_runtime_turn_records(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        claimant_message: MessageRecord,
        agent_message: MessageRecord,
        runtime_trace: RuntimeTraceRecord,
        idempotency: IdempotencyRecord,
        mongo_session: Any,
    ) -> None:
        self._ensure_claim_revision(claim, expected_revision, mongo_session=mongo_session)
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
        ):
            raise KeyError(claim.claim_id)
        existing_idempotency = self._collection.find_one(
            {
                'record_type': 'idempotency',
                'actor_id': idempotency.actor_id,
                'route': idempotency.route,
                'key': idempotency.key,
            },
            session=mongo_session,
        )
        if existing_idempotency is not None:
            exact_retry = (
                existing_idempotency.get('payload', {}).get('request_fingerprint')
                == idempotency.request_fingerprint
                and stored_session == session
                and self._get(
                    'message',
                    claimant_message.message_id,
                    MessageRecord,
                    customer_id=claim.customer_id,
                    session=mongo_session,
                )
                == claimant_message
                and self._get(
                    'message',
                    agent_message.message_id,
                    MessageRecord,
                    customer_id=claim.customer_id,
                    session=mongo_session,
                )
                == agent_message
                and self._get(
                    'runtime_trace',
                    runtime_trace.trace_id,
                    RuntimeTraceRecord,
                    customer_id=claim.customer_id,
                    session=mongo_session,
                )
                == runtime_trace
            )
            if exact_retry:
                self._append_realtime_mutation(
                    RealtimeMutation.RUNTIME_TURN_COMMITTED,
                    claim,
                    mongo_session=mongo_session,
                    outcome=MutationOutcome.EXACT_NOOP,
                    operation_correlation=idempotency.key,
                )
                return
            raise IdempotencyConflict(idempotency.key)
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
        claimant_evidence = [
            item
            for evidence_id in claimant_message.evidence_refs
            if (
                item := self._get(
                    'evidence',
                    evidence_id,
                    EvidenceRecord,
                    customer_id=claim.customer_id,
                    session=mongo_session,
                )
            )
            is not None
        ]
        validate_message_record(
            claimant_message,
            session=stored_session,
            evidence=claimant_evidence,
            reply=(
                self._get(
                    'message',
                    claimant_message.in_reply_to,
                    MessageRecord,
                    customer_id=claim.customer_id,
                    session=mongo_session,
                )
                if claimant_message.in_reply_to is not None
                else None
            ),
            duplicate_client_message=None,
        )
        agent_evidence = [
            item
            for evidence_id in agent_message.evidence_refs
            if (
                item := self._get(
                    'evidence',
                    evidence_id,
                    EvidenceRecord,
                    customer_id=claim.customer_id,
                    session=mongo_session,
                )
            )
            is not None
        ]
        validate_message_record(
            agent_message,
            session=stored_session,
            evidence=agent_evidence,
            reply=(
                claimant_message
                if agent_message.in_reply_to == claimant_message.message_id
                else None
            ),
            duplicate_client_message=None,
        )
        records = (
            ('message', claimant_message.message_id, claimant_message),
            ('message', agent_message.message_id, agent_message),
            ('runtime_trace', runtime_trace.trace_id, runtime_trace),
        )
        for kind, identifier, record in records:
            existing = self._collection.find_one(
                {'_id': self._record_id(kind, identifier), 'record_type': kind},
                projection={'claim_id': 1, 'customer_id': 1},
                session=mongo_session,
            )
            if existing is not None:
                raise IdempotencyConflict(identifier)
            self._reject_client_message_conflict(
                {
                    'record_type': kind,
                    'claim_id': claim.claim_id,
                    'client_message_id': getattr(record, 'client_message_id', None),
                },
                session=mongo_session,
            )
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
        self._append_realtime_mutation(
            RealtimeMutation.RUNTIME_TURN_COMMITTED,
            claim,
            mongo_session=mongo_session,
            operation_correlation=idempotency.key,
            resources=realtime_resources_for_records(
                RealtimeMutation.RUNTIME_TURN_COMMITTED,
                ('message', 'message', 'runtime_trace'),
            ),
        )

    def get_runtime_trace(
        self,
        claim_id: str,
        trace_id: str,
        customer_id: str,
    ) -> RuntimeTraceRecord | None:
        if not self._claim_owned(claim_id, customer_id):
            return None
        record = self._get(
            'runtime_trace',
            trace_id,
            RuntimeTraceRecord,
            customer_id=customer_id,
        )
        return record if record is not None and record.claim_id == claim_id else None

    def find_runtime_trace_for_trigger(
        self,
        claim_id: str,
        trigger_message_id: str,
        customer_id: str,
    ) -> RuntimeTraceRecord | None:
        if not self._claim_owned(claim_id, customer_id):
            return None
        document = self._collection.find_one(
            {
                'record_type': 'runtime_trace',
                'claim_id': claim_id,
                'customer_id': customer_id,
                'trigger_message_id': trigger_message_id,
            },
            sort=[('created_at', -1), ('_id', -1)],
        )
        return self._model_from_document(document, RuntimeTraceRecord)

    def get_runtime_turn_for_trigger(
        self,
        claim_id: str,
        trigger_message_id: str,
        customer_id: str,
    ) -> RuntimeTurnRecords | None:
        if not self._claim_owned(claim_id, customer_id):
            return None
        plan_doc = self._collection.find_one(
            {
                'record_type': 'turn_plan',
                'claim_id': claim_id,
                'customer_id': customer_id,
                'trigger_message_id': trigger_message_id,
            },
            sort=[('created_at', -1), ('_id', -1)],
        )
        plan = self._model_from_document(plan_doc, TurnPlanRecord)
        if plan is None:
            return None
        proposal_doc = self._collection.find_one(
            {
                'record_type': 'agent_proposal',
                'turn_id': plan.turn_id,
                'claim_id': claim_id,
                'customer_id': customer_id,
            }
        )
        proposal = self._model_from_document(proposal_doc, AgentProposalRecord)
        execution = self._collection.find_one(
            {'record_type': 'execution_plan', 'turn_id': plan.turn_id, 'customer_id': customer_id}
        )
        execution_plan = self._model_from_document(execution, ExecutionPlanRecord)
        result_doc = self._collection.find_one(
            {'record_type': 'turn_result', 'turn_id': plan.turn_id, 'customer_id': customer_id}
        )
        result = self._model_from_document(result_doc, TurnResultRecord)
        if proposal is None or execution_plan is None or result is None:
            return None
        envelope_docs = self._collection.find(
            {'record_type': 'action_envelope', 'turn_id': plan.turn_id, 'customer_id': customer_id}
        )
        tool_docs = self._collection.find(
            {'record_type': 'tool_result', 'turn_id': plan.turn_id, 'customer_id': customer_id}
        )
        work_docs = self._collection.find(
            {
                'record_type': 'runtime_work_item',
                'turn_id': plan.turn_id,
                'customer_id': customer_id,
            }
        )
        return RuntimeTurnRecords(
            turn_plan=plan,
            proposal=proposal,
            execution_plan=execution_plan,
            action_envelopes=[
                item
                for item in (
                    self._model_from_document(doc, ActionEnvelopeRecord) for doc in envelope_docs
                )
                if item is not None
            ],
            tool_results=[
                item
                for item in (self._model_from_document(doc, ToolResultRecord) for doc in tool_docs)
                if item is not None
            ],
            result=result,
            work_items=[
                item
                for item in (
                    self._model_from_document(doc, RuntimeWorkItemRecord) for doc in work_docs
                )
                if item is not None
            ],
        )

    def list_runtime_work_items(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[RuntimeWorkItemRecord]:
        if not self._claim_owned(claim_id, customer_id):
            return []
        documents = self._collection.find(
            {
                'record_type': 'runtime_work_item',
                'claim_id': claim_id,
                'customer_id': customer_id,
            },
            sort=[('updated_at', 1), ('_id', 1)],
        )
        return [
            item
            for item in (
                self._model_from_document(document, RuntimeWorkItemRecord) for document in documents
            )
            if item is not None
        ]

    def save_runtime_work_item(
        self,
        item: RuntimeWorkItemRecord,
        customer_id: str,
    ) -> None:
        if not self._claim_owned(item.claim_id, customer_id):
            raise KeyError(item.claim_id)

        def persist(mongo_session: Any) -> None:
            existing = self._get(
                'runtime_work_item',
                item.work_item_id,
                RuntimeWorkItemRecord,
                customer_id=customer_id,
                session=mongo_session,
            )

            if existing is not None:
                if existing == item:
                    return

                immutable_match = (
                    existing.work_item_id == item.work_item_id
                    and existing.claim_id == item.claim_id
                    and existing.turn_id == item.turn_id
                    and existing.kind == item.kind
                    and existing.subject_ref == item.subject_ref
                    and existing.owner == item.owner
                    and existing.created_at == item.created_at
                    and existing.external_offer == item.external_offer
                    and existing.confirmation_request == item.confirmation_request
                )
                valid_settlement = (
                    immutable_match
                    and existing.status in {'open', 'in_progress'}
                    and item.status in {'completed', 'cancelled'}
                    and item.blocks_action is None
                    and item.completed_at is not None
                    and item.updated_at >= existing.updated_at
                )
                if not valid_settlement:
                    raise IdempotencyConflict(item.work_item_id)

                document = {
                    **item.model_dump(mode='json'),
                    '_id': self._record_id('runtime_work_item', item.work_item_id),
                    'record_type': 'runtime_work_item',
                    'customer_id': customer_id,
                    'claim_id': item.claim_id,
                }
                result = self._collection.replace_one(
                    {
                        '_id': self._record_id('runtime_work_item', item.work_item_id),
                        'record_type': 'runtime_work_item',
                        'customer_id': customer_id,
                        'claim_id': item.claim_id,
                        'status': existing.status,
                        'updated_at': existing.model_dump(mode='json')['updated_at'],
                    },
                    document,
                    session=mongo_session,
                )
                if result.matched_count == 1:
                    return

                winner = self._get(
                    'runtime_work_item',
                    item.work_item_id,
                    RuntimeWorkItemRecord,
                    customer_id=customer_id,
                    session=mongo_session,
                )
                if winner == item:
                    return
                raise IdempotencyConflict(item.work_item_id)

            self._put(
                'runtime_work_item',
                item.work_item_id,
                item,
                customer_id=customer_id,
                claim_id=item.claim_id,
                session=mongo_session,
            )

        self._atomic(persist)

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
        runtime_trace: RuntimeTraceRecord | None,
        runtime_records: RuntimeTurnRecords | None,
        checkpointed: bool,
        mongo_session: Any,
    ) -> None:
        if handoff is not None:
            from backend.repositories.handoff_guard import validate_runtime_handoff_update

            stored_handoff = self._get(
                'handoff',
                handoff.handoff_id,
                HandoffRecord,
                customer_id=claim.customer_id,
                session=mongo_session,
            )
            validate_runtime_handoff_update(
                stored_handoff, handoff, claim, claimant_message, decision
            )
        if claimant_message.client_message_id is not None and not checkpointed:
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
        if runtime_trace is not None:
            records.append(('runtime_trace', runtime_trace.trace_id, runtime_trace))
        if runtime_records is not None:
            records.extend(
                [
                    ('turn_plan', runtime_records.turn_plan.turn_id, runtime_records.turn_plan),
                    (
                        'agent_proposal',
                        runtime_records.proposal.proposal_id,
                        runtime_records.proposal,
                    ),
                    (
                        'execution_plan',
                        runtime_records.execution_plan.execution_plan_id,
                        runtime_records.execution_plan,
                    ),
                    *[
                        ('action_envelope', item.envelope_id, item)
                        for item in runtime_records.action_envelopes
                    ],
                    *[
                        ('tool_result', item.result_id, item)
                        for item in runtime_records.tool_results
                    ],
                    ('turn_result', runtime_records.result.result_id, runtime_records.result),
                    *[
                        ('runtime_work_item', item.work_item_id, item)
                        for item in runtime_records.work_items
                    ],
                ]
            )
        self._save_child_mutation(
            claim,
            expected_revision,
            idempotency,
            mongo_session,
            mutation=RealtimeMutation.AGENT_TURN_COMMITTED,
            records=records,
            session=session,
            checkpointed=checkpointed,
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
                mutation=RealtimeMutation.EVIDENCE_CLAIM_CHANGED,
                records=records,
            )
        )

    def save_evidence_action_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        evidence: EvidenceRecord | None,
        link: EvidenceClaimLink | None,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
        branch_evaluation: BranchEvaluationRecord,
    ) -> None:
        if (
            claim.revision != expected_revision + 1
            or idempotency.actor_id != claim.customer_id
            or idempotency.claim_id != claim.claim_id
            or idempotency.session_id != (claim.active_session_id or '')
            or (evidence is not None and evidence.claim_id != claim.claim_id)
            or (link is not None and link.target_claim_id != claim.claim_id)
        ):
            raise KeyError(claim.claim_id)
        self._validate_branch_evaluation(claim, branch_evaluation)

        records: list[tuple[str, str, BaseModel]] = []
        if evidence is not None:
            records.append(('evidence', evidence.evidence_id, evidence))
        if link is not None:
            records.append(
                (
                    'evidence_claim_link',
                    f'{link.target_claim_id}:{link.evidence_id}',
                    link,
                )
            )
        records.append(('branch_evaluation', branch_evaluation.evaluation_id, branch_evaluation))

        def persist(mongo_session: Any) -> None:
            if link is not None:
                source_evidence = self._get(
                    'evidence',
                    link.evidence_id,
                    EvidenceRecord,
                    customer_id=claim.customer_id,
                    session=mongo_session,
                )
                if source_evidence is None or source_evidence.claim_id != link.source_claim_id:
                    raise KeyError(link.evidence_id)
            prepared = self._prepare_audit_events(
                claim,
                (audit_event,),
                mongo_session=mongo_session,
            )
            self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                mutation=RealtimeMutation.EVIDENCE_CLAIM_CHANGED,
                records=records,
            )
            for event in prepared:
                self._insert_audit_event(event, mongo_session=mongo_session)

        self._atomic(persist)

    def save_handoff_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        handoff: HandoffRecord,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
        branch_evaluation: BranchEvaluationRecord | None = None,
        *,
        safety_message: MessageRecord | None = None,
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

        def persist(mongo_session: Any) -> None:
            if safety_message is not None:
                from backend.repositories.handoff_guard import validate_preprovider_safety_handoff

                validate_preprovider_safety_handoff(
                    self._get(
                        'handoff',
                        handoff.handoff_id,
                        HandoffRecord,
                        customer_id=claim.customer_id,
                        session=mongo_session,
                    ),
                    handoff,
                    claim,
                    safety_message,
                    self._get(
                        'message',
                        safety_message.message_id,
                        MessageRecord,
                        customer_id=claim.customer_id,
                        session=mongo_session,
                    ),
                )
            prepared_audit = self._prepare_audit_events(
                claim,
                (audit_event,),
                mongo_session=mongo_session,
            )
            self._save_child_mutation(
                claim,
                expected_revision,
                idempotency,
                mongo_session,
                mutation=RealtimeMutation.HANDOFF_MUTATION_COMMITTED,
                records=records,
            )
            for event in prepared_audit:
                self._insert_audit_event(event, mongo_session=mongo_session)

        self._atomic(persist)

    def _save_child_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        mongo_session: Any,
        *,
        mutation: RealtimeMutation,
        records: list[tuple[str, str, BaseModel]],
        session: SessionRecord | None = None,
        required_staff_id: str | None = None,
        required_staff_revision: int | None = None,
        checkpointed: bool = False,
    ) -> None:
        has_internal_message = any(
            isinstance(record, MessageRecord)
            and record.visibility is MessageVisibility.INTERNAL_ONLY
            for _kind, _identifier, record in records
        )
        excluded = frozenset({RealtimeResource.MESSAGES}) if has_internal_message else frozenset()
        resources = realtime_resources_for_records(
            mutation,
            tuple(kind for kind, _identifier, _record in records),
        )
        if checkpointed:
            saved = self._collection.find_one(
                {
                    'record_type': 'idempotency',
                    'actor_id': idempotency.actor_id,
                    'route': idempotency.route,
                    'key': idempotency.key,
                },
                session=mongo_session,
            )
            payload = saved.get('payload', {}) if saved else {}
            if (
                payload.get('request_fingerprint') != idempotency.request_fingerprint
                or payload.get('message_id') != idempotency.message_id
                or payload.get('decision_id') is not None
                or payload.get('response_payload') is not None
            ):
                raise IdempotencyConflict(idempotency.key)
        else:
            self._reject_existing_idempotency(idempotency, mongo_session=mongo_session)
        self._ensure_claim_revision(claim, expected_revision, mongo_session=mongo_session)
        if required_staff_id is not None:
            presence = self._collection.find_one(
                {
                    '_id': self._record_id('staff_presence', required_staff_id),
                    'record_type': 'staff_presence',
                    'online': True,
                    'available': True,
                    **(
                        {'revision': required_staff_revision}
                        if required_staff_revision is not None
                        else {}
                    ),
                    'expires_at': {'$gt': datetime.now(UTC).isoformat()},
                },
                session=mongo_session,
            )
            if presence is None:
                raise KeyError('staff_not_available')
            guard = self._collection.update_one(
                {
                    '_id': self._record_id('staff_presence', required_staff_id),
                    'record_type': 'staff_presence',
                    'revision': presence['revision'],
                },
                {'$inc': {'revision': 1}},
                session=mongo_session,
            )
            if guard.modified_count != 1:
                raise KeyError('staff_not_available')
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
        pending_messages = {
            record.message_id: record
            for kind, _identifier, record in records
            if kind == 'message' and isinstance(record, MessageRecord)
        }
        pending_evidence = {
            record.evidence_id: record
            for kind, _identifier, record in records
            if kind == 'evidence' and isinstance(record, EvidenceRecord)
        }
        for kind, identifier, record in records:
            if checkpointed and kind == 'message' and identifier == idempotency.message_id:
                stored_message = self._get(
                    'message',
                    identifier,
                    MessageRecord,
                    customer_id=claim.customer_id,
                    session=mongo_session,
                )
                if stored_message != record:
                    raise IdempotencyConflict(identifier)
                continue
            if kind == 'staff_agent_execution':
                if not isinstance(record, StaffAgentExecutionRecord):
                    raise KeyError(claim.claim_id)
                try:
                    validate_staff_agent_execution_source(
                        record,
                        self._get(
                            'staff_agent_session',
                            record.session_id,
                            StaffAgentSession,
                            customer_id=record.staff_id,
                            session=mongo_session,
                        ),
                        self._get(
                            'staff_agent_message',
                            record.message_id,
                            StaffAgentMessage,
                            customer_id=record.staff_id,
                            session=mongo_session,
                        ),
                    )
                except ValueError as error:
                    raise KeyError(claim.claim_id) from error
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
                evidence = []
                for evidence_id in record.evidence_refs:
                    item = pending_evidence.get(evidence_id) or self._get(
                        'evidence',
                        evidence_id,
                        EvidenceRecord,
                        customer_id=claim.customer_id,
                        session=mongo_session,
                    )
                    if item is not None:
                        evidence.append(item)
                reply = pending_messages.get(record.in_reply_to or '')
                if reply is None and record.in_reply_to is not None:
                    reply = self._get(
                        'message',
                        record.in_reply_to,
                        MessageRecord,
                        customer_id=claim.customer_id,
                        session=mongo_session,
                    )
                duplicate_client_message = None
                if record.client_message_id is not None:
                    duplicate_document = self._collection.find_one(
                        {
                            'record_type': 'message',
                            'claim_id': claim.claim_id,
                            'customer_id': claim.customer_id,
                            'client_message_id': record.client_message_id,
                        },
                        session=mongo_session,
                    )
                    duplicate_client_message = self._model_from_document(
                        duplicate_document,
                        MessageRecord,
                    )
                try:
                    validate_message_record(
                        record,
                        session=message_session,
                        evidence=evidence,
                        reply=reply,
                        duplicate_client_message=duplicate_client_message,
                    )
                except DuplicateClientMessage as conflict:
                    raise IdempotencyConflict(
                        record.client_message_id or record.message_id
                    ) from conflict
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
                projection=None if kind == 'evidence' else {'claim_id': 1, 'customer_id': 1},
                session=mongo_session,
            )
            if existing is not None and (
                existing.get('claim_id') != claim.claim_id
                or existing.get('customer_id') != claim.customer_id
                or kind in IMMUTABLE_CHILD_RECORD_KINDS
            ):
                raise IdempotencyConflict(identifier)
            if kind == 'evidence':
                if not isinstance(record, EvidenceRecord):
                    raise KeyError(claim.claim_id)
                validate_evidence_record(record)
                current_evidence = (
                    self._model_from_document(existing, EvidenceRecord)
                    if existing is not None
                    else None
                )
                try:
                    assert_material_history_is_append_only(current_evidence, record)
                except ValueError as conflict:
                    raise IdempotencyConflict(identifier) from conflict
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
            if checkpointed and kind == 'message' and identifier == idempotency.message_id:
                continue
            self._put(
                kind,
                identifier,
                record,
                customer_id=claim.customer_id,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
        if checkpointed:
            self._collection.delete_one(
                {
                    'record_type': 'idempotency',
                    'actor_id': idempotency.actor_id,
                    'route': idempotency.route,
                    'key': idempotency.key,
                },
                session=mongo_session,
            )
        self._save_idempotency(idempotency, mongo_session)
        self._append_realtime_mutation(
            mutation,
            claim,
            mongo_session=mongo_session,
            operation_correlation=idempotency.key,
            resources=resources,
            claimant_resources=claimant_resources_for(
                mutation,
                resources=resources,
                excluded=excluded,
            ),
        )

    def _ensure_claim_revision(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        *,
        mongo_session: Any,
    ) -> None:
        self._ensure_claim_access_open(
            claim.claim_id,
            mongo_session=mongo_session,
        )
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
        self._ensure_claim_access_open(
            claim.claim_id,
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
                'staff_search': self._staff_search_projection(
                    claim, session=mongo_session
                ).model_dump(mode='json'),
                '_id': self._record_id('claim', claim.claim_id),
                'record_type': 'claim',
                'customer_id': claim.customer_id,
                'claim_id': claim.claim_id,
            },
            session=mongo_session,
        )
        return result.matched_count

    def _raise_revision_conflict(self, claim_id: str, *, mongo_session: Any) -> NoReturn:
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

    def find_idempotency(
        self,
        actor_id: str,
        route: str,
        key: str,
    ) -> IdempotencyRecord | None:
        document = self._collection.find_one(
            {
                'record_type': 'idempotency',
                'actor_id': actor_id,
                'route': route,
                'key': key,
            }
        )

        if document is None:
            return None

        record = IdempotencyRecord(**document['payload'])

        # WorkingClaim may already be gone. The retired claimant retry record
        # and durable RetentionOperation are sufficient closure evidence.
        if record.retired:
            operation_document = self._collection.find_one(
                {
                    'record_type': ('retention_operation'),
                    'claim_id': record.claim_id,
                }
            )

            operation = self._model_from_document(
                operation_document,
                RetentionOperation,
            )

            if retention_access_closed(operation):
                raise ResourceAccessClosed(record.claim_id)

        return record

    def find_message_turn_idempotency(
        self,
        actor_id: str,
        route: str,
        claim_id: str,
        message_id: str,
    ) -> IdempotencyRecord | None:
        from backend.repositories.protocols import (
            message_turn_result_priority,
        )

        if self._claimant_actor_access_closed(
            claim_id,
            actor_id,
        ):
            raise ResourceAccessClosed(claim_id)

        documents = self._collection.find(
            {
                'record_type': 'idempotency',
                'actor_id': actor_id,
                'route': route,
                'payload.claim_id': claim_id,
                'payload.message_id': message_id,
                'payload.retired': {'$ne': True},
            },
        )

        records = [IdempotencyRecord(**document['payload']) for document in documents]

        return (
            max(
                records,
                key=message_turn_result_priority,
            )
            if records
            else None
        )

    def reserve_message_turn_idempotency_alias(
        self,
        actor_id: str,
        route: str,
        claim_id: str,
        message_id: str,
        key: str,
        request_fingerprint: str,
    ) -> IdempotencyRecord | None:
        from backend.repositories.protocols import message_turn_result_priority

        def reserve(mongo_session: Any) -> IdempotencyRecord | None:
            if self._claimant_actor_access_closed(
                claim_id,
                actor_id,
                mongo_session=mongo_session,
            ):
                raise ResourceAccessClosed(claim_id)
            original_documents = list(
                self._collection.find(
                    {
                        'record_type': 'idempotency',
                        'actor_id': actor_id,
                        'route': route,
                        'payload.claim_id': claim_id,
                        'payload.message_id': message_id,
                        'payload.retired': {'$ne': True},
                    },
                    session=mongo_session,
                )
            )
            if not original_documents:
                return None
            # The most recently written attempt at this message is not
            # necessarily the completed one -- a failed attempt may have been
            # recorded after an earlier success reconciled, or vice versa.
            # The same completed-over-failed priority fixture uses via
            # find_message_turn_idempotency must decide which attempt an
            # alias is reserved against.
            original_document = max(
                original_documents,
                key=lambda document: message_turn_result_priority(
                    IdempotencyRecord(**document['payload'])
                ),
            )
            if original_document['payload'].get('request_fingerprint') != request_fingerprint:
                raise IdempotencyConflict(key)
            alias = replace(
                IdempotencyRecord(**original_document['payload']),
                key=key,
                request_fingerprint=request_fingerprint,
            )
            query = {
                'record_type': 'idempotency',
                'actor_id': actor_id,
                'route': route,
                'key': key,
            }
            existing = self._collection.find_one(query, session=mongo_session)
            if existing is not None:
                if existing.get('payload') != alias.__dict__:
                    raise IdempotencyConflict(key)
                return alias
            document = {
                **query,
                '_id': self._record_id('idempotency', f'{actor_id}:{route}:{key}'),
                'payload': alias.__dict__,
            }
            try:
                self._collection.insert_one(document, session=mongo_session)
            except DuplicateKeyError:
                raise IdempotencyConflict(key) from None
            return alias

        return self._atomic(reserve)

    def save_idempotency(self, record: IdempotencyRecord) -> None:
        if record.claim_id and self._claimant_actor_access_closed(
            record.claim_id,
            record.actor_id,
        ):
            raise ResourceAccessClosed(record.claim_id)
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

    def find_message_checkpoint(
        self,
        claim_id: str,
        message_id: str,
        customer_id: str,
    ) -> IdempotencyRecord | None:
        if self._claimant_actor_access_closed(
            claim_id,
            customer_id,
        ):
            raise ResourceAccessClosed(claim_id)

        if not self.claimant_resource_access_open(
            claim_id,
            customer_id,
        ):
            return None

        document = self._collection.find_one(
            {
                'record_type': 'idempotency',
                'actor_id': customer_id,
                'payload.claim_id': claim_id,
                'payload.message_id': message_id,
                'payload.revision_before_message': {
                    '$ne': None,
                },
                'payload.inbound_checkpoint': True,
            },
            sort=[
                (
                    'payload.revision_before_message',
                    1,
                )
            ],
        )

        return IdempotencyRecord(**document['payload']) if document is not None else None

    def save_message_recovery(
        self,
        message: MessageRecord,
        idempotency: IdempotencyRecord,
        *,
        agent_message: MessageRecord | None = None,
    ) -> None:
        def write(mongo_session: Any) -> None:
            self._ensure_claim_access_open(
                message.claim_id,
                mongo_session=mongo_session,
            )
            stored = self._get(
                'message',
                message.message_id,
                MessageRecord,
                customer_id=idempotency.actor_id,
                session=mongo_session,
            )
            query = {
                'record_type': 'idempotency',
                'actor_id': idempotency.actor_id,
                'route': idempotency.route,
                'key': idempotency.key,
            }
            existing = self._collection.find_one(query, session=mongo_session)
            if (
                stored is None
                or stored.model_copy(update={'recovery_rule_id': message.recovery_rule_id})
                != message
            ):
                raise IdempotencyConflict(message.message_id)
            if (
                existing is None
                or existing['payload']['request_fingerprint'] != idempotency.request_fingerprint
                or existing['payload'].get('message_id') != message.message_id
                or existing['payload'].get('claim_id') != message.claim_id
                or existing['payload'].get('session_id') != message.session_id
                or existing['payload'].get('response_payload') is not None
                or existing['payload'].get('decision_id') is not None
                or idempotency.message_id != message.message_id
                or message.actor is not ActorType.CLAIMANT
            ):
                raise IdempotencyConflict(idempotency.key)
            if agent_message is not None:
                if (
                    agent_message.actor is not ActorType.AGENT
                    or agent_message.claim_id != message.claim_id
                    or agent_message.session_id != message.session_id
                    or agent_message.in_reply_to != message.message_id
                    or agent_message.recovery_rule_id != message.recovery_rule_id
                    or agent_message.recovery_rule_id is None
                    or idempotency.agent_message_id != agent_message.message_id
                    or self._get(
                        'message', agent_message.message_id, MessageRecord, session=mongo_session
                    )
                    is not None
                ):
                    raise IdempotencyConflict(agent_message.message_id)
                self._put(
                    'message',
                    agent_message.message_id,
                    agent_message,
                    customer_id=idempotency.actor_id,
                    claim_id=message.claim_id,
                    session=mongo_session,
                )
            self._put(
                'message',
                message.message_id,
                message,
                customer_id=idempotency.actor_id,
                claim_id=message.claim_id,
                session=mongo_session,
            )
            self._collection.update_one(
                query, {'$set': {'payload': idempotency.__dict__}}, session=mongo_session
            )

        self._atomic(write)

    def save_incomplete_checkpoint(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        follow_up: FollowUpRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        self._atomic(
            lambda mongo_session: self._save_incomplete_checkpoint(
                claim,
                expected_revision,
                session,
                follow_up,
                idempotency,
                mongo_session,
            )
        )

    def freeze_message_response(
        self, idempotency: IdempotencyRecord, response_payload: dict[str, Any]
    ) -> dict[str, Any]:
        def freeze(mongo_session: Any) -> dict[str, Any]:
            self._ensure_claim_access_open(
                idempotency.claim_id,
                mongo_session=mongo_session,
            )
            query = {
                'record_type': 'idempotency',
                'actor_id': idempotency.actor_id,
                'route': idempotency.route,
                'key': idempotency.key,
            }
            document = self._collection.find_one(query, session=mongo_session)
            saved = IdempotencyRecord(**document['payload']) if document is not None else None
            if (
                saved is None
                or saved.request_fingerprint != idempotency.request_fingerprint
                or saved.claim_id != idempotency.claim_id
                or saved.session_id != idempotency.session_id
                or saved.message_id != idempotency.message_id
                or saved.decision_id != idempotency.decision_id
                or saved.decision_id is None
                or saved.claim_id is None
                or self._get(
                    'claim',
                    saved.claim_id,
                    WorkingClaim,
                    customer_id=saved.actor_id,
                    session=mongo_session,
                )
                is None
                or response_payload.get('claim_id') != saved.claim_id
                or response_payload.get('session_id') != saved.session_id
            ):
                raise IdempotencyConflict(idempotency.key)
            if saved.response_payload is not None:
                return saved.response_payload
            updated = self._collection.find_one_and_update(
                {**query, 'payload.response_payload': None},
                {
                    '$set': {
                        'payload.response_status': 200,
                        'payload.response_payload': response_payload,
                    }
                },
                return_document=ReturnDocument.AFTER,
                session=mongo_session,
            )
            if updated is None:
                updated = self._collection.find_one(query, session=mongo_session)
            if updated is None or updated['payload'].get('response_payload') is None:
                raise IdempotencyConflict(idempotency.key)
            return cast(dict[str, Any], updated['payload']['response_payload'])

        return self._atomic(freeze)

    def _save_incomplete_checkpoint(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        follow_up: FollowUpRecord,
        idempotency: IdempotencyRecord,
        mongo_session: Any,
    ) -> None:
        stored_claim = self._get(
            'claim',
            claim.claim_id,
            WorkingClaim,
            customer_id=claim.customer_id,
            session=mongo_session,
        )
        if stored_claim is None:
            raise KeyError(claim.claim_id)
        if stored_claim.revision != expected_revision:
            raise RevisionConflict(stored_claim.revision)

        stored_session = self._get(
            'session',
            session.session_id,
            SessionRecord,
            customer_id=claim.customer_id,
            session=mongo_session,
        )

        valid = (
            claim.revision == expected_revision + 1
            and stored_claim.active_session_id == session.session_id
            and claim.active_session_id is None
            and stored_session is not None
            and stored_session.claim_id == claim.claim_id
            and stored_session.customer_id == claim.customer_id
            and stored_session.status is SessionStatus.ACTIVE
            and session.claim_id == claim.claim_id
            and session.customer_id == claim.customer_id
            and session.status is SessionStatus.PAUSED
            and session.context_revision == expected_revision
            and session.recovery_context is not None
            and follow_up.claim_id == claim.claim_id
            and follow_up.source_session_id == session.session_id
            and follow_up.status in {FollowUpStatus.PENDING, FollowUpStatus.BLOCKED}
            and follow_up.attempt_count == 0
            and idempotency.actor_id == claim.customer_id
            and idempotency.claim_id == claim.claim_id
            and idempotency.session_id == session.session_id
            and idempotency.follow_up_id == follow_up.follow_up_id
        )
        if not valid:
            raise KeyError(claim.claim_id)

        self._reject_existing_idempotency(
            idempotency,
            mongo_session=mongo_session,
        )

        existing_follow_up = self._collection.find_one(
            {
                'record_type': 'follow_up',
                'claim_id': claim.claim_id,
                'purpose': follow_up.purpose,
                'status': {'$in': [FollowUpStatus.PENDING.value, FollowUpStatus.BLOCKED.value]},
            },
            session=mongo_session,
        )
        if existing_follow_up is not None:
            raise IdempotencyConflict(follow_up.purpose)

        if (
            self._replace_claim_revision(
                claim,
                expected_revision,
                mongo_session=mongo_session,
            )
            == 0
        ):
            self._raise_revision_conflict(
                claim.claim_id,
                mongo_session=mongo_session,
            )

        self._put(
            'session',
            session.session_id,
            session,
            customer_id=claim.customer_id,
            claim_id=claim.claim_id,
            session=mongo_session,
        )
        self._put(
            'follow_up',
            follow_up.follow_up_id,
            follow_up,
            customer_id=claim.customer_id,
            claim_id=claim.claim_id,
            session=mongo_session,
        )
        self._save_idempotency(idempotency, mongo_session)
        self._append_realtime_mutation(
            RealtimeMutation.SESSION_PAUSED,
            claim,
            mongo_session=mongo_session,
            operation_correlation=idempotency.key,
        )

    def save_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
        resolved_follow_up: FollowUpRecord | None = None,
        reconciled_follow_up_operation: FollowUpOperation | None = None,
        replaced_active_session: SessionRecord | None = None,
        audit_event: AuditEventEnvelope | None = None,
    ) -> None:
        self._validate_session_mutation(
            claim,
            expected_revision,
            session,
            idempotency,
            replaced_active_session,
        )
        self._validate_branch_evaluation(claim, branch_evaluation)
        self._atomic(
            lambda mongo_session: self._save_session_mutation(
                claim,
                expected_revision,
                session,
                idempotency,
                branch_evaluation,
                resolved_follow_up,
                reconciled_follow_up_operation,
                replaced_active_session,
                audit_event,
                mongo_session,
            )
        )

    def _validate_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        replaced_active_session: SessionRecord | None,
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
            or (
                replaced_active_session is not None
                and (
                    replaced_active_session.claim_id != claim.claim_id
                    or replaced_active_session.customer_id != claim.customer_id
                    or replaced_active_session.status is not SessionStatus.CLOSED
                    or replaced_active_session.closed_at is None
                )
            )
        ):
            raise KeyError(claim.claim_id)

    def _save_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None,
        resolved_follow_up: FollowUpRecord | None,
        reconciled_follow_up_operation: FollowUpOperation | None,
        replaced_active_session: SessionRecord | None,
        audit_event: AuditEventEnvelope | None,
        mongo_session: Any,
    ) -> None:
        stored_claim_document = self._collection.find_one(
            {
                '_id': self._record_id('claim', claim.claim_id),
                'record_type': 'claim',
                'customer_id': claim.customer_id,
                'revision': expected_revision,
            },
            projection={'revision': 1, 'active_session_id': 1},
            session=mongo_session,
        )
        if stored_claim_document is None:
            self._raise_revision_conflict(claim.claim_id, mongo_session=mongo_session)

        self._reject_session_identity_conflict(
            session,
            mongo_session=mongo_session,
        )

        stored_active_session_id = stored_claim_document.get('active_session_id')
        active_session_documents = list(
            self._collection.find(
                {
                    'record_type': 'session',
                    'claim_id': claim.claim_id,
                    'customer_id': claim.customer_id,
                    'status': SessionStatus.ACTIVE.value,
                },
                projection={'session_id': 1},
                session=mongo_session,
            )
        )
        active_session_ids = {str(document['session_id']) for document in active_session_documents}

        if replaced_active_session is None:
            if stored_active_session_id is not None or active_session_ids:
                raise KeyError(claim.claim_id)
        else:
            if (
                stored_active_session_id != replaced_active_session.session_id
                or active_session_ids != {replaced_active_session.session_id}
            ):
                raise KeyError(claim.claim_id)
            stored_replaced_session = self._get(
                'session',
                replaced_active_session.session_id,
                SessionRecord,
                customer_id=claim.customer_id,
                session=mongo_session,
            )
            if (
                stored_replaced_session is None
                or stored_replaced_session.claim_id != claim.claim_id
                or stored_replaced_session.status is not SessionStatus.ACTIVE
            ):
                raise KeyError(claim.claim_id)
            expected_replaced_session = stored_replaced_session.model_copy(
                update={
                    'status': SessionStatus.CLOSED,
                    'closed_at': replaced_active_session.closed_at,
                }
            )
            if replaced_active_session != expected_replaced_session:
                raise KeyError(claim.claim_id)

        open_follow_up_document = self._collection.find_one(
            {
                'record_type': 'follow_up',
                'claim_id': claim.claim_id,
                'purpose': 'resume_incomplete_claim',
                'status': {'$in': [FollowUpStatus.PENDING.value, FollowUpStatus.BLOCKED.value]},
            },
            session=mongo_session,
        )
        open_follow_up = self._model_from_document(open_follow_up_document, FollowUpRecord)
        if open_follow_up is not None and resolved_follow_up is None:
            raise KeyError(claim.claim_id)
        if resolved_follow_up is not None:
            if (
                open_follow_up is None
                or open_follow_up.follow_up_id != resolved_follow_up.follow_up_id
                or resolved_follow_up.status is not FollowUpStatus.RESOLVED
                or resolved_follow_up.outcome != 'claimant_resumed'
                or resolved_follow_up.reason_code is not FollowUpReasonCode.CLAIMANT_RESUMED
                or resolved_follow_up.updated_at < open_follow_up.updated_at
            ):
                raise KeyError(claim.claim_id)
            expected_follow_up = open_follow_up.model_copy(
                update={
                    'status': FollowUpStatus.RESOLVED,
                    'outcome': resolved_follow_up.outcome,
                    'blocked_reason': None,
                    'resolution_code': resolved_follow_up.resolution_code,
                    'active_operation_id': None,
                    'due_at': None,
                    'updated_at': resolved_follow_up.updated_at,
                }
            )
            if resolved_follow_up != expected_follow_up:
                raise KeyError(claim.claim_id)

            if (
                open_follow_up.deadline_at is not None
                and resolved_follow_up.updated_at >= open_follow_up.deadline_at
            ):
                raise RecoveryDeadlineConflict(open_follow_up.follow_up_id)

            open_operation_document = self._collection.find_one(
                {
                    'record_type': 'follow_up_operation',
                    'claim_id': claim.claim_id,
                    'follow_up_id': open_follow_up.follow_up_id,
                    'customer_id': claim.customer_id,
                    'status': {
                        '$in': [
                            FollowUpOperationStatus.SCHEDULED.value,
                            FollowUpOperationStatus.COMMITTED.value,
                        ]
                    },
                },
                session=mongo_session,
            )
            open_operation = self._model_from_document(
                open_operation_document,
                FollowUpOperation,
            )

            if reconciled_follow_up_operation is None:
                if open_operation is not None:
                    raise KeyError(claim.claim_id)
            else:
                if (
                    open_operation is None
                    or open_operation.operation_id != reconciled_follow_up_operation.operation_id
                ):
                    raise KeyError(claim.claim_id)

                try:
                    assert_follow_up_operation_transition(
                        open_operation,
                        reconciled_follow_up_operation,
                    )
                except ValueError as error:
                    raise KeyError(claim.claim_id) from error

        elif reconciled_follow_up_operation is not None:
            raise KeyError(claim.claim_id)

        if resolved_follow_up is not None:
            if audit_event is None:
                raise KeyError(claim.claim_id)
            prepared_audit = self._prepare_audit_events(
                claim,
                (audit_event,),
                mongo_session=mongo_session,
            )
        else:
            if audit_event is not None:
                raise KeyError(claim.claim_id)
            prepared_audit = ()

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
        if replaced_active_session is not None:
            self._put(
                'session',
                replaced_active_session.session_id,
                replaced_active_session,
                customer_id=replaced_active_session.customer_id,
                claim_id=replaced_active_session.claim_id,
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
        if resolved_follow_up is not None:
            self._put(
                'follow_up',
                resolved_follow_up.follow_up_id,
                resolved_follow_up,
                customer_id=claim.customer_id,
                claim_id=claim.claim_id,
                session=mongo_session,
            )
        if reconciled_follow_up_operation is not None:
            self._put(
                'follow_up_operation',
                reconciled_follow_up_operation.operation_id,
                reconciled_follow_up_operation,
                customer_id=claim.customer_id,
                claim_id=claim.claim_id,
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

        for event in prepared_audit:
            self._insert_audit_event(
                event,
                mongo_session=mongo_session,
            )

        self._append_realtime_mutation(
            RealtimeMutation.SESSION_CHANGED,
            claim,
            mongo_session=mongo_session,
            operation_correlation=idempotency.key,
        )

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

    def get_staff_agent_execution(
        self, execution_id: str, staff_id: str
    ) -> StaffAgentExecutionRecord | None:
        execution = self._get(
            'staff_agent_execution',
            execution_id,
            StaffAgentExecutionRecord,
        )
        if execution is None or execution.staff_id != staff_id:
            return None
        return execution

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
        *,
        session: Any = None,
    ) -> list[ModelT]:
        query = {'record_type': kind, **filters}
        descending = sort_field.startswith('-')
        field = sort_field.removeprefix('-')
        records: list[ModelT] = []
        direction = -1 if descending else 1
        cursor = self._collection.find(query, session=session).sort(
            [(field, direction), ('_id', direction)]
        )
        for document in cursor:
            record = self._model_from_document(document, model_type)
            if record is not None:
                records.append(record)
        return records

    def _atomic(self, operation: Callable[[Any], ResultT]) -> ResultT:
        """Run a multi-record write only where MongoDB transactions are available."""
        with self._client.start_session() as session:
            return session.with_transaction(operation)

    # Remaining PersistenceRepository operations are deliberately explicit until
    # their mapping and transaction tests are added in follow-up commits.
    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f'MongoDB adapter capability is not implemented: {name}')
