"""Staff answers to questions the Agent passed to the claims team.

The Agent records a claimant question it cannot answer with authority on its
message (``turn_record.northwind_questions``). A collaborator on the Claim answers
it here; the answer is a claimant-visible customer update that names the
question, so it reaches the claimant whether or not their session is still open.
"""

from __future__ import annotations

from hashlib import sha256

from pydantic import Field

from backend.core.auth import Principal, require_staff_capability
from backend.core.errors import ApiError
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditPermission,
    AuditPermissionOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.ids import new_id
from backend.domain.models import (
    ActorType,
    ContractModel,
    CustomerUpdateRecord,
    ResponsibleParty,
)
from backend.domain.open_items import open_question
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.claim_conversation import claim_messages
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)
from backend.services.workbench import require_workbench_action

ACTION_CODE = 'conversation.answer_claimant_question'


class AnswerClaimantQuestionRequest(ContractModel):
    answer: str = Field(min_length=1, max_length=1000)


class AnswerClaimantQuestionResponse(ContractModel):
    claim_id: str
    claim_revision: int = Field(ge=1)
    question_id: str
    update: CustomerUpdateRecord


def _replay(
    repository: PersistenceRepository, actor: str, route: str, key: str, fingerprint: str
) -> AnswerClaimantQuestionResponse | None:
    record = repository.find_idempotency(actor, route, key)
    if record is None:
        return None
    if record.request_fingerprint != fingerprint:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The idempotency key was reused with a different request.',
        )
    if record.response_payload is None:
        raise ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The saved answer response is unavailable.',
            retryable=True,
        )
    return AnswerClaimantQuestionResponse.model_validate(record.response_payload)


def answer_claimant_question(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    question_id: str,
    payload: AnswerClaimantQuestionRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> AnswerClaimantQuestionResponse:
    """Record a staff answer to an open claimant question.

    Raises:
        ApiError: Authority, question state, revision, or replay checks fail.
    """
    require_staff_capability(principal, 'workbench:write')
    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    route = f'/api/v1/workbench/claims/{claim_id}/questions/{question_id}/answer'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = _replay(repository, principal.subject, route, key, fingerprint)
    if replay is not None:
        return replay
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise ApiError(
            status_code=404, code='RESOURCE_NOT_FOUND', message='The Claim was not found.'
        )
    if (
        open_question(
            question_id,
            claim_messages(repository, claim),
            repository.list_customer_updates(claim_id),
        )
        is None
    ):
        raise ApiError(
            status_code=409,
            code='QUESTION_NOT_OPEN',
            message='This question has already been answered or does not belong to the Claim.',
        )
    action = require_workbench_action(
        repository, principal, claim, expected, ACTION_CODE, question_id
    )
    timestamp = now_utc()
    update = CustomerUpdateRecord(
        update_id=new_id('cup'),
        claim_id=claim_id,
        summary=payload.answer.strip(),
        responsible_party=ResponsibleParty.CLAIMS_PROFESSIONAL,
        related_refs=[question_id],
        created_by=principal.subject,
        created_at=timestamp,
    )
    updated = claim.model_copy(update={'revision': expected + 1, 'updated_at': timestamp})
    response = AnswerClaimantQuestionResponse(
        claim_id=claim_id,
        claim_revision=updated.revision,
        question_id=question_id,
        update=update,
    )
    record = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=claim.active_session_id or '',
        action_registry_version=action.registry_version,
        action_code=action.action_code,
        target_ref=question_id,
        response_payload=response.model_dump(mode='json'),
        response_status=200,
    )
    audit = AuditEventEnvelope(
        event_id='aud_answer_'
        + sha256(f'{principal.subject}:{route}:{key}'.encode()).hexdigest()[:24],
        event_type=AuditEventType.ACTION_COMPLETED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM, subject_id=claim_id, claim_id=claim_id
        ),
        actor=AuditActor(
            actor_type=ActorType.STAFF,
            actor_id=principal.subject,
            auth_source=principal.auth_source,
        ),
        reason='Staff answered a claimant question passed on by the Agent.',
        source_refs=[question_id, update.update_id],
        permission=AuditPermission(
            required_permission=action.action_code, outcome=AuditPermissionOutcome.AUTHORISED
        ),
        visibility=AuditVisibility.INTERNAL_ONLY,
        correlation_id=key,
        idempotency_key=key,
        claim_revision=updated.revision,
        created_at=timestamp,
    )
    try:
        repository.save_staff_mutation(
            updated, expected, record, customer_update=update, audit_event=audit
        )
    except (RevisionConflict, IdempotencyConflict) as error:
        replayed = _replay(repository, principal.subject, route, key, fingerprint)
        if replayed is not None:
            return replayed
        current = repository.get_claim_internal(claim_id)
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The Claim changed. Refresh before answering again.',
            current_revision=current.revision if current is not None else None,
            retryable=True,
        ) from error
    return response
