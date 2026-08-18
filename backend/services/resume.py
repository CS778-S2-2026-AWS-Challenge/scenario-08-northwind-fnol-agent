from typing import Any, cast

from backend.core.auth import Principal
from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.models import (
    ActorType,
    ClaimantSession,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceStatus,
    FormStatus,
    MessageRecord,
    ResumePackage,
    SessionRecord,
    StartSessionRequest,
    WorkingClaim,
)
from backend.repositories.protocols import ClaimRepository, PersistenceRepository
from backend.services.claims import start_session
from backend.services.support import require_idempotency_key


class _ResumeOverlayRepository:
    def __init__(
        self,
        repository: PersistenceRepository,
        source_session_id: str,
        resume: ResumePackage,
    ) -> None:
        self._repository = repository
        self._source_session_id = source_session_id
        self._resume = resume

    def __getattr__(self, name: str) -> Any:
        return getattr(self._repository, name)

    def list_sessions_for_claim(
        self,
        claim_id: str,
        customer_id: str,
    ) -> list[SessionRecord]:
        sessions = self._repository.list_sessions_for_claim(claim_id, customer_id)
        return [
            session.model_copy(
                update={
                    'summary': self._resume.summary,
                    'unresolved_questions': self._resume.unresolved_questions,
                    'pending_items': self._resume.pending_items,
                    'prior_commitments': self._resume.prior_commitments,
                }
            )
            if session.session_id == self._source_session_id
            else session
            for session in sessions
        ]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _latest_resume_source(
    repository: PersistenceRepository,
    claim_id: str,
    customer_id: str,
) -> SessionRecord | None:
    sessions = repository.list_sessions_for_claim(claim_id, customer_id)
    if not sessions:
        return None
    return max(
        sessions,
        key=lambda item: (item.last_active_at, item.started_at, item.session_id),
    )


def _summary(claim: WorkingClaim, source: SessionRecord | None) -> str | None:
    if source is not None and source.summary:
        return source.summary
    description = claim.form.get('incident.description')
    if (
        description is not None
        and description.status is FormStatus.CONFIRMED
        and isinstance(description.value, str)
        and description.value.strip()
    ):
        return description.value.strip()
    return claim.customer_next_step.summary or None


def _confirmation_field_code(requirement: str) -> str | None:
    prefix = 'confirm:'
    if not requirement.startswith(prefix):
        return None
    field_code = requirement[len(prefix) :].strip()
    return field_code if field_code in REGISTERED_FIELD_CODES else None


def _confirmation_requirement_is_resolved(
    claim: WorkingClaim,
    requirement: str,
) -> bool:
    field_code = _confirmation_field_code(requirement)
    if field_code is None:
        return False
    field = claim.form.get(field_code)
    return field is not None and field.status is FormStatus.CONFIRMED


def _normalise_question(value: str) -> str:
    return ' '.join(value.split()).casefold()


def _resolved_confirmation_question_texts(
    claim: WorkingClaim,
    source: SessionRecord | None,
    requirements: list[str],
    candidates: list[str],
) -> set[str]:
    if source is None or claim.revision <= source.context_revision or not requirements:
        return set()
    if any(_confirmation_field_code(requirement) is None for requirement in requirements):
        return set()
    if not all(
        _confirmation_requirement_is_resolved(claim, requirement)
        for requirement in requirements
    ):
        return set()
    return {_normalise_question(candidate) for candidate in candidates if candidate}


def _unresolved_questions(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    source: SessionRecord | None,
) -> list[str]:
    questions = list(source.unresolved_questions) if source is not None else []
    decisions = repository.list_agent_decisions(claim.claim_id, claim.customer_id)
    if not decisions:
        return _dedupe(questions)

    latest = decisions[-1]
    requirements = latest.next_action_requirements
    if not requirements:
        return _dedupe(questions)

    stale_question_texts = _resolved_confirmation_question_texts(
        claim,
        source,
        requirements,
        [
            latest.customer_reason,
            latest.customer_response,
            latest.customer_next_step.summary,
        ],
    )
    if stale_question_texts:
        questions = [
            question
            for question in questions
            if _normalise_question(question) not in stale_question_texts
        ]

    if any(
        not _confirmation_requirement_is_resolved(claim, requirement)
        for requirement in requirements
    ):
        questions.append(latest.customer_next_step.summary)
    return _dedupe(questions)


