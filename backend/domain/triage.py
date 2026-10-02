"""Deterministic intake triage: how much human handling a created Claim needs next.

Triage does not judge how bad the incident was, whether the loss is covered, or
whether anyone is at fault. It answers three questions in order and keeps every
matched reason so staff can see why a Claim was placed where it is:

1. Does anything need professional judgement? Then the Claim is complex.
2. Otherwise, does anything need follow-up? Then it is standard.
3. Otherwise it is fast-track.

Anything unknown, unavailable or not looked up never yields fast-track.
"""

from collections.abc import Iterable, Mapping, Sequence
from enum import Enum

from backend.domain.branch_registry import BranchRegistrySnapshot
from backend.domain.currency import to_nzd
from backend.domain.evidence import canonical_evidence_kind, evidence_kind
from backend.domain.field_registry import parse_registered_number
from backend.domain.models import (
    AssessorRoutingStatus,
    ClaimCreationStatus,
    ClaimTriage,
    Coverage,
    EvidenceRecord,
    EvidenceStatus,
    FormStatus,
    FraudSignal,
    HandoffRecord,
    HandoffStatus,
    HandoffType,
    RequirementResolution,
    Severity,
    SupportNeed,
    Urgency,
    WorkingClaim,
)
from backend.domain.retrieval import PolicyRetrievalRecord

TRIAGE_RULES_VERSION = 'triage-rules-v1'
# A business setting, not an industry constant: insurers set the value line
# for straight-through handling by their own capacity. NZD 5,000 follows the
# published industry example; exactly the threshold is still fast-track.
DEFAULT_AMOUNT_THRESHOLD = 5000.0

_ACCEPTED_LIABILITY = frozenset({'other_party_accepts', 'claimant_accepts', 'shared'})
_UNRESOLVED_REQUIREMENT_STATES = (
    'missing',
    'disputed',
    'unavailable',
    'pending_generation',
    'proposed',
)
_SEVERITY_RANK = {Severity.FAST_TRACK: 0, Severity.STANDARD: 1, Severity.COMPLEX: 2}
# A receipt or invoice is itself proof of ownership (the tag projection already maps
# both to `evidence.proof_of_ownership`). Every other required kind needs that kind:
# an assessor's report is not the claimant's repair quote.
_SATISFYING_KINDS: dict[str, frozenset[str]] = {
    'proof_of_ownership': frozenset({'proof_of_ownership', 'receipt', 'invoice'}),
}


class TriageReason(str, Enum):
    INJURY_OR_DANGER = 'injury_or_danger'
    LIABILITY_UNRESOLVED = 'liability_unresolved'
    COVERAGE_UNCERTAIN = 'coverage_uncertain'
    COVER_DISAGREEMENT = 'cover_disagreement'
    HOME_UNINHABITABLE_OR_ONGOING = 'home_uninhabitable_or_ongoing'
    FRAUD_REVIEW_REQUIRED = 'fraud_review_required'
    DOCUMENT_OUTSTANDING = 'document_outstanding'
    FACT_UNRESOLVED = 'fact_unresolved'
    POLICY_NOT_VERIFIED = 'policy_not_verified'
    VEHICLE_NOT_DRIVABLE = 'vehicle_not_drivable'
    AMOUNT_OVER_THRESHOLD = 'amount_over_threshold'
    AMOUNT_UNKNOWN = 'amount_unknown'
    THIRD_PARTY_RECOVERY = 'third_party_recovery'


REASON_SEVERITY: dict[TriageReason, Severity] = {
    TriageReason.INJURY_OR_DANGER: Severity.COMPLEX,
    TriageReason.LIABILITY_UNRESOLVED: Severity.COMPLEX,
    TriageReason.COVERAGE_UNCERTAIN: Severity.COMPLEX,
    TriageReason.COVER_DISAGREEMENT: Severity.COMPLEX,
    TriageReason.HOME_UNINHABITABLE_OR_ONGOING: Severity.COMPLEX,
    TriageReason.FRAUD_REVIEW_REQUIRED: Severity.COMPLEX,
    TriageReason.DOCUMENT_OUTSTANDING: Severity.STANDARD,
    TriageReason.FACT_UNRESOLVED: Severity.STANDARD,
    TriageReason.POLICY_NOT_VERIFIED: Severity.STANDARD,
    TriageReason.VEHICLE_NOT_DRIVABLE: Severity.STANDARD,
    TriageReason.AMOUNT_OVER_THRESHOLD: Severity.STANDARD,
    TriageReason.AMOUNT_UNKNOWN: Severity.STANDARD,
    TriageReason.THIRD_PARTY_RECOVERY: Severity.STANDARD,
}


