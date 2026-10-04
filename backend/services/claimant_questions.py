"""A handler settles items on a claim's waiting list.

Staff do not enter a conversation while it is being collected. The Agent puts
what it cannot settle on the waiting list (``turn_record.northwind_questions``):
a question with its proposed answer and basis, or a request to be contacted.
A collaborator on the claim then approves the proposal, edits it, declines it
with a reason, or marks a contact request as contacted.

The decision is a claimant-visible customer update naming the item, so the
claimant's waiting item closes whether or not their session is still open. An
approved or edited answer is also posted to the claimant's open session as the
handler's message, in the same save.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Literal

from pydantic import Field, model_validator

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
    MessageRecord,
    MessageVisibility,
    ResponsibleParty,
    SessionStatus,
)
from backend.domain.open_items import CONTACTED_REF, DECLINED_REF, open_question
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.claim_conversation import claim_messages
from backend.services.staff_message_audit import build_staff_message_audit_event
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)
from backend.services.workbench import require_workbench_action

ACTION_CODE = 'conversation.answer_claimant_question'

WaitingItemDecision = Literal['approve', 'edit', 'decline', 'contacted']


class AnswerClaimantQuestionRequest(ContractModel):
    """approve sends the proposed answer; edit sends ``text``; decline gives ``text``
    as the reason the claimant reads; contacted settles a contact request, with an
    optional note in ``text``."""

    decision: WaitingItemDecision
    text: str | None = Field(default=None, max_length=1000)

    @model_validator(mode='after')
    def _text_where_needed(self) -> AnswerClaimantQuestionRequest:
        if self.decision in {'edit', 'decline'} and not (self.text or '').strip():
            raise ValueError('An edited answer or a decline reason needs text.')
        return self


class AnswerClaimantQuestionResponse(ContractModel):
    claim_id: str
    claim_revision: int = Field(ge=1)
    question_id: str
    decision: WaitingItemDecision
    update: CustomerUpdateRecord
    message: MessageRecord | None = None


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


def _invalid(message: str) -> ApiError:
    return ApiError(status_code=422, code='VALIDATION_ERROR', message=message)


def answer_claimant_question(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    question_id: str,
    payload: AnswerClaimantQuestionRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> AnswerClaimantQuestionResponse:
    """Record a handler's decision on an open waiting-list item.

    Raises:
        ApiError: Authority, item state, revision, or replay checks fail.
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
    item = open_question(
        question_id,
        claim_messages(repository, claim),
        repository.list_customer_updates(claim_id),
    )
    if item is None:
        raise ApiError(
            status_code=409,
            code='QUESTION_NOT_OPEN',
            message='This item has already been settled or does not belong to the Claim.',
        )
    if payload.decision == 'contacted' and item.kind != 'contact_request':
        raise _invalid('Only a contact request can be marked as contacted.')
    if payload.decision in {'approve', 'edit'} and item.kind == 'contact_request':
        raise _invalid('A contact request is settled by marking it contacted or declining it.')
    if payload.decision == 'approve' and not item.proposed_answer:
        raise _invalid('There is no proposed answer to approve; edit one instead.')
    action = require_workbench_action(
        repository, principal, claim, expected, ACTION_CODE, question_id
    )
    text = (
        item.proposed_answer
        if payload.decision == 'approve'
        else (payload.text or '').strip() or 'Northwind contacted you about this request.'
    )
    assert text is not None
    marker = {'decline': [DECLINED_REF], 'contacted': [CONTACTED_REF]}.get(payload.decision, [])
    timestamp = now_utc()
    update = CustomerUpdateRecord(
        update_id=new_id('cup'),
        claim_id=claim_id,
        summary=text,
        responsible_party=ResponsibleParty.CLAIMS_PROFESSIONAL,
        related_refs=[question_id, *marker],
        created_by=principal.subject,
        created_at=timestamp,
    )
    # An answer also reaches the open conversation as the handler's own message.
    message: MessageRecord | None = None
    session = (
        repository.get_session(claim_id, claim.active_session_id, claim.customer_id)
        if claim.active_session_id is not None
        else None
    )
    if (
        payload.decision in {'approve', 'edit'}
        and session is not None
        and (session.status is SessionStatus.ACTIVE)
    ):
        message = MessageRecord(
            message_id=new_id('msg'),
            claim_id=claim_id,
            session_id=session.session_id,
            actor=ActorType.STAFF,
            visibility=MessageVisibility.SHARED,
            content={'type': 'text', 'text': text, 'answers_item_id': question_id},
            created_at=timestamp,
        )
    updated = claim.model_copy(update={'revision': expected + 1, 'updated_at': timestamp})
    response = AnswerClaimantQuestionResponse(
        claim_id=claim_id,
        claim_revision=updated.revision,
        question_id=question_id,
        decision=payload.decision,
        update=update,
        message=message,
    )
    record = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=message.session_id if message is not None else claim.active_session_id or '',
        message_id=message.message_id if message is not None else None,
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
        reason=f'Staff settled a waiting-list item ({payload.decision}).',
        source_refs=[
            question_id,
            update.update_id,
            *([message.message_id] if message is not None else []),
        ],
        permission=AuditPermission(
            required_permission=action.action_code, outcome=AuditPermissionOutcome.AUTHORISED
        ),
        visibility=AuditVisibility.INTERNAL_ONLY,
        correlation_id=key,
        idempotency_key=key,
        claim_revision=updated.revision,
        created_at=timestamp,
    )
    if message is not None:
        # A claimant-visible staff message carries the shared staff-message audit fact.
        audit = build_staff_message_audit_event(
            principal=principal,
            claim=updated,
            message=message,
            route=route,
            idempotency_key=key,
            required_permission=action.action_code,
            created_at=timestamp,
            source_refs=(question_id, update.update_id),
        )
    records: dict[str, Any] = {'customer_update': update}
    if message is not None:
        records['message'] = message
    try:
        repository.save_staff_mutation(updated, expected, record, audit_event=audit, **records)
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
