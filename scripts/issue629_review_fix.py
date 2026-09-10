from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding='utf-8')


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f'{path}: expected exactly one replacement, found {count}: {old[:80]!r}')
    write(path, content.replace(old, new, 1))


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    content = read(path)
    start_index = content.find(start)
    if start_index < 0:
        raise RuntimeError(f'{path}: start marker not found: {start!r}')
    end_index = content.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f'{path}: end marker not found: {end!r}')
    write(path, content[:start_index] + replacement + content[end_index:])


# ---------------------------------------------------------------------------
# Domain contract: an interruption Follow-up needs purpose, source evidence,
# an explicit contact-authority condition, and open/blocked/resolved lifecycle.
# ---------------------------------------------------------------------------
replace_once(
    'backend/domain/models.py',
    "class FollowUpStatus(str, Enum):\n    PENDING = 'pending'\n",
    "class FollowUpStatus(str, Enum):\n"
    "    PENDING = 'pending'\n"
    "    BLOCKED = 'blocked'\n"
    "    RESOLVED = 'resolved'\n\n\n"
    "class FollowUpContactPermission(str, Enum):\n"
    "    AUTHORISED = 'authorised'\n"
    "    NOT_AUTHORISED = 'not_authorised'\n",
)

replace_between(
    'backend/domain/models.py',
    'class FollowUpRecord(ContractModel):\n',
    'class SessionRecord(ContractModel):\n',
    '''class FollowUpRecord(ContractModel):
    """Claim-scoped recovery work with an explicit contact-authority boundary."""

    follow_up_id: str
    claim_id: str
    source_session_id: str
    purpose: str = Field(default='resume_incomplete_claim', min_length=1, max_length=100)
    responsible_party: ResponsibleParty
    source_refs: list[str] = Field(default_factory=list, max_length=20)
    contact_permission: FollowUpContactPermission = FollowUpContactPermission.NOT_AUTHORISED
    attempt_count: int = Field(default=0, ge=0)
    channel: PreferredChannel | None = None
    outcome: str | None = Field(default=None, max_length=1000)
    status: FollowUpStatus = FollowUpStatus.BLOCKED
    due_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode='after')
    def validate_recovery_follow_up(self) -> 'FollowUpRecord':
        if self.updated_at < self.created_at:
            raise ValueError('A Follow-up cannot be updated before it is created.')
        if not self.source_refs:
            self.source_refs = [f'session:{self.source_session_id}']
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError('Follow-up source references must be unique.')
        if self.status is FollowUpStatus.PENDING:
            if (
                self.contact_permission is not FollowUpContactPermission.AUTHORISED
                or self.channel is None
                or self.due_at is None
            ):
                raise ValueError(
                    'A pending Follow-up requires an authorised channel and due time.'
                )
        elif self.status is FollowUpStatus.BLOCKED:
            if (
                self.contact_permission is not FollowUpContactPermission.NOT_AUTHORISED
                or self.channel is not None
                or self.due_at is not None
            ):
                raise ValueError(
                    'A blocked Follow-up must not claim an authorised channel or schedule.'
                )
        return self


''',
)

# ---------------------------------------------------------------------------
# Claim service: bind If-Match into idempotency, make pause snapshots current,
# block anonymous contact, and resolve the open recovery Follow-up on resume.
# ---------------------------------------------------------------------------
replace_once(
    'backend/services/claims.py',
    '    FollowUpRecord,\n    FollowUpStatus,\n',
    '    FollowUpContactPermission,\n    FollowUpRecord,\n    FollowUpStatus,\n',
)
replace_once(
    'backend/services/claims.py',
    '    PauseSessionResponse,\n    ProposedFormChange,\n',
    '    PauseSessionResponse,\n    PreferredChannel,\n    ProposedFormChange,\n',
)

replace_between(
    'backend/services/claims.py',
    'def _claimant_incomplete_context(\n',
    'def _claimant_claim(',
    '''def _claimant_incomplete_context(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> ClaimantIncompleteContext | None:
    if claim.active_session_id is not None:
        return None
    paused_sessions = [
        session
        for session in repository.list_sessions_for_claim(
            claim.claim_id,
            claim.customer_id,
        )
        if session.status is SessionStatus.PAUSED and session.recovery_context is not None
    ]
    if not paused_sessions:
        return None
    source = max(
        paused_sessions,
        key=lambda session: session.recovery_context.interrupted_at
        if session.recovery_context is not None
        else session.last_active_at,
    )
    recovery = source.recovery_context
    if recovery is None:
        return None
    follow_ups = [
        record
        for record in repository.list_follow_ups(claim.claim_id, claim.customer_id)
        if record.source_session_id == source.session_id
        and record.purpose == 'resume_incomplete_claim'
        and record.status in {FollowUpStatus.PENDING, FollowUpStatus.BLOCKED}
    ]
    if not follow_ups:
        return None
    follow_up = max(follow_ups, key=lambda record: (record.created_at, record.follow_up_id))
    return ClaimantIncompleteContext(
        interrupted_at=recovery.interrupted_at,
        last_meaningful_activity_at=recovery.last_meaningful_activity_at,
        resume_point=recovery.resume_point,
        follow_up_due_at=follow_up.due_at,
        follow_up_status=follow_up.status,
    )


''',
)

