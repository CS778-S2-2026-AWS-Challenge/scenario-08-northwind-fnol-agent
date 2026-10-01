from collections.abc import Iterator, Sequence
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Condition, Event, RLock
from typing import Any

from backend.domain.account_data import (
    IdentityDocumentRecord,
    PaymentDestinationRecord,
    PolicyNumberRecord,
)
from backend.domain.agent_context_runtime import VerifiedConversationSummary
from backend.domain.assets import AssetRecord, ClaimAssetSnapshot
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
    TerminalDispositionReasonCode,
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
    ObjectDeletionOutcome,
    ResourceAccessClosed,
    RetentionClassification,
    RetentionCleanupTarget,
    RetentionDeleteAuthorization,
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
    retention_delete_authorization_id,
    retention_next_attempt,
    retention_record_identity,
    retention_step_evidence_id,
    retention_target_statuses,
    retention_tombstone_authority,
    retention_tombstone_id,
    validate_retention_eligibility_source,
    validate_retention_hold_transition,
    validate_retention_operation_transition,
    validate_retention_source_authority,
)
from backend.domain.retrieval import RetrievalRecord, ReviewSignalRecord
from backend.domain.runtime import (
    RuntimeTurnRecords,
    RuntimeWorkItemRecord,
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
    StaffSessionSearchCandidate,
    build_staff_claim_search_candidate,
    staff_claim_search_matches,
    staff_session_search_matches,
)
from backend.domain.staff_identity import StaffPresenceRecord
from backend.repositories.account_data import (
    AccountCursorKey,
    AccountRecord,
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
    PersistenceRepository,
    RecoveryDeadlineConflict,
    RepositorySearchLimitExceeded,
    RevisionConflict,
    ValidationSeedGraph,
    validate_handoff_mutation_audit,
    validate_staff_agent_execution,
    validate_staff_agent_execution_source,
    validate_validation_seed_session,
)


