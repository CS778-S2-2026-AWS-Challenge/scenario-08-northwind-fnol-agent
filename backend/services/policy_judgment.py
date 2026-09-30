"""Gate advisory policy judgments on confirmed facts and authorized clause evidence."""

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import ValidationError

from backend.domain.agent_v8 import V8PolicyJudgmentProposal
from backend.domain.knowledge import KnowledgeCitation
from backend.domain.models import FactPrecision, FactResolutionState, FormStatus, WorkingClaim
from backend.domain.retrieval import ReviewSignalRecord


@dataclass(frozen=True)
class JudgmentPointSpec:
    """Structural prerequisites, not rules that decide policy applicability."""

    clauses_by_family: Mapping[str, tuple[str, ...]]
    required_fields: tuple[str, ...]
    required_values: Mapping[str, object] = field(default_factory=dict)


_EXCESS_CLAUSES = {
    'motor': ('MTR-EXC-01',),
    'home': ('HOM-EXC-01',),
    'contents': ('CON-EXC-01',),
}
JUDGMENT_POINT_TAXONOMY: dict[str, JudgmentPointSpec] = {
    'liability_split': JudgmentPointSpec(
        {'motor': ('MTR-COV-02',)},
        ('parties.other_parties', 'incident.description'),
        {'parties.other_parties': True},
    ),
    'excess_multiplicity': JudgmentPointSpec(_EXCESS_CLAUSES, ('incident.description',)),
    'driver_permission_status': JudgmentPointSpec(
        {'motor': ('MTR-EXC-02',)}, ('driver.owner_permission', 'driver.licence_status')
    ),
    'alcohol_drug_applicability': JudgmentPointSpec(
        {'motor': ('MTR-EXC-03',)}, ('incident.description',)
    ),
    'unsafe_use_applicability': JudgmentPointSpec(
        {'motor': ('MTR-EXC-04',)}, ('vehicle.use', 'incident.description')
    ),
    'gradual_damage_discoverability': JudgmentPointSpec(
        {'home': ('HOM-BEN-03',)}, ('incident.discovered_at', 'incident.description')
    ),
    'natural_hazard_allocation': JudgmentPointSpec(
        {'home': ('HOM-NHZ-01',)}, ('incident.location', 'incident.description')
    ),
    'occupancy_change_applicability': JudgmentPointSpec(
        {'home': ('HOM-EXC-04',)}, ('property.occupancy', 'incident.description')
    ),
    'theft_circumstance': JudgmentPointSpec(
        {'contents': ('CON-COV-02',)}, ('theft.entry_context', 'incident.description')
    ),
    'unsecured_property_dispute': JudgmentPointSpec(
        {'contents': ('CON-EXC-04',)}, ('contents.items', 'incident.description')
    ),
    'multi_event_dispute': JudgmentPointSpec(_EXCESS_CLAUSES, ('incident.description',)),
    'item_classification_dispute': JudgmentPointSpec(
        {'contents': ('CON-AUTH-01',)}, ('contents.items',)
    ),
}


def _known_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {'', 'unknown', 'not_applicable', 'not provided', 'n/a'}
    if isinstance(value, Mapping):
        if value.get('precision') == 'unknown':
            return False
        return any(_known_value(item) for key, item in value.items() if key != 'precision')
    if isinstance(value, list | tuple):
        return bool(value) and all(_known_value(item) for item in value)
    return isinstance(value, bool | int | float)


def _has_fact(claim: WorkingClaim, code: str) -> bool:
    if code == 'contents.items':
        return any(
            item.status is FormStatus.CONFIRMED
            and item.resolution_state is FactResolutionState.RESOLVED
            and _known_value(item.description)
            and _known_value(item.category)
            for item in claim.contents_items
        )
    fact = claim.form.get(code)
    return (
        fact is not None
        and fact.status is FormStatus.CONFIRMED
        and fact.resolution_state is FactResolutionState.RESOLVED
        and fact.precision is not FactPrecision.UNKNOWN
        and _known_value(fact.value)
    )


def _citations(knowledge: Sequence[Mapping[str, object]]) -> dict[str, KnowledgeCitation]:
    citations: dict[str, KnowledgeCitation] = {}
    for chunk in knowledge:
        try:
            citation = KnowledgeCitation.model_validate(chunk)
        except ValidationError:
            continue
        if all(value.strip() for value in citation.model_dump().values()):
            citations[citation.chunk_id] = citation
    return citations


def _authorized_refs(
    proposal: V8PolicyJudgmentProposal,
    clauses: tuple[str, ...],
    knowledge: Sequence[Mapping[str, object]],
) -> list[str] | None:
    allowed: set[str] = set()
    for citation in _citations(knowledge).values():
        if any(
            re.search(rf'(?<![A-Z0-9-]){re.escape(clause)}(?![A-Z0-9-])', citation.section_path)
            for clause in clauses
        ):
            allowed.add(citation.chunk_id)
    refs = list(dict.fromkeys(proposal.source_refs))
    return refs if refs and all(ref in allowed for ref in refs) else None