replace_between(
    'backend/services/claims.py',
    'def pause_session(\n',
    'def start_claim(',
    '''def pause_session(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    session_id: str,
    idempotency_key: str | None,
    if_match: str | None,
) -> PauseSessionResponse:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause'
    fingerprint = request_fingerprint(
        {'operation': 'pause', 'expected_revision': expected_revision}
    )

    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint or existing.response_payload is None:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was already used for another request.',
            )
        return PauseSessionResponse.model_validate(existing.response_payload)

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this request was prepared.',
            retryable=True,
            current_revision=claim.revision,
        )

    session = repository.get_session(claim_id, session_id, principal.subject)
    if session is None:
        raise _session_not_found()
    if claim.active_session_id != session_id or session.status is not SessionStatus.ACTIVE:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='Only the current active claimant session can be paused.',
        )

    timestamp = now_utc()
    claimant_messages = [
        message
        for message in repository.list_messages(
            claim_id,
            session_id,
            principal.subject,
        )
        if message.actor is ActorType.CLAIMANT
    ]
    last_meaningful_activity_at = max(
        (message.created_at for message in claimant_messages),
        default=session.last_active_at,
    )
    resume_point = (session.summary or claim.customer_next_step.summary).strip()
    recovery = SessionRecoveryContext(
        interrupted_at=timestamp,
        last_meaningful_activity_at=last_meaningful_activity_at,
        resume_point=resume_point,
    )
    paused_session = session.model_copy(
        update={
            'status': SessionStatus.PAUSED,
            'context_revision': expected_revision,
            'recovery_context': recovery,
        }
    )
    updated_claim = claim.model_copy(
        update={
            'active_session_id': None,
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    contact_authorised = principal.auth_source != 'anonymous:browser_session'
    follow_up = FollowUpRecord(
        follow_up_id=new_id('fup'),
        claim_id=claim_id,
        source_session_id=session_id,
        purpose='resume_incomplete_claim',
        responsible_party=ResponsibleParty.SYSTEM,
        source_refs=[
            f'claim:{claim_id}:revision:{updated_claim.revision}',
            f'session:{session_id}',
        ],
        contact_permission=(
            FollowUpContactPermission.AUTHORISED
            if contact_authorised
            else FollowUpContactPermission.NOT_AUTHORISED
        ),
        attempt_count=0,
        channel=PreferredChannel.IN_APP if contact_authorised else None,
        outcome=None,
        status=FollowUpStatus.PENDING if contact_authorised else FollowUpStatus.BLOCKED,
        due_at=timestamp if contact_authorised else None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    incomplete_context = ClaimantIncompleteContext(
        interrupted_at=recovery.interrupted_at,
        last_meaningful_activity_at=recovery.last_meaningful_activity_at,
        resume_point=recovery.resume_point,
        follow_up_due_at=follow_up.due_at,
        follow_up_status=follow_up.status,
    )
    claimant_before = _claimant_claim(repository, claim)
    response = PauseSessionResponse(
        claim=claimant_before.model_copy(
            update={
                'revision': updated_claim.revision,
                'updated_at': updated_claim.updated_at,
                'incomplete_context': incomplete_context,
            }
        ),
        session=_claimant_session(
            paused_session,
            updated_claim.customer_next_step,
        ),
    )
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=session_id,
        follow_up_id=follow_up.follow_up_id,
        response_payload=response.model_dump(mode='json'),
    )

    try:
        repository.save_incomplete_checkpoint(
            updated_claim,
            expected_revision=expected_revision,
            session=paused_session,
            follow_up=follow_up,
            idempotency=idempotency,
        )
    except RevisionConflict as error:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed before the interruption checkpoint was saved.',
            retryable=True,
            current_revision=error.current_revision,
        ) from error
    except IdempotencyConflict as error:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The interruption checkpoint conflicts with an existing request.',
        ) from error

    return response


''',
)

