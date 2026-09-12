from collections.abc import Mapping
from datetime import datetime

from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.branch_registry import (
    BranchRuleEvaluator,
    validate_registered_field_value,
)
from backend.domain.evidence import evidence_summary_for
from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.ids import new_id
from backend.domain.intake import next_requirement_step
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AssertionRelation,
    ClaimantClaim,
    ClaimantContentsItem,
    ClaimantHandoff,
    ClaimantIncompleteContext,
    ClaimantSession,
    ClaimListItem,
    ClaimListResponse,
    ClaimState,
    CreateClaimRequest,
    CreateClaimResponse,
    CustomerNextStep,
    FieldSelectionState,
    FollowUpContactPermission,
    FollowUpRecord,
    FollowUpStatus,
    FormConfirmationRequest,
    FormConfirmationResponse,
    FormPatchRequest,
    FormPatchResponse,
    FormSource,
    FormStatus,
    NeededFor,
    PageInfo,
    PauseSessionResponse,
    PreferredChannel,
    ProposedFormChange,
    ResponsibleParty,
    ResumePackage,
    SessionRecord,
    SessionRecoveryContext,
    SessionStatus,
    StartSessionRequest,
    StructuredFormField,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.protocols import (
    ClaimRepository,
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.branching import (
    build_applied_branch_evaluation,
    claimant_dynamic_form_projection,
)
from backend.services.claimant_form_projection import project_claimant_form_fields
from backend.services.evidence_visibility import claimant_visible_evidence
from backend.services.external_services import claimant_assessor_action, claimant_next_step
from backend.services.fact_resolution import (
    confirm_contents_item,
    confirm_form_field,
    resolve_form_change,
)
from backend.services.handoffs import claimant_handoff
from backend.services.incomplete_claims import (
    find_incomplete_recovery,
    recovery_checkpoint_allowed,
)
from backend.services.support import (
    decode_cursor,
    encode_cursor,
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)


def _claim_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The claim was not found.',
    )


def _session_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The session was not found.',
    )


def _apply_product_family_transition(
    claim: WorkingClaim,
    changed_fields: Mapping[str, StructuredFormField],
) -> str | None:
    """Project a confirmed form family onto the legacy top-level Claim field.

    Args:
        claim: The authoritative Claim snapshot before the mutation.
        changed_fields: Validated fields being written in the same Claim revision.

    Returns:
        The product family to persist in ``WorkingClaim.incident_type``.

    Raises:
        ApiError: If an ordinary form mutation attempts to reclassify a created Claim.
    """

    changed_family = changed_fields.get('claim.product_family')
    if changed_family is None or not isinstance(changed_family.value, str):
        return claim.incident_type
    target_family = changed_family.value.strip().lower()
    if (
        claim.external_claim is not None
        or claim.claim_state.workflow_state is WorkflowState.CREATED
    ) and claim.incident_type != target_family:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='A created claim cannot change product family through the ordinary form flow.',
            details=[
                ErrorDetail(
                    field='claim.product_family',
                    reason='Use the approved correction or professional-review path.',
                )
            ],
        )
    if changed_family.status is not FormStatus.CONFIRMED:
        return claim.incident_type
    return target_family


def _field_transition_refs(claim: WorkingClaim, field_codes: Mapping[str, object]) -> list[str]:
    return [
        f'claim:{claim.claim_id}:revision:{claim.revision + 1}:field:{field_code}'
        for field_code in sorted(field_codes)
    ]


