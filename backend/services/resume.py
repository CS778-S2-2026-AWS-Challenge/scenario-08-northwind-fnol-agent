from typing import Any, cast

from backend.core.auth import Principal
from backend.domain.models import (
    ActorType,
    ClaimantSession,
    EvidenceFileStatus,
    EvidenceStatus,
    FormStatus,
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


def _unresolved_questions(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    source: SessionRecord | None,
) -> list[str]:
    questions = list(source.unresolved_questions) if source is not None else []
    decisions = repository.list_agent_decisions(claim.claim_id, claim.customer_id)
    if decisions and decisions[-1].next_action_requirements:
        questions.append(decisions[-1].customer_next_step.summary)
    return _dedupe(questions)


def _evidence_is_resolved(status: EvidenceStatus, file_status: EvidenceFileStatus) -> bool:
    return status is EvidenceStatus.RECEIVED and file_status is EvidenceFileStatus.READY


def _pending_items(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    source: SessionRecord | None,
) -> list[str]:
    evidence_records = repository.list_evidence(claim.claim_id, claim.customer_id)
    if not evidence_records:
        return _dedupe(list(source.pending_items) if source is not None else [])

    has_resolved_evidence = any(
        _evidence_is_resolved(evidence.status, evidence.file_status)
        for evidence in evidence_records
    )
    items: list[str] = []
    if not has_resolved_evidence and source is not None:
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

    has_resolved_evidence = len(unresolved_evidence_ids) != len(evidence_records)
    messages = {}
    commitments: list[str] = []
    if not has_resolved_evidence and source is not None:
        commitments.extend(source.prior_commitments)
    for session in repository.list_sessions_for_claim(claim.claim_id, claim.customer_id):
        for message in repository.list_messages(
            claim.claim_id,
            session.session_id,
            claim.customer_id,
        ):
            messages[message.message_id] = message
            if (
                message.actor in {ActorType.AGENT, ActorType.STAFF}
                and unresolved_evidence_ids.intersection(message.evidence_refs)
            ):
                text = message.content.get('text')
                if isinstance(text, str) and text.strip():
                    commitments.append(text.strip())

    for decision in repository.list_agent_decisions(claim.claim_id, claim.customer_id):
        if 'EVIDENCE_PENDING_GENERATION' not in decision.reason_codes:
            continue
        trigger = messages.get(decision.trigger_message_id)
        if trigger is not None and trigger.evidence_refs:
            if not unresolved_evidence_ids.intersection(trigger.evidence_refs):
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