def _evidence_is_resolved(status: EvidenceStatus, file_status: EvidenceFileStatus) -> bool:
    return status is EvidenceStatus.RECEIVED and file_status is EvidenceFileStatus.READY


def _source_evidence_context_is_current(
    source: SessionRecord | None,
    evidence_records: list[EvidenceRecord],
) -> bool:
    if source is None:
        return False
    return all(
        not _evidence_is_resolved(evidence.status, evidence.file_status)
        and evidence.updated_at <= source.last_active_at
        for evidence in evidence_records
    )


def _pending_items(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    source: SessionRecord | None,
) -> list[str]:
    evidence_records = repository.list_evidence(claim.claim_id, claim.customer_id)
    if not evidence_records:
        return _dedupe(list(source.pending_items) if source is not None else [])

    items: list[str] = []
    if _source_evidence_context_is_current(source, evidence_records) and source is not None:
        items.extend(source.pending_items)
    for evidence in evidence_records:
        if _evidence_is_resolved(evidence.status, evidence.file_status):
            continue
        if evidence.claimant_note and evidence.claimant_note.strip():
            items.append(evidence.claimant_note.strip())
        else:
            label = evidence.kind.replace('_', ' ')
            state = evidence.status.value.replace('_', ' ')
            items.append(f'{label}: {state}.')
    return _dedupe(items)


def _prior_commitments(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    source: SessionRecord | None,
) -> list[str]:
    evidence_records = repository.list_evidence(claim.claim_id, claim.customer_id)
    if not evidence_records:
        return _dedupe(list(source.prior_commitments) if source is not None else [])

    unresolved_evidence_ids = {
        evidence.evidence_id
        for evidence in evidence_records
        if not _evidence_is_resolved(evidence.status, evidence.file_status)
    }
    if not unresolved_evidence_ids:
        return []

    source_context_is_current = _source_evidence_context_is_current(source, evidence_records)
    messages: dict[str, MessageRecord] = {}
    commitments: list[str] = []
    if source_context_is_current and source is not None:
        commitments.extend(source.prior_commitments)
    for session in repository.list_sessions_for_claim(claim.claim_id, claim.customer_id):
        for message in repository.list_messages(
            claim.claim_id,
            session.session_id,
            claim.customer_id,
        ):
            messages[message.message_id] = message
            if message.actor in {
                ActorType.AGENT,
                ActorType.STAFF,
            } and not unresolved_evidence_ids.isdisjoint(message.evidence_refs):
                text = message.content.get('text')
                if isinstance(text, str) and text.strip():
                    commitments.append(text.strip())

    for decision in repository.list_agent_decisions(claim.claim_id, claim.customer_id):
        if 'EVIDENCE_PENDING_GENERATION' not in decision.reason_codes:
            continue
        trigger = messages.get(decision.trigger_message_id)
        if trigger is not None and trigger.evidence_refs:
            if unresolved_evidence_ids.isdisjoint(trigger.evidence_refs):
                continue
        elif not source_context_is_current:
            continue
        commitments.append(decision.customer_response)

    return _dedupe(commitments)


def start_session_with_recovery(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: StartSessionRequest,
    idempotency_key: str | None,
) -> ClaimantSession:
    key = require_idempotency_key(idempotency_key)
    route = f'/api/v1/claims/{claim_id}/sessions'
    existing_retry = repository.find_idempotency(principal.subject, route, key)
    claim = repository.get_claim(claim_id, principal.subject)
    active_session = repository.get_active_session(claim_id, principal.subject)

    should_recover = claim is not None and existing_retry is None and active_session is None
    source = (
        _latest_resume_source(repository, claim_id, principal.subject) if should_recover else None
    )
    if claim is None or not should_recover or source is None:
        return start_session(repository, principal, claim_id, payload, idempotency_key)

    resume = ResumePackage(
        summary=_summary(claim, source),
        unresolved_questions=_unresolved_questions(repository, claim, source),
        pending_items=_pending_items(repository, claim, source),
        prior_commitments=_prior_commitments(repository, claim, source),
        customer_next_step=claim.customer_next_step,
    )
    overlay = _ResumeOverlayRepository(repository, source.session_id, resume)
    return start_session(
        cast(ClaimRepository, overlay),
        principal,
        claim_id,
        payload,
        idempotency_key,
    )