def validate_policy_judgment_proposals(
    proposals: Sequence[V8PolicyJudgmentProposal],
    *,
    claim: WorkingClaim,
    authorized_knowledge: Sequence[Mapping[str, object]],
    handoff_active: bool = False,
) -> tuple[list[V8PolicyJudgmentProposal], list[dict[str, str]]]:
    """Validate model advice without deciding coverage or changing Claim facts.

    Args:
        proposals: Untrusted optional model proposals.
        claim: Authoritative Claim after the reducer validates this turn's fact changes.
        authorized_knowledge: Actual server-authorized knowledge loaded in this turn.
        handoff_active: Whether an active handoff suppresses new proposals.

    Returns:
        Accepted proposals with canonical chunk references, and bounded rejection reasons.
    """
    accepted: list[V8PolicyJudgmentProposal] = []
    rejected: list[dict[str, str]] = []
    family_fact = claim.form.get('claim.product_family')
    family = family_fact.value if _has_fact(claim, 'claim.product_family') and family_fact else None
    for proposal in proposals:
        spec = JUDGMENT_POINT_TAXONOMY.get(proposal.kind)
        clauses = spec.clauses_by_family.get(family, ()) if spec and isinstance(family, str) else ()
        refs = _authorized_refs(proposal, clauses, authorized_knowledge)
        if handoff_active:
            reason = 'suppressed_during_handoff'
        elif spec is None:
            reason = 'unknown_kind'
        elif not clauses:
            reason = 'family_not_eligible'
        elif not all(_has_fact(claim, code) for code in spec.required_fields) or any(
            claim.form.get(code) is None or claim.form[code].value != value
            for code, value in spec.required_values.items()
        ):
            reason = 'required_facts_missing'
        elif refs is None:
            reason = 'policy_evidence_not_authorized'
        elif any(item.kind == proposal.kind for item in accepted):
            reason = 'duplicate_kind'
        else:
            accepted.append(proposal.model_copy(update={'source_refs': refs}))
            continue
        rejected.append({'kind': proposal.kind, 'reason': reason})
    return accepted, rejected


def review_signal_for_policy_judgment(
    claim_id: str,
    proposal: V8PolicyJudgmentProposal,
    *,
    claim_revision: int,
    trigger_message_id: str,
    created_at: datetime,
    authorized_knowledge: Sequence[Mapping[str, object]],
) -> ReviewSignalRecord:
    """Build one retry-stable advisory signal from a validated proposal.

    Args:
        claim_id: Owning Claim identity.
        claim_revision: Accepted turn revision containing the prerequisite facts.
        proposal: Proposal already validated against authorized facts and knowledge.
        trigger_message_id: Durable triggering message identity; unchanged on retry.
        created_at: Server-observed creation time.
        authorized_knowledge: Server-loaded evidence retained for durable provenance.

    Returns:
        A staff-only ReviewSignalRecord, not a decision.
    """
    identity = f'{claim_id}\x00{trigger_message_id}\x00{proposal.kind}'
    citations = _citations(authorized_knowledge)
    sources = [citations[ref] for ref in dict.fromkeys(proposal.source_refs)]
    return ReviewSignalRecord(
        signal_id=f'sig_{hashlib.sha256(identity.encode()).hexdigest()[:24]}',
        claim_id=claim_id,
        code='POLICY_JUDGMENT_PROPOSAL',
        source_refs=[
            trigger_message_id,
            f'claim:{claim_id}:revision:{claim_revision}',
            *dict.fromkeys(proposal.source_refs),
        ],
        reason_codes=[f'JUDGMENT_POINT:{proposal.kind}'],
        summary=(
            f'Policy application requires professional review for {proposal.kind}: '
            f'{proposal.rationale}'
        )[:1000],
        created_at=created_at,
        judgment_point_kind=proposal.kind,
        proposed_assessment=proposal.assessment,
        proposal_rationale=proposal.rationale,
        policy_sources=sources,
    )


def policy_judgment_signals(
    claim: WorkingClaim,
    proposals: Sequence[V8PolicyJudgmentProposal],
    *,
    authorized_knowledge: Sequence[Mapping[str, object]],
    trigger_message_id: str,
    created_at: datetime,
    handoff_active: bool = False,
) -> tuple[list[ReviewSignalRecord], list[dict[str, str]]]:
    """Convert eligible model proposals into existing staff review records.

    Args:
        claim: Authoritative persisted Claim.
        proposals: Optional model proposals.
        authorized_knowledge: Actual server-authorized knowledge loaded in this turn.
        trigger_message_id: Stable durable message identity.
        created_at: Server-observed creation time.
        handoff_active: Active handoff suppression gate.

    Returns:
        Validated staff signals and rejection reasons; no Claim or decision mutation.
    """
    valid, rejected = validate_policy_judgment_proposals(
        proposals,
        claim=claim,
        authorized_knowledge=authorized_knowledge,
        handoff_active=handoff_active,
    )
    return [
        review_signal_for_policy_judgment(
            claim.claim_id,
            item,
            claim_revision=claim.revision,
            trigger_message_id=trigger_message_id,
            created_at=created_at,
            authorized_knowledge=authorized_knowledge,
        )
        for item in valid
    ], rejected
