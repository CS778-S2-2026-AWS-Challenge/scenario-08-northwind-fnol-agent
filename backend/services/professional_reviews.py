from backend.domain.ids import new_id
from backend.domain.models import (
    CustomerNextStep,
    EvidenceRecord,
    FormStatus,
    HandoffPacket,
    HandoffPriority,
    HandoffRecord,
    HandoffStatus,
    HandoffTrigger,
    HandoffType,
    MessageVisibility,
    ResponsibleParty,
    WorkingClaim,
)
from backend.domain.retrieval import PolicyRetrievalRecord, ReviewSignalRecord
from backend.repositories.protocols import PersistenceRepository
from backend.services.evidence_handoff import (
    assemble_evidence_handoff_packet,
    default_handoff_visibility,
)
from backend.services.handoff_context import build_handoff_transfer_context
from backend.services.support import now_utc

PROFESSIONAL_REVIEW_NEXT_STEP_STATUS = 'professional_review_queued'
PROFESSIONAL_REVIEW_RESPONSIBLE_PARTY = ResponsibleParty.CLAIMS_PROFESSIONAL


def build_policy_review_handoff(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    *,
    retrieval: PolicyRetrievalRecord,
    signal: ReviewSignalRecord,
    source_message_id: str,
    pending_evidence: EvidenceRecord | None = None,
) -> tuple[HandoffRecord, CustomerNextStep]:
    """Build an internal decision request without asserting claimant intent."""

    timestamp = now_utc()
    messages = (
        repository.list_messages(claim.claim_id, claim.active_session_id, claim.customer_id)
        if claim.active_session_id is not None
        else []
    )
    evidence = repository.list_evidence(claim.claim_id, claim.customer_id)
    if pending_evidence is not None:
        evidence.append(pending_evidence)
    transfer_context = build_handoff_transfer_context(
        repository,
        claim,
        evidence=evidence,
        handoffs=repository.list_handoffs(claim.claim_id, claim.customer_id),
    )
    form_values = list(claim.form.items())
    incident_field = claim.form.get('incident.description')
    promised_next_step = (
        'A claims specialist is checking one policy point. You can add the police report when it '
        'becomes available; the current review can continue now.'
    )
    source_refs = list(
        dict.fromkeys(
            [
                retrieval.retrieval_id,
                signal.signal_id,
                *signal.source_refs,
                source_message_id,
                *transfer_context.history_retrieval_refs,
                *transfer_context.provenance_refs,
            ]
        )
    )
    packet = HandoffPacket(
        incident_summary=str(incident_field.value) if incident_field is not None else None,
        form_revision=claim.revision,
        form_snapshot=claim.form,
        missing_items=[code for code, field in form_values if field.status is FormStatus.MISSING],
        pending_items=[
            code for code, field in form_values if field.status is FormStatus.PENDING_GENERATION
        ],
        conflicts=[code for code, field in form_values if field.status is FormStatus.DISPUTED],
        low_confidence_items=[
            code
            for code, field in form_values
            if field.confidence is not None and field.confidence < 0.8
        ],
        policy_citation_refs=[retrieval.retrieval_id],
        history_evidence_refs=transfer_context.history_retrieval_refs,
        source_refs=source_refs,
        prior_customer_updates=[
            str(message.content.get('text'))
            for message in messages
            if message.actor.value in {'agent', 'staff'}
            and message.visibility is not MessageVisibility.INTERNAL_ONLY
            and message.content.get('text')
        ],
        promised_next_step=promised_next_step,
    )
    packet = assemble_evidence_handoff_packet(
        packet,
        claim.claim_id,
        ((record, default_handoff_visibility(record)) for record in evidence),
    )
    handoff = HandoffRecord(
        handoff_id=new_id('hnd'),
        claim_id=claim.claim_id,
        type=HandoffType.PROFESSIONAL_REVIEW,
        status=HandoffStatus.QUEUED,
        priority=HandoffPriority.STANDARD,
        queue='professional_review',
        support_need=None,
        trigger=HandoffTrigger.PROFESSIONAL_REVIEW_REQUIRED,
        reason_codes=signal.reason_codes,
        reason=signal.summary,
        requested_action=(
            'Determine whether the reported rear-end collision can proceed under the cited '
            'collision-damage wording. Record the decision, reason, and source. The pending police '
            'report must not block this review unless the cited policy wording requires it.'
        ),
        applied_rule='sourced_policy_uncertainty_requires_staff_review',
        packet=packet,
        source_message_id=source_message_id,
        created_at=timestamp,
    )
    next_step = CustomerNextStep(
        status=PROFESSIONAL_REVIEW_NEXT_STEP_STATUS,
        summary=promised_next_step,
        responsible_party=PROFESSIONAL_REVIEW_RESPONSIBLE_PARTY,
    )
    return handoff, next_step
