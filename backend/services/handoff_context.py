from collections.abc import Sequence
from dataclasses import dataclass

from backend.domain.models import (
    EvidenceRecord,
    HandoffRecord,
    SignalDecisionRecord,
    SignalDecisionValue,
    WorkingClaim,
)
from backend.domain.retrieval import RetrievalKind, ReviewSignalRecord
from backend.domain.tag_registry import TAG_REGISTRY_ID
from backend.repositories.protocols import PersistenceRepository
from backend.services.tag_projection import project_staff_tags


@dataclass(frozen=True, slots=True)
class HandoffTransferContext:
    """Immutable coordinates for the context visible when a handoff is created."""

    policy_retrieval_refs: list[str]
    history_retrieval_refs: list[str]
    provenance_refs: list[str]


def build_handoff_transfer_context(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    *,
    evidence: Sequence[EvidenceRecord],
    handoffs: Sequence[HandoffRecord],
) -> HandoffTransferContext:
    """Build bounded transfer-time references without copying live Workbench state.

    Args:
        repository: Authoritative Claim persistence boundary.
        claim: Working Claim being handed off.
        evidence: Persisted Claim Evidence available at transfer time.
        handoffs: Handoffs that already existed before this transfer.

    Returns:
        Stable retrieval, signal, and tag-registry coordinates for the packet.

    Raises:
        ValueError: The tag projection cannot reconstruct a source-linked tag.
    """

    retrievals = repository.list_retrieval_records(claim.claim_id, claim.customer_id)
    signals = repository.list_review_signals(claim.claim_id, claim.customer_id)
    decisions = repository.list_signal_decisions(claim.claim_id)
    active_signals = _active_signals(signals, decisions)
    tags = project_staff_tags(
        claim,
        evidence=evidence,
        handoffs=handoffs,
        review_signals=active_signals,
        signal_decisions=decisions,
    )

    policy_retrieval_refs = [
        record.retrieval_id for record in retrievals if record.kind is RetrievalKind.POLICY
    ]
    history_retrieval_refs = [
        record.retrieval_id for record in retrievals if record.kind is RetrievalKind.CLAIM_HISTORY
    ]
    provenance_refs: list[str] = []
    for signal in active_signals:
        provenance_refs.extend([signal.signal_id, *signal.source_refs])
    for tag in tags:
        provenance_refs.append(f'tag_registry:{TAG_REGISTRY_ID}:{tag.registry_version}:{tag.code}')
        provenance_refs.extend(tag.source_refs)

    return HandoffTransferContext(
        policy_retrieval_refs=list(dict.fromkeys(policy_retrieval_refs)),
        history_retrieval_refs=list(dict.fromkeys(history_retrieval_refs)),
        provenance_refs=list(dict.fromkeys(ref for ref in provenance_refs if ref)),
    )


def _active_signals(
    signals: Sequence[ReviewSignalRecord],
    decisions: Sequence[SignalDecisionRecord],
) -> list[ReviewSignalRecord]:
    latest_decision: dict[str, SignalDecisionRecord] = {}
    for decision in decisions:
        current = latest_decision.get(decision.signal_id)
        if current is None or decision.created_at >= current.created_at:
            latest_decision[decision.signal_id] = decision

    inactive = {SignalDecisionValue.DISMISSED, SignalDecisionValue.RESOLVED}
    return [
        signal
        for signal in signals
        if latest_decision.get(signal.signal_id) is None
        or latest_decision[signal.signal_id].decision not in inactive
    ]