replace_between(
    'backend/services/claims.py',
    'def start_session(\n',
    'def get_session(',
    '''def start_session(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: StartSessionRequest,
    idempotency_key: str | None,
) -> ClaimantSession:
    key = require_idempotency_key(idempotency_key)
    route = f'/api/v1/claims/{claim_id}/sessions'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        claim = repository.get_claim(claim_id, principal.subject)
        session = repository.get_session(claim_id, existing.session_id, principal.subject)
        if claim is None or session is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent result could not be restored.',
                retryable=True,
            )
        return _claimant_session(session, claim.customer_next_step)

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()

    active_session = repository.get_active_session(claim_id, principal.subject)
    resume_source = active_session
    if resume_source is None:
        previous_sessions = repository.list_sessions_for_claim(
            claim_id,
            principal.subject,
        )
        if previous_sessions:
            resume_source = max(
                previous_sessions,
                key=lambda item: (
                    item.last_active_at,
                    item.started_at,
                    item.session_id,
                ),
            )
    if (
        payload.intent != 'new'
        and resume_source is not None
        and payload.model_profile_id is not None
        and payload.model_profile_id != resume_source.model_profile_id
    ):
        raise ApiError(
            status_code=409,
            code='MODEL_PROFILE_CONFLICT',
            message='The saved session is bound to a different model profile.',
            details=[
                ErrorDetail(
                    field='model_profile_id',
                    reason='Resume without overriding the persisted session model profile.',
                )
            ],
        )
    if (
        payload.intent != 'new'
        and active_session is not None
        and active_session.status is SessionStatus.ACTIVE
    ):
        session = active_session
        try:
            repository.save_idempotency(
                IdempotencyRecord(
                    actor_id=principal.subject,
                    route=route,
                    key=key,
                    request_fingerprint=fingerprint,
                    claim_id=claim_id,
                    session_id=session.session_id,
                )
            )
        except IdempotencyConflict as conflict:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The session resume request conflicted with an existing retry or session.',
            ) from conflict
    else:
        timestamp = now_utc()
        resolved_follow_up: FollowUpRecord | None = None
        if resume_source is not None and resume_source.status is SessionStatus.PAUSED:
            open_follow_ups = [
                record
                for record in repository.list_follow_ups(claim_id, principal.subject)
                if record.source_session_id == resume_source.session_id
                and record.purpose == 'resume_incomplete_claim'
                and record.status in {FollowUpStatus.PENDING, FollowUpStatus.BLOCKED}
            ]
            if open_follow_ups:
                current_follow_up = max(
                    open_follow_ups,
                    key=lambda record: (record.created_at, record.follow_up_id),
                )
                resolved_follow_up = current_follow_up.model_copy(
                    update={
                        'status': FollowUpStatus.RESOLVED,
                        'outcome': 'claimant_resumed',
                        'updated_at': timestamp,
                    }
                )
        session = SessionRecord(
            session_id=new_id('ses'),
            claim_id=claim_id,
            customer_id=principal.subject,
            model_profile_id=(
                resume_source.model_profile_id
                if resume_source is not None and payload.intent != 'new'
                else (payload.model_profile_id or 'qwen-local')
            ),
            summary=resume_source.summary if resume_source is not None else None,
            unresolved_questions=(
                list(resume_source.unresolved_questions) if resume_source is not None else []
            ),
            pending_items=list(resume_source.pending_items) if resume_source is not None else [],
            prior_commitments=(
                list(resume_source.prior_commitments) if resume_source is not None else []
            ),
            question_budget=resume_source.question_budget if resume_source is not None else 9,
            question_turn_count=(
                resume_source.question_turn_count if resume_source is not None else 0
            ),
            requested_fact_count=(
                resume_source.requested_fact_count if resume_source is not None else 0
            ),
            repeated_question_count=(
                resume_source.repeated_question_count if resume_source is not None else 0
            ),
            post_session_follow_up_required=(
                resume_source.post_session_follow_up_required
                if resume_source is not None
                else False
            ),
            question_history=(
                list(resume_source.question_history) if resume_source is not None else []
            ),
            context_revision=claim.revision,
            started_at=timestamp,
            last_active_at=timestamp,
        )
        if active_session is not None and active_session.status is SessionStatus.ACTIVE:
            # A claim has one active conversation at a time. Preserve the old
            # transcript while closing it before promoting the new session.
            repository.save_session(
                active_session.model_copy(
                    update={'status': SessionStatus.CLOSED, 'closed_at': timestamp}
                )
            )
        updated_claim = claim.model_copy(
            update={
                'active_session_id': session.session_id,
                'revision': claim.revision + 1,
                'updated_at': timestamp,
            }
        )
        idempotency = IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=session.session_id,
        )
        branch_evaluation = build_applied_branch_evaluation(
            updated_claim,
            repository=repository,
            recomputation_reason='session_resumed',
            session_id=session.session_id,
        )
        try:
            if resolved_follow_up is None:
                repository.save_session_mutation(
                    updated_claim,
                    expected_revision=claim.revision,
                    session=session,
                    idempotency=idempotency,
                    branch_evaluation=branch_evaluation,
                )
            else:
                repository.save_session_mutation(
                    updated_claim,
                    expected_revision=claim.revision,
                    session=session,
                    idempotency=idempotency,
                    branch_evaluation=branch_evaluation,
                    resolved_follow_up=resolved_follow_up,
                )
        except RevisionConflict as conflict:
            raise ApiError(
                status_code=409,
                code='REVISION_CONFLICT',
                message='The claim changed while the session was being resumed.',
                retryable=True,
                current_revision=conflict.current_revision,
            ) from conflict
        except IdempotencyConflict as conflict:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The session resume request conflicted with an existing retry or session.',
            ) from conflict
        claim = updated_claim

    return _claimant_session(session, claim.customer_next_step)


''',
)

