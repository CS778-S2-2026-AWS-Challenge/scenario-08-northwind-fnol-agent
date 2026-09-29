"""Validation and staff-signal projection for policy application judgments."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast

from backend.domain.agent_v8 import V8PolicyJudgmentProposal
from backend.domain.ids import new_id
from backend.domain.retrieval import ReviewSignalRecord

JUDGMENT_POINT_TAXONOMY: Mapping[str, Mapping[str, object]] = {
    'liability_split': {
        'families': frozenset({'motor'}),
        'fields': frozenset({'parties.other_parties'}),
    },
    'excess_multiplicity': {
        'families': frozenset({'motor', 'home', 'contents'}),
        'fields': frozenset({'claim.product_family'}),
    },
    'driver_permission_status': {
        'families': frozenset({'motor'}),
        'fields': frozenset({'driver.licence_status'}),
    },
    'unsafe_use_applicability': {
        'families': frozenset({'motor'}),
        'fields': frozenset({'vehicle.usage'}),
    },
    'gradual_damage_discoverability': {
        'families': frozenset({'home'}),
        'fields': frozenset({'incident.discovered_at'}),
    },
    'natural_hazard_allocation': {
        'families': frozenset({'home'}),
        'fields': frozenset({'incident.location'}),
    },
    'occupancy_change_applicability': {
        'families': frozenset({'home'}),
        'fields': frozenset({'property.habitable'}),
    },
    'theft_circumstance': {
        'families': frozenset({'contents'}),
        'fields': frozenset({'incident.description'}),
    },
    'unsecured_property_dispute': {
        'families': frozenset({'contents'}),
        'fields': frozenset({'incident.description'}),
    },
    'multi_event_dispute': {
        'families': frozenset({'motor', 'home', 'contents'}),
        'fields': frozenset({'incident.description'}),
    },
    'item_classification_dispute': {
        'families': frozenset({'contents'}),
        'fields': frozenset({'contents.items'}),
    },
}


def validate_policy_judgment_proposals(
    proposals: Sequence[V8PolicyJudgmentProposal],
    *,
    product_family: str | None,
    present_fields: set[str],
    handoff_active: bool = False,
) -> tuple[list[V8PolicyJudgmentProposal], list[dict[str, str]]]:
    accepted: list[V8PolicyJudgmentProposal] = []
    rejected: list[dict[str, str]] = []
    for proposal in proposals:
        spec = JUDGMENT_POINT_TAXONOMY[proposal.kind]
        families = cast(frozenset[str], spec['families'])
        fields = cast(frozenset[str], spec['fields'])
        if handoff_active:
            reason = 'suppressed_during_handoff'
        elif product_family not in families:
            reason = 'family_not_eligible'
        elif not fields.issubset(present_fields):
            reason = 'required_facts_missing'
        elif any(item.kind == proposal.kind for item in accepted):
            reason = 'duplicate_kind'
        else:
            accepted.append(proposal)
            continue
        rejected.append({'kind': proposal.kind, 'reason': reason})
    return accepted, rejected


def review_signal_for_policy_judgment(
    claim_id: str, proposal: V8PolicyJudgmentProposal, *, created_at: datetime
) -> ReviewSignalRecord:
    return ReviewSignalRecord(
        signal_id=new_id('sig'),
        claim_id=claim_id,
        code='POLICY_JUDGMENT_PROPOSAL',
        source_refs=list(dict.fromkeys(proposal.source_refs)),
        reason_codes=[f'JUDGMENT_POINT:{proposal.kind}'],
        summary=(
            f'Policy application requires professional review for {proposal.kind}: '
            f'{proposal.rationale}'
        )[:1000],
        created_at=created_at,
        judgment_point_kind=proposal.kind,
        proposed_assessment=proposal.assessment,
        proposal_rationale=proposal.rationale,
    )


def policy_judgment_signals(
    claim_id: str,
    proposals: Sequence[V8PolicyJudgmentProposal],
    *,
    product_family: str | None,
    present_fields: set[str],
    created_at: datetime,
    handoff_active: bool = False,
) -> tuple[list[ReviewSignalRecord], list[dict[str, str]]]:
    valid, rejected = validate_policy_judgment_proposals(
        proposals,
        product_family=product_family,
        present_fields=present_fields,
        handoff_active=handoff_active,
    )
    return [
        review_signal_for_policy_judgment(claim_id, item, created_at=created_at) for item in valid
    ], rejected