def claim_is_created(claim: WorkingClaim) -> bool:
    """Triage applies only once the report has become a Claim in the claims service."""
    return (
        claim.external_claim is not None
        and claim.external_claim.creation_status is ClaimCreationStatus.CREATED
    )


def triage_claim(
    claim: WorkingClaim,
    *,
    evidence: Sequence[EvidenceRecord],
    handoffs: Sequence[HandoffRecord],
    policy_records: Sequence[PolicyRetrievalRecord],
    active_branches: Sequence[str],
    requirements: RequirementResolution,
    registry: BranchRegistrySnapshot,
    amount_threshold: float = DEFAULT_AMOUNT_THRESHOLD,
    interpreted_kinds: Mapping[str, str] | None = None,
) -> ClaimTriage | None:
    """Return the staff-only triage of a created Claim, or None before creation."""
    if not claim_is_created(claim):
        return None
    reasons = _matched_reasons(
        claim,
        evidence=evidence,
        handoffs=handoffs,
        policy_records=policy_records,
        active_branches=active_branches,
        requirements=requirements,
        registry=registry,
        amount_threshold=amount_threshold,
        interpreted_kinds=interpreted_kinds,
    )
    return ClaimTriage(
        severity=max(
            (REASON_SEVERITY[reason] for reason in reasons),
            key=_SEVERITY_RANK.__getitem__,
            default=Severity.FAST_TRACK,
        ),
        reasons=[reason.value for reason in reasons],
        rules_version=TRIAGE_RULES_VERSION,
        amount_threshold=amount_threshold,
    )


def _matched_reasons(
    claim: WorkingClaim,
    *,
    evidence: Sequence[EvidenceRecord],
    handoffs: Sequence[HandoffRecord],
    policy_records: Sequence[PolicyRetrievalRecord],
    active_branches: Sequence[str],
    requirements: RequirementResolution,
    registry: BranchRegistrySnapshot,
    amount_threshold: float,
    interpreted_kinds: Mapping[str, str] | None = None,
) -> list[TriageReason]:
    checks: list[tuple[TriageReason, bool]] = []
    other_party = _confirmed(claim, 'parties.other_parties') is True
    liability = _confirmed(claim, 'incident.liability_position')
    current_policy = _current_policy_record(claim, policy_records)
    amount = _highest_amount(claim)
    checks.extend(
        [
            (TriageReason.INJURY_OR_DANGER, _injury_or_danger(claim, handoffs)),
            (
                TriageReason.LIABILITY_UNRESOLVED,
                other_party and liability not in _ACCEPTED_LIABILITY,
            ),
            (
                TriageReason.COVERAGE_UNCERTAIN,
                claim.claim_state.coverage is Coverage.AMBIGUOUS
                or (current_policy is not None and bool(current_policy.uncertainty)),
            ),
            (
                TriageReason.COVER_DISAGREEMENT,
                _confirmed(claim, 'claim.cover_disagreement') in {'excess', 'cover'},
            ),
            (
                TriageReason.HOME_UNINHABITABLE_OR_ONGOING,
                _confirmed(claim, 'property.habitable') is False
                or _confirmed(claim, 'property.ongoing_risk') not in {None, 'none'},
            ),
            (
                TriageReason.FRAUD_REVIEW_REQUIRED,
                claim.claim_state.fraud_signal is FraudSignal.REVIEW_REQUIRED,
            ),
            (
                TriageReason.DOCUMENT_OUTSTANDING,
                bool(
                    _outstanding_documents(active_branches, evidence, registry, interpreted_kinds)
                ),
            ),
            (
                TriageReason.FACT_UNRESOLVED,
                any(requirements.by_state.get(state) for state in _UNRESOLVED_REQUIREMENT_STATES),
            ),
            (TriageReason.POLICY_NOT_VERIFIED, current_policy is None),
            (TriageReason.VEHICLE_NOT_DRIVABLE, _vehicle_needs_handling(claim)),
            (
                TriageReason.AMOUNT_OVER_THRESHOLD,
                amount is not None and amount > amount_threshold,
            ),
            (TriageReason.AMOUNT_UNKNOWN, amount is None),
            (
                TriageReason.THIRD_PARTY_RECOVERY,
                other_party and liability in _ACCEPTED_LIABILITY,
            ),
        ]
    )
    return [reason for reason, matched in checks if matched]