# ---------------------------------------------------------------------------
# Repository protocol and fixture adapter: resolve the recovery Follow-up in
# the same session-activation mutation and dedupe open work by Claim+purpose.
# ---------------------------------------------------------------------------
replace_once(
    'backend/repositories/protocols.py',
    '''    def save_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
    ) -> None:
        """Atomically persist a resumed session, claim revision, and retry metadata."""
        raise NotImplementedError
''',
    '''    def save_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
        resolved_follow_up: FollowUpRecord | None = None,
    ) -> None:
        """Atomically activate a session and resolve recovery work when supplied."""
        raise NotImplementedError
''',
)

replace_between(
    'backend/repositories/fixture.py',
    '    def save_incomplete_checkpoint(\n',
    '    def _validate_branch_evaluation(\n',
    '''    def save_incomplete_checkpoint(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        follow_up: FollowUpRecord,
        idempotency: IdempotencyRecord,
    ) -> None:
        stored_claim = self._validate_claim_mutation(
            claim,
            expected_revision,
            allow_active_session_change=True,
        )
        stored_session = self._sessions.get(session.session_id)
        lookup = (idempotency.actor_id, idempotency.route, idempotency.key)

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

        self._claims[claim.claim_id] = deepcopy(claim)
        self._sessions[session.session_id] = deepcopy(session)
        self._follow_ups[follow_up.follow_up_id] = deepcopy(follow_up)
        self._idempotency[lookup] = deepcopy(idempotency)

    def save_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
        resolved_follow_up: FollowUpRecord | None = None,
    ) -> None:
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
            self._branch_evaluations[branch_evaluation.evaluation_id] = deepcopy(branch_evaluation)
        self._idempotency[lookup] = deepcopy(idempotency)

''',
)

# ---------------------------------------------------------------------------
# MongoDB adapter: same open Claim+purpose rule and atomic resolution.
# ---------------------------------------------------------------------------
replace_once(
    'backend/repositories/mongodb.py',
    '''        self._collection.create_index(
            [('record_type', 1), ('claim_id', 1), ('source_session_id', 1)],
            unique=True,
            name='follow_up_source_session_unique',
            partialFilterExpression={'record_type': 'follow_up'},
        )
''',
    '''        self._collection.create_index(
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
''',
)

replace_between(
    'backend/repositories/mongodb.py',
    '    def save_incomplete_checkpoint(\n',
    '    @staticmethod\n    def _validate_branch_evaluation(\n',
    '''    def save_incomplete_checkpoint(
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
                'status': {
                    '$in': [FollowUpStatus.PENDING.value, FollowUpStatus.BLOCKED.value]
                },
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

    def save_session_mutation(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        session: SessionRecord,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord | None = None,
        resolved_follow_up: FollowUpRecord | None = None,
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
                resolved_follow_up,
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
        resolved_follow_up: FollowUpRecord | None,
        mongo_session: Any,
    ) -> None:
        if (
            self.get_active_session(claim.claim_id, claim.customer_id, mongo_session=mongo_session)
            is not None
        ):
            raise IdempotencyConflict(session.session_id)
        self._reject_session_identity_conflict(session, mongo_session=mongo_session)
        open_follow_up_document = self._collection.find_one(
            {
                'record_type': 'follow_up',
                'claim_id': claim.claim_id,
                'purpose': 'resume_incomplete_claim',
                'status': {
                    '$in': [FollowUpStatus.PENDING.value, FollowUpStatus.BLOCKED.value]
                },
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
                or resolved_follow_up.updated_at < open_follow_up.updated_at
            ):
                raise KeyError(claim.claim_id)
            expected_follow_up = open_follow_up.model_copy(
                update={
                    'status': FollowUpStatus.RESOLVED,
                    'outcome': resolved_follow_up.outcome,
                    'updated_at': resolved_follow_up.updated_at,
                }
            )
            if resolved_follow_up != expected_follow_up:
                raise KeyError(claim.claim_id)
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
        if resolved_follow_up is not None:
            self._put(
                'follow_up',
                resolved_follow_up.follow_up_id,
                resolved_follow_up,
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

''',
)

