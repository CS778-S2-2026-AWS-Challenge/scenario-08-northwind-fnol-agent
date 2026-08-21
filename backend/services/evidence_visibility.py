from collections.abc import Iterable

from backend.domain.models import EvidenceRecord, EvidenceSource, MessageVisibility


def default_evidence_visibility(source: EvidenceSource) -> MessageVisibility:
    """Return the current safe record-level visibility default for evidence."""

    if source is EvidenceSource.CLAIMANT:
        return MessageVisibility.SHARED
    return MessageVisibility.INTERNAL_ONLY


def claimant_visible_evidence(records: Iterable[EvidenceRecord]) -> list[EvidenceRecord]:
    """Keep only authoritative evidence records that are safe for claimant projection."""

    return [
        record
        for record in records
        if default_evidence_visibility(record.source) is not MessageVisibility.INTERNAL_ONLY
    ]
