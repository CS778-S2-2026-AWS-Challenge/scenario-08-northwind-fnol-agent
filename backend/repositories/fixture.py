from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any

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
    FollowUpRecord,
    FollowUpStatus,
    HandoffRecord,
    MessageRecord,
    RuntimeTraceRecord,
    SessionRecord,
    SessionStatus,
    SignalDecisionRecord,
    StaffActionRecord,
    StaffActionStatus,
    WorkingClaim,
)
from backend.domain.retrieval import RetrievalRecord, ReviewSignalRecord
from backend.domain.staff_agent import StaffAgentMessage, StaffAgentSession
from backend.domain.staff_identity import StaffPresenceRecord
from backend.repositories.protocols import (
    DemoSeedConflict,
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
    ValidationSeedGraph,
    validate_validation_seed_session,
)


class FixtureRepository(PersistenceRepository):
    """In-memory repository used by the prototype and replaceable contract tests."""

    def __init__(self) -> None:
        self._validation_seed_lock = RLock()
        self._claim_mutation_lock = RLock()
        self._claims: dict[str, WorkingClaim] = {}
        self._audit_events: dict[str, AuditEventEnvelope] = {}
        self._sessions: dict[str, SessionRecord] = {}
        self._follow_ups: dict[str, FollowUpRecord] = {}
        self._messages: dict[str, MessageRecord] = {}
        self._runtime_traces: dict[str, RuntimeTraceRecord] = {}
        self._staff_agent_sessions: dict[str, StaffAgentSession] = {}
        self._staff_agent_messages: dict[str, StaffAgentMessage] = {}
        self._decisions: dict[str, AgentDecisionRecord] = {}
        self._branch_evaluations: dict[str, BranchEvaluationRecord] = {}
        self._assessor_routing_operations: dict[str, AssessorRoutingOperation] = {}
        self._evidence: dict[str, EvidenceRecord] = {}
        self._external_tasks: dict[str, ExternalTaskRecord] = {}
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
        now = datetime.now(UTC)
        self._staff_presence['stf_demo'] = StaffPresenceRecord(
            staff_id='stf_demo',
            online=True,
            available=True,
            last_seen_at=now,
            expires_at=now + timedelta(minutes=5),
            updated_at=now,
        )

    def connection_status(self) -> str:
        return 'using_fixture'

    @property
    def claim_count(self) -> int:
        return len(self._claims)

    def reset_demo_state(self) -> dict[str, int]:
        """Clear only records owned by this in-memory prototype repository."""
        cleared = {
            'claims': len(self._claims),
            'audit_events': len(self._audit_events),
            'sessions': len(self._sessions),
            'follow_ups': len(self._follow_ups),
            'messages': len(self._messages),
            'runtime_traces': len(self._runtime_traces),
            'staff_agent_sessions': len(self._staff_agent_sessions),
            'staff_agent_messages': len(self._staff_agent_messages),
            'agent_decisions': len(self._decisions),
            'branch_evaluations': len(self._branch_evaluations),
            'assessor_routing_operations': len(self._assessor_routing_operations),
            'evidence': len(self._evidence),
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
        }
        self._claims.clear()
        self._audit_events.clear()
        self._sessions.clear()
        self._follow_ups.clear()
        self._messages.clear()
        self._runtime_traces.clear()
        self._staff_agent_sessions.clear()
        self._staff_agent_messages.clear()
        self._decisions.clear()
        self._branch_evaluations.clear()
        self._assessor_routing_operations.clear()
        self._evidence.clear()
        self._external_tasks.clear()
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
        self._claims[claim.claim_id] = deepcopy(claim)
        self._sessions[session.session_id] = deepcopy(session)

    def seed_validation_graph(self, graph: ValidationSeedGraph) -> IdempotencyRecord | None:
        """Serialize validation seeds so a same-key race cannot create two graphs."""
        with self._validation_seed_lock:
            return self._seed_validation_graph(graph)

    def _seed_validation_graph(self, graph: ValidationSeedGraph) -> IdempotencyRecord | None:
        """Persist validation records as one rollback-safe fixture operation."""
        snapshot = {
            key: deepcopy(value)
            for key, value in self.__dict__.items()
            if key not in {'_validation_seed_lock', '_claim_mutation_lock'}
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
            for message in graph.messages:
                self.save_message(message, claims_by_id[message.claim_id].customer_id)
            self.save_idempotency(graph.idempotency)
        except Exception:
            validation_seed_lock = self._validation_seed_lock
            claim_mutation_lock = self._claim_mutation_lock
            self.__dict__.clear()
            self.__dict__.update(snapshot)
            self._validation_seed_lock = validation_seed_lock
            self._claim_mutation_lock = claim_mutation_lock
            raise
        return None

    def get_claim(self, claim_id: str, customer_id: str) -> WorkingClaim | None:
        claim = self._claims.get(claim_id)
        if claim is None or claim.customer_id != customer_id:
            return None
        return deepcopy(claim)

    def promote_claim_owner(
        self,
        claim_id: str,
        anonymous_customer_id: str,
        customer_id: str,
    ) -> WorkingClaim | None:
        claim = self._claims.get(claim_id)
        if claim is None or claim.customer_id != anonymous_customer_id:
            return None
        self._claims[claim_id] = claim.model_copy(update={'customer_id': customer_id})
        stores: tuple[dict[str, Any], ...] = (
            self._sessions,
            self._follow_ups,
            self._messages,
            self._decisions,
            self._assessor_routing_operations,
            self._evidence,
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
            if record.claim_id == claim_id and record.actor_id == anonymous_customer_id:
                self._idempotency.pop(idempotency_key, None)
                promoted_record = replace(record, actor_id=customer_id)
                self._idempotency[(customer_id, record.route, record.key)] = promoted_record
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
            self._claims[claim.claim_id] = deepcopy(claim)
            if branch_evaluation is not None:
                self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(
                    branch_evaluation
                )

    def _validate_claim_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        *,
        allow_active_session_change: bool = False,
    ) -> WorkingClaim:
        """Validate the shared Claim State precondition before any child write."""
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

            self._claims[claim.claim_id] = deepcopy(claim)
            if branch_evaluation is not None:
                self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(
                    branch_evaluation
                )
            self._idempotency[lookup] = deepcopy(idempotency)

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
        self._validate_branch_evaluation(claim, branch_evaluation)
        prepared = self._prepare_audit_events(claim, audit_events)
        self.save_claim_mutation(
            claim,
            expected_revision,
            idempotency,
            branch_evaluation=branch_evaluation,
        )
        for event in prepared:
            self._audit_events[event.event_id] = deepcopy(event)

    def get_session(
        self,
        claim_id: str,
        session_id: str,
        customer_id: str,
    ) -> SessionRecord | None:
        session = self._sessions.get(session_id)
        if session is None or session.claim_id != claim_id or session.customer_id != customer_id:
            return None
        return deepcopy(session)

    def save_session(self, session: SessionRecord) -> None:
        claim = self._claims.get(session.claim_id)
        if claim is None or claim.customer_id != session.customer_id:
            raise KeyError(session.claim_id)
        self._sessions[session.session_id] = deepcopy(session)

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

            self._claims[claim.claim_id] = prepared_claim
            self._sessions[session.session_id] = prepared_session
            self._follow_ups[follow_up.follow_up_id] = prepared_follow_up
            self._idempotency[lookup] = prepared_idempotency

    def save_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
        resolved_follow_up: FollowUpRecord | None = None,
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
            if any(
                existing.claim_id == claim.claim_id and existing.status is SessionStatus.ACTIVE
                for existing in self._sessions.values()
            ):
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
                    or resolved_follow_up.updated_at < stored_follow_up.updated_at
                ):
                    raise KeyError(claim.claim_id)
                expected_follow_up = stored_follow_up.model_copy(
                    update={
                        'status': FollowUpStatus.RESOLVED,
                        'outcome': resolved_follow_up.outcome,
                        'updated_at': resolved_follow_up.updated_at,
                    }
                )
                if resolved_follow_up != expected_follow_up:
                    raise KeyError(claim.claim_id)
            lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
            if self._idempotency.get(lookup) is not None:
                raise IdempotencyConflict(idempotency.key)
            self._validate_branch_evaluation(claim, branch_evaluation)

            self._claims[claim.claim_id] = deepcopy(claim)
            self._sessions[session.session_id] = deepcopy(session)
            if resolved_follow_up is not None:
                self._follow_ups[resolved_follow_up.follow_up_id] = deepcopy(resolved_follow_up)
            if branch_evaluation is not None:
                self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(
                    branch_evaluation
                )
            self._idempotency[lookup] = deepcopy(idempotency)

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
        return self._idempotency.get((actor_id, route, key))

    def save_idempotency(self, record: IdempotencyRecord) -> None:
        lookup = (record.actor_id, record.route, record.key)
        existing = self._idempotency.get(lookup)
        if existing is not None and existing.request_fingerprint != record.request_fingerprint:
            raise IdempotencyConflict(record.key)
        self._idempotency[lookup] = record

    def list_claims_for_customer(self, customer_id: str) -> list[WorkingClaim]:
        claims = [
            deepcopy(claim) for claim in self._claims.values() if claim.customer_id == customer_id
        ]
        return sorted(claims, key=lambda claim: claim.created_at)

    def list_claims_internal(self) -> list[WorkingClaim]:
        return sorted(
            (deepcopy(claim) for claim in self._claims.values()),
            key=lambda claim: claim.updated_at,
            reverse=True,
        )

    def save_message(self, message: MessageRecord, customer_id: str) -> None:
        if (
            self.get_claim(message.claim_id, customer_id) is None
            or self.get_session(
                message.claim_id,
                message.session_id,
                customer_id,
            )
            is None
        ):
            raise KeyError(message.claim_id)
        self._messages[message.message_id] = deepcopy(message)

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
        self._claims[claim.claim_id] = deepcopy(claim)
        self._sessions[session.session_id] = deepcopy(session)
        self._messages[message.message_id] = deepcopy(message)
        self._idempotency[lookup] = deepcopy(idempotency)

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
        return sorted(messages, key=lambda message: (message.created_at, message.message_id))

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
        if (
            claim is None
            or claim.external_claim is None
            or claim.external_claim.external_claim_id != operation.external_claim_id
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
        allowed_statuses = {
            AssessorRoutingOperationStatus.RETRYABLE_FAILURE,
            AssessorRoutingOperationStatus.TERMINAL_FAILURE,
            AssessorRoutingOperationStatus.ACCEPTED,
        }
        if operation.status not in allowed_statuses:
            if existing != operation:
                raise IdempotencyConflict(operation.operation_id)
            return
        self._assessor_routing_operations[operation.operation_id] = deepcopy(operation)

    def save_assessor_routing_preparation(
        self,
        operation: AssessorRoutingOperation,
        decision: AgentDecisionRecord,
        customer_id: str,
        audit_events: tuple[AuditEventEnvelope, ...] = (),
    ) -> None:
        claim = self._claims.get(operation.claim_id)
        session = self._sessions.get(decision.session_id)
        if (
            claim is None
            or claim.customer_id != customer_id
            or claim.active_session_id != decision.session_id
            or session is None
            or session.claim_id != claim.claim_id
            or session.customer_id != customer_id
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
    ) -> None:
        stored_claim = self._validate_claim_mutation(claim, expected_revision)
        stored_session = self._sessions.get(session.session_id)
        existing_claimant_message = self._messages.get(claimant_message.message_id)
        existing_agent_message = self._messages.get(agent_message.message_id)
        existing_decision = self._decisions.get(decision.decision_id)
        existing_handoff = self._handoffs.get(handoff.handoff_id) if handoff is not None else None
        existing_evidence = (
            self._evidence.get(evidence.evidence_id) if evidence is not None else None
        )
        existing_children = (
            existing_claimant_message,
            existing_agent_message,
            existing_decision,
            existing_handoff,
            existing_evidence,
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
                )
                if existing is not None
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
        if duplicate_client_message is not None:
            raise IdempotencyConflict(claimant_message.client_message_id or '')
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing_idempotency = self._idempotency.get(lookup)
        if (
            existing_idempotency is not None
            and existing_idempotency.request_fingerprint != idempotency.request_fingerprint
        ):
            raise IdempotencyConflict(idempotency.key)

        self._claims[claim.claim_id] = deepcopy(claim)
        self._sessions[session.session_id] = deepcopy(session)
        self._messages[claimant_message.message_id] = deepcopy(claimant_message)
        self._messages[agent_message.message_id] = deepcopy(agent_message)
        self._decisions[decision.decision_id] = deepcopy(decision)
        if handoff is not None:
            self._handoffs[handoff.handoff_id] = deepcopy(handoff)
        if evidence is not None:
            self._evidence[evidence.evidence_id] = deepcopy(evidence)
        if branch_evaluation is not None:
            if branch_evaluation.evaluation_id in self._branch_evaluations:
                raise IdempotencyConflict(branch_evaluation.evaluation_id)
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
        self._idempotency[lookup] = idempotency

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
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing_idempotency = self._idempotency.get(lookup)
        if (
            existing_idempotency is not None
            and existing_idempotency.request_fingerprint != idempotency.request_fingerprint
        ):
            raise IdempotencyConflict(idempotency.key)
        self._sessions[session.session_id] = deepcopy(session)
        self._messages[claimant_message.message_id] = deepcopy(claimant_message)
        self._messages[agent_message.message_id] = deepcopy(agent_message)
        self._runtime_traces[runtime_trace.trace_id] = deepcopy(runtime_trace)
        self._idempotency[lookup] = deepcopy(idempotency)

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
        if self.get_claim(evidence.claim_id, customer_id) is None:
            raise KeyError(evidence.claim_id)
        self._evidence[evidence.evidence_id] = deepcopy(evidence)

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

    def save_evidence_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        evidence: EvidenceRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        self._validate_claim_mutation(claim, expected_revision)
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
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing_idempotency = self._idempotency.get(lookup)
        if (
            existing_idempotency is not None
            and existing_idempotency.request_fingerprint != idempotency.request_fingerprint
        ):
            raise IdempotencyConflict(idempotency.key)

        self._claims[claim.claim_id] = deepcopy(claim)
        self._evidence[evidence.evidence_id] = deepcopy(evidence)
        if branch_evaluation is not None:
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
        self._idempotency[lookup] = idempotency

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
        self._external_tasks[task.task_id] = deepcopy(task)

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
            first_send = (
                existing.sent_at is None
                and existing.operation_id is None
                and request.sent_at is not None
                and request.operation_id is not None
            )
            if changed_identity or not first_send:
                raise IdempotencyConflict(request.request_id)
        self._external_task_requests[request.request_id] = deepcopy(request)

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
        self._external_task_evidence_links[key] = deepcopy(link)

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
            try:
                assert_result_advance_is_permitted(held, result)
            except ValueError as conflict:
                raise IdempotencyConflict(result.result_id) from conflict
        self._external_task_results[result.result_id] = deepcopy(result)

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
    ) -> None:
        self._validate_claim_mutation(claim, expected_revision)
        coworker_records = coworkers or []
        if (
            collaboration_request.claim_id != claim.claim_id
            or any(item.claim_id != claim.claim_id for item in coworker_records)
            or (handoff is not None and handoff.claim_id != claim.claim_id)
            or idempotency.claim_id != claim.claim_id
        ):
            raise KeyError(claim.claim_id)
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing_idempotency = self._idempotency.get(lookup)
        if existing_idempotency is not None:
            if existing_idempotency.request_fingerprint != idempotency.request_fingerprint:
                raise IdempotencyConflict(idempotency.key)
            return
        existing_request = self._collaboration_requests.get(collaboration_request.request_id)
        if existing_request is not None and existing_request.claim_id != claim.claim_id:
            raise IdempotencyConflict(collaboration_request.request_id)
        self._claims[claim.claim_id] = deepcopy(claim)
        self._collaboration_requests[collaboration_request.request_id] = deepcopy(
            collaboration_request
        )
        for coworker in coworker_records:
            self._claim_coworkers[coworker.coworker_id] = deepcopy(coworker)
        if handoff is not None:
            self._handoffs[handoff.handoff_id] = deepcopy(handoff)
        self._idempotency[lookup] = deepcopy(idempotency)

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
    ) -> None:
        stored_claim = self._validate_claim_mutation(claim, expected_revision)
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
        if required_staff_id is not None and required_staff_revision is not None:
            assert presence is not None
            self._staff_presence[required_staff_id] = deepcopy(
                presence.model_copy(update={'revision': presence.revision + 1})
            )
        if existing_message is not None:
            raise IdempotencyConflict(message.message_id if message is not None else '')
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)
        existing = self._idempotency.get(lookup)
        if existing is not None and existing.request_fingerprint != idempotency.request_fingerprint:
            raise IdempotencyConflict(idempotency.key)
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
            self._messages[message.message_id] = deepcopy(message)
        self._idempotency[lookup] = deepcopy(idempotency)

    def save_handoff(self, handoff: HandoffRecord, customer_id: str) -> None:
        if self.get_claim(handoff.claim_id, customer_id) is None:
            raise KeyError(handoff.claim_id)
        self._handoffs[handoff.handoff_id] = deepcopy(handoff)

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
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        self._validate_claim_mutation(claim, expected_revision)
        self._validate_branch_evaluation(claim, branch_evaluation)
        existing_handoff = self._handoffs.get(handoff.handoff_id)
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

        self._claims[claim.claim_id] = deepcopy(claim)
        self._handoffs[handoff.handoff_id] = deepcopy(handoff)
        if branch_evaluation is not None:
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
        self._idempotency[lookup] = idempotency


def _serialize_material_claim_mutation(method_name: str) -> None:
    """Wrap an existing Fixture mutation in the shared Claim mutation lock."""
    method = getattr(FixtureRepository, method_name)

    def serialized(self: FixtureRepository, *args: Any, **kwargs: Any) -> Any:
        with self._claim_mutation_lock:
            return method(self, *args, **kwargs)

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
    'save_evidence_mutation',
    'save_ownership_mutation',
    'save_staff_mutation',
    'save_handoff_mutation',
):
    _serialize_material_claim_mutation(_material_claim_mutation)

del _material_claim_mutation