# ---------------------------------------------------------------------------
# Workbench: incomplete state is derived only from a real paused checkpoint and
# open recovery Follow-up. Never synthesize not_scheduled state for active work.
# ---------------------------------------------------------------------------
replace_once(
    'backend/services/workbench.py',
    '    FormStatus,\n    HandoffPriority,\n',
    '    FollowUpStatus,\n    FormStatus,\n    HandoffPriority,\n',
)

replace_between(
    'backend/services/workbench.py',
    'def _queue_key(',
    'def _external_tasks(',
    '''def _queue_key(
    claim: WorkingClaim,
    active_handoffs: Sequence[HandoffRecord],
    incomplete_context: WorkbenchIncompleteContext | None,
) -> str:
    if active_handoffs:
        handoff = active_handoffs[-1]
        if handoff.support_need is SupportNeed.HUMAN_REQUESTED:
            return 'claimant_support'
        if handoff.type is HandoffType.PROFESSIONAL_REVIEW:
            return 'professional_review'
        return handoff.queue
    if incomplete_context is not None:
        return 'incomplete_claims'
    return {
        WorkflowState.COLLECTING: 'claimant_active',
        WorkflowState.READY_FOR_NEXT: 'ready_to_progress',
        WorkflowState.AWAITING_EVIDENCE: 'awaiting_evidence',
        WorkflowState.PROFESSIONAL_REVIEW: 'professional_review',
        WorkflowState.CREATED: 'created_routed',
    }[claim.claim_state.workflow_state]


def _incomplete_context(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    sessions: Sequence[SessionRecord],
) -> WorkbenchIncompleteContext | None:
    if (
        claim.claim_state.workflow_state is not WorkflowState.COLLECTING
        or claim.active_session_id is not None
    ):
        return None
    paused = [
        session
        for session in sessions
        if session.status is SessionStatus.PAUSED and session.recovery_context is not None
    ]
    if not paused:
        return None
    source = max(
        paused,
        key=lambda item: (
            item.recovery_context.interrupted_at
            if item.recovery_context is not None
            else item.last_active_at
        ),
    )
    recovery = source.recovery_context
    if recovery is None:
        return None
    follow_ups = [
        record
        for record in repository.list_follow_ups(claim.claim_id, claim.customer_id)
        if record.source_session_id == source.session_id
        and record.purpose == 'resume_incomplete_claim'
        and record.status in {FollowUpStatus.PENDING, FollowUpStatus.BLOCKED}
    ]
    if not follow_ups:
        return None
    follow_up = max(
        follow_ups,
        key=lambda record: (record.created_at, record.follow_up_id),
    )
    return WorkbenchIncompleteContext(
        interrupted_at=recovery.interrupted_at,
        last_meaningful_activity_at=recovery.last_meaningful_activity_at,
        resume_point=recovery.resume_point,
        follow_up_due_at=follow_up.due_at,
        follow_up_status=follow_up.status.value,
        follow_up_attempts=follow_up.attempt_count,
    )


''',
)

replace_once(
    'backend/services/workbench.py',
    '''    claimant_messages = [item for item in messages if item.actor.value == 'claimant']
    work_summary = WorkbenchWorkSummary(
        queue_key=_queue_key(claim, active_handoffs),
''',
    '''    claimant_messages = [item for item in messages if item.actor.value == 'claimant']
    incomplete_context = _incomplete_context(repository, claim, sessions)
    work_summary = WorkbenchWorkSummary(
        queue_key=_queue_key(claim, active_handoffs, incomplete_context),
''',
)
replace_once(
    'backend/services/workbench.py',
    '        incomplete_context=_incomplete_context(repository, claim, sessions),\n',
    '        incomplete_context=incomplete_context,\n',
)

