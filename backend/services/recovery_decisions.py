"""Adapters from existing subsystem facts into the pure Recovery reducer.

These functions do not persist recovery state. They normalise facts already
owned by Claim / ExternalTask / repository boundaries and return the common
RecoveryTransition decision contract.
"""

from datetime import datetime
from hashlib import sha256
from typing import Literal, cast

from backend.domain.recovery import (
    NormalizedRecoveryEvent,
    RecoveryAuthoritativeSnapshot,
    RecoveryTransition,
    reduce_recovery,
)
from backend.domain.recovery_policy_registry import (
    RecoveryTrigger,
    classify_recovery,
)
from backend.domain.runtime import RuntimeWorkItemRecord


def reduce_revision_conflict_recovery(
    *,
    claim_id: str,
    expected_revision: int,
    current_revision: int,
    event_id: str,
    source_refs: list[str],
    now: datetime,
) -> RecoveryTransition:
    """Discard stale work and require authoritative-state reload."""

    trigger = RecoveryTrigger(
        source='repository',
        outcome_code='revision_conflict',
    )
    policy = classify_recovery(trigger)

    return reduce_recovery(
        policy,
        NormalizedRecoveryEvent(
            event_id=event_id,
            trigger=trigger,
            expected_claim_revision=expected_revision,
            source_refs=source_refs,
        ),
        RecoveryAuthoritativeSnapshot(
            claim_id=claim_id,
            claim_revision=current_revision,
            source_refs=[
                f'claim:{claim_id}:revision:{current_revision}',
            ],
        ),
        now,
    )


def reduce_external_unknown_recovery(
    *,
    claim_id: str,
    claim_revision: int,
    operation_id: str,
    delivery_state: Literal['submitted', 'unknown'],
    event_id: str,
    source_refs: list[str],
    now: datetime,
) -> RecoveryTransition:
    """Require reconciliation of the existing external operation identity."""

    trigger = RecoveryTrigger(
        source='external',
        outcome_code='unknown_outcome',
        delivery_state=delivery_state,
    )
    policy = classify_recovery(trigger)

    return reduce_recovery(
        policy,
        NormalizedRecoveryEvent(
            event_id=event_id,
            trigger=trigger,
            expected_claim_revision=claim_revision,
            operation_id=operation_id,
            source_refs=source_refs,
        ),
        RecoveryAuthoritativeSnapshot(
            claim_id=claim_id,
            claim_revision=claim_revision,
            operation_id=operation_id,
            source_refs=[
                f'claim:{claim_id}:revision:{claim_revision}',
            ],
        ),
        now,
    )


def reduce_dependency_unavailable_recovery(
    *,
    source: Literal['tool', 'retrieval'],
    blocking: bool,
    claim_id: str,
    claim_revision: int,
    event_id: str,
    source_refs: list[str],
    now: datetime,
) -> RecoveryTransition:
    """Classify one unavailable dependency without inventing Claim truth."""

    trigger = RecoveryTrigger(
        source=source,
        outcome_code='unavailable',
        blocking=blocking,
    )
    policy = classify_recovery(trigger)

    return reduce_recovery(
        policy,
        NormalizedRecoveryEvent(
            event_id=event_id,
            trigger=trigger,
            expected_claim_revision=claim_revision,
            source_refs=source_refs,
        ),
        RecoveryAuthoritativeSnapshot(
            claim_id=claim_id,
            claim_revision=claim_revision,
            source_refs=[
                f'claim:{claim_id}:revision:{claim_revision}',
            ],
        ),
        now,
    )


def reduce_high_impact_review_recovery(
    *,
    claim_id: str,
    claim_revision: int,
    event_id: str,
    source_refs: list[str],
    now: datetime,
) -> RecoveryTransition:
    """Require existing WorkItem/Handoff authority for high-impact review."""

    trigger = RecoveryTrigger(
        source='human',
        outcome_code='high_impact_review_required',
    )
    policy = classify_recovery(trigger)

    return reduce_recovery(
        policy,
        NormalizedRecoveryEvent(
            event_id=event_id,
            trigger=trigger,
            expected_claim_revision=claim_revision,
            source_refs=source_refs,
        ),
        RecoveryAuthoritativeSnapshot(
            claim_id=claim_id,
            claim_revision=claim_revision,
            source_refs=[
                f'claim:{claim_id}:revision:{claim_revision}',
            ],
        ),
        now,
    )


def reduce_external_terminal_recovery(
    *,
    claim_id: str,
    claim_revision: int,
    operation_id: str,
    event_id: str,
    source_refs: list[str],
    now: datetime,
) -> RecoveryTransition:
    trigger = RecoveryTrigger(
        source='external',
        outcome_code='terminal_failure',
        delivery_state='submitted',
    )
    policy = classify_recovery(trigger)

    return reduce_recovery(
        policy,
        NormalizedRecoveryEvent(
            event_id=event_id,
            trigger=trigger,
            expected_claim_revision=claim_revision,
            operation_id=operation_id,
            source_refs=source_refs,
        ),
        RecoveryAuthoritativeSnapshot(
            claim_id=claim_id,
            claim_revision=claim_revision,
            operation_id=operation_id,
            source_refs=[
                f'claim:{claim_id}:revision:{claim_revision}',
            ],
        ),
        now,
    )


def build_recovery_work_item(
    transition: RecoveryTransition,
    *,
    claim_id: str,
    subject_ref: str,
    now: datetime,
    status: Literal[
        'open',
        'in_progress',
        'completed',
        'cancelled',
        'unavailable',
    ] = 'open',
) -> RuntimeWorkItemRecord | None:
    """Materialise policy responsibility without creating a new authority."""

    if 'work_item.ensure' not in transition.required_actions:
        return None

    if transition.work_item_kind is None:
        raise ValueError('A Recovery policy requiring a WorkItem must publish its kind.')

    owner = cast(
        Literal['claimant', 'staff', 'system', 'external'],
        transition.responsibility,
    )

    digest = sha256(
        (f'{claim_id}|{transition.event_id}|{transition.rule_id}|{subject_ref}').encode()
    ).hexdigest()[:24]

    completed = status in {'completed', 'cancelled'}

    return RuntimeWorkItemRecord(
        work_item_id=f'wki_recovery_{digest}',
        claim_id=claim_id,
        turn_id=f'recovery_{digest}',
        kind=transition.work_item_kind,
        subject_ref=subject_ref,
        owner=owner,
        status=status,
        blocks_action=(None if completed else transition.blocks_action),
        source_refs=list(transition.source_refs),
        created_at=now,
        updated_at=now,
        completed_at=now if completed else None,
    )
