from collections.abc import Iterable

from backend.domain.models import ClaimantEvidence, EvidenceSource, MessageVisibility


def default_evidence_visibility(source: EvidenceSource) -> MessageVisibility:
    """Return the current safe record-level visibility default for evidence."""

    if source is EvidenceSource.CLAIMANT:
        return MessageVisibility.SHARED
    return MessageVisibility.INTERNAL_ONLY


def claimant_visible_evidence(items: Iterable[ClaimantEvidence]) -> list[ClaimantEvidence]:
    """Keep only evidence records that the shared visibility policy allows claimants to see."""

    return [
        item
        for item in items
        if default_evidence_visibility(item.source) is not MessageVisibility.INTERNAL_ONLY
    ]