# ---------------------------------------------------------------------------
# Existing focused tests: construct the strengthened persisted Follow-up shape
# and assert that resume resolves the old work item.
# ---------------------------------------------------------------------------
replace_once(
    'tests/test_incomplete_claim_recovery.py',
    '    FollowUpRecord,\n    FollowUpStatus,\n',
    '    FollowUpContactPermission,\n    FollowUpRecord,\n    FollowUpStatus,\n',
)
replace_once(
    'tests/test_incomplete_claim_recovery.py',
    '    ResponsibleParty,\n    SessionRecord,\n',
    '    PreferredChannel,\n    ResponsibleParty,\n    SessionRecord,\n',
)
replace_once(
    'tests/test_incomplete_claim_recovery.py',
    '''    follow_up = FollowUpRecord(
        follow_up_id='fup_p17_mongo',
        claim_id=claim.claim_id,
        source_session_id=session.session_id,
        responsible_party=ResponsibleParty.SYSTEM,
        status=FollowUpStatus.PENDING,
        created_at=timestamp,
        updated_at=timestamp,
    )
''',
    '''    follow_up = FollowUpRecord(
        follow_up_id='fup_p17_mongo',
        claim_id=claim.claim_id,
        source_session_id=session.session_id,
        purpose='resume_incomplete_claim',
        responsible_party=ResponsibleParty.SYSTEM,
        source_refs=[f'session:{session.session_id}'],
        contact_permission=FollowUpContactPermission.AUTHORISED,
        channel=PreferredChannel.IN_APP,
        status=FollowUpStatus.PENDING,
        due_at=timestamp,
        created_at=timestamp,
        updated_at=timestamp,
    )
''',
)
replace_once(
    'tests/test_incomplete_claim_recovery.py',
    '''    assert final_claim.active_session_id == resumed.json()['session_id']
    assert len(repository.list_follow_ups(claim_id, 'cus_demo')) == 1
''',
    '''    assert final_claim.active_session_id == resumed.json()['session_id']
    resumed_follow_ups = repository.list_follow_ups(claim_id, 'cus_demo')
    assert len(resumed_follow_ups) == 1
    assert resumed_follow_ups[0].status is FollowUpStatus.RESOLVED
    assert resumed_follow_ups[0].outcome == 'claimant_resumed'
''',
)

review_tests = '''from fastapi.testclient import TestClient

from backend.domain.models import FollowUpContactPermission, FollowUpStatus, PreferredChannel
from backend.repositories.fixture import FixtureRepository


def _create_claim(
    client: TestClient,
    headers: dict[str, str],
    key: str,
) -> tuple[str, str, int]:
    response = client.post(
        '/api/v1/claims',
        headers={**headers, 'Idempotency-Key': key},
        json={'channel': 'web_agent', 'locale': 'en-NZ', 'incident_type': 'motor'},
    )
    assert response.status_code == 201
    body = response.json()
    return (
        str(body['claim']['claim_id']),
        str(body['session']['session_id']),
        int(body['claim']['revision']),
    )


def test_active_collecting_claim_is_not_projected_as_incomplete(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
) -> None:
    claim_id, _, _ = _create_claim(client, auth_headers, 'p17-active-create')

    detail = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers)
    assert detail.status_code == 200
    assert detail.json()['work_summary']['queue_key'] != 'incomplete_claims'
    assert detail.json()['work_summary']['incomplete_context'] is None

    incomplete = client.get(
        '/api/v1/workbench/claims',
        params={'view': 'incomplete_claims'},
        headers=staff_auth_headers,
    )
    assert incomplete.status_code == 200
    assert claim_id not in {item['claim_id'] for item in incomplete.json()['items']}


def test_pause_resume_resolves_follow_up_and_resumed_session_can_pause_again(
    client: TestClient,
    auth_headers: dict[str, str],
    staff_auth_headers: dict[str, str],
    repository: FixtureRepository,
) -> None:
    claim_id, first_session_id, revision = _create_claim(
        client,
        auth_headers,
        'p17-roundtrip-create',
    )
    first_pause = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{first_session_id}/pause',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p17-roundtrip-pause-1',
            'If-Match': f'"{revision}"',
        },
    )
    assert first_pause.status_code == 200
    first_follow_up = repository.list_follow_ups(claim_id, 'cus_demo')[0]
    assert first_follow_up.status is FollowUpStatus.PENDING
    assert first_follow_up.purpose == 'resume_incomplete_claim'
    assert first_follow_up.channel is PreferredChannel.IN_APP
    assert first_follow_up.contact_permission is FollowUpContactPermission.AUTHORISED
    assert first_follow_up.due_at is not None
    assert first_follow_up.source_refs

    resumed = client.post(
        f'/api/v1/claims/{claim_id}/sessions',
        headers={**auth_headers, 'Idempotency-Key': 'p17-roundtrip-resume'},
        json={'intent': 'resume'},
    )
    assert resumed.status_code == 201
    resumed_session_id = str(resumed.json()['session_id'])

    after_resume = repository.list_follow_ups(claim_id, 'cus_demo')
    assert len(after_resume) == 1
    assert after_resume[0].status is FollowUpStatus.RESOLVED
    assert after_resume[0].outcome == 'claimant_resumed'

    workbench = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=staff_auth_headers)
    assert workbench.status_code == 200
    assert workbench.json()['work_summary']['queue_key'] != 'incomplete_claims'
    assert workbench.json()['work_summary']['incomplete_context'] is None

    current = client.get(f'/api/v1/claims/{claim_id}', headers=auth_headers)
    assert current.status_code == 200
    current_revision = int(current.json()['revision'])
    second_pause = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{resumed_session_id}/pause',
        headers={
            **auth_headers,
            'Idempotency-Key': 'p17-roundtrip-pause-2',
            'If-Match': f'"{current_revision}"',
        },
    )
    assert second_pause.status_code == 200
    all_follow_ups = repository.list_follow_ups(claim_id, 'cus_demo')
    assert len(all_follow_ups) == 2
    open_follow_ups = [
        item
        for item in all_follow_ups
        if item.status in {FollowUpStatus.PENDING, FollowUpStatus.BLOCKED}
        and item.purpose == 'resume_incomplete_claim'
    ]
    assert len(open_follow_ups) == 1
    assert open_follow_ups[0].source_session_id == resumed_session_id


def test_anonymous_pause_persists_blocked_not_authorised_follow_up(
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    anonymous_session = '4c7f9f6e-0f31-4ce3-a5cc-5e3a4d8e4b10'
    headers = {'X-Northwind-Anonymous-Session': anonymous_session}
    claim_id, session_id, revision = _create_claim(client, headers, 'p17-anon-create')

    paused = client.post(
        f'/api/v1/claims/{claim_id}/sessions/{session_id}/pause',
        headers={
            **headers,
            'Idempotency-Key': 'p17-anon-pause',
            'If-Match': f'"{revision}"',
        },
    )
    assert paused.status_code == 200
    assert paused.json()['claim']['incomplete_context']['follow_up_status'] == 'blocked'

    follow_ups = repository.list_follow_ups(claim_id, f'anonymous:{anonymous_session}')
    assert len(follow_ups) == 1
    follow_up = follow_ups[0]
    assert follow_up.status is FollowUpStatus.BLOCKED
    assert follow_up.contact_permission is FollowUpContactPermission.NOT_AUTHORISED
    assert follow_up.channel is None
    assert follow_up.due_at is None
    assert follow_up.attempt_count == 0
'''
write('tests/test_incomplete_claim_recovery_review.py', review_tests)