def _confirmed(claim: WorkingClaim, code: str) -> object | None:
    field = claim.form.get(code)
    if field is None or field.status is not FormStatus.CONFIRMED:
        return None
    value = field.value
    return value.strip().lower() if isinstance(value, str) else value


def _injury_or_danger(claim: WorkingClaim, handoffs: Iterable[HandoffRecord]) -> bool:
    return (
        _confirmed(claim, 'incident.injury_or_danger') is True
        or claim.claim_state.urgency in {Urgency.URGENT, Urgency.IMMEDIATE_SAFETY_RISK}
        or any(
            item.type is HandoffType.URGENT_SUPPORT or item.support_need is SupportNeed.URGENT
            for item in handoffs
            if item.status is not HandoffStatus.CANCELLED
        )
    )


def _current_policy_record(
    claim: WorkingClaim, records: Sequence[PolicyRetrievalRecord]
) -> PolicyRetrievalRecord | None:
    reference = _confirmed(claim, 'policy.policy_number') or _recorded(
        claim, 'policy.policy_number'
    )
    if not isinstance(reference, str) or not reference:
        return None
    matching = [
        item for item in records if item.facts.policy_reference.strip().lower() == reference
    ]
    return matching[-1] if matching else None


def _recorded(claim: WorkingClaim, code: str) -> object | None:
    field = claim.form.get(code)
    if field is None or field.value is None:
        return None
    value = field.value
    return value.strip().lower() if isinstance(value, str) else value


def _outstanding_documents(
    active_branches: Sequence[str],
    evidence: Sequence[EvidenceRecord],
    registry: BranchRegistrySnapshot,
    interpreted_kinds: Mapping[str, str] | None = None,
) -> set[str]:
    wanted: set[str] = set()
    for branch_id in active_branches:
        branch = registry.branch_by_id.get(branch_id)
        if branch is not None:
            wanted.update(canonical_evidence_kind(kind) for kind in branch.document_requirements)
    received = {
        evidence_kind(item, interpreted_kinds)
        for item in evidence
        if item.status is EvidenceStatus.RECEIVED
    }
    return {
        kind for kind in wanted if not (_SATISFYING_KINDS.get(kind, frozenset({kind})) & received)
    }


def _vehicle_needs_handling(claim: WorkingClaim) -> bool:
    routing = claim.assessor_routing
    return (
        _confirmed(claim, 'vehicle.drivable') is False
        or _confirmed(claim, 'vehicle.towing_required') in {'required', 'already_towed'}
        or (
            routing is not None
            and routing.routing_status
            in {AssessorRoutingStatus.ASSIGNED, AssessorRoutingStatus.QUEUED}
        )
    )


def _highest_amount(claim: WorkingClaim) -> float | None:
    amounts: list[float] = []
    stated = parse_registered_number(_confirmed(claim, 'loss.estimated_amount'))
    if stated is not None:
        amounts.append(stated)
    item_values = [
        to_nzd(item.estimated_value)
        for item in claim.contents_items
        if item.status is FormStatus.CONFIRMED and item.estimated_value is not None
    ]
    if any(value is None for value in item_values):
        # Part of the contents total cannot be expressed in NZD, so the total is unknown.
        return None
    if item_values:
        amounts.append(sum(value for value in item_values if value is not None))
    return max(amounts) if amounts else None