class FixtureRepository(PersistenceRepository):
    """In-memory repository used by the prototype and replaceable contract tests."""

    def __init__(self) -> None:
        self._validation_seed_lock = RLock()
        self._claim_mutation_lock = RLock()
        self._realtime_condition = Condition(self._claim_mutation_lock)
        self._claims: dict[str, WorkingClaim] = {}
        self._policies: dict[str, PolicyNumberRecord] = {}
        self._payment_destinations: dict[str, PaymentDestinationRecord] = {}
        self._identity_documents: dict[str, IdentityDocumentRecord] = {}
        self._assets: dict[str, AssetRecord] = {}
        self._claim_asset_snapshots: dict[str, ClaimAssetSnapshot] = {}
        self._audit_events: dict[str, AuditEventEnvelope] = {}
        self._sessions: dict[str, SessionRecord] = {}
        self._session_ids_by_claim: dict[tuple[str, str], list[str]] = {}
        self._message_ids_by_session: dict[str, list[str]] = {}
        self._follow_ups: dict[str, FollowUpRecord] = {}
        self._follow_up_operations: dict[str, FollowUpOperation] = {}
        self._messages: dict[str, MessageRecord] = {}
        self._conversation_summaries: dict[str, VerifiedConversationSummary] = {}
        self._runtime_traces: dict[str, RuntimeTraceRecord] = {}
        self._runtime_turns: dict[str, RuntimeTurnRecords] = {}
        self._standalone_runtime_work_items: dict[str, RuntimeWorkItemRecord] = {}
        self._staff_agent_sessions: dict[str, StaffAgentSession] = {}
        self._staff_agent_messages: dict[str, StaffAgentMessage] = {}
        self._staff_agent_executions: dict[str, StaffAgentExecutionRecord] = {}
        self._decisions: dict[str, AgentDecisionRecord] = {}
        self._branch_evaluations: dict[str, BranchEvaluationRecord] = {}
        self._claim_creation_operations: dict[str, ClaimCreationOperationRecord] = {}
        self._assessor_routing_operations: dict[str, AssessorRoutingOperation] = {}
        self._evidence: dict[str, EvidenceRecord] = {}
        self._evidence_claim_links: dict[tuple[str, str], EvidenceClaimLink] = {}
        self._motor_other_drivers: dict[str, MotorOtherDriverRecord] = {}
        self._contents_item_evidence_associations: dict[str, ContentsItemEvidenceAssociation] = {}
        self._external_tasks: dict[str, ExternalTaskRecord] = {}
        self._external_task_attempts: dict[str, ExternalTaskAttempt] = {}
        self._external_task_requests: dict[str, ExternalTaskRequest] = {}
        self._external_task_evidence_links: dict[tuple[str, str], ExternalTaskEvidenceLink] = {}
        self._external_task_results: dict[str, ExternalTaskResult] = {}
        self._retrievals: dict[str, RetrievalRecord] = {}
        self._review_signals: dict[str, ReviewSignalRecord] = {}
        self._staff_actions: dict[str, StaffActionRecord] = {}
        self._customer_updates: dict[str, CustomerUpdateRecord] = {}
        self._signal_decisions: dict[str, SignalDecisionRecord] = {}
        self._collaboration_requests: dict[str, ClaimCollaborationRequest] = {}
        self._claim_coworkers: dict[str, ClaimCoworkerRecord] = {}
        self._handoffs: dict[str, HandoffRecord] = {}
        self._idempotency: dict[tuple[str, str, str], IdempotencyRecord] = {}
        self._staff_presence: dict[str, StaffPresenceRecord] = {}
        self._realtime_events: dict[str, RealtimeEvent] = {}
        self._realtime_sequence = 0
        now = datetime.now(UTC)
        self._staff_presence['stf_demo'] = StaffPresenceRecord(
            staff_id='stf_demo',
            online=True,
            available=True,
            last_seen_at=now,
            expires_at=now + timedelta(minutes=5),
            updated_at=now,
        )

        self._retention_operations: dict[str, RetentionOperation] = {}
        self._retention_tombstones: dict[str, RetentionRecordTombstone] = {}
        self._retention_operation_by_claim: dict[str, str] = {}
        self._retention_holds: dict[str, RetentionHoldRecord] = {}

    def get_retention_operation(
        self,
        operation_id: str,
    ) -> RetentionOperation | None:
        with self._claim_mutation_lock:
            operation = self._retention_operations.get(operation_id)
            return deepcopy(operation)

    def get_retention_operation_for_claim(
        self,
        claim_id: str,
    ) -> RetentionOperation | None:
        with self._claim_mutation_lock:
            operation_id = self._retention_operation_by_claim.get(claim_id)

            if operation_id is None:
                return None

            return deepcopy(self._retention_operations.get(operation_id))

    def list_pending_retention_operations(
        self,
        *,
        limit: int,
    ) -> list[RetentionOperation]:
        if not 1 <= limit <= 100:
            raise ValueError('Retention discovery limit must be between 1 and 100.')
        with self._claim_mutation_lock:
            operations = sorted(
                (
                    operation
                    for operation in self._retention_operations.values()
                    if operation.status is not RetentionOperationStatus.COMPLETED
                    and (
                        operation.status is not RetentionOperationStatus.HELD
                        or operation.active_delete_authorization_id is not None
                    )
                ),
                key=lambda operation: (
                    operation.updated_at,
                    operation.operation_id,
                ),
            )
            return deepcopy(operations[:limit])

    def list_retention_handoff_candidates(
        self,
        *,
        limit: int,
    ) -> list[str]:
        if not 1 <= limit <= 100:
            raise ValueError('Retention handoff discovery limit must be between 1 and 100.')
        with self._claim_mutation_lock:
            reserved = {operation.claim_id for operation in self._retention_operations.values()}
            expired = sorted(
                (
                    (claim.terminal_disposition.recorded_at, claim.claim_id)
                    for claim in self._claims.values()
                    if claim.terminal_disposition is not None
                    and claim.terminal_disposition.reason_code
                    is TerminalDispositionReasonCode.RECOVERY_EXPIRED
                    and claim.claim_id not in reserved
                ),
            )
            return [claim_id for _, claim_id in expired[:limit]]

    def reserve_eligible_retention_operation(
        self,
        operation: RetentionOperation,
    ) -> RetentionOperation:
        """Atomically validate P17 retention authority and close claimant access."""

        with self._claim_mutation_lock:
            existing_id = self._retention_operation_by_claim.get(operation.claim_id)

            if existing_id is not None:
                existing = self._retention_operations.get(existing_id)

                if existing is None:
                    raise KeyError(existing_id)

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

                return deepcopy(existing)

            claim = self._claims.get(operation.claim_id)

            if claim is None:
                raise RetentionEligibilityRejected(
                    RetentionEligibilityReason.CLAIM_NOT_FOUND,
                    operation.claim_id,
                )

            validate_retention_eligibility_source(
                claim,
                operation,
            )

            recovery_open = any(
                item.claim_id == operation.claim_id
                and item.status.value
                in {
                    FollowUpOperationStatus.RESERVED.value,
                    'committed',
                }
                for item in self._follow_up_operations.values()
            )

            if recovery_open:
                raise RetentionEligibilityRejected(
                    RetentionEligibilityReason.RECOVERY_OPERATION_OPEN,
                    operation.claim_id,
                )

            external_unknown = any(
                item.claim_id == operation.claim_id and item.status.value == 'unknown_outcome'
                for item in self._external_tasks.values()
            )

            if external_unknown:
                raise RetentionEligibilityRejected(
                    RetentionEligibilityReason.EXTERNAL_OUTCOME_UNKNOWN,
                    operation.claim_id,
                )

            runtime_items = [
                item for turn in self._runtime_turns.values() for item in turn.work_items
            ]
            runtime_items.extend(self._standalone_runtime_work_items.values())

            staff_work_open = any(
                item.claim_id == operation.claim_id
                and item.status
                in {
                    'open',
                    'in_progress',
                }
                and item.owner
                in {
                    'staff',
                    'system',
                    'external',
                }
                for item in runtime_items
            )

            handoff_open = any(
                item.claim_id == operation.claim_id
                and item.status.value
                in {
                    'requested',
                    'queued',
                    'accepted',
                    'in_progress',
                }
                for item in self._handoffs.values()
            )

            if staff_work_open or handoff_open:
                raise RetentionEligibilityRejected(
                    RetentionEligibilityReason.STAFF_RESPONSIBILITY_OPEN,
                    operation.claim_id,
                )

            active_hold_ids = sorted(
                hold.hold_id
                for hold in self._retention_holds.values()
                if (hold.claim_id == operation.claim_id and hold.active)
            )

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

            self._retention_operations[candidate.operation_id] = deepcopy(candidate)

            self._retention_operation_by_claim[candidate.claim_id] = candidate.operation_id

            for lookup, record in list(self._idempotency.items()):
                if (
                    record.claim_id == candidate.claim_id
                    and record.actor_id == claim.customer_id
                    and not record.retired
                ):
                    self._idempotency[lookup] = replace(
                        record,
                        retired=True,
                    )

            return deepcopy(candidate)

    def reserve_retention_operation(
        self,
        operation: RetentionOperation,
    ) -> bool:
        with self._claim_mutation_lock:
            if operation.revision != 1 or operation.status is not RetentionOperationStatus.RESERVED:
                raise ValueError('Initial retention reservation must be revision 1 and reserved.')

            existing_id = self._retention_operation_by_claim.get(operation.claim_id)

            if existing_id is not None:
                existing = self._retention_operations[existing_id]

                if existing.operation_id == operation.operation_id and existing == operation:
                    return False

                raise IdempotencyConflict(operation.operation_id)

            self._retention_operations[operation.operation_id] = deepcopy(operation)

            self._retention_operation_by_claim[operation.claim_id] = operation.operation_id

            claim = self._claims.get(operation.claim_id)

            for lookup, record in list(self._idempotency.items()):
                if (
                    record.claim_id == operation.claim_id
                    and claim is not None
                    and record.actor_id == claim.customer_id
                    and not record.retired
                ):
                    self._idempotency[lookup] = replace(
                        record,
                        retired=True,
                    )

            return True

    def freeze_retention_targets(
        self,
        operation_id: str,
        expected_revision: int,
        *,
        frozen_at: datetime,
    ) -> RetentionOperation:
        """Freeze one exact Claim-scoped cleanup inventory under the mutation lock."""

        with self._claim_mutation_lock:
            operation = self._retention_operations.get(operation_id)

            if operation is None:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.OPERATION_NOT_FOUND,
                    operation_id,
                )

            if operation.revision != expected_revision:
                raise RevisionConflict(operation.revision)

            if operation.targets_frozen_at is not None:
                return deepcopy(operation)

            claim = self._claims.get(operation.claim_id)

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

            active_holds = [
                hold
                for hold in self._retention_holds.values()
                if (hold.claim_id == operation.claim_id and hold.active)
            ]

            if active_holds:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.ACTIVE_HOLD,
                    operation.claim_id,
                )

            recovery_open = any(
                item.claim_id == operation.claim_id
                and item.status.value
                in {
                    FollowUpOperationStatus.RESERVED.value,
                    'committed',
                }
                for item in self._follow_up_operations.values()
            )

            if recovery_open:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.RECOVERY_OPERATION_OPEN,
                    operation.claim_id,
                )

            external_unknown = any(
                item.claim_id == operation.claim_id and item.status.value == 'unknown_outcome'
                for item in self._external_tasks.values()
            )

            if external_unknown:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.EXTERNAL_OUTCOME_UNKNOWN,
                    operation.claim_id,
                )

            runtime_items = [
                item for turn in self._runtime_turns.values() for item in turn.work_items
            ]
            runtime_items.extend(self._standalone_runtime_work_items.values())

            open_responsibility = any(
                item.claim_id == operation.claim_id
                and item.status in {'open', 'in_progress'}
                and item.owner in {'staff', 'system', 'external'}
                for item in runtime_items
            )

            open_handoff = any(
                item.claim_id == operation.claim_id
                and item.status.value
                in {
                    'requested',
                    'queued',
                    'accepted',
                    'in_progress',
                }
                for item in self._handoffs.values()
            )

            if open_responsibility or open_handoff:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.STAFF_RESPONSIBILITY_OPEN,
                    operation.claim_id,
                )

            targets: dict[str, RetentionCleanupTarget] = {}

            def add_record(
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

            add_record(
                'claim',
                claim.claim_id,
                source_refs=(f'claim:{claim.claim_id}',),
            )

            for session in self._sessions.values():
                if session.claim_id == operation.claim_id:
                    add_record(
                        'session',
                        session.session_id,
                        source_refs=(f'session:{session.session_id}',),
                    )

            for message in self._messages.values():
                if message.claim_id == operation.claim_id:
                    add_record(
                        'message',
                        message.message_id,
                        source_refs=(f'message:{message.message_id}',),
                    )

            for follow_up in self._follow_ups.values():
                if follow_up.claim_id == operation.claim_id:
                    add_record(
                        'follow_up',
                        follow_up.follow_up_id,
                        source_refs=(f'follow-up:{follow_up.follow_up_id}',),
                    )

            for follow_up_operation in self._follow_up_operations.values():
                if follow_up_operation.claim_id == operation.claim_id:
                    add_record(
                        'follow_up_operation',
                        follow_up_operation.operation_id,
                        source_refs=(f'follow-up-operation:{follow_up_operation.operation_id}',),
                    )

            for work_item in runtime_items:
                if work_item.claim_id == operation.claim_id:
                    add_record(
                        'runtime_work_item',
                        work_item.work_item_id,
                        source_refs=(f'work-item:{work_item.work_item_id}',),
                    )

            for handoff in self._handoffs.values():
                if handoff.claim_id == operation.claim_id:
                    add_record(
                        'handoff',
                        handoff.handoff_id,
                        source_refs=(f'handoff:{handoff.handoff_id}',),
                    )

            for evidence in self._evidence.values():
                if evidence.claim_id != operation.claim_id:
                    continue

                add_record(
                    'evidence',
                    evidence.evidence_id,
                    source_refs=(f'evidence:{evidence.evidence_id}',),
                )

                storage_key = evidence.provenance.get('storage_key')

                if storage_key is not None:
                    if not isinstance(storage_key, str) or not storage_key.strip():
                        raise RetentionTargetFreezeRejected(
                            RetentionTargetFreezeReason.INVALID_STORAGE_REFERENCE,
                            operation.claim_id,
                        )

                    object_target = build_retention_cleanup_target(
                        operation=operation,
                        record_type='EvidenceObjectBytes',
                        record_id=evidence.evidence_id,
                        classification=RetentionClassification.DELETE,
                        kind=RetentionTargetKind.OBJECT_BYTES,
                        storage_key=storage_key,
                        source_refs=(f'evidence:{evidence.evidence_id}',),
                    )

                    targets[object_target.target_id] = object_target

            for evidence_link in self._evidence_claim_links.values():
                if (
                    evidence_link.source_claim_id == operation.claim_id
                    or evidence_link.target_claim_id == operation.claim_id
                ):
                    add_record(
                        'evidence_claim_link',
                        evidence_link.link_id,
                        source_refs=(
                            f'evidence:{evidence_link.evidence_id}',
                            f'claim:{evidence_link.source_claim_id}',
                            f'claim:{evidence_link.target_claim_id}',
                        ),
                    )

            for task in self._external_tasks.values():
                if task.claim_id == operation.claim_id:
                    add_record(
                        'external_task',
                        task.task_id,
                        source_refs=(f'external-task:{task.task_id}',),
                    )

            for request in self._external_task_requests.values():
                if request.claim_id == operation.claim_id:
                    add_record(
                        'external_task_request',
                        request.request_id,
                        source_refs=(f'external-request:{request.request_id}',),
                    )

            for attempt in self._external_task_attempts.values():
                if attempt.claim_id == operation.claim_id:
                    add_record(
                        'external_task_attempt',
                        attempt.attempt_id,
                        source_refs=(f'external-attempt:{attempt.attempt_id}',),
                    )

            for result in self._external_task_results.values():
                if result.claim_id == operation.claim_id:
                    add_record(
                        'external_task_result',
                        result.result_id,
                        source_refs=(f'external-result:{result.result_id}',),
                    )

            for external_link in self._external_task_evidence_links.values():
                if external_link.claim_id == operation.claim_id:
                    link_id = retention_record_identity(
                        'external_link',
                        external_link.task_id,
                        external_link.evidence_id,
                    )

                    add_record(
                        'external_task_evidence_link',
                        link_id,
                        source_refs=(
                            f'external-task:{external_link.task_id}',
                            f'evidence:{external_link.evidence_id}',
                        ),
                    )

            for record in self._idempotency.values():
                if record.claim_id != operation.claim_id or record.actor_id != claim.customer_id:
                    continue

                record_id = retention_record_identity(
                    'idempotency',
                    record.actor_id,
                    record.route,
                    record.key,
                )

                add_record(
                    'idempotency',
                    record_id,
                    source_refs=(f'idempotency:{record_id}',),
                )

            for event in self._audit_events.values():
                if event.subject.claim_id == operation.claim_id:
                    add_record(
                        'audit_event',
                        event.event_id,
                        source_refs=(f'audit:{event.event_id}',),
                    )

            for hold in self._retention_holds.values():
                if hold.claim_id == operation.claim_id:
                    add_record(
                        'retention_hold',
                        hold.hold_id,
                        source_refs=(f'retention-hold:{hold.hold_id}',),
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

            self._retention_operations[operation.operation_id] = deepcopy(candidate)

            return deepcopy(candidate)

    def get_retention_tombstone(
        self,
        target_id: str,
    ) -> RetentionRecordTombstone | None:
        with self._claim_mutation_lock:
            return deepcopy(self._retention_tombstones.get(target_id))

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
        with self._claim_mutation_lock:
            operation = self._retention_operations.get(operation_id)

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
                return deepcopy(operation)

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

            self._retention_operations[operation.operation_id] = deepcopy(candidate)

            return deepcopy(candidate)

    def authorize_retention_object_target(
        self,
        operation_id: str,
        target_id: str,
        expected_revision: int,
        *,
        now: datetime,
    ) -> tuple[RetentionOperation, RetentionDeleteAuthorization]:
        with self._claim_mutation_lock:
            operation = self._retention_operations.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)

            if operation.active_delete_authorization_id is not None:
                authorization = next(
                    item
                    for item in operation.delete_authorizations
                    if item.authorization_id == operation.active_delete_authorization_id
                )
                if authorization.target_id != target_id:
                    raise IdempotencyConflict(operation.active_delete_authorization_id)
                return deepcopy(operation), deepcopy(authorization)

            if operation.revision != expected_revision:
                raise RevisionConflict(operation.revision)
            if operation.status is RetentionOperationStatus.COMPLETED:
                raise ValueError('Completed retention cannot authorize deletion.')

            active_holds = [
                hold
                for hold in self._retention_holds.values()
                if hold.claim_id == operation.claim_id and hold.active
            ]
            if active_holds:
                raise RetentionTargetFreezeRejected(
                    RetentionTargetFreezeReason.ACTIVE_HOLD,
                    operation.claim_id,
                )

            statuses = retention_target_statuses(operation.targets, operation.step_evidence)
            target = next(
                (item for item in operation.targets if item.target_id == target_id),
                None,
            )
            if target is None:
                raise KeyError(target_id)
            if target.kind is not RetentionTargetKind.OBJECT_BYTES:
                raise ValueError(
                    'Only object-byte targets may be authorized for provider deletion.'
                )
            if statuses[target_id] is RetentionStepStatus.SATISFIED:
                raise ValueError('Satisfied retention targets cannot be re-authorized.')

            attempt = retention_next_attempt(operation, target_id)
            authorization = RetentionDeleteAuthorization(
                authorization_id=retention_delete_authorization_id(
                    operation.operation_id,
                    target_id,
                    attempt,
                ),
                target_id=target_id,
                attempt=attempt,
                authorized_at=now,
            )
            payload = operation.model_dump(mode='python')
            payload.update(
                {
                    'revision': operation.revision + 1,
                    'delete_authorizations': [*operation.delete_authorizations, authorization],
                    'active_delete_authorization_id': authorization.authorization_id,
                    'updated_at': now,
                    'completed_at': None,
                }
            )
            candidate = RetentionOperation.model_validate(payload)
            validate_retention_operation_transition(operation, candidate)
            self._retention_operations[operation_id] = deepcopy(candidate)
            return deepcopy(candidate), deepcopy(authorization)

    def record_retention_object_result(
        self,
        operation_id: str,
        authorization_id: str,
        *,
        outcome: ObjectDeletionOutcome,
        now: datetime,
    ) -> RetentionOperation:
        with self._claim_mutation_lock:
            operation = self._retention_operations.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)

            existing = next(
                (
                    evidence
                    for evidence in operation.step_evidence
                    if evidence.authorization_id == authorization_id
                ),
                None,
            )
            if existing is not None:
                return deepcopy(operation)

            authorization = next(
                (
                    item
                    for item in operation.delete_authorizations
                    if item.authorization_id == authorization_id
                ),
                None,
            )
            if authorization is None:
                raise KeyError(authorization_id)
            if operation.active_delete_authorization_id != authorization_id:
                raise IdempotencyConflict(authorization_id)

            target = next(
                item for item in operation.targets if item.target_id == authorization.target_id
            )
            status = {
                ObjectDeletionOutcome.DELETED: RetentionStepStatus.SATISFIED,
                ObjectDeletionOutcome.ALREADY_ABSENT: RetentionStepStatus.SATISFIED,
                ObjectDeletionOutcome.FAILED: RetentionStepStatus.FAILED,
                ObjectDeletionOutcome.UNKNOWN: RetentionStepStatus.UNKNOWN,
            }[outcome]
            diagnostic_code = (
                None
                if status is RetentionStepStatus.SATISFIED
                else (
                    'OBJECT_DELETE_FAILED'
                    if status is RetentionStepStatus.FAILED
                    else 'OBJECT_DELETE_UNKNOWN'
                )
            )
            evidence = RetentionStepEvidence(
                evidence_id=retention_step_evidence_id(
                    operation.operation_id,
                    target.target_id,
                    authorization.attempt,
                ),
                target_id=target.target_id,
                attempt=authorization.attempt,
                status=status,
                object_outcome=outcome,
                authorization_id=authorization.authorization_id,
                diagnostic_code=diagnostic_code,
                source_refs=list(target.source_refs),
                recorded_at=now,
            )
            candidate = retention_candidate_after_step(operation, evidence, now=now)
            active_holds = sorted(
                hold.hold_id
                for hold in self._retention_holds.values()
                if hold.claim_id == operation.claim_id and hold.active
            )
            payload = candidate.model_dump(mode='python')
            payload['active_delete_authorization_id'] = None
            if active_holds:
                payload.update(
                    {
                        'status': RetentionOperationStatus.HELD,
                        'hold_refs': sorted(set(candidate.hold_refs).union(active_holds)),
                        'completed_at': None,
                    }
                )
            candidate = RetentionOperation.model_validate(payload)
            validate_retention_operation_transition(operation, candidate)
            self._retention_operations[operation_id] = deepcopy(candidate)
            return deepcopy(candidate)

    def apply_retention_record_target(
        self,
        operation_id: str,
        target_id: str,
        expected_revision: int,
        *,
        now: datetime,
    ) -> RetentionOperation:
        """Apply one frozen database cleanup step atomically under the fixture lock."""

        with self._claim_mutation_lock:
            operation = self._retention_operations.get(operation_id)

            if operation is None:
                raise KeyError(operation_id)

            if operation.revision != expected_revision:
                raise RevisionConflict(operation.revision)

            if operation.status is RetentionOperationStatus.COMPLETED:
                return deepcopy(operation)

            active_holds = [
                hold
                for hold in self._retention_holds.values()
                if (hold.claim_id == operation.claim_id and hold.active)
            ]

            if active_holds:
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
                return deepcopy(operation)

            object_incomplete = any(
                item.kind is RetentionTargetKind.OBJECT_BYTES
                and statuses[item.target_id] is not RetentionStepStatus.SATISFIED
                for item in operation.targets
            )

            if object_incomplete:
                raise ValueError(
                    'Database cleanup cannot begin before every object target is satisfied.'
                )

            # Recheck the blockers that must never be erased by retention.
            recovery_open = any(
                item.claim_id == operation.claim_id
                and item.status.value
                in {
                    FollowUpOperationStatus.RESERVED.value,
                    'committed',
                }
                for item in self._follow_up_operations.values()
            )

            external_unknown = any(
                item.claim_id == operation.claim_id and item.status.value == 'unknown_outcome'
                for item in self._external_tasks.values()
            )

            runtime_items = [
                work_item for turn in self._runtime_turns.values() for work_item in turn.work_items
            ]
            runtime_items.extend(self._standalone_runtime_work_items.values())

            staff_open = any(
                work_item.claim_id == operation.claim_id
                and work_item.status in {'open', 'in_progress'}
                and work_item.owner in {'staff', 'system', 'external'}
                for work_item in runtime_items
            )

            handoff_open = any(
                handoff.claim_id == operation.claim_id
                and handoff.status.value
                in {
                    'requested',
                    'queued',
                    'accepted',
                    'in_progress',
                }
                for handoff in self._handoffs.values()
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

            def regular_record() -> Any | None:
                record_type = target.record_type

                if record_type == 'WorkingClaim':
                    return self._claims.get(target.record_id)

                if record_type == 'SessionRecord':
                    return self._sessions.get(target.record_id)

                if record_type == 'MessageRecord':
                    return self._messages.get(target.record_id)

                if record_type == 'FollowUpRecord':
                    return self._follow_ups.get(target.record_id)

                if record_type == 'FollowUpOperation':
                    return self._follow_up_operations.get(target.record_id)

                if record_type == 'HandoffRecord':
                    return self._handoffs.get(target.record_id)

                if record_type == 'EvidenceRecord':
                    return self._evidence.get(target.record_id)

                if record_type == 'EvidenceClaimLink':
                    return next(
                        (
                            evidence_link
                            for evidence_link in self._evidence_claim_links.values()
                            if evidence_link.link_id == target.record_id
                        ),
                        None,
                    )

                if record_type == 'ExternalTaskRecord':
                    return self._external_tasks.get(target.record_id)

                if record_type == 'ExternalTaskRequest':
                    return self._external_task_requests.get(target.record_id)

                if record_type == 'ExternalTaskAttempt':
                    return self._external_task_attempts.get(target.record_id)

                if record_type == 'ExternalTaskResult':
                    return self._external_task_results.get(target.record_id)

                if record_type == 'AuditEventEnvelope':
                    return self._audit_events.get(target.record_id)

                if record_type == 'RetentionHoldRecord':
                    return self._retention_holds.get(target.record_id)

                if record_type == 'RuntimeWorkItemRecord':
                    direct = self._standalone_runtime_work_items.get(target.record_id)

                    if direct is not None:
                        return direct

                    return next(
                        (
                            work_item
                            for turn in self._runtime_turns.values()
                            for work_item in turn.work_items
                            if work_item.work_item_id == target.record_id
                        ),
                        None,
                    )

                if record_type == 'ExternalTaskEvidenceLink':
                    return next(
                        (
                            link
                            for link in self._external_task_evidence_links.values()
                            if retention_record_identity(
                                'external_link',
                                link.task_id,
                                link.evidence_id,
                            )
                            == target.record_id
                        ),
                        None,
                    )

                return None

            idempotency_match = None

            if target.record_type == 'IdempotencyRecord':
                idempotency_match = next(
                    (
                        (lookup, record)
                        for lookup, record in self._idempotency.items()
                        if (
                            record.claim_id == operation.claim_id
                            and retention_record_identity(
                                'idempotency',
                                record.actor_id,
                                record.route,
                                record.key,
                            )
                            == target.record_id
                        )
                    ),
                    None,
                )

            existing_tombstone = self._retention_tombstones.get(target.target_id)

            source_record = None if target.record_type == 'IdempotencyRecord' else regular_record()

            step_status = RetentionStepStatus.SATISFIED
            diagnostic_code = None
            tombstone = None
            sanitised_idempotency = None

            if target.classification is RetentionClassification.RETAIN:
                if source_record is None:
                    step_status = RetentionStepStatus.UNKNOWN
                    diagnostic_code = 'RETAINED_RECORD_MISSING'

            elif target.record_type == 'IdempotencyRecord':
                if idempotency_match is None:
                    step_status = RetentionStepStatus.UNKNOWN
                    diagnostic_code = 'IDEMPOTENCY_RECORD_MISSING'
                else:
                    _, record = idempotency_match

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
                if source_record is None:
                    step_status = RetentionStepStatus.UNKNOWN
                    diagnostic_code = 'DELETE_SOURCE_RECORD_MISSING'

            elif target.classification in {
                RetentionClassification.ANONYMISE,
                RetentionClassification.TOMBSTONE,
            }:
                if existing_tombstone is not None:
                    if (
                        existing_tombstone.operation_id != operation.operation_id
                        or existing_tombstone.target_id != target.target_id
                    ):
                        raise IdempotencyConflict(target.target_id)
                elif source_record is None:
                    step_status = RetentionStepStatus.UNKNOWN
                    diagnostic_code = 'ANONYMISE_SOURCE_RECORD_MISSING'
                else:
                    payload = source_record.model_dump(mode='json')

                    tombstone = RetentionRecordTombstone(
                        tombstone_id=retention_tombstone_id(target.target_id),
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

            # Every destructive assignment below is non-throwing after all
            # models/transitions have already been validated.
            if step_status is RetentionStepStatus.SATISFIED:
                if sanitised_idempotency is not None:
                    assert idempotency_match is not None
                    lookup, _ = idempotency_match

                    self._idempotency[lookup] = sanitised_idempotency

                elif target.classification is RetentionClassification.DELETE:
                    if target.record_type == 'MessageRecord':
                        message = self._messages.pop(
                            target.record_id,
                            None,
                        )

                        if message is not None:
                            ids = self._message_ids_by_session.get(message.session_id)

                            if ids is not None:
                                ids[:] = [
                                    message_id
                                    for message_id in ids
                                    if message_id != target.record_id
                                ]

                elif tombstone is not None:
                    self._retention_tombstones[target.target_id] = tombstone

                    if target.record_type == 'WorkingClaim':
                        self._claims.pop(
                            target.record_id,
                            None,
                        )

                    elif target.record_type == 'SessionRecord':
                        session = self._sessions.pop(
                            target.record_id,
                            None,
                        )

                        if session is not None:
                            session_ids = self._session_ids_by_claim.get(
                                (
                                    operation.claim_id,
                                    session.customer_id,
                                )
                            )

                            if session_ids is not None:
                                session_ids[:] = [
                                    session_id
                                    for session_id in session_ids
                                    if session_id != target.record_id
                                ]

                    elif target.record_type == 'FollowUpRecord':
                        self._follow_ups.pop(
                            target.record_id,
                            None,
                        )

                    elif target.record_type == 'HandoffRecord':
                        self._handoffs.pop(
                            target.record_id,
                            None,
                        )

                    elif target.record_type == 'EvidenceRecord':
                        self._evidence.pop(
                            target.record_id,
                            None,
                        )

                    elif target.record_type == 'EvidenceClaimLink':
                        link_key = next(
                            (
                                key
                                for key, evidence_link in self._evidence_claim_links.items()
                                if evidence_link.link_id == target.record_id
                            ),
                            None,
                        )

                        if link_key is not None:
                            self._evidence_claim_links.pop(
                                link_key,
                                None,
                            )

                    elif target.record_type == 'ExternalTaskRecord':
                        self._external_tasks.pop(
                            target.record_id,
                            None,
                        )

                    elif target.record_type == 'ExternalTaskRequest':
                        self._external_task_requests.pop(
                            target.record_id,
                            None,
                        )

                    elif target.record_type == 'ExternalTaskResult':
                        self._external_task_results.pop(
                            target.record_id,
                            None,
                        )

            self._retention_operations[operation.operation_id] = deepcopy(candidate)

            return deepcopy(candidate)

    def save_retention_operation(
        self,
        operation: RetentionOperation,
        expected_revision: int,
    ) -> None:
        with self._claim_mutation_lock:
            current = self._retention_operations.get(operation.operation_id)

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

            self._retention_operations[operation.operation_id] = deepcopy(operation)

    def save_retention_hold(
        self,
        hold: RetentionHoldRecord,
    ) -> None:
        with self._claim_mutation_lock:
            current = self._retention_holds.get(hold.hold_id)

            if current is None:
                if hold.released_at is not None:
                    raise ValueError('A retention hold must be persisted before release.')

                operation = next(
                    (
                        item
                        for item in self._retention_operations.values()
                        if item.claim_id == hold.claim_id
                    ),
                    None,
                )
                if (
                    operation is not None
                    and operation.status is not RetentionOperationStatus.COMPLETED
                ):
                    payload = operation.model_dump(mode='python')
                    payload.update(
                        {
                            'revision': operation.revision + 1,
                            'status': RetentionOperationStatus.HELD,
                            'hold_refs': sorted(set(operation.hold_refs).union({hold.hold_id})),
                            'updated_at': max(operation.updated_at, hold.applied_at),
                            'completed_at': None,
                        }
                    )
                    held = RetentionOperation.model_validate(payload)
                    validate_retention_operation_transition(operation, held)
                    self._retention_operations[operation.operation_id] = deepcopy(held)

                self._retention_holds[hold.hold_id] = deepcopy(hold)
                return

            if current == hold:
                return

            validate_retention_hold_transition(current, hold)
            released_at = hold.released_at
            assert released_at is not None
            self._retention_holds[hold.hold_id] = deepcopy(hold)

            operation = next(
                (
                    item
                    for item in self._retention_operations.values()
                    if item.claim_id == hold.claim_id
                ),
                None,
            )
            if operation is None or operation.status is not RetentionOperationStatus.HELD:
                return

            if any(
                item.claim_id == hold.claim_id and item.active
                for item in self._retention_holds.values()
            ):
                return

            statuses = retention_target_statuses(
                operation.targets,
                operation.step_evidence,
            )
            next_status: RetentionOperationStatus
            completed_at: datetime | None
            if operation.targets and all(
                status is RetentionStepStatus.SATISFIED for status in statuses.values()
            ):
                next_status = RetentionOperationStatus.COMPLETED
                completed_at = released_at
            elif any(
                status
                in {
                    RetentionStepStatus.FAILED,
                    RetentionStepStatus.UNKNOWN,
                }
                for status in statuses.values()
            ):
                next_status = RetentionOperationStatus.RECONCILIATION_REQUIRED
                completed_at = None
            else:
                next_status = RetentionOperationStatus.RESERVED
                completed_at = None

            payload = operation.model_dump(mode='python')
            payload.update(
                {
                    'revision': operation.revision + 1,
                    'status': next_status,
                    'updated_at': max(operation.updated_at, released_at),
                    'completed_at': completed_at,
                }
            )
            resumed = RetentionOperation.model_validate(payload)
            validate_retention_operation_transition(operation, resumed)
            self._retention_operations[operation.operation_id] = deepcopy(resumed)

    def list_retention_holds(
        self,
        claim_id: str,
    ) -> list[RetentionHoldRecord]:
        with self._claim_mutation_lock:
            holds = [hold for hold in self._retention_holds.values() if hold.claim_id == claim_id]

            return deepcopy(
                sorted(
                    holds,
                    key=lambda hold: (
                        hold.applied_at,
                        hold.hold_id,
                    ),
                )
            )

    def connection_status(self) -> str:
        return 'using_fixture'

    def append_realtime_publication(
        self,
        publication: RealtimePublication | AgentTurnProgressPublication,
    ) -> RealtimeEvent:
        with self._realtime_condition:
            prepared = self._prepare_realtime_publication(
                publication,
                MutationOutcome.CHANGED,
            )
            assert prepared is not None
            self._commit_realtime_event(prepared)
            return deepcopy(prepared)

    def _prepare_realtime_publication(
        self,
        publication: RealtimePublication | AgentTurnProgressPublication,
        outcome: MutationOutcome,
    ) -> RealtimeEvent | None:
        """Prepare one repository-owned event while the mutation lock is held."""

        if outcome is not MutationOutcome.CHANGED:
            return None
        return realtime_event_from_publication(
            publication,
            occurred_at=datetime.now(UTC),
            sequence=self._next_realtime_sequence(),
        )

    def _prepare_realtime_mutation(
        self,
        mutation: RealtimeMutation,
        claim: WorkingClaim,
        outcome: MutationOutcome = MutationOutcome.CHANGED,
        *,
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
        return self._prepare_realtime_publication(publication, outcome)

    def _next_realtime_sequence(self) -> int:
        return self._realtime_sequence + 1

    def _commit_realtime_event(self, event: RealtimeEvent) -> None:
        """Commit one already-prepared event without another failure point."""

        assert event.sequence is not None
        self._realtime_events[event.event_id] = event
        self._realtime_sequence = event.sequence
        self._realtime_condition.notify_all()

    @staticmethod
    def _realtime_order(event: RealtimeEvent) -> tuple[int, object, str]:
        if event.sequence is not None:
            return (1, event.sequence, event.event_id)
        return (0, event.occurred_at, event.event_id)

    def replay_realtime_events(
        self,
        after: RealtimeCursor | None,
        *,
        limit: int,
    ) -> list[RealtimeEvent]:
        if not 1 <= limit <= 1000:
            raise ValueError('Realtime replay limit must be between 1 and 1000.')
        with self._claim_mutation_lock:
            if after is not None:
                stored = self._realtime_events.get(after.event_id)
                if (
                    stored is None
                    or stored.occurred_at != after.occurred_at
                    or (after.sequence is not None and stored.sequence != after.sequence)
                ):
                    raise ValueError('The realtime cursor is outside the available replay window.')
            events = sorted(
                self._realtime_events.values(),
                key=self._realtime_order,
            )
            if after is not None:
                assert stored is not None
                anchor_order = self._realtime_order(stored)
                events = [item for item in events if self._realtime_order(item) > anchor_order]
            return deepcopy(events[:limit])

    def realtime_high_watermark(self) -> RealtimeEvent | None:
        with self._claim_mutation_lock:
            if not self._realtime_events:
                return None
            return deepcopy(max(self._realtime_events.values(), key=self._realtime_order))

    def watch_realtime_events(self, stop: Event) -> Iterator[RealtimeEvent]:
        cursor: RealtimeCursor | None = None
        while not stop.is_set():
            with self._realtime_condition:
                available = self.replay_realtime_events(cursor, limit=500)
                if not available:
                    self._realtime_condition.wait(timeout=1.0)
                    continue
            for event in available:
                cursor = RealtimeCursor(
                    occurred_at=event.occurred_at,
                    event_id=event.event_id,
                    sequence=event.sequence,
                )
                yield event

    def _account_store(self, record: AccountRecord) -> dict[str, Any]:
        if isinstance(record, PolicyNumberRecord):
            return self._policies
        if isinstance(record, PaymentDestinationRecord):
            return self._payment_destinations
        return self._identity_documents

    def create_account_record(
        self,
        record: AccountRecord,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
    ) -> AccountRecord:
        with self._claim_mutation_lock:
            kind, identifier, _ = account_record_identity(record)
            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            store = self._account_store(record)
            if (
                record.customer_id != idempotency.actor_id
                or identifier != idempotency.claim_id
                or identifier in store
                or lookup in self._idempotency
                or audit_event.event_id in self._audit_events
            ):
                raise IdempotencyConflict(idempotency.key)
            stored_record = record
            stored_idempotency = idempotency
            if isinstance(record, PaymentDestinationRecord) and record.active:
                active = [
                    item
                    for item in self._payment_destinations.values()
                    if item.customer_id == record.customer_id and item.active
                ]
                stored_record = record.model_copy(update={'is_common': not active})
                stored_idempotency = payment_destination_create_result(stored_record, idempotency)
            if not account_record_audit_matches(
                stored_record, audit_event, idempotency_key=stored_idempotency.key
            ):
                raise IdempotencyConflict(idempotency.key)
            del kind
            store[identifier] = deepcopy(stored_record)
            self._idempotency[lookup] = deepcopy(stored_idempotency)
            self._audit_events[audit_event.event_id] = deepcopy(audit_event)
            return deepcopy(stored_record)

    def get_policy(self, policy_id: str, customer_id: str) -> PolicyNumberRecord | None:
        record = self._policies.get(policy_id)
        return (
            deepcopy(record) if record is not None and record.customer_id == customer_id else None
        )

    def get_payment_destination(
        self, payment_destination_id: str, customer_id: str
    ) -> PaymentDestinationRecord | None:
        record = self._payment_destinations.get(payment_destination_id)
        return (
            deepcopy(record) if record is not None and record.customer_id == customer_id else None
        )

    def get_identity_document(
        self, identity_id: str, customer_id: str
    ) -> IdentityDocumentRecord | None:
        record = self._identity_documents.get(identity_id)
        return (
            deepcopy(record) if record is not None and record.customer_id == customer_id else None
        )

    @staticmethod
    def _account_page(
        records: list[AccountRecord],
        customer_id: str,
        include_inactive: bool,
        after: AccountCursorKey | None,
        limit: int,
    ) -> tuple[list[Any], bool]:
        selected = sorted(
            (
                deepcopy(record)
                for record in records
                if record.customer_id == customer_id and (include_inactive or record.active)
            ),
            key=lambda record: (record.created_at, account_record_identity(record)[1]),
            reverse=True,
        )
        if after is not None:
            selected = [
                record
                for record in selected
                if (record.created_at, account_record_identity(record)[1]) < after
            ]
        page = selected[: limit + 1]
        return page[:limit], len(page) > limit

    def list_policies(
        self,
        customer_id: str,
        *,
        include_inactive: bool,
        after: AccountCursorKey | None,
        limit: int,
    ) -> tuple[list[PolicyNumberRecord], bool]:
        records, more = self._account_page(
            list(self._policies.values()), customer_id, include_inactive, after, limit
        )
        return [record for record in records if isinstance(record, PolicyNumberRecord)], more

    def list_payment_destinations(
        self,
        customer_id: str,
        *,
        include_inactive: bool,
        after: AccountCursorKey | None,
        limit: int,
    ) -> tuple[list[PaymentDestinationRecord], bool]:
        records, more = self._account_page(
            list(self._payment_destinations.values()),
            customer_id,
            include_inactive,
            after,
            limit,
        )
        destinations = [
            record for record in records if isinstance(record, PaymentDestinationRecord)
        ]
        return destinations, more

    def list_identity_documents(
        self,
        customer_id: str,
        *,
        include_inactive: bool,
        after: AccountCursorKey | None,
        limit: int,
    ) -> tuple[list[IdentityDocumentRecord], bool]:
        records, more = self._account_page(
            list(self._identity_documents.values()),
            customer_id,
            include_inactive,
            after,
            limit,
        )
        return [record for record in records if isinstance(record, IdentityDocumentRecord)], more

    def update_account_record(
        self,
        record: AccountRecord,
        expected_revision: int,
        audit_event: AuditEventEnvelope,
        related_audit_event_id: str | None = None,
    ) -> None:
        with self._claim_mutation_lock:
            _, identifier, _ = account_record_identity(record)
            store = self._account_store(record)
            current = store.get(identifier)
            if current is None or current.customer_id != record.customer_id:
                raise KeyError(identifier)
            if current.revision != expected_revision:
                raise RevisionConflict(current.revision)
            if (
                record.revision != expected_revision + 1
                or record.created_at != current.created_at
                or not account_record_audit_matches(record, audit_event, idempotency_key=None)
                or audit_event.event_id in self._audit_events
            ):
                raise KeyError(identifier)
            if isinstance(record, PaymentDestinationRecord) and record.is_common:
                if (
                    not isinstance(current, PaymentDestinationRecord)
                    or not current.active
                    or not record.active
                ):
                    raise PaymentDestinationDesignationConflict(identifier, reason='inactive')
                previous = [
                    other
                    for other_id, other in self._payment_destinations.items()
                    if other_id != record.payment_destination_id
                    and other.customer_id == record.customer_id
                    and other.active
                    and other.is_common
                ]
                if len(previous) > 1 or (previous and related_audit_event_id is None):
                    raise KeyError(identifier)
                if previous:
                    assert related_audit_event_id is not None
                    demoted, demotion_event = payment_destination_demotion(
                        previous[0], audit_event, related_audit_event_id
                    )
                    if (
                        not account_record_audit_matches(
                            demoted, demotion_event, idempotency_key=None
                        )
                        or demotion_event.event_id in self._audit_events
                    ):
                        raise KeyError(identifier)
                    self._payment_destinations[demoted.payment_destination_id] = demoted
                    self._audit_events[demotion_event.event_id] = demotion_event
            store[identifier] = deepcopy(record)
            self._audit_events[audit_event.event_id] = deepcopy(audit_event)

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
        with self._claim_mutation_lock:
            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            if lookup in self._idempotency:
                raise IdempotencyConflict(idempotency.key)
            self._validate_claim_mutation(claim, expected_revision)
            self._validate_branch_evaluation(claim, branch_evaluation)
            policy = self._policies.get(policy_id)
            if policy is None or policy.customer_id != claim.customer_id or not policy.active:
                raise PolicySelectionConflict(policy_id, reason='unavailable')
            if policy.revision != policy_revision:
                raise PolicySelectionConflict(
                    policy_id, reason='changed', current_revision=policy.revision
                )
            if (
                idempotency.actor_id != claim.customer_id
                or idempotency.claim_id != claim.claim_id
                or idempotency.session_id != (claim.active_session_id or '')
                or not policy_selection_audit_matches(
                    claim, policy_id, policy_revision, idempotency, audit_event
                )
            ):
                raise KeyError(claim.claim_id)
            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                claim,
                operation_correlation=idempotency.key,
                resources=realtime_resources_for_records(
                    RealtimeMutation.CLAIM_CHANGED, ('branch_evaluation',)
                ),
            )
            assert realtime_event is not None
            self._claims[claim.claim_id] = deepcopy(claim)
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
            self._idempotency[lookup] = deepcopy(idempotency)
            self._audit_events[audit_event.event_id] = deepcopy(audit_event)
            self._commit_realtime_event(realtime_event)

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
        with self._claim_mutation_lock:
            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            if lookup in self._idempotency:
                raise IdempotencyConflict(idempotency.key)
            self._validate_claim_mutation(claim, expected_revision)
            self._validate_branch_evaluation(claim, branch_evaluation)
            destination = self._payment_destinations.get(payment_destination_id)
            if (
                destination is None
                or destination.customer_id != claim.customer_id
                or not destination.active
            ):
                raise PaymentDestinationSelectionConflict(
                    payment_destination_id, reason='unavailable'
                )
            if destination.revision != payment_destination_revision:
                raise PaymentDestinationSelectionConflict(
                    payment_destination_id,
                    reason='changed',
                    current_revision=destination.revision,
                )
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
            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                claim,
                operation_correlation=idempotency.key,
                resources=realtime_resources_for_records(
                    RealtimeMutation.CLAIM_CHANGED, ('branch_evaluation',)
                ),
            )
            assert realtime_event is not None
            self._claims[claim.claim_id] = deepcopy(claim)
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
            self._idempotency[lookup] = deepcopy(idempotency)
            self._audit_events[audit_event.event_id] = deepcopy(audit_event)
            self._commit_realtime_event(realtime_event)

    def create_asset(
        self,
        asset: AssetRecord,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
    ) -> None:
        with self._claim_mutation_lock:
            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            if (
                asset.customer_id != idempotency.actor_id
                or asset.asset_id != idempotency.claim_id
                or not asset_audit_matches(asset, audit_event)
                or audit_event.idempotency_key != idempotency.key
                or asset.asset_id in self._assets
                or lookup in self._idempotency
            ):
                raise IdempotencyConflict(idempotency.key)
            existing_audit = self._audit_events.get(audit_event.event_id)
            if existing_audit is not None:
                raise IdempotencyConflict(audit_event.event_id)
            self._assets[asset.asset_id] = deepcopy(asset)
            self._idempotency[lookup] = deepcopy(idempotency)
            self._audit_events[audit_event.event_id] = deepcopy(audit_event)

    def get_asset(self, asset_id: str, customer_id: str) -> AssetRecord | None:
        asset = self._assets.get(asset_id)
        if asset is None or asset.customer_id != customer_id:
            return None
        return deepcopy(asset)

    def list_assets(
        self,
        customer_id: str,
        *,
        include_inactive: bool = False,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[AssetRecord], bool]:
        records = sorted(
            (
                deepcopy(asset)
                for asset in self._assets.values()
                if asset.customer_id == customer_id and (include_inactive or asset.active)
            ),
            key=lambda asset: (asset.updated_at, asset.asset_id),
            reverse=True,
        )
        page = records[offset : offset + limit + 1]
        return page[:limit], len(page) > limit

    def update_asset(
        self,
        asset: AssetRecord,
        expected_revision: int,
        audit_event: AuditEventEnvelope,
    ) -> None:
        with self._claim_mutation_lock:
            current = self._assets.get(asset.asset_id)
            if current is None or current.customer_id != asset.customer_id:
                raise KeyError(asset.asset_id)
            if current.revision != expected_revision:
                raise RevisionConflict(current.revision)
            if (
                asset.revision != expected_revision + 1
                or asset.created_at != current.created_at
                or not asset_audit_matches(asset, audit_event)
                or audit_event.idempotency_key is not None
            ):
                raise KeyError(asset.asset_id)
            existing_audit = self._audit_events.get(audit_event.event_id)
            if existing_audit is not None:
                raise IdempotencyConflict(audit_event.event_id)
            self._assets[asset.asset_id] = deepcopy(asset)
            self._audit_events[audit_event.event_id] = deepcopy(audit_event)

    def save_asset_selection(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        snapshot: ClaimAssetSnapshot,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord,
        audit_event: AuditEventEnvelope,
    ) -> None:
        with self._claim_mutation_lock:
            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            if lookup in self._idempotency:
                raise IdempotencyConflict(idempotency.key)
            self._validate_claim_mutation(claim, expected_revision)
            self._validate_branch_evaluation(claim, branch_evaluation)
            asset = self._assets.get(snapshot.asset_id)
            if asset is None or asset.customer_id != claim.customer_id or not asset.active:
                raise AssetSelectionUnavailableError(snapshot.asset_id)
            if asset.revision != snapshot.asset_revision:
                raise AssetSelectionRevisionConflictError(asset.revision)
            if not asset_matches_snapshot(asset, snapshot):
                raise AssetSelectionSnapshotConflictError(snapshot.asset_id)
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
            existing_audit = self._audit_events.get(audit_event.event_id)
            if snapshot.snapshot_id in self._claim_asset_snapshots or existing_audit is not None:
                raise IdempotencyConflict(idempotency.key)
            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                claim,
                operation_correlation=idempotency.key,
                resources=realtime_resources_for_records(
                    RealtimeMutation.CLAIM_CHANGED,
                    ('claim_asset_snapshot', 'branch_evaluation'),
                ),
            )
            assert realtime_event is not None
            self._claims[claim.claim_id] = deepcopy(claim)
            self._claim_asset_snapshots[snapshot.snapshot_id] = deepcopy(snapshot)
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
            self._idempotency[lookup] = deepcopy(idempotency)
            self._audit_events[audit_event.event_id] = deepcopy(audit_event)
            self._commit_realtime_event(realtime_event)

    def list_claim_asset_snapshots(
        self,
        claim_id: str,
        customer_id: str,
        *,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[ClaimAssetSnapshot], bool]:
        records = sorted(
            (
                deepcopy(snapshot)
                for snapshot in self._claim_asset_snapshots.values()
                if snapshot.claim_id == claim_id and snapshot.customer_id == customer_id
            ),
            key=lambda snapshot: (snapshot.captured_at, snapshot.snapshot_id),
        )
        page = records[offset : offset + limit + 1]
        return page[:limit], len(page) > limit

    @property
    def claim_count(self) -> int:
        return len(self._claims)

    def reset_demo_state(self) -> dict[str, int]:
        """Clear only records owned by this in-memory prototype repository."""
        cleared = {
            'claims': len(self._claims),
            'policies': len(self._policies),
            'payment_destinations': len(self._payment_destinations),
            'identity_documents': len(self._identity_documents),
            'assets': len(self._assets),
            'claim_asset_snapshots': len(self._claim_asset_snapshots),
            'audit_events': len(self._audit_events),
            'sessions': len(self._sessions),
            'follow_ups': len(self._follow_ups),
            'follow_up_operations': len(self._follow_up_operations),
            'retention_operations': len(self._retention_operations),
            'messages': len(self._messages),
            'conversation_summaries': len(self._conversation_summaries),
            'runtime_traces': len(self._runtime_traces),
            'staff_agent_sessions': len(self._staff_agent_sessions),
            'staff_agent_messages': len(self._staff_agent_messages),
            'staff_agent_executions': len(self._staff_agent_executions),
            'agent_decisions': len(self._decisions),
            'branch_evaluations': len(self._branch_evaluations),
            'claim_creation_operations': len(self._claim_creation_operations),
            'assessor_routing_operations': len(self._assessor_routing_operations),
            'evidence': len(self._evidence),
            'evidence_claim_links': len(self._evidence_claim_links),
            'motor_other_drivers': len(self._motor_other_drivers),
            'contents_item_evidence_associations': len(self._contents_item_evidence_associations),
            'external_tasks': len(self._external_tasks),
            'external_task_requests': len(self._external_task_requests),
            'external_task_evidence_links': len(self._external_task_evidence_links),
            'external_task_results': len(self._external_task_results),
            'retrievals': len(self._retrievals),
            'review_signals': len(self._review_signals),
            'staff_actions': len(self._staff_actions),
            'customer_updates': len(self._customer_updates),
            'signal_decisions': len(self._signal_decisions),
            'collaboration_requests': len(self._collaboration_requests),
            'claim_coworkers': len(self._claim_coworkers),
            'handoffs': len(self._handoffs),
            'idempotency_records': len(self._idempotency),
            'staff_presence': len(self._staff_presence),
            'realtime_events': len(self._realtime_events),
        }
        self._claims.clear()
        self._policies.clear()
        self._payment_destinations.clear()
        self._identity_documents.clear()
        self._assets.clear()
        self._claim_asset_snapshots.clear()
        self._audit_events.clear()
        self._sessions.clear()
        self._session_ids_by_claim.clear()
        self._message_ids_by_session.clear()
        self._follow_ups.clear()
        self._follow_up_operations.clear()
        self._retention_operations.clear()
        self._messages.clear()
        self._conversation_summaries.clear()
        self._runtime_traces.clear()
        self._staff_agent_sessions.clear()
        self._staff_agent_messages.clear()
        self._staff_agent_executions.clear()
        self._decisions.clear()
        self._branch_evaluations.clear()
        self._claim_creation_operations.clear()
        self._assessor_routing_operations.clear()
        self._evidence.clear()
        self._evidence_claim_links.clear()
        self._motor_other_drivers.clear()
        self._contents_item_evidence_associations.clear()
        self._external_tasks.clear()
        self._external_task_attempts.clear()
        self._external_task_requests.clear()
        self._external_task_evidence_links.clear()
        self._external_task_results.clear()
        self._retrievals.clear()
        self._review_signals.clear()
        self._staff_actions.clear()
        self._customer_updates.clear()
        self._signal_decisions.clear()
        self._collaboration_requests.clear()
        self._claim_coworkers.clear()
        self._handoffs.clear()
        self._idempotency.clear()
        self._staff_presence.clear()
        self._realtime_events.clear()
        self._realtime_sequence = 0
        now = datetime.now(UTC)
        self._staff_presence['stf_demo'] = StaffPresenceRecord(
            staff_id='stf_demo',
            online=True,
            available=True,
            last_seen_at=now,
            expires_at=now + timedelta(minutes=5),
            updated_at=now,
        )
        return cleared

    def get_staff_presence(self, staff_id: str) -> StaffPresenceRecord | None:
        record = self._staff_presence.get(staff_id)
        return deepcopy(record) if record is not None else None

    def list_staff_presence(self) -> list[StaffPresenceRecord]:
        return sorted(
            (deepcopy(record) for record in self._staff_presence.values()),
            key=lambda record: record.staff_id,
        )

    def save_staff_presence(
        self, presence: StaffPresenceRecord, expected_revision: int | None = None
    ) -> None:
        current = self._staff_presence.get(presence.staff_id)
        if current is None:
            if expected_revision not in (None, 0):
                raise RevisionConflict(0)
            self._staff_presence[presence.staff_id] = deepcopy(presence)
            return
        if expected_revision is not None and current.revision != expected_revision:
            raise RevisionConflict(current.revision)
        if presence.revision != current.revision + 1:
            raise RevisionConflict(current.revision)
        self._staff_presence[presence.staff_id] = deepcopy(presence)

    def append_audit_event(self, event: AuditEventEnvelope) -> None:
        """Append one immutable audit event to the fixture store.

        Args:
            event: Audit event to persist.

        Returns:
            None.

        Raises:
            IdempotencyConflict: The event identity exists with different content.
        """
        existing = self._audit_events.get(event.event_id)
        if existing is not None:
            if existing != event:
                raise IdempotencyConflict(event.event_id)
            return
        self._audit_events[event.event_id] = deepcopy(event)

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
            Deep-copied matching events in stable time and identity order.

        Raises:
            ValueError: The requested time range is invalid.
        """
        if start_at is not None and end_at is not None and start_at > end_at:
            raise ValueError('Audit event start_at must not be after end_at.')

        events = [
            deepcopy(event)
            for event in self._audit_events.values()
            if event.subject == subject
            and (start_at is None or event.created_at >= start_at)
            and (end_at is None or event.created_at <= end_at)
        ]
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
        if start_at is not None and end_at is not None and start_at > end_at:
            raise ValueError('Audit event start_at must not be after end_at.')
        events = [
            deepcopy(event)
            for event in self._audit_events.values()
            if (event_type is None or event.event_type.value == event_type)
            and (subject_type is None or event.subject.subject_type.value == subject_type)
            and (actor_id is None or event.actor.actor_id == actor_id)
            and (start_at is None or event.created_at >= start_at)
            and (end_at is None or event.created_at <= end_at)
        ]
        return sorted(events, key=lambda event: (event.created_at, event.event_id))

    def _prepare_audit_events(
        self,
        claim: WorkingClaim,
        audit_events: tuple[AuditEventEnvelope, ...],
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
            existing = self._audit_events.get(event.event_id)
            if existing is not None and existing != event:
                raise IdempotencyConflict(event.event_id)
            prepared[event.event_id] = event
        return tuple(prepared.values())

    def create_claim(self, claim: WorkingClaim, session: SessionRecord) -> None:
        with self._claim_mutation_lock:
            existing_claim = self._claims.get(claim.claim_id)
            existing_session = self._sessions.get(session.session_id)
            if existing_claim is not None or existing_session is not None:
                if existing_claim == claim and existing_session == session:
                    self._prepare_realtime_mutation(
                        RealtimeMutation.CLAIM_CREATED,
                        claim,
                        MutationOutcome.EXACT_NOOP,
                    )
                    return
                raise IdempotencyConflict(claim.claim_id)
            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CREATED,
                claim,
            )
            assert realtime_event is not None
            self._claims[claim.claim_id] = deepcopy(claim)
            self._store_session(session)
            self._commit_realtime_event(realtime_event)

    def _store_message(self, message: MessageRecord) -> None:
        """Store a message and maintain the bounded-search child index."""

        self._preflight_messages((message,))
        self._messages[message.message_id] = deepcopy(message)
        message_ids = self._message_ids_by_session.setdefault(message.session_id, [])
        if message.message_id not in message_ids:
            message_ids.append(message.message_id)
        ordered = order_messages([self._messages[message_id] for message_id in message_ids])
        message_ids[:] = [message.message_id for message in ordered]

    def _preflight_messages(
        self,
        messages: Sequence[MessageRecord],
        *,
        sessions: Sequence[SessionRecord] = (),
        evidence: Sequence[EvidenceRecord] = (),
    ) -> None:
        """Validate a complete pending message set without mutating Fixture state."""

        available_sessions = {**self._sessions, **{item.session_id: item for item in sessions}}
        available_evidence = {**self._evidence, **{item.evidence_id: item for item in evidence}}
        available_messages = dict(self._messages)
        pending_by_id = {message.message_id: message for message in messages}
        validate_message_graph(tuple(available_messages.values()) + tuple(pending_by_id.values()))
        for message in messages:
            session = available_sessions.get(message.session_id)
            if session is None:
                raise ValueError('Message Session does not exist.')
            referenced_evidence = [
                item
                for evidence_id in message.evidence_refs
                if (item := available_evidence.get(evidence_id)) is not None
            ]
            reply = pending_by_id.get(
                message.in_reply_to or '',
                available_messages.get(message.in_reply_to or ''),
            )
            duplicate_client_message = next(
                (
                    item
                    for item in available_messages.values()
                    if message.client_message_id is not None
                    and item.claim_id == message.claim_id
                    and item.client_message_id == message.client_message_id
                ),
                None,
            )
            try:
                validate_message_record(
                    message,
                    session=session,
                    evidence=referenced_evidence,
                    reply=reply,
                    duplicate_client_message=duplicate_client_message,
                )
            except DuplicateClientMessage as conflict:
                raise IdempotencyConflict(
                    message.client_message_id or message.message_id
                ) from conflict
            available_messages[message.message_id] = message

    def _store_evidence(self, evidence: EvidenceRecord) -> None:
        """Validate and store one provider-neutral Evidence record."""

        validate_evidence_record(evidence)
        self._evidence[evidence.evidence_id] = deepcopy(evidence)

    def _store_session(self, session: SessionRecord) -> None:
        self._sessions[session.session_id] = deepcopy(session)
        self._message_ids_by_session.setdefault(session.session_id, [])
        session_ids = self._session_ids_by_claim.setdefault(
            (session.claim_id, session.customer_id), []
        )
        if session.session_id not in session_ids:
            session_ids.append(session.session_id)
        session_ids.sort(
            key=lambda session_id: (
                self._sessions[session_id].started_at,
                session_id,
            ),
            reverse=True,
        )

    def seed_validation_graph(self, graph: ValidationSeedGraph) -> IdempotencyRecord | None:
        """Serialize validation seeds so a same-key race cannot create two graphs."""
        with self._validation_seed_lock:
            return self._seed_validation_graph(graph)

    def _seed_validation_graph(self, graph: ValidationSeedGraph) -> IdempotencyRecord | None:
        """Persist validation records as one rollback-safe fixture operation."""
        snapshot = {
            key: deepcopy(value)
            for key, value in self.__dict__.items()
            if key not in {'_validation_seed_lock', '_claim_mutation_lock', '_realtime_condition'}
        }
        try:
            existing = self.find_idempotency(
                graph.idempotency.actor_id,
                graph.idempotency.route,
                graph.idempotency.key,
            )
            if existing is not None:
                if existing.request_fingerprint != graph.idempotency.request_fingerprint:
                    raise IdempotencyConflict(graph.idempotency.key)
                return existing
            if self.list_claims_internal():
                raise DemoSeedConflict('The validation seed requires an empty claim queue.')

            claims_by_id = {claim.claim_id: claim for claim in graph.claims}
            if len(claims_by_id) != len(graph.claims) or not claims_by_id:
                raise ValueError('Validation seed claims must be unique and non-empty.')
            sessions_by_id = {session.session_id: session for session in graph.sessions}
            if len(sessions_by_id) != len(graph.sessions):
                raise ValueError('Validation seed sessions must be unique.')
            messages_by_id = {message.message_id: message for message in graph.messages}
            if len(messages_by_id) != len(graph.messages):
                raise ValueError('Validation seed messages must be unique.')
            evidence_by_id = {item.evidence_id: item for item in graph.evidence}
            if len(evidence_by_id) != len(graph.evidence):
                raise ValueError('Validation seed evidence must be unique.')
            self._preflight_messages(
                graph.messages,
                sessions=graph.sessions,
                evidence=graph.evidence,
            )

            self.save_staff_presence(graph.staff_presence, graph.expected_presence_revision)
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
                self.create_claim(claim, active[0])
            for session in graph.sessions:
                if session.session_id != claims_by_id[session.claim_id].active_session_id:
                    self.save_session(session)
            for evidence in graph.evidence:
                self.save_evidence(evidence, claims_by_id[evidence.claim_id].customer_id)
            for message in order_messages(graph.messages):
                self.save_message(message, claims_by_id[message.claim_id].customer_id)
            self.save_idempotency(graph.idempotency)
        except Exception:
            validation_seed_lock = self._validation_seed_lock
            claim_mutation_lock = self._claim_mutation_lock
            realtime_condition = self._realtime_condition
            self.__dict__.clear()
            self.__dict__.update(snapshot)
            self._validation_seed_lock = validation_seed_lock
            self._claim_mutation_lock = claim_mutation_lock
            self._realtime_condition = realtime_condition
            raise
        return None

    def _claim_access_closed(
        self,
        claim_id: str,
    ) -> bool:
        return claim_id in self._retention_operation_by_claim

    def claimant_resource_access_open(
        self,
        claim_id: str,
        customer_id: str,
    ) -> bool:
        claim = self._claims.get(claim_id)

        return (
            claim is not None
            and claim.customer_id == customer_id
            and not self._claim_access_closed(claim_id)
        )

    def _ensure_claim_access_open(
        self,
        claim_id: str,
    ) -> None:
        if self._claim_access_closed(claim_id):
            raise ResourceAccessClosed(claim_id)

    def _claimant_actor_access_closed(
        self,
        claim_id: str,
        actor_id: str,
    ) -> bool:
        claim = self._claims.get(claim_id)

        return (
            claim is not None
            and claim.customer_id == actor_id
            and self._claim_access_closed(claim_id)
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

        return deepcopy(self._claims[claim_id])

    def promote_claim_owner(
        self,
        claim_id: str,
        anonymous_customer_id: str,
        customer_id: str,
    ) -> WorkingClaim | None:
        with self._claim_mutation_lock:
            self._ensure_claim_access_open(claim_id)
            claim = self._claims.get(claim_id)
            if claim is None or claim.customer_id != anonymous_customer_id:
                return None
            promoted_idempotency = [
                replace(record, actor_id=customer_id, retired=False)
                for record in self._idempotency.values()
                if record.claim_id == claim_id
                and record.actor_id == anonymous_customer_id
                and not record.retired
            ]
            for promoted_record in promoted_idempotency:
                existing = self._idempotency.get(
                    (customer_id, promoted_record.route, promoted_record.key)
                )
                if existing is not None and existing != promoted_record:
                    raise IdempotencyConflict(promoted_record.key)
            promoted_claim = claim.model_copy(update={'customer_id': customer_id})
            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_OWNER_CHANGED,
                promoted_claim,
            )
            assert realtime_event is not None
            self._claims[claim_id] = promoted_claim
            stores: tuple[dict[str, Any], ...] = (
                self._sessions,
                self._follow_ups,
                self._messages,
                self._decisions,
                self._claim_creation_operations,
                self._assessor_routing_operations,
                self._evidence,
                self._motor_other_drivers,
                self._contents_item_evidence_associations,
                self._retrievals,
                self._review_signals,
                self._staff_actions,
                self._customer_updates,
                self._signal_decisions,
                self._collaboration_requests,
                self._claim_coworkers,
                self._handoffs,
            )
            for store in stores:
                for record_key, record in list(store.items()):
                    if getattr(record, 'claim_id', None) == claim_id:
                        store[record_key] = (
                            record.model_copy(update={'customer_id': customer_id})
                            if 'customer_id' in type(record).model_fields
                            else record
                        )
            for idempotency_key, record in list(self._idempotency.items()):
                if (
                    record.claim_id == claim_id
                    and record.actor_id == anonymous_customer_id
                    and not record.retired
                ):
                    self._idempotency[idempotency_key] = replace(record, retired=True)
                    promoted_record = replace(record, actor_id=customer_id, retired=False)
                    self._idempotency[(customer_id, record.route, record.key)] = promoted_record
            self._commit_realtime_event(realtime_event)
            return deepcopy(self._claims[claim_id])

    def get_claim_internal(self, claim_id: str) -> WorkingClaim | None:
        claim = self._claims.get(claim_id)
        return deepcopy(claim) if claim is not None else None

    def save_claim(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        with self._claim_mutation_lock:
            self._validate_claim_mutation(claim, expected_revision)
            self._validate_branch_evaluation(claim, branch_evaluation)
            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                claim,
            )
            assert realtime_event is not None
            self._claims[claim.claim_id] = deepcopy(claim)
            if branch_evaluation is not None:
                self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(
                    branch_evaluation
                )
            self._commit_realtime_event(realtime_event)

    def _validate_claim_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        *,
        allow_active_session_change: bool = False,
    ) -> WorkingClaim:
        """Validate the shared Claim State precondition before any child write."""
        self._ensure_claim_access_open(claim.claim_id)
        stored_claim = self._claims.get(claim.claim_id)
        if stored_claim is None:
            raise KeyError(claim.claim_id)
        if stored_claim.revision != expected_revision:
            raise RevisionConflict(stored_claim.revision)
        if stored_claim.customer_id != claim.customer_id or claim.revision != expected_revision + 1:
            raise KeyError(claim.claim_id)
        if (
            not allow_active_session_change
            and stored_claim.active_session_id != claim.active_session_id
        ):
            raise KeyError(claim.claim_id)
        return stored_claim

    def save_claim_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        with self._claim_mutation_lock:
            self._validate_claim_mutation(claim, expected_revision)
            self._validate_branch_evaluation(claim, branch_evaluation)
            if (
                idempotency.actor_id != claim.customer_id
                or idempotency.claim_id != claim.claim_id
                or idempotency.session_id != (claim.active_session_id or '')
            ):
                raise KeyError(claim.claim_id)
            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            if lookup in self._idempotency:
                raise IdempotencyConflict(idempotency.key)

            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                claim,
                operation_correlation=idempotency.key,
            )
            assert realtime_event is not None
            self._claims[claim.claim_id] = deepcopy(claim)
            if branch_evaluation is not None:
                self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(
                    branch_evaluation
                )
            self._idempotency[lookup] = deepcopy(idempotency)
            self._commit_realtime_event(realtime_event)

    def save_claim_mutation_with_audit(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        idempotency: IdempotencyRecord,
        audit_events: tuple[AuditEventEnvelope, ...],
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        """Persist one claim mutation and its prevalidated audit facts atomically.

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
        with self._claim_mutation_lock:
            self._validate_claim_mutation(claim, expected_revision)
            self._validate_branch_evaluation(claim, branch_evaluation)
            prepared = self._prepare_audit_events(claim, audit_events)
            if idempotency.claim_id != claim.claim_id or idempotency.session_id != (
                claim.active_session_id or ''
            ):
                raise KeyError(claim.claim_id)
            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            if lookup in self._idempotency:
                raise IdempotencyConflict(idempotency.key)

            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                claim,
                operation_correlation=idempotency.key,
            )
            assert realtime_event is not None
            self._claims[claim.claim_id] = deepcopy(claim)
            if branch_evaluation is not None:
                self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(
                    branch_evaluation
                )
            self._idempotency[lookup] = deepcopy(idempotency)
            for event in prepared:
                self._audit_events[event.event_id] = deepcopy(event)
            self._commit_realtime_event(realtime_event)

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

        session = self._sessions.get(session_id)

        if session is None or session.claim_id != claim_id or session.customer_id != customer_id:
            return None

        return deepcopy(session)

    def save_session(self, session: SessionRecord) -> None:
        self._ensure_claim_access_open(session.claim_id)
        claim = self._claims.get(session.claim_id)
        if claim is None or claim.customer_id != session.customer_id:
            raise KeyError(session.claim_id)
        self._store_session(session)

    def get_follow_up(
        self,
        claim_id: str,
        follow_up_id: str,
        customer_id: str,
    ) -> FollowUpRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        record = self._follow_ups.get(follow_up_id)
        if record is None or record.claim_id != claim_id:
            return None
        return deepcopy(record)

    def list_follow_ups(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[FollowUpRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        records = [
            deepcopy(record) for record in self._follow_ups.values() if record.claim_id == claim_id
        ]
        return sorted(records, key=lambda record: (record.created_at, record.follow_up_id))

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

        with self._claim_mutation_lock:
            for follow_up_id in list(self._follow_ups):
                current = self._follow_ups[follow_up_id]

                decision = backfill_legacy_follow_up_record(
                    current,
                    self._sessions.get(current.source_session_id),
                    recorded_at=migration_time,
                )

                if decision.outcome == 'noop':
                    continue

                assert decision.audit_event is not None

                existing_audit = self._audit_events.get(decision.audit_event.event_id)

                if existing_audit is not None and existing_audit != decision.audit_event:
                    raise IdempotencyConflict(decision.audit_event.event_id)

                self._follow_ups[follow_up_id] = deepcopy(decision.record)
                self._audit_events[decision.audit_event.event_id] = deepcopy(decision.audit_event)

                if decision.outcome == 'bound':
                    bound_count += 1
                else:
                    failed_count += 1

        return bound_count, failed_count

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
        with self._claim_mutation_lock:
            claim = self._claims.get(expected_follow_up.claim_id)
            current_follow_up = self._follow_ups.get(expected_follow_up.follow_up_id)
            source_session = self._sessions.get(expected_follow_up.source_session_id)

            if (
                claim is None
                or claim.customer_id != customer_id
                or current_follow_up is None
                or source_session is None
            ):
                raise KeyError(expected_follow_up.follow_up_id)

            if claim.revision != expected_claim_revision:
                raise RevisionConflict(claim.revision)

            if current_follow_up != expected_follow_up:
                raise IdempotencyConflict(expected_follow_up.follow_up_id)

            lookup = (
                idempotency.actor_id,
                idempotency.route,
                idempotency.key,
            )

            if self._idempotency.get(lookup) is not None:
                raise IdempotencyConflict(idempotency.key)

            operations = sorted(
                (
                    deepcopy(operation)
                    for operation in self._follow_up_operations.values()
                    if operation.claim_id == claim.claim_id
                    and operation.follow_up_id == current_follow_up.follow_up_id
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

            if reconciled_operation is not None:
                stored_operation = self._follow_up_operations.get(reconciled_operation.operation_id)
                if stored_operation is None:
                    raise IdempotencyConflict(reconciled_operation.operation_id)

                try:
                    assert_follow_up_operation_transition(
                        stored_operation,
                        reconciled_operation,
                    )
                except ValueError as error:
                    raise IdempotencyConflict(reconciled_operation.operation_id) from error

            prepared_audit = self._prepare_audit_events(
                updated_claim,
                (audit_event,),
            )

            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                updated_claim,
                operation_correlation=idempotency.key,
            )
            assert realtime_event is not None

            if reconciled_operation is not None:
                self._follow_up_operations[reconciled_operation.operation_id] = deepcopy(
                    reconciled_operation
                )

            self._follow_ups[updated_follow_up.follow_up_id] = deepcopy(updated_follow_up)

            self._claims[updated_claim.claim_id] = deepcopy(updated_claim)

            self._idempotency[lookup] = deepcopy(idempotency)

            for event in prepared_audit:
                self._audit_events[event.event_id] = deepcopy(event)

            self._commit_realtime_event(realtime_event)

    def commit_follow_up_contact_withdrawal(
        self,
        expected_claim_revision: int,
        expected_follow_up: FollowUpRecord,
        updated_follow_up: FollowUpRecord,
        reconciled_operation: FollowUpOperation | None,
        customer_id: str,
        audit_event: AuditEventEnvelope,
    ) -> None:
        with self._claim_mutation_lock:
            claim = self._claims.get(expected_follow_up.claim_id)
            current_follow_up = self._follow_ups.get(expected_follow_up.follow_up_id)
            source_session = self._sessions.get(expected_follow_up.source_session_id)

            if (
                claim is None
                or claim.customer_id != customer_id
                or current_follow_up is None
                or source_session is None
            ):
                raise KeyError(expected_follow_up.follow_up_id)

            if claim.revision != expected_claim_revision:
                raise RevisionConflict(claim.revision)

            if current_follow_up != expected_follow_up:
                raise IdempotencyConflict(expected_follow_up.follow_up_id)

            operations = sorted(
                (
                    deepcopy(operation)
                    for operation in self._follow_up_operations.values()
                    if operation.claim_id == claim.claim_id
                    and operation.follow_up_id == current_follow_up.follow_up_id
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

            if reconciled_operation is not None:
                stored_operation = self._follow_up_operations.get(reconciled_operation.operation_id)
                if stored_operation is None:
                    raise IdempotencyConflict(reconciled_operation.operation_id)
                try:
                    assert_follow_up_operation_transition(
                        stored_operation,
                        reconciled_operation,
                    )
                except ValueError as error:
                    raise IdempotencyConflict(reconciled_operation.operation_id) from error

            prepared_audit = self._prepare_audit_events(
                claim,
                (audit_event,),
            )

            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                claim,
                operation_correlation=(f'follow-up-contact:{updated_follow_up.follow_up_id}'),
            )
            assert realtime_event is not None

            if reconciled_operation is not None:
                self._follow_up_operations[reconciled_operation.operation_id] = deepcopy(
                    reconciled_operation
                )

            self._follow_ups[updated_follow_up.follow_up_id] = deepcopy(updated_follow_up)

            for event in prepared_audit:
                self._audit_events[event.event_id] = deepcopy(event)

            self._commit_realtime_event(realtime_event)

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
        with self._claim_mutation_lock:
            claim = self._claims.get(expected_follow_up.claim_id)
            current_follow_up = self._follow_ups.get(expected_follow_up.follow_up_id)
            source_session = self._sessions.get(expected_follow_up.source_session_id)

            if (
                claim is None
                or claim.customer_id != customer_id
                or current_follow_up is None
                or source_session is None
            ):
                raise KeyError(expected_follow_up.follow_up_id)

            if claim.revision != expected_claim_revision:
                raise RevisionConflict(claim.revision)

            if current_follow_up != expected_follow_up:
                raise IdempotencyConflict(expected_follow_up.follow_up_id)

            operations = sorted(
                (
                    deepcopy(operation)
                    for operation in self._follow_up_operations.values()
                    if operation.claim_id == claim.claim_id
                    and operation.follow_up_id == current_follow_up.follow_up_id
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
                raise IdempotencyConflict(expected_follow_up.follow_up_id) from error

            if (
                transition.claim != updated_claim
                or transition.follow_up != updated_follow_up
                or transition.reconciled_operation != reconciled_operation
            ):
                raise IdempotencyConflict(expected_follow_up.follow_up_id)

            if reconciled_operation is not None:
                stored_operation = self._follow_up_operations.get(reconciled_operation.operation_id)
                if stored_operation is None:
                    raise IdempotencyConflict(reconciled_operation.operation_id)
                try:
                    assert_follow_up_operation_transition(
                        stored_operation,
                        reconciled_operation,
                    )
                except ValueError as error:
                    raise IdempotencyConflict(reconciled_operation.operation_id) from error

            prepared_audit = self._prepare_audit_events(
                updated_claim,
                (audit_event,),
            )

            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                updated_claim,
                operation_correlation=(f'recovery-expiry:{updated_follow_up.follow_up_id}'),
            )
            assert realtime_event is not None

            if reconciled_operation is not None:
                self._follow_up_operations[reconciled_operation.operation_id] = deepcopy(
                    reconciled_operation
                )

            self._follow_ups[updated_follow_up.follow_up_id] = deepcopy(updated_follow_up)
            self._claims[updated_claim.claim_id] = deepcopy(updated_claim)

            for event in prepared_audit:
                self._audit_events[event.event_id] = deepcopy(event)

            self._commit_realtime_event(realtime_event)

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
        with self._claim_mutation_lock:
            claim = self._claims.get(expected_follow_up.claim_id)
            current_follow_up = self._follow_ups.get(expected_follow_up.follow_up_id)
            source_session = self._sessions.get(expected_follow_up.source_session_id)

            if (
                claim is None
                or claim.customer_id != customer_id
                or current_follow_up is None
                or source_session is None
            ):
                raise KeyError(expected_follow_up.follow_up_id)

            existing_operation = self._follow_up_operations.get(operation.operation_id)

            if existing_operation is not None:
                if (
                    existing_operation == operation
                    and self._messages.get(in_app_message.message_id) == in_app_message
                    and current_follow_up.attempt_count >= updated_follow_up.attempt_count
                    and current_follow_up.updated_at >= updated_follow_up.updated_at
                ):
                    return
                raise IdempotencyConflict(operation.operation_id)

            if current_follow_up != expected_follow_up:
                raise IdempotencyConflict(expected_follow_up.follow_up_id)

            prior_operations = sorted(
                (
                    deepcopy(stored)
                    for stored in self._follow_up_operations.values()
                    if stored.follow_up_id == expected_follow_up.follow_up_id
                    and stored.claim_id == expected_follow_up.claim_id
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

            if settled_previous_operation is not None:
                stored_previous = self._follow_up_operations.get(
                    settled_previous_operation.operation_id
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

            if any(
                stored.follow_up_id == operation.follow_up_id
                and stored.sequence == operation.sequence
                for stored in self._follow_up_operations.values()
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
            self._preflight_messages((in_app_message,))

            prepared_audit = self._prepare_audit_events(
                claim,
                (audit_event,),
            )

            if settled_previous_operation is not None:
                self._follow_up_operations[settled_previous_operation.operation_id] = deepcopy(
                    settled_previous_operation
                )

            self._follow_up_operations[operation.operation_id] = deepcopy(operation)
            self._store_message(in_app_message)

            self._follow_ups[updated_follow_up.follow_up_id] = deepcopy(updated_follow_up)

            for event in prepared_audit:
                self._audit_events[event.event_id] = deepcopy(event)

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

        records = sorted(
            (
                deepcopy(record)
                for record in self._follow_ups.values()
                if record.status is FollowUpStatus.PENDING
                and record.due_at is not None
                and record.deadline_at is not None
                and record.due_at <= due_before
                and record.deadline_at > due_before
                and (
                    after is None
                    or (
                        record.due_at,
                        record.follow_up_id,
                    )
                    > (
                        after.ordered_at,
                        after.follow_up_id,
                    )
                )
            ),
            key=lambda record: (
                record.due_at,
                record.follow_up_id,
            ),
        )

        page = records[: limit + 1]
        selected = page[:limit]
        next_cursor = None

        if len(page) > limit:
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

        records = sorted(
            (
                deepcopy(record)
                for record in self._follow_ups.values()
                if record.status
                in {
                    FollowUpStatus.PENDING,
                    FollowUpStatus.BLOCKED,
                }
                and record.deadline_at is not None
                and record.deadline_at <= deadline_before
                and (
                    after is None
                    or (
                        record.deadline_at,
                        record.follow_up_id,
                    )
                    > (
                        after.ordered_at,
                        after.follow_up_id,
                    )
                )
            ),
            key=lambda record: (
                record.deadline_at,
                record.follow_up_id,
            ),
        )

        page = records[: limit + 1]
        selected = page[:limit]
        next_cursor = None

        if len(page) > limit:
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
        if self.get_claim(claim_id, customer_id) is None:
            return None
        operation = self._follow_up_operations.get(operation_id)
        if operation is None or operation.claim_id != claim_id:
            return None
        return deepcopy(operation)

    def list_follow_up_operations(
        self,
        claim_id: str,
        follow_up_id: str,
        customer_id: str,
    ) -> list[FollowUpOperation]:
        if self.get_claim(claim_id, customer_id) is None:
            return []

        follow_up = self._follow_ups.get(follow_up_id)
        if follow_up is None or follow_up.claim_id != claim_id:
            return []

        operations = [
            deepcopy(operation)
            for operation in self._follow_up_operations.values()
            if operation.claim_id == claim_id and operation.follow_up_id == follow_up_id
        ]

        return sorted(
            operations,
            key=lambda operation: (
                operation.sequence,
                operation.operation_id,
            ),
        )

    def save_follow_up_operation(
        self,
        operation: FollowUpOperation,
        customer_id: str,
    ) -> None:
        with self._claim_mutation_lock:
            claim = self._claims.get(operation.claim_id)
            follow_up = self._follow_ups.get(operation.follow_up_id)

            if (
                claim is None
                or claim.customer_id != customer_id
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

            existing = self._follow_up_operations.get(operation.operation_id)

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

                self._follow_up_operations[operation.operation_id] = deepcopy(operation)
                return

            if operation.status is not FollowUpOperationStatus.SCHEDULED:
                raise IdempotencyConflict(operation.operation_id)

            if operation.based_on_claim_revision != claim.revision:
                raise IdempotencyConflict(operation.operation_id)

            if any(
                stored.follow_up_id == operation.follow_up_id
                and stored.sequence == operation.sequence
                for stored in self._follow_up_operations.values()
            ):
                raise IdempotencyConflict(operation.operation_id)

            prior_sequences = [
                stored.sequence
                for stored in self._follow_up_operations.values()
                if stored.follow_up_id == operation.follow_up_id
            ]

            expected_sequence = max(prior_sequences, default=0) + 1

            if operation.sequence != expected_sequence:
                raise IdempotencyConflict(operation.operation_id)

            self._follow_up_operations[operation.operation_id] = deepcopy(operation)

    def save_incomplete_checkpoint(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        follow_up: FollowUpRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        self._validate_claim_mutation(
            claim,
            expected_revision,
            allow_active_session_change=True,
        )

        with self._claim_mutation_lock:
            self._ensure_claim_access_open(claim.claim_id)
            stored_claim = self._claims.get(claim.claim_id)

            if stored_claim is None:
                raise KeyError(claim.claim_id)

            if stored_claim.revision != expected_revision:
                raise RevisionConflict(stored_claim.revision)

            if (
                stored_claim.customer_id != claim.customer_id
                or claim.revision != expected_revision + 1
            ):
                raise KeyError(claim.claim_id)

            stored_session = self._sessions.get(session.session_id)

            lookup = (
                idempotency.actor_id,
                idempotency.route,
                idempotency.key,
            )

            valid = (
                stored_claim.active_session_id == session.session_id
                and claim.active_session_id is None
                and session.claim_id == claim.claim_id
                and session.customer_id == claim.customer_id
                and stored_session is not None
                and stored_session.claim_id == claim.claim_id
                and stored_session.customer_id == claim.customer_id
                and stored_session.status is SessionStatus.ACTIVE
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

            if lookup in self._idempotency:
                raise IdempotencyConflict(idempotency.key)

            if follow_up.follow_up_id in self._follow_ups:
                raise IdempotencyConflict(follow_up.follow_up_id)

            if any(
                record.claim_id == claim.claim_id
                and record.purpose == follow_up.purpose
                and record.status in {FollowUpStatus.PENDING, FollowUpStatus.BLOCKED}
                for record in self._follow_ups.values()
            ):
                raise IdempotencyConflict(follow_up.purpose)

            prepared_claim = deepcopy(claim)
            prepared_session = deepcopy(session)
            prepared_follow_up = deepcopy(follow_up)
            prepared_idempotency = deepcopy(idempotency)
            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.SESSION_PAUSED,
                claim,
                operation_correlation=idempotency.key,
            )
            assert realtime_event is not None

            self._claims[claim.claim_id] = prepared_claim
            self._store_session(prepared_session)
            self._follow_ups[follow_up.follow_up_id] = prepared_follow_up
            self._idempotency[lookup] = prepared_idempotency
            self._commit_realtime_event(realtime_event)

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
        with self._claim_mutation_lock:
            stored_claim = self._validate_claim_mutation(
                claim,
                expected_revision,
                allow_active_session_change=True,
            )
            records_match = (
                stored_claim.customer_id == claim.customer_id
                and claim.active_session_id == session.session_id
                and session.claim_id == claim.claim_id
                and session.customer_id == claim.customer_id
                and session.status is SessionStatus.ACTIVE
                and session.context_revision == expected_revision
                and idempotency.actor_id == claim.customer_id
                and idempotency.claim_id == claim.claim_id
                and idempotency.session_id == session.session_id
            )
            if not records_match:
                raise KeyError(claim.claim_id)
            if session.session_id in self._sessions:
                raise IdempotencyConflict(session.session_id)

            active_sessions = [
                existing
                for existing in self._sessions.values()
                if existing.claim_id == claim.claim_id
                and existing.customer_id == claim.customer_id
                and existing.status is SessionStatus.ACTIVE
            ]
            if replaced_active_session is None:
                if stored_claim.active_session_id is not None or active_sessions:
                    raise KeyError(claim.claim_id)
            else:
                stored_replaced_session = self._sessions.get(replaced_active_session.session_id)
                if (
                    stored_claim.active_session_id != replaced_active_session.session_id
                    or stored_replaced_session is None
                    or stored_replaced_session.claim_id != claim.claim_id
                    or stored_replaced_session.customer_id != claim.customer_id
                    or stored_replaced_session.status is not SessionStatus.ACTIVE
                    or replaced_active_session.status is not SessionStatus.CLOSED
                    or replaced_active_session.closed_at is None
                    or any(
                        existing.session_id != replaced_active_session.session_id
                        for existing in active_sessions
                    )
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

            open_recovery = [
                record
                for record in self._follow_ups.values()
                if record.claim_id == claim.claim_id
                and record.purpose == 'resume_incomplete_claim'
                and record.status in {FollowUpStatus.PENDING, FollowUpStatus.BLOCKED}
            ]
            if open_recovery and resolved_follow_up is None:
                raise KeyError(claim.claim_id)
            if resolved_follow_up is not None:
                stored_follow_up = self._follow_ups.get(resolved_follow_up.follow_up_id)
                if (
                    stored_follow_up is None
                    or stored_follow_up not in open_recovery
                    or resolved_follow_up.status is not FollowUpStatus.RESOLVED
                    or resolved_follow_up.outcome != 'claimant_resumed'
                    or resolved_follow_up.reason_code is not FollowUpReasonCode.CLAIMANT_RESUMED
                    or resolved_follow_up.updated_at < stored_follow_up.updated_at
                ):
                    raise KeyError(claim.claim_id)
                expected_follow_up = stored_follow_up.model_copy(
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
                    stored_follow_up.deadline_at is not None
                    and resolved_follow_up.updated_at >= stored_follow_up.deadline_at
                ):
                    raise RecoveryDeadlineConflict(stored_follow_up.follow_up_id)

                open_operations = [
                    operation
                    for operation in self._follow_up_operations.values()
                    if operation.follow_up_id == stored_follow_up.follow_up_id
                    and operation.claim_id == claim.claim_id
                    and operation.status
                    in {
                        FollowUpOperationStatus.SCHEDULED,
                        FollowUpOperationStatus.COMMITTED,
                    }
                ]

                if reconciled_follow_up_operation is None:
                    if open_operations:
                        raise KeyError(claim.claim_id)
                else:
                    if (
                        len(open_operations) != 1
                        or open_operations[0].operation_id
                        != reconciled_follow_up_operation.operation_id
                    ):
                        raise KeyError(claim.claim_id)

                    try:
                        assert_follow_up_operation_transition(
                            open_operations[0],
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
                )
            else:
                if audit_event is not None:
                    raise KeyError(claim.claim_id)
                prepared_audit = ()

            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            if self._idempotency.get(lookup) is not None:
                raise IdempotencyConflict(idempotency.key)
            self._validate_branch_evaluation(claim, branch_evaluation)

            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.SESSION_CHANGED,
                claim,
                operation_correlation=idempotency.key,
            )
            assert realtime_event is not None
            self._claims[claim.claim_id] = deepcopy(claim)
            if replaced_active_session is not None:
                self._store_session(replaced_active_session)
            self._store_session(session)
            if resolved_follow_up is not None:
                self._follow_ups[resolved_follow_up.follow_up_id] = deepcopy(resolved_follow_up)
            if reconciled_follow_up_operation is not None:
                self._follow_up_operations[reconciled_follow_up_operation.operation_id] = deepcopy(
                    reconciled_follow_up_operation
                )
            if branch_evaluation is not None:
                self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(
                    branch_evaluation
                )
            self._idempotency[lookup] = deepcopy(idempotency)

            for event in prepared_audit:
                self._audit_events[event.event_id] = deepcopy(event)

            self._commit_realtime_event(realtime_event)

    def _validate_branch_evaluation(
        self,
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
        if branch_evaluation.evaluation_id in self._branch_evaluations:
            raise IdempotencyConflict(branch_evaluation.evaluation_id)

    def get_active_session(self, claim_id: str, customer_id: str) -> SessionRecord | None:
        claim = self.get_claim(claim_id, customer_id)
        if claim is None or claim.active_session_id is None:
            return None
        return self.get_session(claim_id, claim.active_session_id, customer_id)

    def list_sessions_for_claim(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[SessionRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        sessions = [
            deepcopy(session)
            for session in self._sessions.values()
            if session.claim_id == claim_id and session.customer_id == customer_id
        ]
        return sorted(sessions, key=lambda session: session.started_at)

    def find_idempotency(
        self,
        actor_id: str,
        route: str,
        key: str,
    ) -> IdempotencyRecord | None:
        with self._claim_mutation_lock:
            record = self._idempotency.get((actor_id, route, key))

            if record is None:
                return None

            # Retention may already have tombstoned the WorkingClaim, so
            # claimant replay closure cannot depend on the live Claim record.
            # Only claimant idempotency is retired by retention.
            if record.retired:
                operation_id = self._retention_operation_by_claim.get(record.claim_id)

                operation = (
                    self._retention_operations.get(operation_id)
                    if operation_id is not None
                    else None
                )

                if retention_access_closed(operation):
                    raise ResourceAccessClosed(record.claim_id)

            return deepcopy(record)

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

        with self._claim_mutation_lock:
            if self._claimant_actor_access_closed(
                claim_id,
                actor_id,
            ):
                raise ResourceAccessClosed(claim_id)

            matches = [
                record
                for record in self._idempotency.values()
                if record.actor_id == actor_id
                and record.route == route
                and record.claim_id == claim_id
                and record.message_id == message_id
                and not record.retired
            ]

            return (
                deepcopy(
                    max(
                        matches,
                        key=message_turn_result_priority,
                    )
                )
                if matches
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
        with self._claim_mutation_lock:
            if self._claimant_actor_access_closed(claim_id, actor_id):
                raise ResourceAccessClosed(claim_id)
            original = self.find_message_turn_idempotency(
                actor_id,
                route,
                claim_id,
                message_id,
            )
            if original is None:
                return None
            if original.request_fingerprint != request_fingerprint:
                raise IdempotencyConflict(key)
            alias = replace(
                original,
                key=key,
                request_fingerprint=request_fingerprint,
            )
            lookup = (actor_id, route, key)
            existing = self._idempotency.get(lookup)
            if existing is not None:
                if existing != alias:
                    raise IdempotencyConflict(key)
                return deepcopy(existing)
            self._idempotency[lookup] = alias
            return deepcopy(alias)

    def save_idempotency(self, record: IdempotencyRecord) -> None:
        if record.claim_id and self._claimant_actor_access_closed(
            record.claim_id,
            record.actor_id,
        ):
            raise ResourceAccessClosed(record.claim_id)
        with self._claim_mutation_lock:
            lookup = (record.actor_id, record.route, record.key)
            existing = self._idempotency.get(lookup)
            if existing is not None and (
                existing.request_fingerprint != record.request_fingerprint or existing.retired
            ):
                raise IdempotencyConflict(record.key)
            self._idempotency[lookup] = deepcopy(record)

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

        matches = [
            item
            for item in self._idempotency.values()
            if item.claim_id == claim_id
            and item.actor_id == customer_id
            and item.message_id == message_id
            and item.revision_before_message is not None
            and item.inbound_checkpoint
        ]

        return (
            deepcopy(
                min(
                    matches,
                    key=lambda item: item.revision_before_message or 0,
                )
            )
            if matches
            else None
        )

    def save_message_recovery(
        self,
        message: MessageRecord,
        idempotency: IdempotencyRecord,
        *,
        agent_message: MessageRecord | None = None,
    ) -> None:
        with self._claim_mutation_lock:
            self._ensure_claim_access_open(message.claim_id)
            stored = self.get_message(
                message.claim_id, message.session_id, message.message_id, idempotency.actor_id
            )
            existing = self.find_idempotency(
                idempotency.actor_id, idempotency.route, idempotency.key
            )
            if (
                stored is None
                or stored.model_copy(update={'recovery_rule_id': message.recovery_rule_id})
                != message
            ):
                raise IdempotencyConflict(message.message_id)
            if (
                existing is None
                or existing.request_fingerprint != idempotency.request_fingerprint
                or existing.message_id != message.message_id
                or existing.claim_id != message.claim_id
                or existing.session_id != message.session_id
                or existing.response_payload is not None
                or existing.decision_id is not None
                or idempotency.message_id != message.message_id
                or message.actor is not ActorType.CLAIMANT
            ):
                raise IdempotencyConflict(idempotency.key)
            if agent_message is not None and (
                agent_message.actor is not ActorType.AGENT
                or agent_message.claim_id != message.claim_id
                or agent_message.session_id != message.session_id
                or agent_message.in_reply_to != message.message_id
                or agent_message.recovery_rule_id != message.recovery_rule_id
                or agent_message.recovery_rule_id is None
                or idempotency.agent_message_id != agent_message.message_id
                or agent_message.message_id in self._messages
            ):
                raise IdempotencyConflict(agent_message.message_id)
            self._store_message(message)
            if agent_message is not None:
                self._store_message(agent_message)
            self._idempotency[(idempotency.actor_id, idempotency.route, idempotency.key)] = (
                deepcopy(idempotency)
            )

    def list_claims_for_customer(
        self,
        customer_id: str,
    ) -> list[WorkingClaim]:
        claims = [
            deepcopy(claim)
            for claim in self._claims.values()
            if claim.customer_id == customer_id and not self._claim_access_closed(claim.claim_id)
        ]

        return sorted(
            claims,
            key=lambda claim: claim.created_at,
        )

    def freeze_message_response(
        self, idempotency: IdempotencyRecord, response_payload: dict[str, Any]
    ) -> dict[str, Any]:
        with self._claim_mutation_lock:
            if idempotency.claim_id:
                self._ensure_claim_access_open(idempotency.claim_id)
            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            saved = self._idempotency.get(lookup)
            if (
                saved is None
                or saved.request_fingerprint != idempotency.request_fingerprint
                or saved.claim_id != idempotency.claim_id
                or saved.session_id != idempotency.session_id
                or saved.message_id != idempotency.message_id
                or saved.decision_id != idempotency.decision_id
                or saved.decision_id is None
                or saved.claim_id is None
                or self.get_claim(saved.claim_id, saved.actor_id) is None
                or response_payload.get('claim_id') != saved.claim_id
                or response_payload.get('session_id') != saved.session_id
            ):
                raise IdempotencyConflict(idempotency.key)
            if saved.response_payload is not None:
                return deepcopy(saved.response_payload)
            self._idempotency[lookup] = replace(
                saved, response_status=200, response_payload=deepcopy(response_payload)
            )
            return deepcopy(response_payload)

    def list_claims_internal(self) -> list[WorkingClaim]:
        return sorted(
            (deepcopy(claim) for claim in self._claims.values()),
            key=lambda claim: claim.updated_at,
            reverse=True,
        )

    def search_claims_internal(
        self, filters: dict[str, object], limit: int
    ) -> list[StaffClaimSearchCandidate]:
        """Apply registered Claim filters before returning a bounded candidate set."""
        matches: list[StaffClaimSearchCandidate] = []
        for claim in sorted(self._claims.values(), key=lambda item: item.updated_at, reverse=True):
            candidate = build_staff_claim_search_candidate(
                claim,
                [item for item in self._evidence.values() if item.claim_id == claim.claim_id],
                [item for item in self._handoffs.values() if item.claim_id == claim.claim_id],
            )
            if not staff_claim_search_matches(candidate, filters):
                continue
            matches.append(candidate.model_copy(deep=True))
            if len(matches) >= limit:
                break
        return matches

    def search_sessions_internal(
        self,
        claim_id: str,
        customer_id: str,
        filters: dict[str, object],
        limit: int,
    ) -> list[StaffSessionSearchCandidate]:
        """Search only a bounded Claim-scoped Session and message set."""

        if self.get_claim(claim_id, customer_id) is None:
            return []
        session_ids = self._session_ids_by_claim.get((claim_id, customer_id), [])
        matches: list[StaffSessionSearchCandidate] = []
        for examined, session_id in enumerate(
            session_ids[: STAFF_SESSION_MAX_EXAMINED + 1], start=1
        ):
            if examined > STAFF_SESSION_MAX_EXAMINED:
                raise RepositorySearchLimitExceeded(
                    'The Session search exceeded its maximum examined set; narrow the filters.'
                )
            session = self._sessions[session_id]
            session_filter = filters.get('session_id')
            if session_filter and session.session_id != session_filter:
                continue
            if (
                filters.get('started_date')
                and str(filters['started_date']) != session.started_at.date().isoformat()
            ):
                continue
            if filters.get('status') and str(filters['status']) != session.status.value:
                continue
            message_ids = self._message_ids_by_session.get(session.session_id, [])
            if len(message_ids) > STAFF_SESSION_MESSAGE_MAX_EXAMINED:
                raise RepositorySearchLimitExceeded(
                    'The Session message search exceeded its maximum examined set; '
                    'narrow the filters.'
                )
            messages = [self._messages[message_id] for message_id in message_ids]
            if not staff_session_search_matches(session, messages, filters):
                continue
            matches.append(
                StaffSessionSearchCandidate(
                    session=deepcopy(session),
                    message_count=len(messages),
                )
            )
            if len(matches) >= limit:
                break
        return matches

    def save_message(self, message: MessageRecord, customer_id: str) -> None:
        with self._claim_mutation_lock:
            claim = self._claims.get(message.claim_id)
            session = self._sessions.get(message.session_id)
            if (
                claim is None
                or claim.customer_id != customer_id
                or session is None
                or session.claim_id != message.claim_id
                or session.customer_id != customer_id
            ):
                raise KeyError(message.claim_id)
            existing = self._messages.get(message.message_id)
            if existing is not None:
                if existing == message:
                    self._prepare_realtime_mutation(
                        RealtimeMutation.MESSAGE_CHANGED,
                        claim,
                        MutationOutcome.EXACT_NOOP,
                        claimant_visible=message.visibility is not MessageVisibility.INTERNAL_ONLY,
                    )
                    return
                raise IdempotencyConflict(message.message_id)
            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.MESSAGE_CHANGED,
                claim,
                claimant_visible=message.visibility is not MessageVisibility.INTERNAL_ONLY,
            )
            assert realtime_event is not None
            self._store_message(message)
            self._commit_realtime_event(realtime_event)

    def save_staff_agent_session(self, session: StaffAgentSession) -> None:
        existing = self._staff_agent_sessions.get(session.session_id)
        if existing is not None and existing != session:
            raise IdempotencyConflict(session.session_id)
        self._staff_agent_sessions[session.session_id] = deepcopy(session)

    def get_staff_agent_session(self, session_id: str, staff_id: str) -> StaffAgentSession | None:
        session = self._staff_agent_sessions.get(session_id)
        if session is None or session.staff_id != staff_id:
            return None
        return deepcopy(session)

    def list_staff_agent_sessions(self, staff_id: str) -> list[StaffAgentSession]:
        return deepcopy(
            [item for item in self._staff_agent_sessions.values() if item.staff_id == staff_id]
        )

    def list_staff_agent_messages(self, session_id: str, staff_id: str) -> list[StaffAgentMessage]:
        if self.get_staff_agent_session(session_id, staff_id) is None:
            return []
        return deepcopy(
            [
                item
                for item in self._staff_agent_messages.values()
                if item.session_id == session_id and item.staff_id == staff_id
            ]
        )

    def get_staff_agent_execution(
        self, execution_id: str, staff_id: str
    ) -> StaffAgentExecutionRecord | None:
        execution = self._staff_agent_executions.get(execution_id)
        if execution is None or execution.staff_id != staff_id:
            return None
        return deepcopy(execution)

    def _validate_staff_agent_execution_source(
        self, execution: StaffAgentExecutionRecord | None
    ) -> None:
        if execution is None:
            return
        validate_staff_agent_execution_source(
            execution,
            self._staff_agent_sessions.get(execution.session_id),
            self._staff_agent_messages.get(execution.message_id),
        )

    def find_staff_agent_message_by_client_id(
        self, session_id: str, staff_id: str, client_message_id: str
    ) -> StaffAgentMessage | None:
        return deepcopy(
            next(
                (
                    item
                    for item in self._staff_agent_messages.values()
                    if item.session_id == session_id
                    and item.staff_id == staff_id
                    and item.client_message_id == client_message_id
                ),
                None,
            )
        )

    def save_staff_agent_turn(
        self,
        session: StaffAgentSession,
        staff_message: StaffAgentMessage,
        assistant_message: StaffAgentMessage,
    ) -> None:
        stored = self.get_staff_agent_session(session.session_id, session.staff_id)
        if stored is None:
            raise KeyError(session.session_id)
        if (
            staff_message.session_id != session.session_id
            or assistant_message.session_id != session.session_id
            or staff_message.staff_id != session.staff_id
            or assistant_message.staff_id != session.staff_id
            or assistant_message.in_reply_to != staff_message.message_id
        ):
            raise KeyError(session.session_id)
        for message in (staff_message, assistant_message):
            existing = self._staff_agent_messages.get(message.message_id)
            if existing is not None and existing != message:
                raise IdempotencyConflict(message.message_id)
        duplicate = self.find_staff_agent_message_by_client_id(
            session.session_id,
            session.staff_id,
            staff_message.client_message_id or '',
        )
        if duplicate is not None and duplicate.message_id != staff_message.message_id:
            raise IdempotencyConflict(staff_message.client_message_id or '')
        self._staff_agent_sessions[session.session_id] = deepcopy(session)
        self._staff_agent_messages[staff_message.message_id] = deepcopy(staff_message)
        self._staff_agent_messages[assistant_message.message_id] = deepcopy(assistant_message)

    def save_message_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        message: MessageRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        stored_claim = self._validate_claim_mutation(claim, expected_revision)
        stored_session = self._sessions.get(session.session_id)
        records_match = (
            stored_session is not None
            and stored_claim.active_session_id == session.session_id
            and stored_session.claim_id == claim.claim_id
            and stored_session.customer_id == claim.customer_id
            and stored_session.status is SessionStatus.ACTIVE
            and claim.active_session_id == session.session_id
            and session.claim_id == claim.claim_id
            and session.customer_id == claim.customer_id
            and session.status is SessionStatus.ACTIVE
            and session.context_revision == claim.revision
            and message.claim_id == claim.claim_id
            and message.session_id == session.session_id
            and message.actor is ActorType.CLAIMANT
            and idempotency.actor_id == claim.customer_id
            and idempotency.claim_id == claim.claim_id
            and idempotency.session_id == session.session_id
            and idempotency.message_id == message.message_id
        )
        if not records_match:
            raise KeyError(claim.claim_id)
        if message.message_id in self._messages:
            raise IdempotencyConflict(message.message_id)
        if message.client_message_id is not None and any(
            existing.claim_id == claim.claim_id
            and existing.client_message_id == message.client_message_id
            for existing in self._messages.values()
        ):
            raise IdempotencyConflict(message.client_message_id)
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing = self._idempotency.get(lookup)
        if existing is not None and existing.request_fingerprint != idempotency.request_fingerprint:
            raise IdempotencyConflict(idempotency.key)
        self._preflight_messages((message,), sessions=(session,))
        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.MESSAGE_MUTATION_COMMITTED,
            claim,
            operation_correlation=idempotency.key,
            resources=realtime_resources_for_records(
                RealtimeMutation.MESSAGE_MUTATION_COMMITTED,
                ('message',),
            ),
        )
        assert realtime_event is not None
        self._claims[claim.claim_id] = deepcopy(claim)
        self._store_session(session)
        self._store_message(message)
        self._idempotency[lookup] = deepcopy(idempotency)
        self._commit_realtime_event(realtime_event)

    def get_message(
        self,
        claim_id: str,
        session_id: str,
        message_id: str,
        customer_id: str,
    ) -> MessageRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        message = self._messages.get(message_id)
        if message is None or message.claim_id != claim_id or message.session_id != session_id:
            return None
        return deepcopy(message)

    def find_message_by_client_id(
        self,
        claim_id: str,
        client_message_id: str,
        customer_id: str,
    ) -> MessageRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        for message in self._messages.values():
            if message.claim_id == claim_id and message.client_message_id == client_message_id:
                return deepcopy(message)
        return None

    def list_messages(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> list[MessageRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        messages = [
            deepcopy(message)
            for message in self._messages.values()
            if message.claim_id == claim_id and message.session_id == session_id
        ]
        return order_messages(messages)

    def list_recent_messages(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
        limit: int,
    ) -> list[MessageRecord]:
        if self.get_session(claim_id, session_id, customer_id) is None:
            return []
        message_ids = self._message_ids_by_session.get(session_id, [])[-limit:]
        return [deepcopy(self._messages[message_id]) for message_id in message_ids]

    def save_conversation_summary(
        self,
        summary: VerifiedConversationSummary,
        customer_id: str,
    ) -> None:
        if self.get_session(summary.claim_id, summary.session_id, customer_id) is None:
            raise KeyError(summary.session_id)
        existing = self._conversation_summaries.get(summary.summary_id)
        if existing is not None and existing != summary:
            raise IdempotencyConflict(summary.summary_id)
        self._conversation_summaries[summary.summary_id] = deepcopy(summary)

    def get_latest_conversation_summary(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> VerifiedConversationSummary | None:
        if self.get_session(claim_id, session_id, customer_id) is None:
            return None
        matches = [
            item
            for item in self._conversation_summaries.values()
            if item.claim_id == claim_id and item.session_id == session_id
        ]
        if not matches:
            return None
        return deepcopy(max(matches, key=lambda item: (item.created_at, item.summary_id)))

    def save_agent_decision(self, decision: AgentDecisionRecord, customer_id: str) -> None:
        if (
            self.get_claim(decision.claim_id, customer_id) is None
            or self.get_session(
                decision.claim_id,
                decision.session_id,
                customer_id,
            )
            is None
        ):
            raise KeyError(decision.claim_id)
        self._decisions[decision.decision_id] = deepcopy(decision)

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
        existing = self._branch_evaluations.get(evaluation.evaluation_id)
        if existing is not None:
            if existing == evaluation:
                return
            raise IdempotencyConflict(evaluation.evaluation_id)
        self._branch_evaluations[evaluation.evaluation_id] = deepcopy(evaluation)

    def list_branch_evaluations(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[BranchEvaluationRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        return sorted(
            (
                deepcopy(record)
                for record in self._branch_evaluations.values()
                if record.claim_id == claim_id
            ),
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
        operation = self._claim_creation_operations.get(operation_id)
        return deepcopy(operation) if operation is not None else None

    def reserve_claim_creation_operation(
        self,
        operation: ClaimCreationOperationRecord,
    ) -> bool:
        with self._claim_mutation_lock:
            claim = self._claims.get(operation.claim_id)
            decision = self._decisions.get(operation.authorised_decision_id)
            evidence = [
                record
                for record in self._evidence.values()
                if record.claim_id == operation.claim_id
            ]
            if (
                operation.status is not ClaimCreationOperationStatus.PREPARED
                or claim is None
                or claim.customer_id != operation.customer_id
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

            existing_for_claim = next(
                (
                    item
                    for item in self._claim_creation_operations.values()
                    if item.claim_id == operation.claim_id
                ),
                None,
            )
            if existing_for_claim is not None:
                if existing_for_claim.operation_id != operation.operation_id:
                    raise IdempotencyConflict(operation.operation_id)
                if existing_for_claim.status is ClaimCreationOperationStatus.RETRYABLE_FAILURE:
                    try:
                        assert_claim_creation_operation_transition(existing_for_claim, operation)
                    except ValueError as conflict:
                        raise IdempotencyConflict(operation.operation_id) from conflict
                    self._claim_creation_operations[operation.operation_id] = deepcopy(operation)
                    return True
                if (
                    existing_for_claim.request_fingerprint != operation.request_fingerprint
                    or existing_for_claim.evidence_snapshot_fingerprint
                    != operation.evidence_snapshot_fingerprint
                    or existing_for_claim.route != operation.route
                    or existing_for_claim.integration_source is not operation.integration_source
                ):
                    raise IdempotencyConflict(operation.operation_id)
                return False

            self._claim_creation_operations[operation.operation_id] = deepcopy(operation)
            return True

    def save_claim_creation_operation(
        self,
        operation: ClaimCreationOperationRecord,
    ) -> None:
        with self._claim_mutation_lock:
            current = self._claim_creation_operations.get(operation.operation_id)
            if current is None:
                raise KeyError(operation.operation_id)
            try:
                assert_claim_creation_operation_transition(current, operation)
            except ValueError as conflict:
                raise IdempotencyConflict(operation.operation_id) from conflict
            self._claim_creation_operations[operation.operation_id] = deepcopy(operation)

    def save_claim_creation_outcome(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        operation: ClaimCreationOperationRecord,
        branch_evaluation: BranchEvaluationRecord,
    ) -> None:
        with self._claim_mutation_lock:
            self._validate_claim_mutation(claim, expected_revision)
            self._validate_branch_evaluation(claim, branch_evaluation)
            current = self._claim_creation_operations.get(operation.operation_id)
            evidence = [
                record for record in self._evidence.values() if record.claim_id == claim.claim_id
            ]
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
            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                claim,
                operation_correlation=operation.operation_id,
            )
            assert realtime_event is not None
            self._claims[claim.claim_id] = deepcopy(claim)
            self._claim_creation_operations[operation.operation_id] = deepcopy(operation)
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
            self._commit_realtime_event(realtime_event)

    def get_assessor_routing_operation(
        self,
        operation_id: str,
    ) -> AssessorRoutingOperation | None:
        operation = self._assessor_routing_operations.get(operation_id)
        return deepcopy(operation) if operation is not None else None

    def save_assessor_routing_operation(
        self,
        operation: AssessorRoutingOperation,
    ) -> None:
        claim = self._claims.get(operation.claim_id)
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

        existing = self._assessor_routing_operations.get(operation.operation_id)
        if existing is None:
            if operation.status is not AssessorRoutingOperationStatus.PREPARED:
                raise IdempotencyConflict(operation.operation_id)
            self._assessor_routing_operations[operation.operation_id] = deepcopy(operation)
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
        if any(
            getattr(existing, field_name) != getattr(operation, field_name)
            for field_name in immutable_identity
        ):
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
        self._assessor_routing_operations[operation.operation_id] = deepcopy(operation)

    def save_assessor_routing_settlement(
        self,
        operation: AssessorRoutingOperation,
        task: ExternalTaskRecord,
        attempt: ExternalTaskAttempt,
        customer_id: str,
    ) -> None:
        """Atomically persist an assessor outcome and its attempt in fixture storage."""
        with self._claim_mutation_lock:
            operations = deepcopy(self._assessor_routing_operations)
            tasks = deepcopy(self._external_tasks)
            attempts = deepcopy(self._external_task_attempts)
            events = deepcopy(self._realtime_events)
            sequence = self._realtime_sequence
            try:
                self.save_assessor_routing_operation(operation)
                self.save_external_task(task, customer_id)
                self.save_external_task_attempt(attempt, customer_id)
            except Exception:
                self._assessor_routing_operations = operations
                self._external_tasks = tasks
                self._external_task_attempts = attempts
                self._realtime_events = events
                self._realtime_sequence = sequence
                raise

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
        """Atomically settle one unknown assessor operation in fixture storage.

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
            required_staff_revision: Exact presence revision guarded by the write.

        Returns:
            None.

        Raises:
            RevisionConflict: The stored Claim revision changed first.
            IdempotencyConflict: Stored identity or lifecycle state conflicts.
            KeyError: A record is missing, belongs elsewhere, or is malformed.
        """

        with self._claim_mutation_lock:
            validate_evidence_record(evidence)
            current_claim = self._validate_claim_mutation(claim, expected_revision)
            if (staff_action is None) is not (idempotency is None):
                raise KeyError(claim.claim_id)
            presence = None
            if staff_action is not None and idempotency is not None:
                presence = self._staff_presence.get(required_staff_id or '')
                if (
                    required_staff_id is None
                    or presence is None
                    or not presence.is_claimable(datetime.now(UTC))
                    or (
                        required_staff_revision is not None
                        and presence.revision != required_staff_revision
                    )
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
                lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
                if lookup in self._idempotency or staff_action.action_id in self._staff_actions:
                    raise IdempotencyConflict(idempotency.key)
            current_task = self._external_tasks.get(task.task_id)
            current_operation = self._assessor_routing_operations.get(operation.operation_id)
            if (
                current_claim.customer_id != customer_id
                or current_task is None
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
            held_evidence = self._evidence.get(evidence.evidence_id)
            held_link = self._external_task_evidence_links.get((link.claim_id, link.evidence_id))
            if (held_evidence is not None and held_evidence != evidence) or (
                held_link is not None and held_link != link
            ):
                raise IdempotencyConflict(evidence.evidence_id)
            self._validate_branch_evaluation(claim, branch_evaluation)

            held_request = self._external_task_requests.get(request.request_id)
            if held_request is None or held_request.claim_id != claim.claim_id:
                raise KeyError(request.request_id)

            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.ASSESSOR_RECONCILED,
                claim,
                operation_correlation=(idempotency.key if idempotency is not None else None),
                resources=realtime_resources_for_records(
                    RealtimeMutation.ASSESSOR_RECONCILED,
                    ('staff_action',) if staff_action is not None else (),
                ),
            )
            assert realtime_event is not None

            self._claims[claim.claim_id] = deepcopy(claim)
            self._external_tasks[task.task_id] = deepcopy(task)
            self._assessor_routing_operations[operation.operation_id] = deepcopy(operation)
            self._external_task_requests[request.request_id] = deepcopy(request)
            self._store_evidence(evidence)
            self._external_task_evidence_links[(link.claim_id, link.evidence_id)] = deepcopy(link)
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
            if staff_action is not None and idempotency is not None and presence is not None:
                self._staff_actions[staff_action.action_id] = deepcopy(staff_action)
                self._idempotency[(idempotency.actor_id, idempotency.route, idempotency.key)] = (
                    deepcopy(idempotency)
                )
                if required_staff_revision is not None:
                    self._staff_presence[required_staff_id or ''] = deepcopy(
                        presence.model_copy(update={'revision': presence.revision + 1})
                    )
            self._commit_realtime_event(realtime_event)

    def save_assessor_routing_preparation(
        self,
        operation: AssessorRoutingOperation,
        decision: AgentDecisionRecord,
        customer_id: str,
        audit_events: tuple[AuditEventEnvelope, ...] = (),
    ) -> None:
        claim = self._claims.get(operation.claim_id)
        session = self._sessions.get(decision.session_id)
        external_claim_id = (
            claim.external_claim.external_claim_id
            if claim is not None
            and claim.external_claim is not None
            and claim.external_claim.external_claim_id is not None
            else operation.claim_id
        )
        if (
            claim is None
            or claim.customer_id != customer_id
            or claim.active_session_id != decision.session_id
            or session is None
            or session.claim_id != claim.claim_id
            or session.customer_id != customer_id
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

        prepared_audit = self._prepare_audit_events(claim, audit_events)
        existing_operation = self._assessor_routing_operations.get(operation.operation_id)
        existing_decision = self._decisions.get(decision.decision_id)
        if existing_operation is not None or existing_decision is not None:
            if existing_operation == operation and existing_decision == decision:
                for event in prepared_audit:
                    self._audit_events[event.event_id] = deepcopy(event)
                return
            raise IdempotencyConflict(operation.operation_id)

        self._decisions[decision.decision_id] = deepcopy(decision)
        self._assessor_routing_operations[operation.operation_id] = deepcopy(operation)
        for event in prepared_audit:
            self._audit_events[event.event_id] = deepcopy(event)

    def get_agent_decision(
        self,
        claim_id: str,
        decision_id: str,
        customer_id: str,
    ) -> AgentDecisionRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        decision = self._decisions.get(decision_id)
        if decision is None or decision.claim_id != claim_id:
            return None
        return deepcopy(decision)

    def get_agent_decision_internal(
        self,
        claim_id: str,
        decision_id: str,
    ) -> AgentDecisionRecord | None:
        decision = self._decisions.get(decision_id)
        if decision is None or decision.claim_id != claim_id:
            return None
        return deepcopy(decision)

    def find_agent_decision_for_trigger(
        self,
        claim_id: str,
        trigger_message_id: str,
        customer_id: str,
    ) -> AgentDecisionRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        for decision in self._decisions.values():
            if decision.claim_id == claim_id and decision.trigger_message_id == trigger_message_id:
                return deepcopy(decision)
        return None

    def list_agent_decisions(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[AgentDecisionRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        decisions = [
            deepcopy(decision)
            for decision in self._decisions.values()
            if decision.claim_id == claim_id
        ]
        return sorted(
            decisions,
            key=lambda decision: (
                decision.resulting_revision,
                decision.created_at,
                decision.decision_id,
            ),
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
        review_signals: Sequence[ReviewSignalRecord] | None = None,
    ) -> None:
        stored_claim = self._validate_claim_mutation(claim, expected_revision)
        incoming_signals: dict[str, ReviewSignalRecord] = {}
        for signal in review_signals or ():
            if signal.claim_id != claim.claim_id:
                raise KeyError(claim.claim_id)
            if signal.signal_id in incoming_signals or signal.signal_id in self._review_signals:
                raise IdempotencyConflict(signal.signal_id)
            incoming_signals[signal.signal_id] = signal
        stored_session = self._sessions.get(session.session_id)
        existing_claimant_message = self._messages.get(claimant_message.message_id)
        existing_agent_message = self._messages.get(agent_message.message_id)
        existing_decision = self._decisions.get(decision.decision_id)
        existing_handoff = self._handoffs.get(handoff.handoff_id) if handoff is not None else None
        if handoff is not None:
            from backend.repositories.handoff_guard import validate_runtime_handoff_update

            validate_runtime_handoff_update(
                existing_handoff, handoff, claim, claimant_message, decision
            )
        existing_evidence = (
            self._evidence.get(evidence.evidence_id) if evidence is not None else None
        )
        existing_children = (
            existing_claimant_message,
            existing_agent_message,
            existing_decision,
            existing_handoff,
            existing_evidence,
            self._runtime_traces.get(runtime_trace.trace_id) if runtime_trace is not None else None,
        )
        child_ownership_matches = all(
            existing is None or existing.claim_id == claim.claim_id
            for existing in existing_children
        )
        records_match = (
            child_ownership_matches
            and claimant_message.message_id != agent_message.message_id
            and stored_claim.customer_id == claim.customer_id
            and stored_session is not None
            and stored_session.claim_id == claim.claim_id
            and stored_session.customer_id == claim.customer_id
            and stored_session.status is SessionStatus.ACTIVE
            and stored_claim.active_session_id == session.session_id
            and claim.active_session_id == session.session_id
            and session.status is SessionStatus.ACTIVE
            and claim.customer_id == session.customer_id
            and idempotency.actor_id == claim.customer_id
            and claim.claim_id == session.claim_id
            and claim.claim_id == claimant_message.claim_id
            and claim.claim_id == agent_message.claim_id
            and claim.claim_id == decision.claim_id
            and session.session_id == claimant_message.session_id
            and session.session_id == agent_message.session_id
            and session.session_id == decision.session_id
            and session.context_revision == claim.revision
            and decision.resulting_revision == claim.revision
            and claimant_message.actor is ActorType.CLAIMANT
            and agent_message.actor is ActorType.AGENT
            and claimant_message.message_id == decision.trigger_message_id
            and claimant_message.message_id == agent_message.in_reply_to
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
                runtime_trace is None
                or (
                    runtime_trace.claim_id == claim.claim_id
                    and runtime_trace.session_id == session.session_id
                    and runtime_trace.trigger_message_id == claimant_message.message_id
                )
            )
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
        existing_branch_evaluation = (
            self._branch_evaluations.get(branch_evaluation.evaluation_id)
            if branch_evaluation is not None
            else None
        )
        immutable_collision = next(
            (
                identity
                for identity, existing in (
                    (claimant_message.message_id, existing_claimant_message),
                    (agent_message.message_id, existing_agent_message),
                    (decision.decision_id, existing_decision),
                    (
                        branch_evaluation.evaluation_id if branch_evaluation is not None else '',
                        existing_branch_evaluation,
                    ),
                    (
                        runtime_trace.trace_id if runtime_trace is not None else '',
                        self._runtime_traces.get(runtime_trace.trace_id)
                        if runtime_trace is not None
                        else None,
                    ),
                )
                if existing is not None
                and not (checkpointed and identity == claimant_message.message_id)
            ),
            None,
        )
        if immutable_collision is not None:
            raise IdempotencyConflict(immutable_collision)
        duplicate_client_message = next(
            (
                message
                for message in self._messages.values()
                if message.claim_id == claim.claim_id
                and message.client_message_id == claimant_message.client_message_id
            ),
            None,
        )
        if duplicate_client_message is not None and not checkpointed:
            raise IdempotencyConflict(claimant_message.client_message_id or '')
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing_idempotency = self._idempotency.get(lookup)
        if checkpointed and (
            existing_claimant_message != claimant_message
            or existing_idempotency is None
            or existing_idempotency.message_id != claimant_message.message_id
            or existing_idempotency.decision_id is not None
            or existing_idempotency.response_payload is not None
        ):
            raise IdempotencyConflict(idempotency.key)
        if (
            existing_idempotency is not None
            and existing_idempotency.request_fingerprint != idempotency.request_fingerprint
        ):
            raise IdempotencyConflict(idempotency.key)

        pending_evidence = (evidence,) if evidence is not None else ()
        for item in pending_evidence:
            validate_evidence_record(item)
        self._preflight_messages(
            (claimant_message, agent_message),
            sessions=(session,),
            evidence=pending_evidence,
        )

        public_messages = all(
            item.visibility is not MessageVisibility.INTERNAL_ONLY
            for item in (claimant_message, agent_message)
        )
        changed_record_kinds = ['message', 'message']
        changed_record_kinds.extend('review_signal' for _ in incoming_signals)
        if handoff is not None:
            changed_record_kinds.append('handoff')
        if evidence is not None:
            changed_record_kinds.append('evidence')
        if runtime_records is not None:
            changed_record_kinds.extend('runtime_work_item' for _ in runtime_records.work_items)
        resources = realtime_resources_for_records(
            RealtimeMutation.AGENT_TURN_COMMITTED,
            tuple(changed_record_kinds),
        )
        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.AGENT_TURN_COMMITTED,
            claim,
            operation_correlation=idempotency.key,
            resources=resources,
            claimant_resources=(
                claimant_resources_for(
                    RealtimeMutation.AGENT_TURN_COMMITTED,
                    resources=resources,
                )
                if public_messages
                else claimant_resources_for(
                    RealtimeMutation.AGENT_TURN_COMMITTED,
                    resources=resources,
                    excluded=frozenset({RealtimeResource.MESSAGES}),
                )
            ),
        )
        assert realtime_event is not None
        self._claims[claim.claim_id] = deepcopy(claim)
        self._store_session(session)
        if not checkpointed:
            self._store_message(claimant_message)
        self._store_message(agent_message)
        self._decisions[decision.decision_id] = deepcopy(decision)
        for signal in incoming_signals.values():
            self._review_signals[signal.signal_id] = deepcopy(signal)
        if handoff is not None:
            self._handoffs[handoff.handoff_id] = deepcopy(handoff)
        if evidence is not None:
            self._store_evidence(evidence)
        if branch_evaluation is not None:
            if branch_evaluation.evaluation_id in self._branch_evaluations:
                raise IdempotencyConflict(branch_evaluation.evaluation_id)
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
        if runtime_trace is not None:
            self._runtime_traces[runtime_trace.trace_id] = deepcopy(runtime_trace)
        if runtime_records is not None:
            existing_runtime = self._runtime_turns.get(runtime_records.turn_plan.turn_id)
            if existing_runtime is not None and existing_runtime != runtime_records:
                raise IdempotencyConflict(runtime_records.turn_plan.turn_id)
            self._runtime_turns[runtime_records.turn_plan.turn_id] = deepcopy(runtime_records)
        self._idempotency[lookup] = idempotency
        self._commit_realtime_event(realtime_event)

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
        """Persist a namespaced read-only turn without changing Claim revision."""
        stored_claim = self._claims.get(claim.claim_id)
        stored_session = self._sessions.get(session.session_id)
        if stored_claim is None:
            raise KeyError(claim.claim_id)
        if stored_claim.revision != expected_revision:
            raise RevisionConflict(stored_claim.revision)
        records_match = (
            claim == stored_claim
            and stored_session is not None
            and stored_session.claim_id == claim.claim_id
            and stored_session.customer_id == claim.customer_id
            and stored_session.status is SessionStatus.ACTIVE
            and session.status is SessionStatus.ACTIVE
            and session.claim_id == claim.claim_id
            and session.customer_id == claim.customer_id
            and session.context_revision == claim.revision
            and claim.active_session_id == session.session_id
            and claimant_message.claim_id == claim.claim_id
            and agent_message.claim_id == claim.claim_id
            and claimant_message.session_id == session.session_id
            and agent_message.session_id == session.session_id
            and claimant_message.actor is ActorType.CLAIMANT
            and agent_message.actor is ActorType.AGENT
            and agent_message.in_reply_to == claimant_message.message_id
            and runtime_trace.claim_id == claim.claim_id
            and runtime_trace.session_id == session.session_id
            and runtime_trace.trigger_message_id == claimant_message.message_id
            and idempotency.actor_id == claim.customer_id
            and idempotency.claim_id == claim.claim_id
            and idempotency.session_id == session.session_id
            and idempotency.message_id == claimant_message.message_id
            and idempotency.agent_message_id == agent_message.message_id
            and idempotency.runtime_trace_id == runtime_trace.trace_id
            and idempotency.decision_id is None
        )
        if not records_match:
            raise KeyError(claim.claim_id)
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing_idempotency = self._idempotency.get(lookup)
        if existing_idempotency is not None:
            if (
                existing_idempotency.request_fingerprint == idempotency.request_fingerprint
                and stored_session == session
                and self._messages.get(claimant_message.message_id) == claimant_message
                and self._messages.get(agent_message.message_id) == agent_message
                and self._runtime_traces.get(runtime_trace.trace_id) == runtime_trace
            ):
                self._prepare_realtime_mutation(
                    RealtimeMutation.RUNTIME_TURN_COMMITTED,
                    claim,
                    MutationOutcome.EXACT_NOOP,
                    operation_correlation=idempotency.key,
                )
                return
            raise IdempotencyConflict(idempotency.key)
        if any(
            existing is not None
            for existing in (
                self._messages.get(claimant_message.message_id),
                self._messages.get(agent_message.message_id),
                self._runtime_traces.get(runtime_trace.trace_id),
            )
        ):
            raise IdempotencyConflict(runtime_trace.trace_id)
        duplicate_client_message = next(
            (
                message
                for message in self._messages.values()
                if message.claim_id == claim.claim_id
                and message.client_message_id == claimant_message.client_message_id
            ),
            None,
        )
        if duplicate_client_message is not None:
            raise IdempotencyConflict(claimant_message.client_message_id or '')
        self._preflight_messages(
            (claimant_message, agent_message),
            sessions=(session,),
        )
        public_messages = all(
            item.visibility is not MessageVisibility.INTERNAL_ONLY
            for item in (claimant_message, agent_message)
        )
        resources = realtime_resources_for_records(
            RealtimeMutation.RUNTIME_TURN_COMMITTED,
            ('message', 'message', 'runtime_trace'),
        )
        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.RUNTIME_TURN_COMMITTED,
            claim,
            operation_correlation=idempotency.key,
            resources=resources,
            claimant_resources=(
                claimant_resources_for(
                    RealtimeMutation.RUNTIME_TURN_COMMITTED,
                    resources=resources,
                )
                if public_messages
                else claimant_resources_for(
                    RealtimeMutation.RUNTIME_TURN_COMMITTED,
                    resources=resources,
                    excluded=frozenset({RealtimeResource.MESSAGES}),
                )
            ),
        )
        assert realtime_event is not None
        self._store_session(session)
        self._store_message(claimant_message)
        self._store_message(agent_message)
        self._runtime_traces[runtime_trace.trace_id] = deepcopy(runtime_trace)
        self._idempotency[lookup] = deepcopy(idempotency)
        self._commit_realtime_event(realtime_event)

    def get_runtime_trace(
        self,
        claim_id: str,
        trace_id: str,
        customer_id: str,
    ) -> RuntimeTraceRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        trace = self._runtime_traces.get(trace_id)
        if trace is None or trace.claim_id != claim_id:
            return None
        return deepcopy(trace)

    def get_runtime_turn_for_trigger(
        self,
        claim_id: str,
        trigger_message_id: str,
        customer_id: str,
    ) -> RuntimeTurnRecords | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        matches = [
            record
            for record in self._runtime_turns.values()
            if record.turn_plan.claim_id == claim_id
            and record.turn_plan.trigger_message_id == trigger_message_id
        ]
        return deepcopy(matches[-1]) if matches else None

    def list_runtime_work_items(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[RuntimeWorkItemRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        items = [
            item
            for turn in self._runtime_turns.values()
            for item in turn.work_items
            if item.claim_id == claim_id
        ]
        items.extend(
            item
            for item in self._standalone_runtime_work_items.values()
            if item.claim_id == claim_id
        )
        return deepcopy(
            sorted(
                items,
                key=lambda item: (
                    item.updated_at,
                    item.work_item_id,
                ),
            )
        )

    def save_runtime_work_item(
        self,
        item: RuntimeWorkItemRecord,
        customer_id: str,
    ) -> None:
        with self._claim_mutation_lock:
            claim = self._claims.get(item.claim_id)

            if claim is None or claim.customer_id != customer_id:
                raise KeyError(item.claim_id)

            existing = self._standalone_runtime_work_items.get(item.work_item_id)

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

                self._standalone_runtime_work_items[item.work_item_id] = deepcopy(item)
                return

            self._standalone_runtime_work_items[item.work_item_id] = deepcopy(item)

    def find_runtime_trace_for_trigger(
        self,
        claim_id: str,
        trigger_message_id: str,
        customer_id: str,
    ) -> RuntimeTraceRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        matches = [
            trace
            for trace in self._runtime_traces.values()
            if trace.claim_id == claim_id and trace.trigger_message_id == trigger_message_id
        ]
        if not matches:
            return None
        return deepcopy(max(matches, key=lambda trace: (trace.created_at, trace.trace_id)))

    def save_evidence(self, evidence: EvidenceRecord, customer_id: str) -> None:
        claim = self._claims.get(evidence.claim_id)
        if claim is None or claim.customer_id != customer_id:
            raise KeyError(evidence.claim_id)
        validate_evidence_record(evidence)
        existing = self._evidence.get(evidence.evidence_id)
        try:
            assert_material_history_is_append_only(existing, evidence)
        except ValueError as conflict:
            raise IdempotencyConflict(evidence.evidence_id) from conflict
        if existing == evidence:
            self._prepare_realtime_mutation(
                RealtimeMutation.EVIDENCE_CHANGED,
                claim,
                MutationOutcome.EXACT_NOOP,
            )
            return
        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.EVIDENCE_CHANGED,
            claim,
        )
        assert realtime_event is not None
        self._store_evidence(evidence)
        self._commit_realtime_event(realtime_event)

    def get_evidence(
        self,
        claim_id: str,
        evidence_id: str,
        customer_id: str,
    ) -> EvidenceRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        evidence = self._evidence.get(evidence_id)
        if evidence is None or evidence.claim_id != claim_id:
            return None
        return deepcopy(evidence)

    def list_evidence(self, claim_id: str, customer_id: str) -> list[EvidenceRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        evidence_records = [
            deepcopy(evidence)
            for evidence in self._evidence.values()
            if evidence.claim_id == claim_id
        ]
        return sorted(evidence_records, key=lambda evidence: evidence.created_at)

    def list_evidence_for_customer(
        self,
        customer_id: str,
    ) -> list[EvidenceRecord]:
        claims = {
            claim.claim_id
            for claim in self._claims.values()
            if claim.customer_id == customer_id and not self._claim_access_closed(claim.claim_id)
        }

        evidence_records = [
            deepcopy(evidence)
            for evidence in self._evidence.values()
            if evidence.claim_id in claims and evidence.source.value == 'claimant'
        ]

        return sorted(
            evidence_records,
            key=lambda evidence: (
                evidence.created_at,
                evidence.evidence_id,
            ),
        )

    def list_evidence_recovery_page(
        self, after_evidence_id: str | None = None, limit: int = 10
    ) -> list[EvidenceRecord]:
        """Discover a bounded internal page using the persistence port contract.

        Args:
            after_evidence_id: Exclusive Evidence identity cursor.
            limit: Page size clamped to 1 through 50.
        Returns:
            Detached Evidence records in strictly increasing identity order.
        Raises:
            ValueError: If stored Evidence has an inconsistent identity.
        """
        with self._claim_mutation_lock:
            identifiers = sorted(
                identifier
                for identifier in self._evidence
                if after_evidence_id is None or identifier > after_evidence_id
            )[: max(1, min(limit, 50))]
            records = [deepcopy(self._evidence[identifier]) for identifier in identifiers]
            if any(
                record.evidence_id != identifier
                for record, identifier in zip(records, identifiers, strict=True)
            ):
                raise ValueError('Stored Evidence identity does not match its recovery cursor.')
            return records

    def get_motor_other_driver(
        self, claim_id: str, customer_id: str
    ) -> MotorOtherDriverRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        record = self._motor_other_drivers.get(claim_id)
        return deepcopy(record) if record is not None else None

    def save_motor_other_driver_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        participant: MotorOtherDriverRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        with self._claim_mutation_lock:
            self._validate_claim_mutation(claim, expected_revision)
            if (
                claim.incident_type != 'motor'
                or participant.claim_id != claim.claim_id
                or participant.customer_id != claim.customer_id
                or idempotency.actor_id != claim.customer_id
                or idempotency.claim_id != claim.claim_id
                or idempotency.session_id != (claim.active_session_id or '')
                or claim.claim_id in self._motor_other_drivers
            ):
                raise IdempotencyConflict(participant.participant_id)
            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            if lookup in self._idempotency:
                raise IdempotencyConflict(idempotency.key)
            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                claim,
                operation_correlation=idempotency.key,
            )
            assert realtime_event is not None
            self._claims[claim.claim_id] = deepcopy(claim)
            self._motor_other_drivers[claim.claim_id] = deepcopy(participant)
            self._idempotency[lookup] = deepcopy(idempotency)
            self._commit_realtime_event(realtime_event)

    def list_contents_item_evidence_associations(
        self, claim_id: str, customer_id: str
    ) -> list[ContentsItemEvidenceAssociation]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        return sorted(
            (
                deepcopy(record)
                for record in self._contents_item_evidence_associations.values()
                if record.claim_id == claim_id and record.customer_id == customer_id
            ),
            key=lambda record: (record.created_at, record.association_id),
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
        )

        if self.get_claim(claim_id, customer_id) is None:
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
        records = sorted(
            (
                deepcopy(record)
                for record in self._contents_item_evidence_associations.values()
                if record.claim_id == claim_id
                and record.customer_id == customer_id
                and record.item_id == item_id
                and (
                    after is None
                    or (record.created_at, record.association_id)
                    > (after.created_at, after.association_id)
                )
            ),
            key=lambda record: (record.created_at, record.association_id),
        )
        page = records[: limit + 1]
        selected = page[:limit]
        next_cursor = None
        if len(page) > limit:
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
        with self._claim_mutation_lock:
            self._validate_claim_mutation(claim, expected_revision)
            evidence = self._evidence.get(association.evidence_id)
            if (
                association.claim_id != claim.claim_id
                or association.customer_id != claim.customer_id
                or not any(item.item_id == association.item_id for item in claim.contents_items)
                or evidence is None
                or evidence.claim_id != claim.claim_id
                or idempotency.actor_id != claim.customer_id
                or idempotency.claim_id != claim.claim_id
                or idempotency.session_id != (claim.active_session_id or '')
                or association.association_id in self._contents_item_evidence_associations
                or any(
                    held.claim_id == claim.claim_id
                    and held.item_id == association.item_id
                    and held.evidence_id == association.evidence_id
                    for held in self._contents_item_evidence_associations.values()
                )
            ):
                raise IdempotencyConflict(association.association_id)
            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            if lookup in self._idempotency:
                raise IdempotencyConflict(idempotency.key)
            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.CLAIM_CHANGED,
                claim,
                operation_correlation=idempotency.key,
            )
            assert realtime_event is not None
            self._claims[claim.claim_id] = deepcopy(claim)
            self._contents_item_evidence_associations[association.association_id] = deepcopy(
                association
            )
            self._idempotency[lookup] = deepcopy(idempotency)
            self._commit_realtime_event(realtime_event)

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

        link = self._evidence_claim_links.get((target_claim_id, evidence_id))

        if (
            link is None
            or link.customer_id != customer_id
            or not self.claimant_resource_access_open(
                link.source_claim_id,
                customer_id,
            )
        ):
            return None

        return deepcopy(link)

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

        return sorted(
            (
                deepcopy(link)
                for link in self._evidence_claim_links.values()
                if link.customer_id == customer_id
                and (target_claim_id is None or link.target_claim_id == target_claim_id)
                and self.claimant_resource_access_open(
                    link.source_claim_id,
                    customer_id,
                )
                and self.claimant_resource_access_open(
                    link.target_claim_id,
                    customer_id,
                )
            ),
            key=lambda link: (
                link.created_at,
                link.link_id,
            ),
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
        with self._claim_mutation_lock:
            if evidence is not None:
                validate_evidence_record(evidence)
            self._validate_claim_mutation(claim, expected_revision)
            self._validate_branch_evaluation(claim, branch_evaluation)
            prepared = self._prepare_audit_events(claim, (audit_event,))
            if (
                idempotency.actor_id != claim.customer_id
                or idempotency.claim_id != claim.claim_id
                or idempotency.session_id != (claim.active_session_id or '')
            ):
                raise KeyError(claim.claim_id)
            if evidence is not None:
                source_claim = self._claims.get(evidence.claim_id)
                if source_claim is None or source_claim.customer_id != claim.customer_id:
                    raise KeyError(evidence.evidence_id)
            if link is not None and (
                link.target_claim_id != claim.claim_id or link.customer_id != claim.customer_id
            ):
                raise KeyError(link.link_id)
            if link is not None:
                source_evidence = self._evidence.get(link.evidence_id)
                source_claim = self._claims.get(link.source_claim_id)
                if (
                    source_evidence is None
                    or source_evidence.claim_id != link.source_claim_id
                    or source_claim is None
                    or source_claim.customer_id != claim.customer_id
                ):
                    raise KeyError(link.evidence_id)
            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            existing = self._idempotency.get(lookup)
            if existing is not None:
                raise IdempotencyConflict(idempotency.key)
            realtime_event = self._prepare_realtime_mutation(
                RealtimeMutation.EVIDENCE_CLAIM_CHANGED,
                claim,
                operation_correlation=idempotency.key,
                resources=realtime_resources_for_records(
                    RealtimeMutation.EVIDENCE_CLAIM_CHANGED,
                    tuple(
                        kind
                        for kind, present in (
                            ('evidence', evidence is not None),
                            ('evidence_claim_link', link is not None),
                        )
                        if present
                    ),
                ),
            )
            assert realtime_event is not None
            self._claims[claim.claim_id] = deepcopy(claim)
            if evidence is not None:
                self._store_evidence(evidence)
            if link is not None:
                self._evidence_claim_links[(link.target_claim_id, link.evidence_id)] = deepcopy(
                    link
                )
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
            self._idempotency[lookup] = idempotency
            for event in prepared:
                self._audit_events[event.event_id] = deepcopy(event)
            self._commit_realtime_event(realtime_event)

    def save_evidence_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        evidence: EvidenceRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        self._validate_claim_mutation(claim, expected_revision)
        validate_evidence_record(evidence)
        self._validate_branch_evaluation(claim, branch_evaluation)
        existing_evidence = self._evidence.get(evidence.evidence_id)
        if (
            evidence.claim_id != claim.claim_id
            or (existing_evidence is not None and existing_evidence.claim_id != claim.claim_id)
            or idempotency.claim_id != claim.claim_id
            or idempotency.actor_id != claim.customer_id
            or idempotency.session_id != (claim.active_session_id or '')
        ):
            raise KeyError(claim.claim_id)
        try:
            assert_material_history_is_append_only(existing_evidence, evidence)
        except ValueError as conflict:
            raise IdempotencyConflict(evidence.evidence_id) from conflict
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing_idempotency = self._idempotency.get(lookup)
        if (
            existing_idempotency is not None
            and existing_idempotency.request_fingerprint != idempotency.request_fingerprint
        ):
            raise IdempotencyConflict(idempotency.key)

        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.EVIDENCE_CLAIM_CHANGED,
            claim,
            operation_correlation=idempotency.key,
            resources=realtime_resources_for_records(
                RealtimeMutation.EVIDENCE_CLAIM_CHANGED,
                ('evidence',),
            ),
        )
        assert realtime_event is not None
        self._claims[claim.claim_id] = deepcopy(claim)
        self._store_evidence(evidence)
        if branch_evaluation is not None:
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
        self._idempotency[lookup] = idempotency
        self._commit_realtime_event(realtime_event)

    def save_external_task(self, task: ExternalTaskRecord, customer_id: str) -> None:
        """Create or advance one claim-owned external task.

        Args:
            task: External task state to create or advance.
            customer_id: Customer who owns the parent claim.

        Returns:
            None.

        Raises:
            KeyError: The claim is missing or not owned by the customer.
            IdempotencyConflict: The write changes immutable identity or is stale.
        """
        if self.get_claim(task.claim_id, customer_id) is None:
            raise KeyError(task.claim_id)
        existing = self._external_tasks.get(task.task_id)
        if existing is not None and existing.claim_id != task.claim_id:
            raise IdempotencyConflict(task.task_id)
        if existing == task:
            self._prepare_realtime_mutation(
                RealtimeMutation.EXTERNAL_TASK_CHANGED,
                self._claims[task.claim_id],
                MutationOutcome.EXACT_NOOP,
            )
            return
        immutable_identity = (
            'claim_id',
            'service_identity',
            'requested_action',
            'integration_source',
            'created_at',
        )
        if existing is not None and existing != task:
            changed_identity = any(
                getattr(existing, name) != getattr(task, name) for name in immutable_identity
            )
            if changed_identity or task.updated_at <= existing.updated_at:
                raise IdempotencyConflict(task.task_id)
        assert_external_task_registry_compatible(task)
        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.EXTERNAL_TASK_CHANGED,
            self._claims[task.claim_id],
        )
        assert realtime_event is not None
        self._external_tasks[task.task_id] = deepcopy(task)
        self._commit_realtime_event(realtime_event)

    def reserve_external_dispatch(
        self,
        claim_id: str,
        request_id: str,
        customer_id: str,
        reserved_at: datetime,
        operation_id: str,
    ) -> ExternalTaskRequest | None:
        """Atomically claim the sole right to dispatch one prepared request.

        The read and the write are inside the claim mutation lock together, because a
        reservation that could be read by one caller and written by another is not a
        reservation.

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

        with self._claim_mutation_lock:
            request = self._held_request(claim_id, request_id, customer_id)
            if request.dispatch_reserved_at is not None:
                return None
            reserved = request.model_copy(
                update={'dispatch_reserved_at': reserved_at, 'operation_id': operation_id}
            )
            self._external_task_requests[request_id] = deepcopy(reserved)
            return reserved

    def save_external_task_attempt(
        self,
        attempt: ExternalTaskAttempt,
        customer_id: str,
    ) -> None:
        """Append one claim-owned attempt without replacing prior history."""
        with self._claim_mutation_lock:
            if self.get_claim(attempt.claim_id, customer_id) is None:
                raise KeyError(attempt.claim_id)
            task = self._external_tasks.get(attempt.task_id)
            if task is None or task.claim_id != attempt.claim_id:
                raise KeyError(attempt.task_id)
            request = next(
                (
                    item
                    for item in self._external_task_requests.values()
                    if item.task_id == attempt.task_id
                ),
                None,
            )
            if request is None or request.operation_id != attempt.operation_id:
                raise KeyError(attempt.operation_id)
            existing = self._external_task_attempts.get(attempt.attempt_id)
            if existing is not None:
                if existing != attempt:
                    raise IdempotencyConflict(attempt.attempt_id)
                return
            for stored in self._external_task_attempts.values():
                if (
                    stored.task_id == attempt.task_id
                    and stored.attempt_number == attempt.attempt_number
                ):
                    raise IdempotencyConflict(attempt.attempt_id)
            prior = [
                stored.attempt_number
                for stored in self._external_task_attempts.values()
                if stored.task_id == attempt.task_id
            ]
            expected_number = max(prior, default=0) + 1
            if attempt.attempt_number != expected_number:
                raise IdempotencyConflict(attempt.attempt_id)
            self._external_task_attempts[attempt.attempt_id] = deepcopy(attempt)

    def save_external_task_settlement(
        self,
        task: ExternalTaskRecord,
        attempt: ExternalTaskAttempt,
        customer_id: str,
    ) -> None:
        """Atomically persist a generic task outcome and its attempt in fixture storage."""
        with self._claim_mutation_lock:
            tasks = deepcopy(self._external_tasks)
            attempts = deepcopy(self._external_task_attempts)
            events = deepcopy(self._realtime_events)
            sequence = self._realtime_sequence
            try:
                self.save_external_task(task, customer_id)
                self.save_external_task_attempt(attempt, customer_id)
            except Exception:
                self._external_tasks = tasks
                self._external_task_attempts = attempts
                self._realtime_events = events
                self._realtime_sequence = sequence
                raise

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

        with self._claim_mutation_lock:
            request = self._held_request(claim_id, request_id, customer_id)
            if request.dispatch_reserved_at is None:
                return
            released = request.model_copy(update={'dispatch_reserved_at': None})
            self._external_task_requests[request_id] = deepcopy(released)

    def _held_request(
        self,
        claim_id: str,
        request_id: str,
        customer_id: str,
    ) -> ExternalTaskRequest:
        if self.get_claim(claim_id, customer_id) is None:
            raise KeyError(claim_id)
        request = self._external_task_requests.get(request_id)
        if request is None or request.claim_id != claim_id:
            raise KeyError(request_id)
        return request

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
        task = self._external_tasks.get(request.task_id)
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
        decision = self._decisions.get(request.authorisation.northwind_authority_ref)
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
        for held in self._external_task_requests.values():
            if held.task_id == request.task_id and held.request_id != request.request_id:
                raise IdempotencyConflict(request.task_id)
        existing = self._external_task_requests.get(request.request_id)
        if existing == request:
            self._prepare_realtime_mutation(
                RealtimeMutation.EXTERNAL_REQUEST_CHANGED,
                claim,
                MutationOutcome.EXACT_NOOP,
                operation_correlation=request.operation_id,
            )
            return
        if existing is not None and existing != request:
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
            # The reservation records the operation identity before the send, so a
            # first send now advances a record that may already carry it. What must not
            # change is which operation it names.
            first_send = (
                existing.sent_at is None
                and request.sent_at is not None
                and request.operation_id is not None
                and existing.operation_id in {None, request.operation_id}
            )
            if changed_identity or not first_send:
                raise IdempotencyConflict(request.request_id)
        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.EXTERNAL_REQUEST_CHANGED,
            claim,
            operation_correlation=request.operation_id,
        )
        assert realtime_event is not None
        self._external_task_requests[request.request_id] = deepcopy(request)
        self._commit_realtime_event(realtime_event)

    def list_external_task_requests_internal(
        self,
        claim_id: str,
    ) -> list[ExternalTaskRequest]:
        """List request records for an already-authorised internal claim read.

        Args:
            claim_id: Working Claim whose requests are requested.

        Returns:
            Deep-copied requests in stable preparation order.

        Raises:
            RuntimeError: The in-memory fixture cannot complete the read.
        """
        requests = [
            deepcopy(request)
            for request in self._external_task_requests.values()
            if request.claim_id == claim_id
        ]
        return sorted(requests, key=lambda request: (request.prepared_at, request.request_id))

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
        if self.get_claim(link.claim_id, customer_id) is None:
            raise KeyError(link.claim_id)
        task = self._external_tasks.get(link.task_id)
        if task is None or task.claim_id != link.claim_id:
            raise KeyError(link.task_id)
        if self.get_evidence(link.claim_id, link.evidence_id, customer_id) is None:
            raise KeyError(link.evidence_id)
        key = (link.claim_id, link.evidence_id)
        existing = self._external_task_evidence_links.get(key)
        if existing is not None and existing != link:
            raise IdempotencyConflict(link.evidence_id)
        claim = self._claims[link.claim_id]
        if existing == link:
            self._prepare_realtime_mutation(
                RealtimeMutation.EXTERNAL_EVIDENCE_LINKED,
                claim,
                MutationOutcome.EXACT_NOOP,
            )
            return
        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.EXTERNAL_EVIDENCE_LINKED,
            claim,
        )
        assert realtime_event is not None
        self._external_task_evidence_links[key] = deepcopy(link)
        self._commit_realtime_event(realtime_event)

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
        if self.get_claim(result.claim_id, customer_id) is None:
            raise KeyError(result.claim_id)
        task = self._external_tasks.get(result.task_id)
        if task is None:
            raise KeyError(result.task_id)
        # The domain already decides which task states can carry an answer and how a
        # result reaches its material. Re-deciding either here would be a second,
        # quietly different rule.
        try:
            assert_result_matches_task(result, task)
            assert_result_evidence_is_linked(
                result,
                [
                    link
                    for link in self._external_task_evidence_links.values()
                    if link.evidence_id in result.evidence_ids
                ],
            )
        except ValueError as mismatch:
            raise KeyError(result.task_id) from mismatch
        for evidence_id in result.evidence_ids:
            if self.get_evidence(result.claim_id, evidence_id, customer_id) is None:
                raise KeyError(evidence_id)

        held = next(
            (
                stored
                for stored in self._external_task_results.values()
                if stored.task_id == result.task_id
            ),
            None,
        )
        # A result identity belongs to one task for good, so a reused identifier is a
        # conflict even when the task it now names holds nothing.
        by_identity = self._external_task_results.get(result.result_id)
        if by_identity is not None and by_identity.task_id != result.task_id:
            raise IdempotencyConflict(result.result_id)
        if held is None:
            # Only the verification operation may record a check, so an answer arrives
            # unverified or not at all.
            if result.verification is not ExternalTaskResultVerification.UNVERIFIED:
                raise IdempotencyConflict(result.result_id)
        else:
            if held == result:
                self._prepare_realtime_mutation(
                    RealtimeMutation.EXTERNAL_RESULT_CHANGED,
                    self._claims[result.claim_id],
                    MutationOutcome.EXACT_NOOP,
                )
                return
            try:
                assert_result_advance_is_permitted(held, result)
            except ValueError as conflict:
                raise IdempotencyConflict(result.result_id) from conflict
        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.EXTERNAL_RESULT_CHANGED,
            self._claims[result.claim_id],
        )
        assert realtime_event is not None
        self._external_task_results[result.result_id] = deepcopy(result)
        self._commit_realtime_event(realtime_event)

    def list_external_tasks_internal(self, claim_id: str) -> list[ExternalTaskRecord]:
        """List task records for an already-authorised internal claim read.

        Args:
            claim_id: Working Claim whose tasks are requested.

        Returns:
            Deep-copied tasks in stable creation order.

        Raises:
            RuntimeError: The in-memory fixture cannot complete the read.
        """
        tasks = [
            deepcopy(task) for task in self._external_tasks.values() if task.claim_id == claim_id
        ]
        return sorted(tasks, key=lambda task: (task.created_at, task.task_id))

    def list_external_task_attempts_internal(
        self,
        claim_id: str,
    ) -> list[ExternalTaskAttempt]:
        """Return immutable attempts in task/sequence order."""
        attempts = [
            deepcopy(attempt)
            for attempt in self._external_task_attempts.values()
            if attempt.claim_id == claim_id
        ]
        return sorted(
            attempts, key=lambda item: (item.task_id, item.attempt_number, item.attempt_id)
        )

    def list_external_task_results_internal(self, claim_id: str) -> list[ExternalTaskResult]:
        """List returned results for an already-authorised internal claim read.

        Args:
            claim_id: Working Claim whose external task results are requested.

        Returns:
            Deep-copied result records, oldest ingestion first.

        Raises:
            RuntimeError: The in-memory fixture cannot complete the read.
        """
        results = [
            deepcopy(result)
            for result in self._external_task_results.values()
            if result.claim_id == claim_id
        ]
        results.sort(key=lambda item: (item.received_at, item.result_id))
        return results

    def list_external_task_evidence_links_internal(
        self,
        claim_id: str,
    ) -> list[ExternalTaskEvidenceLink]:
        """List evidence-origin links for an authorised internal claim read.

        Args:
            claim_id: Working Claim whose evidence links are requested.

        Returns:
            Deep-copied links in stable linkage order.

        Raises:
            RuntimeError: The in-memory fixture cannot complete the read.
        """
        links = [
            deepcopy(link)
            for link in self._external_task_evidence_links.values()
            if link.claim_id == claim_id
        ]
        return sorted(links, key=lambda link: (link.linked_at, link.evidence_id, link.task_id))

    def save_retrieval_bundle(
        self,
        record: RetrievalRecord,
        review_signals: list[ReviewSignalRecord],
        customer_id: str,
    ) -> None:
        if self.get_claim(record.claim_id, customer_id) is None:
            raise KeyError(record.claim_id)
        if any(
            signal.claim_id != record.claim_id or record.retrieval_id not in signal.source_refs
            for signal in review_signals
        ):
            raise KeyError(record.claim_id)

        existing_record = self._retrievals.get(record.retrieval_id)
        if existing_record is not None and existing_record != record:
            raise IdempotencyConflict(record.retrieval_id)

        incoming_signals: dict[str, ReviewSignalRecord] = {}
        for signal in review_signals:
            incoming_signal = incoming_signals.get(signal.signal_id)
            if incoming_signal is not None and incoming_signal != signal:
                raise IdempotencyConflict(signal.signal_id)
            incoming_signals[signal.signal_id] = signal

        for signal in incoming_signals.values():
            existing_signal = self._review_signals.get(signal.signal_id)
            if existing_signal is not None and existing_signal != signal:
                raise IdempotencyConflict(signal.signal_id)

        self._retrievals[record.retrieval_id] = deepcopy(record)
        for signal in incoming_signals.values():
            self._review_signals[signal.signal_id] = deepcopy(signal)

    def list_retrieval_records(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[RetrievalRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        records = [
            deepcopy(record) for record in self._retrievals.values() if record.claim_id == claim_id
        ]
        return sorted(records, key=lambda record: (record.source.retrieved_at, record.retrieval_id))

    def list_review_signals(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[ReviewSignalRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        signals = [
            deepcopy(signal)
            for signal in self._review_signals.values()
            if signal.claim_id == claim_id
        ]
        return sorted(signals, key=lambda signal: (signal.created_at, signal.signal_id))

    def list_staff_actions(self, claim_id: str) -> list[StaffActionRecord]:
        return sorted(
            [deepcopy(item) for item in self._staff_actions.values() if item.claim_id == claim_id],
            key=lambda item: (item.created_at, item.action_id),
        )

    def get_staff_action(self, claim_id: str, action_id: str) -> StaffActionRecord | None:
        action = self._staff_actions.get(action_id)
        if action is None or action.claim_id != claim_id:
            return None
        return deepcopy(action)

    def list_customer_updates(self, claim_id: str) -> list[CustomerUpdateRecord]:
        return sorted(
            [
                deepcopy(item)
                for item in self._customer_updates.values()
                if item.claim_id == claim_id
            ],
            key=lambda item: (item.created_at, item.update_id),
        )

    def list_signal_decisions(self, claim_id: str) -> list[SignalDecisionRecord]:
        return sorted(
            [
                deepcopy(item)
                for item in self._signal_decisions.values()
                if item.claim_id == claim_id
            ],
            key=lambda item: (item.created_at, item.signal_decision_id),
        )

    def list_collaboration_requests(self, claim_id: str) -> list[ClaimCollaborationRequest]:
        return sorted(
            [
                deepcopy(item)
                for item in self._collaboration_requests.values()
                if item.claim_id == claim_id
            ],
            key=lambda item: (item.created_at, item.request_id),
        )

    def list_claim_coworkers(self, claim_id: str) -> list[ClaimCoworkerRecord]:
        return sorted(
            [
                deepcopy(item)
                for item in self._claim_coworkers.values()
                if item.claim_id == claim_id and item.active
            ],
            key=lambda item: (item.granted_at, item.coworker_id),
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
            self._validate_staff_agent_execution_source(staff_agent_execution)
        except ValueError as error:
            raise KeyError(claim.claim_id) from error
        self._validate_claim_mutation(claim, expected_revision)
        coworker_records = coworkers or []
        try:
            validate_handoff_mutation_audit(claim, handoff, idempotency, audit_event)
        except ValueError as error:
            raise KeyError(claim.claim_id) from error
        if (
            collaboration_request.claim_id != claim.claim_id
            or any(item.claim_id != claim.claim_id for item in coworker_records)
            or (handoff is not None and handoff.claim_id != claim.claim_id)
            or (handoff is not None and idempotency.handoff_id != handoff.handoff_id)
            or (handoff is None and idempotency.handoff_id is not None)
            or idempotency.claim_id != claim.claim_id
        ):
            raise KeyError(claim.claim_id)
        prepared_audit = (
            self._prepare_audit_events(claim, (audit_event,)) if audit_event is not None else ()
        )
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing_idempotency = self._idempotency.get(lookup)
        if existing_idempotency is not None:
            if existing_idempotency.request_fingerprint != idempotency.request_fingerprint:
                raise IdempotencyConflict(idempotency.key)
            self._prepare_realtime_mutation(
                RealtimeMutation.OWNERSHIP_CHANGED,
                claim,
                MutationOutcome.EXACT_NOOP,
                operation_correlation=idempotency.key,
            )
            return
        existing_request = self._collaboration_requests.get(collaboration_request.request_id)
        if existing_request is not None and existing_request.claim_id != claim.claim_id:
            raise IdempotencyConflict(collaboration_request.request_id)
        if (
            staff_agent_execution is not None
            and staff_agent_execution.execution_id in self._staff_agent_executions
        ):
            raise IdempotencyConflict(staff_agent_execution.execution_id)
        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.OWNERSHIP_CHANGED,
            claim,
            operation_correlation=idempotency.key,
            resources=realtime_resources_for_records(
                RealtimeMutation.OWNERSHIP_CHANGED,
                (
                    'collaboration_request',
                    *(('claim_coworker',) if coworker_records else ()),
                    *(('handoff',) if handoff is not None else ()),
                    *(('staff_agent_execution',) if staff_agent_execution is not None else ()),
                ),
            ),
        )
        assert realtime_event is not None
        self._claims[claim.claim_id] = deepcopy(claim)
        self._collaboration_requests[collaboration_request.request_id] = deepcopy(
            collaboration_request
        )
        for coworker in coworker_records:
            self._claim_coworkers[coworker.coworker_id] = deepcopy(coworker)
        if handoff is not None:
            self._handoffs[handoff.handoff_id] = deepcopy(handoff)
        if staff_agent_execution is not None:
            self._staff_agent_executions[staff_agent_execution.execution_id] = deepcopy(
                staff_agent_execution
            )
        self._idempotency[lookup] = deepcopy(idempotency)
        for event in prepared_audit:
            self._audit_events[event.event_id] = deepcopy(event)
        self._commit_realtime_event(realtime_event)

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
            self._validate_staff_agent_execution_source(staff_agent_execution)
        except ValueError as error:
            raise KeyError(claim.claim_id) from error
        stored_claim = self._validate_claim_mutation(claim, expected_revision)
        try:
            validate_handoff_mutation_audit(claim, handoff, idempotency, audit_event)
        except ValueError as error:
            raise KeyError(claim.claim_id) from error
        if required_staff_id is not None:
            presence = self._staff_presence.get(required_staff_id)
            if (
                presence is None
                or not presence.is_claimable(datetime.now(UTC))
                or (
                    required_staff_revision is not None
                    and presence.revision != required_staff_revision
                )
            ):
                raise KeyError('staff_not_available')
        if not any((staff_action, customer_update, signal_decision, handoff, message)):
            raise KeyError(claim.claim_id)
        records = (staff_action, customer_update, signal_decision, handoff, message)
        active_session_id = claim.active_session_id or ''
        stored_session = self._sessions.get(active_session_id) if message is not None else None
        existing_staff_action = (
            self._staff_actions.get(staff_action.action_id) if staff_action is not None else None
        )
        existing_customer_update = (
            self._customer_updates.get(customer_update.update_id)
            if customer_update is not None
            else None
        )
        existing_signal_decision = (
            self._signal_decisions.get(signal_decision.signal_decision_id)
            if signal_decision is not None
            else None
        )
        existing_handoff = self._handoffs.get(handoff.handoff_id) if handoff is not None else None
        existing_message = self._messages.get(message.message_id) if message is not None else None
        child_ownership_matches = all(
            existing is None or existing.claim_id == claim.claim_id
            for existing in (
                existing_staff_action,
                existing_customer_update,
                existing_signal_decision,
                existing_handoff,
                existing_message,
            )
        )
        records_match = (
            child_ownership_matches
            and all(item is None or item.claim_id == claim.claim_id for item in records)
            and idempotency.claim_id == claim.claim_id
            and idempotency.session_id in {'', active_session_id}
            and (
                staff_action is None
                or (
                    staff_action.status is not StaffActionStatus.COMPLETED
                    and staff_action.completed_by is None
                )
                or (
                    staff_action.status is StaffActionStatus.COMPLETED
                    and staff_action.completed_by == idempotency.actor_id
                )
            )
            and (customer_update is None or customer_update.created_by == idempotency.actor_id)
            and (signal_decision is None or signal_decision.actor_id == idempotency.actor_id)
            and (handoff is None or idempotency.handoff_id == handoff.handoff_id)
            and (
                message is None
                or (
                    stored_claim.active_session_id == active_session_id
                    and stored_session is not None
                    and stored_session.claim_id == claim.claim_id
                    and stored_session.customer_id == claim.customer_id
                    and stored_session.status is SessionStatus.ACTIVE
                    and message.actor is ActorType.STAFF
                    and message.session_id == active_session_id
                    and message.session_id == idempotency.session_id
                    and idempotency.message_id == message.message_id
                )
            )
        )
        if not records_match:
            raise KeyError(claim.claim_id)
        if (
            staff_agent_execution is not None
            and staff_agent_execution.execution_id in self._staff_agent_executions
        ):
            raise IdempotencyConflict(staff_agent_execution.execution_id)
        if existing_message is not None:
            raise IdempotencyConflict(message.message_id if message is not None else '')
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing = self._idempotency.get(lookup)
        if existing is not None and existing.request_fingerprint != idempotency.request_fingerprint:
            raise IdempotencyConflict(idempotency.key)
        if message is not None:
            assert stored_session is not None
            self._preflight_messages((message,), sessions=(stored_session,))
        prepared_audit = (
            self._prepare_audit_events(claim, (audit_event,)) if audit_event is not None else ()
        )
        excluded = (
            frozenset({RealtimeResource.MESSAGES})
            if message is not None and message.visibility is MessageVisibility.INTERNAL_ONLY
            else frozenset()
        )
        changed_record_kinds = tuple(
            kind
            for kind, present in (
                ('staff_action', staff_action is not None),
                ('customer_update', customer_update is not None),
                ('signal_decision', signal_decision is not None),
                ('handoff', handoff is not None),
                ('message', message is not None),
            )
            if present
        )
        resources = realtime_resources_for_records(
            RealtimeMutation.STAFF_MUTATION_COMMITTED,
            changed_record_kinds,
        )
        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.STAFF_MUTATION_COMMITTED,
            claim,
            operation_correlation=idempotency.key,
            resources=resources,
            claimant_resources=claimant_resources_for(
                RealtimeMutation.STAFF_MUTATION_COMMITTED,
                resources=resources,
                excluded=excluded,
            ),
        )
        assert realtime_event is not None
        if required_staff_id is not None and required_staff_revision is not None:
            assert presence is not None
            self._staff_presence[required_staff_id] = deepcopy(
                presence.model_copy(update={'revision': presence.revision + 1})
            )
        self._claims[claim.claim_id] = deepcopy(claim)
        if staff_action is not None:
            self._staff_actions[staff_action.action_id] = deepcopy(staff_action)
        if customer_update is not None:
            self._customer_updates[customer_update.update_id] = deepcopy(customer_update)
        if signal_decision is not None:
            self._signal_decisions[signal_decision.signal_decision_id] = deepcopy(signal_decision)
        if handoff is not None:
            self._handoffs[handoff.handoff_id] = deepcopy(handoff)
        if message is not None:
            self._store_message(message)
        if staff_agent_execution is not None:
            self._staff_agent_executions[staff_agent_execution.execution_id] = deepcopy(
                staff_agent_execution
            )
        self._idempotency[lookup] = deepcopy(idempotency)
        for event in prepared_audit:
            self._audit_events[event.event_id] = deepcopy(event)
        self._commit_realtime_event(realtime_event)

    def save_handoff(self, handoff: HandoffRecord, customer_id: str) -> None:
        claim = self._claims.get(handoff.claim_id)
        if claim is None or claim.customer_id != customer_id:
            raise KeyError(handoff.claim_id)
        existing = self._handoffs.get(handoff.handoff_id)
        if existing == handoff:
            self._prepare_realtime_mutation(
                RealtimeMutation.HANDOFF_CHANGED,
                claim,
                MutationOutcome.EXACT_NOOP,
            )
            return
        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.HANDOFF_CHANGED,
            claim,
        )
        assert realtime_event is not None
        self._handoffs[handoff.handoff_id] = deepcopy(handoff)
        self._commit_realtime_event(realtime_event)

    def get_handoff(
        self,
        claim_id: str,
        handoff_id: str,
        customer_id: str,
    ) -> HandoffRecord | None:
        if self.get_claim(claim_id, customer_id) is None:
            return None
        handoff = self._handoffs.get(handoff_id)
        if handoff is None or handoff.claim_id != claim_id:
            return None
        return deepcopy(handoff)

    def list_handoffs(self, claim_id: str, customer_id: str) -> list[HandoffRecord]:
        if self.get_claim(claim_id, customer_id) is None:
            return []
        handoffs = [
            deepcopy(handoff) for handoff in self._handoffs.values() if handoff.claim_id == claim_id
        ]
        return sorted(handoffs, key=lambda handoff: handoff.created_at)

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
        self._validate_claim_mutation(claim, expected_revision)
        self._validate_branch_evaluation(claim, branch_evaluation)
        prepared_audit = self._prepare_audit_events(claim, (audit_event,))
        existing_handoff = self._handoffs.get(handoff.handoff_id)
        if safety_message is not None:
            from backend.repositories.handoff_guard import validate_preprovider_safety_handoff

            validate_preprovider_safety_handoff(
                existing_handoff,
                handoff,
                claim,
                safety_message,
                self.get_message(
                    claim.claim_id,
                    safety_message.session_id,
                    safety_message.message_id,
                    claim.customer_id,
                ),
            )
        if (
            handoff.claim_id != claim.claim_id
            or (existing_handoff is not None and existing_handoff.claim_id != claim.claim_id)
            or idempotency.claim_id != claim.claim_id
            or idempotency.actor_id != claim.customer_id
            or idempotency.session_id != (claim.active_session_id or '')
            or idempotency.handoff_id != handoff.handoff_id
        ):
            raise KeyError(claim.claim_id)
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing_idempotency = self._idempotency.get(lookup)
        if (
            existing_idempotency is not None
            and existing_idempotency.request_fingerprint != idempotency.request_fingerprint
        ):
            raise IdempotencyConflict(idempotency.key)

        realtime_event = self._prepare_realtime_mutation(
            RealtimeMutation.HANDOFF_MUTATION_COMMITTED,
            claim,
            operation_correlation=idempotency.key,
            resources=realtime_resources_for_records(
                RealtimeMutation.HANDOFF_MUTATION_COMMITTED,
                ('handoff',),
            ),
        )
        assert realtime_event is not None
        self._claims[claim.claim_id] = deepcopy(claim)
        self._handoffs[handoff.handoff_id] = deepcopy(handoff)
        if branch_evaluation is not None:
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
        self._idempotency[lookup] = deepcopy(idempotency)
        for event in prepared_audit:
            self._audit_events[event.event_id] = deepcopy(event)
        self._commit_realtime_event(realtime_event)


def _serialize_material_claim_mutation(method_name: str) -> None:
    """Run one Fixture mutation under the lock with complete rollback on failure."""
    method = getattr(FixtureRepository, method_name)

    def serialized(self: FixtureRepository, *args: Any, **kwargs: Any) -> Any:
        with self._claim_mutation_lock:
            excluded = {'_validation_seed_lock', '_claim_mutation_lock', '_realtime_condition'}
            snapshot = {
                key: deepcopy(value, {id(self): self})
                for key, value in self.__dict__.items()
                if key not in excluded
            }
            try:
                return method(self, *args, **kwargs)
            except Exception:
                retained = {key: self.__dict__[key] for key in excluded}
                self.__dict__.clear()
                self.__dict__.update(snapshot)
                self.__dict__.update(retained)
                raise

    serialized.__name__ = method.__name__
    serialized.__qualname__ = method.__qualname__
    serialized.__doc__ = method.__doc__
    setattr(FixtureRepository, method_name, serialized)


for _material_claim_mutation in (
    'promote_claim_owner',
    'save_claim_mutation_with_audit',
    'save_message_mutation',
    'save_agent_turn',
    'save_runtime_turn',
    'save_assessor_reconciliation',
    'save_evidence',
    'save_evidence_action_mutation',
    'save_evidence_mutation',
    'save_external_task',
    'save_external_task_attempt',
    'save_external_task_request',
    'save_external_task_evidence_link',
    'save_external_task_result',
    'save_ownership_mutation',
    'save_staff_mutation',
    'save_handoff',
    'save_handoff_mutation',
):
    _serialize_material_claim_mutation(_material_claim_mutation)

del _material_claim_mutation