# ---------------------------------------------------------------------------
# Contract documentation: state the reviewed P17.1 boundaries without claiming
# P17.2 scheduling/delivery or production contact authority.
# ---------------------------------------------------------------------------
replace_once(
    'docs/api.md',
    '''`POST /api/v1/claims/{claim_id}/sessions/{session_id}/pause` is the explicit P17.1 interruption boundary. It requires the current Claim revision through `If-Match` plus an `Idempotency-Key`, atomically marks the current session `paused`, clears the Claim's active-session pointer, stores bounded recovery context, and creates exactly one Claim-scoped initial follow-up record. It does not create a second Claim State, send a follow-up, make an abandonment decision, or apply a retention transition.

After that checkpoint, claimant Claim detail and Claim list projections may include `incomplete_context` containing the interruption time, last meaningful activity, bounded resume point, and the claimant-safe initial follow-up state. The Workbench reads the same durable records rather than maintaining its own incomplete-Claim state.

When a claimant resumes an existing working claim, the server starts a new interaction session using the current claim state and bounded resume context. A previously paused session MAY be closed when the new session is created.
''',
    '''`POST /api/v1/claims/{claim_id}/sessions/{session_id}/pause` is the explicit P17.1 interruption boundary. It requires the current Claim revision through `If-Match` plus an `Idempotency-Key`, atomically marks the current session `paused`, aligns that Session's recovery snapshot to the accepted Claim revision, clears the Claim's active-session pointer, stores bounded recovery context, and creates exactly one open Claim-scoped recovery Follow-up for the `resume_incomplete_claim` purpose. The accepted Claim revision is part of the idempotency fingerprint, so reusing the same key with a different `If-Match` value returns `409 IDEMPOTENCY_CONFLICT`. It does not create a second Claim State, send a follow-up, make an abandonment decision, or apply a retention transition.

The recovery Follow-up persists purpose, source references, responsible party, channel, due time, status, attempt count, and a contact-permission condition. An authenticated claimant may receive a `pending` in-app recovery Follow-up; that record does not authorise email, SMS, or phone contact. An anonymous browser claimant has no durable authorised contact channel in P17.1, so the record is persisted as `blocked` with `contact_permission=not_authorised`, no channel, and no due time. P17.2 owns any later scheduling, delivery, attempt, or escalation policy.

After that checkpoint, claimant Claim detail and Claim list projections may include `incomplete_context` containing the interruption time, last meaningful activity, bounded resume point, and the claimant-safe open Follow-up state. The Workbench classifies a Claim as `incomplete_claims` only when the non-terminal Claim has no authoritative active Session, has a paused recovery checkpoint, and has a relevant open recovery Follow-up. An ordinary active `collecting` Claim is not an incomplete Claim.

When a claimant resumes an existing working claim, the server starts a new interaction session using the current Claim State and bounded resume context and atomically marks the open recovery Follow-up `resolved`. A later interruption of that resumed Session may create the next recovery Follow-up for the same purpose because only one open Claim+purpose record is allowed at a time.
''',
)