def _claimant_form(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> dict[str, StructuredFormField]:
    """Keep field provenance but never expose internal retrieval identifiers to a claimant."""

    return project_claimant_form_fields(repository, claim, claim.form)


def _claimant_contents_items(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> list[ClaimantContentsItem]:
    """Project contents items without internal assessment metadata."""

    internal_refs = {
        record.retrieval_id
        for record in repository.list_retrieval_records(claim.claim_id, claim.customer_id)
    }
    projected: list[ClaimantContentsItem] = []
    for item in claim.contents_items:
        visible_refs = [
            ref
            for ref in item.source_refs
            if ref not in internal_refs and (ref.startswith('msg_') or ref.startswith('evd_'))
        ]
        projected.append(
            ClaimantContentsItem(
                item_id=item.item_id,
                description=item.description,
                category=item.category,
                quantity=item.quantity,
                loss_type=item.loss_type,
                ownership=item.ownership,
                estimated_value=item.estimated_value,
                source=item.source,
                source_refs=visible_refs,
                status=item.status,
                needed_for=item.needed_for,
                resolution_state=item.resolution_state,
                updated_at=item.updated_at,
            )
        )
    return projected


def _claimant_incomplete_context(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> ClaimantIncompleteContext | None:
    records = find_incomplete_recovery(repository, claim)

    if records is None:
        return None

    source, follow_up = records
    recovery = source.recovery_context

    if recovery is None:
        return None

    return ClaimantIncompleteContext(
        interrupted_at=recovery.interrupted_at,
        last_meaningful_activity_at=recovery.last_meaningful_activity_at,
        resume_point=recovery.resume_point,
        follow_up_due_at=follow_up.due_at,
        follow_up_status=follow_up.status,
    )


def _claimant_claim(repository: PersistenceRepository, claim: WorkingClaim) -> ClaimantClaim:
    claimant_evidence = claimant_visible_evidence(
        repository.list_evidence(claim.claim_id, claim.customer_id)
    )
    # Derived once and passed to both fields: the next step is corrected against the
    # action, so reading the action twice could let the two disagree again.
    external_service_action = claimant_assessor_action(repository, claim)
    handoff: ClaimantHandoff | None = None
    if claim.active_session_id is not None:
        # Claimant receives only the public lifecycle state, never staff routing data.
        open_handoffs = [
            item
            for item in repository.list_handoffs(claim.claim_id, claim.customer_id)
            if item.status.value not in {'resolved', 'cancelled'} and item.support_need is not None
        ]
        if open_handoffs:
            active = open_handoffs[-1]
            handoff = claimant_handoff(active)
    return ClaimantClaim(
        claim_id=claim.claim_id,
        revision=claim.revision,
        incident_type=claim.incident_type,
        workflow_state=claim.claim_state.workflow_state,
        form=_claimant_form(repository, claim),
        contents_items=_claimant_contents_items(repository, claim),
        evidence_summary=evidence_summary_for(claimant_evidence),
        external_claim=claim.external_claim,
        external_service_action=external_service_action,
        dynamic_form=claimant_dynamic_form_projection(repository, claim),
        customer_next_step=claimant_next_step(claim, external_service_action),
        incomplete_context=_claimant_incomplete_context(repository, claim),
        handoff=handoff,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )


def _claim_list_item(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> ClaimListItem:
    return ClaimListItem(
        claim_id=claim.claim_id,
        revision=claim.revision,
        incident_type=claim.incident_type,
        workflow_state=claim.claim_state.workflow_state,
        external_claim=claim.external_claim,
        customer_next_step=claim.customer_next_step,
        incomplete_context=_claimant_incomplete_context(repository, claim),
        created_at=claim.created_at,
        updated_at=claim.updated_at,
        can_resume=claim.customer_next_step.can_resume,
    )


def _claimant_session(session: SessionRecord, next_step: CustomerNextStep) -> ClaimantSession:
    return ClaimantSession(
        session_id=session.session_id,
        claim_id=session.claim_id,
        status=session.status,
        model_profile_id=session.model_profile_id,
        resume=ResumePackage(
            summary=session.summary,
            unresolved_questions=session.unresolved_questions,
            pending_items=session.pending_items,
            prior_commitments=session.prior_commitments,
            question_budget=session.question_budget,
            question_turn_count=session.question_turn_count,
            requested_fact_count=session.requested_fact_count,
            repeated_question_count=session.repeated_question_count,
            remaining_question_budget=max(
                session.question_budget - session.question_turn_count,
                0,
            ),
            post_session_follow_up_required=session.post_session_follow_up_required,
            customer_next_step=next_step,
        ),
        started_at=session.started_at,
        last_active_at=session.last_active_at,
        closed_at=session.closed_at,
    )


def _latest_meaningful_claimant_activity(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> tuple[datetime, str]:
    candidates: list[tuple[datetime, str]] = [
        (
            claim.created_at,
            f'claim:{claim.claim_id}:revision:1',
        )
    ]

    for session in repository.list_sessions_for_claim(
        claim.claim_id,
        claim.customer_id,
    ):
        for message in repository.list_messages(
            claim.claim_id,
            session.session_id,
            claim.customer_id,
        ):
            if message.actor is ActorType.CLAIMANT:
                candidates.append(
                    (
                        message.created_at,
                        message.message_id,
                    )
                )

    for field in claim.form.values():
        if field.updated_by.actor_type is ActorType.CLAIMANT and field.source_refs:
            candidates.append(
                (
                    field.updated_at,
                    field.source_refs[-1],
                )
            )

    for item in claim.contents_items:
        if item.updated_by.actor_type is ActorType.CLAIMANT and item.source_refs:
            candidates.append(
                (
                    item.updated_at,
                    item.source_refs[-1],
                )
            )

    for consent in claim.external_service_consents:
        if consent.granted_by.actor_type is ActorType.CLAIMANT:
            candidates.append(
                (
                    consent.granted_at,
                    f'consent:{consent.consent_ref}',
                )
            )

    return max(
        candidates,
        key=lambda candidate: (
            candidate[0],
            candidate[1],
        ),
    )


def pause_session(
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

    if not recovery_checkpoint_allowed(claim):
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='Only a non-terminal resumable Claim can be paused.',
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
    (
        last_meaningful_activity_at,
        last_meaningful_activity_source_ref,
    ) = _latest_meaningful_claimant_activity(
        repository,
        claim,
    )
    resume_point = (session.summary or claim.customer_next_step.summary).strip()
    recovery = SessionRecoveryContext(
        interrupted_at=timestamp,
        last_meaningful_activity_at=last_meaningful_activity_at,
        last_meaningful_activity_source_ref=(last_meaningful_activity_source_ref),
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
            last_meaningful_activity_source_ref,
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
    claimant_after = _claimant_claim(
        repository,
        updated_claim,
    )

    response = PauseSessionResponse(
        claim=claimant_after.model_copy(update={'incomplete_context': incomplete_context}),
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


def start_claim(
    repository: PersistenceRepository,
    principal: Principal,
    payload: CreateClaimRequest,
    idempotency_key: str | None,
) -> CreateClaimResponse:
    key = require_idempotency_key(idempotency_key)
    route = '/api/v1/claims'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        claim = repository.get_claim(existing.claim_id, principal.subject)
        session = repository.get_session(existing.claim_id, existing.session_id, principal.subject)
        if claim is None or session is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent result could not be restored.',
                retryable=True,
            )
        return CreateClaimResponse(
            claim=_claimant_claim(repository, claim),
            session=_claimant_session(session, claim.customer_next_step),
        )

    timestamp = now_utc()
    claim_id = new_id('clm')
    session_id = new_id('ses')
    next_step = CustomerNextStep(
        status='describe_incident',
        summary='Tell me what happened in your own words.',
        responsible_party=ResponsibleParty.CLAIMANT,
    )
    claim = WorkingClaim(
        claim_id=claim_id,
        customer_id=principal.subject,
        channel=payload.channel,
        locale=payload.locale,
        incident_type=payload.incident_type,
        claim_state=ClaimState(),
        active_session_id=session_id,
        customer_next_step=next_step,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id=session_id,
        claim_id=claim_id,
        customer_id=principal.subject,
        model_profile_id=payload.model_profile_id or 'qwen-local',
        context_revision=claim.revision,
        started_at=timestamp,
        last_active_at=timestamp,
    )
    repository.create_claim(claim, session)
    repository.save_idempotency(
        IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=session_id,
        )
    )
    return CreateClaimResponse(
        claim=_claimant_claim(repository, claim),
        session=_claimant_session(session, next_step),
    )


def get_claim(
    repository: PersistenceRepository, principal: Principal, claim_id: str
) -> ClaimantClaim:
    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    return _claimant_claim(repository, claim)


def promote_anonymous_claim(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    anonymous_session: str,
) -> ClaimantClaim:
    """Attach the current anonymous conversation to the authenticated account."""
    if not anonymous_session:
        raise _claim_not_found()
    promoted = repository.promote_claim_owner(
        claim_id,
        f'anonymous:{anonymous_session}',
        principal.subject,
    )
    if promoted is None:
        raise _claim_not_found()
    return _claimant_claim(repository, promoted)


def list_claims(
    repository: PersistenceRepository,
    principal: Principal,
    *,
    limit: int,
    cursor: str | None,
    workflow_state: WorkflowState | None,
    updated_after: datetime | None,
) -> ClaimListResponse:
    if updated_after is not None and updated_after.utcoffset() is None:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The updated_after filter must include a timezone offset.',
            details=[
                ErrorDetail(
                    field='updated_after',
                    reason='Use an ISO 8601 timestamp with a timezone offset.',
                )
            ],
        )
    claims = repository.list_claims_for_customer(principal.subject)
    if workflow_state is not None:
        claims = [claim for claim in claims if claim.claim_state.workflow_state == workflow_state]
    if updated_after is not None:
        claims = [claim for claim in claims if claim.updated_at > updated_after]
    claims.sort(key=lambda claim: (claim.updated_at, claim.claim_id), reverse=True)

    offset = decode_cursor(cursor)
    page_claims = claims[offset : offset + limit]
    next_offset = offset + len(page_claims)
    next_cursor = encode_cursor(next_offset) if next_offset < len(claims) else None
    return ClaimListResponse(
        items=[_claim_list_item(repository, claim) for claim in page_claims],
        page=PageInfo(next_cursor=next_cursor),
    )


def start_session(
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
        replaced_active_session = None
        if active_session is not None and active_session.status is SessionStatus.ACTIVE:
            # Closing the previous active Session is part of the same
            # revision-checked mutation that activates the replacement.
            replaced_active_session = active_session.model_copy(
                update={'status': SessionStatus.CLOSED, 'closed_at': timestamp}
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
                    replaced_active_session=replaced_active_session,
                )
            else:
                repository.save_session_mutation(
                    updated_claim,
                    expected_revision=claim.revision,
                    session=session,
                    idempotency=idempotency,
                    branch_evaluation=branch_evaluation,
                    resolved_follow_up=resolved_follow_up,
                    replaced_active_session=replaced_active_session,
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


def get_session(
    repository: ClaimRepository,
    principal: Principal,
    claim_id: str,
    session_id: str,
) -> ClaimantSession:
    claim = repository.get_claim(claim_id, principal.subject)
    session = repository.get_session(claim_id, session_id, principal.subject)
    if claim is None or session is None:
        raise _session_not_found()
    return _claimant_session(session, claim.customer_next_step)


def update_form(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: FormPatchRequest,
    if_match: str | None,
) -> FormPatchResponse:
    expected_revision = parse_if_match(if_match)
    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )

    timestamp = now_utc()
    updated_fields: dict[str, StructuredFormField] = {}
    for update in payload.updates:
        if update.field_code not in REGISTERED_FIELD_CODES:
            raise ApiError(
                status_code=422,
                code='VALIDATION_ERROR',
                message='The field code is not registered.',
                details=[
                    ErrorDetail(field='field_code', reason=f'Unknown field: {update.field_code}.')
                ],
            )
        try:
            validate_registered_field_value(
                update.field_code,
                update.value,
                status=update.status,
            )
        except ValueError as error:
            raise ApiError(
                status_code=422,
                code='VALIDATION_ERROR',
                message='The form update contains an invalid registered-field value.',
                details=[ErrorDetail(field=update.field_code, reason=str(error))],
            ) from error
        existing = claim.form.get(update.field_code)
        if (
            existing is not None
            and existing.status.value == 'confirmed'
            and existing.value != update.value
            and update.correction_reason is None
        ):
            raise ApiError(
                status_code=409,
                code='INVALID_STATE_TRANSITION',
                message='A confirmed field cannot be silently overwritten.',
                details=[
                    ErrorDetail(
                        field=update.field_code,
                        reason='Submit a correction through the validated form flow.',
                    )
                ],
            )
        source_ref = (
            f'claim:{claim.claim_id}:revision:{claim.revision + 1}:field:{update.field_code}'
        )
        updated_fields[update.field_code] = resolve_form_change(
            field_code=update.field_code,
            existing=existing,
            proposal=ProposedFormChange(
                field_code=update.field_code,
                value=update.value,
                source=FormSource.CLAIMANT,
                status=update.status,
                needed_for=NeededFor.CURRENT_ACTION,
                relation=(
                    AssertionRelation.CORRECTION if update.correction_reason is not None else None
                ),
                reported_text=update.correction_reason,
            ),
            source_ref=source_ref,
            message_text=update.correction_reason,
            timestamp=timestamp,
            accepted_status=update.status,
            updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id=principal.subject),
            explicit_correction=update.correction_reason is not None,
        )

    incident_type = _apply_product_family_transition(claim, updated_fields)
    projected_claim = claim.model_copy(
        update={
            'form': {**claim.form, **updated_fields},
            'incident_type': incident_type,
        }
    )
    candidate_branch_evaluation = BranchRuleEvaluator().evaluate(
        projected_claim,
        current_action=claim.claim_state.next_action,
        recomputation_reason='form_update_validation',
    )
    candidate_field_selection = {
        item.field_code: item.selection_state
        for item in candidate_branch_evaluation.field_selection
    }
    for update in payload.updates:
        if (
            update.field_code != 'claim.product_family'
            and candidate_field_selection.get(update.field_code) is FieldSelectionState.INACTIVE
        ):
            raise ApiError(
                status_code=422,
                code='VALIDATION_ERROR',
                message='The form update is incompatible with the selected claim family.',
                details=[
                    ErrorDetail(
                        field=update.field_code,
                        reason='The field is inactive for the selected or confirmed family.',
                    )
                ],
            )
    next_step = next_requirement_step(candidate_branch_evaluation.requirements)
    updated_claim = projected_claim.model_copy(
        update={
            'customer_next_step': next_step,
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    try:
        repository.save_claim(
            updated_claim,
            expected_revision=expected_revision,
            branch_evaluation=build_applied_branch_evaluation(
                updated_claim,
                repository=repository,
                recomputation_reason='form_updated',
                trigger_source_refs=_field_transition_refs(claim, updated_fields),
            ),
        )
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict
    claimant_updated_fields = project_claimant_form_fields(
        repository,
        updated_claim,
        updated_fields,
    )
    return FormPatchResponse(
        claim_id=claim_id,
        revision=updated_claim.revision,
        updated_fields=claimant_updated_fields,
        customer_next_step=next_step,
        dynamic_form=claimant_dynamic_form_projection(repository, updated_claim),
    )


def confirm_form_fields(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: FormConfirmationRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> FormConfirmationResponse:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/form/confirmations'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing_idempotency = repository.find_idempotency(principal.subject, route, key)
    if existing_idempotency is not None:
        if existing_idempotency.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused with a different request.',
            )
        if existing_idempotency.response_payload is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent confirmation result could not be restored.',
                retryable=True,
            )
        return FormConfirmationResponse.model_validate(existing_idempotency.response_payload)

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    duplicate_codes = len(set(payload.field_codes)) != len(payload.field_codes)
    unavailable_codes = [
        field_code
        for field_code in payload.field_codes
        if (
            field_code == 'contents.items'
            and not any(item.status is FormStatus.PROPOSED for item in claim.contents_items)
        )
        or (
            field_code != 'contents.items'
            and (
                field_code not in claim.form
                or claim.form[field_code].status not in {FormStatus.PROPOSED, FormStatus.CONFIRMED}
            )
        )
    ]
    if duplicate_codes or unavailable_codes:
        details = [
            ErrorDetail(field=field_code, reason='The field does not exist or is not confirmable.')
            for field_code in unavailable_codes
        ]
        if duplicate_codes:
            details.append(
                ErrorDetail(field='field_codes', reason='Field codes must not be repeated.')
            )
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='One or more fields cannot be confirmed.',
            details=details,
        )

    timestamp = now_utc()
    confirmation_revision = claim.revision + 1
    confirmed_fields = {
        field_code: confirm_form_field(
            claim.form[field_code],
            timestamp=timestamp,
            updated_by=ActorReference(
                actor_type=ActorType.CLAIMANT,
                actor_id=principal.subject,
            ),
            source_ref=(
                f'claim:{claim.claim_id}:revision:{confirmation_revision}:field:{field_code}'
            ),
        )
        for field_code in payload.field_codes
        if field_code != 'contents.items'
    }
    confirmed_contents_items = [
        confirm_contents_item(
            item,
            timestamp=timestamp,
            updated_by=ActorReference(
                actor_type=ActorType.CLAIMANT,
                actor_id=principal.subject,
            ),
            source_ref=(
                f'claim:{claim.claim_id}:revision:{confirmation_revision}:field:contents.items'
            ),
        )
        if item.status is FormStatus.PROPOSED and 'contents.items' in payload.field_codes
        else item
        for item in claim.contents_items
    ]
    incident_type = _apply_product_family_transition(claim, confirmed_fields)
    projected_claim = claim.model_copy(
        update={
            'form': {**claim.form, **confirmed_fields},
            'contents_items': confirmed_contents_items,
            'incident_type': incident_type,
        }
    )
    resolved_requirements = (
        BranchRuleEvaluator()
        .evaluate(
            projected_claim,
            current_action=AgentAction.CONFIRM,
            recomputation_reason='form_confirmation_preview',
        )
        .requirements
    )
    next_step = next_requirement_step(resolved_requirements)
    updated_claim = claim.model_copy(
        update={
            'form': {**claim.form, **confirmed_fields},
            'contents_items': confirmed_contents_items,
            'incident_type': incident_type,
            'claim_state': claim.claim_state.model_copy(update={'next_action': AgentAction.ASK}),
            'customer_next_step': next_step,
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    try:
        repository.save_claim(
            updated_claim,
            expected_revision=expected_revision,
            branch_evaluation=build_applied_branch_evaluation(
                updated_claim,
                repository=repository,
                recomputation_reason='form_confirmed',
                current_action=AgentAction.CONFIRM,
                trigger_source_refs=_field_transition_refs(claim, confirmed_fields),
            ),
        )
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict
    claimant_confirmed_fields = project_claimant_form_fields(
        repository,
        updated_claim,
        confirmed_fields,
    )
    response = FormConfirmationResponse(
        claim_id=claim_id,
        revision=updated_claim.revision,
        confirmed_fields=claimant_confirmed_fields,
        confirmed_contents_items=_claimant_contents_items(repository, updated_claim),
        customer_next_step=next_step,
        dynamic_form=claimant_dynamic_form_projection(repository, updated_claim),
    )
    repository.save_idempotency(
        IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=claim.active_session_id or '',
            response_payload=response.model_dump(mode='json'),
        )
    )
    return response