replace_between(
    'docs/persistence-schema.md',
    '## P17.1 Incomplete Claim Checkpoint\n',
    '',
    '',
) if False else None

persistence = read('docs/persistence-schema.md')
marker = '## P17.1 Incomplete Claim Checkpoint\n'
index = persistence.find(marker)
if index < 0:
    raise RuntimeError('docs/persistence-schema.md: P17.1 marker missing')
persistence_section = '''## P17.1 Incomplete Claim Checkpoint

The explicit incomplete-Claim checkpoint is a provider-neutral atomic mutation. It does not add a
second Claim State.

For Claim revision `N`, the checkpoint persists together:

- the same authoritative `WorkingClaim` at revision `N + 1`, with `active_session_id` cleared;
- the previously active Session changed to `paused`, with its recovery snapshot aligned to revision
  `N`;
- bounded Session recovery context containing `interrupted_at`,
  `last_meaningful_activity_at`, and a plain-language `resume_point`;
- exactly one open Claim-scoped Follow-up for purpose `resume_incomplete_claim`; and
- the idempotency record for the claimant, route, key, accepted revision, Claim, Session, and
  Follow-up identity.

Follow-up IDs use the `fup_` prefix. The minimum P17.1 record persists stable identity, Claim,
source Session, purpose, source references, responsible party, channel, due time, status, attempt
count, contact-permission condition, optional outcome, and timestamps. `pending` means P17.1 has
an authorised current channel; `blocked` means contact is not authorised and therefore has no
channel or schedule; `resolved` records that the claimant resumed. An authenticated in-app
recovery record does not grant email, SMS, or phone authority. An anonymous browser interruption
is persisted as `blocked` / `not_authorised` rather than as executable outbound work.

The Fixture and MongoDB adapters enforce at most one open (`pending` or `blocked`) Follow-up for
the same Claim and purpose. A stale revision, mismatched Claim/Session/customer, conflicting
idempotency identity, invalid contact-authority condition, or second open Claim+purpose record
fails before any bundle member becomes authoritative.

Resume continues to create a new active interaction Session for the same Working Claim. The same
atomic session-activation mutation marks the open recovery Follow-up `resolved`, so Workbench no
longer exposes stale follow-up work after claimant recovery. The paused Session and recovery
context remain historical continuity evidence and never supersede the latest Working Claim.

P17.1 does not implement notification delivery, retry cadence, attempt processing, abandonment,
escalation, purge, anonymisation, or retention transitions; those remain owned by later P17
slices.
'''
write('docs/persistence-schema.md', persistence[:index] + persistence_section)

transaction = read('docs/claim-state-transaction-boundary.md')
clarification = '''

## P17.1 Recovery Follow-up Clarification

The pause/checkpoint mutation binds its idempotency request fingerprint to the accepted Claim
revision and persists one open recovery Follow-up per Claim and purpose. The Follow-up carries its
purpose, source references, channel/due metadata, attempt count, and explicit contact-permission
condition; a browser-anonymous claimant without an authorised durable channel is `blocked`, not
scheduled.

Activating a new claimant Session for a Claim with an open `resume_incomplete_claim` Follow-up
must resolve that Follow-up in the same provider-neutral mutation. A resolved historical record no
longer makes the Claim incomplete and does not prevent a later interruption from creating a new
open record for the same purpose. Workbench incomplete state is therefore a projection of the
Claim active-session pointer plus persisted paused recovery and open Follow-up records, never a
status inferred from `WorkflowState.COLLECTING` alone.
'''
if '## P17.1 Recovery Follow-up Clarification' not in transaction:
    write('docs/claim-state-transaction-boundary.md', transaction.rstrip() + clarification)

print('Issue #629 review repair transformations applied successfully.')
