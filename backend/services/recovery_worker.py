"""Bounded execution entrypoint for P17 recovery and retention progression."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from backend.adapters.evidence_storage import EvidenceStorage
from backend.domain.retention import (
    RetentionEligibilityRejected,
    RetentionTargetFreezeRejected,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.follow_up_recovery import (
    process_due_follow_up,
    process_expiring_follow_up,
)
from backend.services.retention import (
    execute_retention_cleanup,
    freeze_retention_cleanup_targets,
    reserve_retention_from_terminal,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecoveryCycleResult:
    """Observable outcome from one deliberately bounded worker cycle."""

    expiring_candidates: int
    expired: int
    due_candidates: int
    contacted: int
    retention_progressed: int
    retention_blocked: int
    failed_candidates: int


def run_recovery_cycle(
    repository: PersistenceRepository,
    storage: EvidenceStorage,
    *,
    now: datetime,
    limit: int = 50,
) -> RecoveryCycleResult:
    """Advance one bounded page of recovery work.

    Expiry is processed before due contact so the deadline-precedence rule is
    preserved even when both classes are discovered in the same worker tick.
    Candidate reads are hints only; each service reloads and revalidates its
    authoritative records before committing.
    """

    if now.utcoffset() is None:
        raise ValueError('Recovery worker time must be timezone-aware.')
    if not 1 <= limit <= 100:
        raise ValueError('Recovery worker limit must be between 1 and 100.')

    expiring, _ = repository.list_expiring_follow_ups(
        now,
        limit=limit,
    )
    expired = 0
    retention_progressed = 0
    retention_blocked = 0
    failed_candidates = 0

    for candidate in expiring:
        try:
            transition = process_expiring_follow_up(
                repository,
                candidate,
                now,
            )
        except Exception:
            failed_candidates += 1
            LOGGER.exception(
                'P17 expiry candidate failed; later candidates remain eligible.',
                extra={'follow_up_id': candidate.follow_up_id},
            )
            continue
        if transition is None:
            continue

        expired += 1
        try:
            reserve_retention_from_terminal(
                repository,
                transition.claim.claim_id,
                now=now,
            )
        except RetentionEligibilityRejected:
            # A blocking recovery/external responsibility is preserved and the
            # terminal fact remains authoritative for later reconciliation.
            retention_blocked += 1
        except Exception:
            failed_candidates += 1
            LOGGER.exception(
                'P17 retention reservation failed after expiry; later candidates continue.',
                extra={'claim_id': transition.claim.claim_id},
            )

    pending_retention = repository.list_pending_retention_operations(limit=limit)
    for retention in pending_retention:
        try:
            if retention.targets_frozen_at is None:
                retention = freeze_retention_cleanup_targets(
                    repository,
                    retention.operation_id,
                    now=now,
                )
            execute_retention_cleanup(
                repository,
                storage,
                retention.operation_id,
                now=now,
            )
            retention_progressed += 1
        except RetentionTargetFreezeRejected:
            retention_blocked += 1
        except Exception:
            failed_candidates += 1
            LOGGER.exception(
                'P17 retention candidate failed; later candidates remain eligible.',
                extra={'retention_operation_id': retention.operation_id},
            )

    due, _ = repository.list_due_follow_ups(
        now,
        limit=limit,
    )
    contacted = 0
    for candidate in due:
        try:
            if process_due_follow_up(repository, candidate, now) is not None:
                contacted += 1
        except Exception:
            failed_candidates += 1
            LOGGER.exception(
                'P17 due candidate failed; later candidates remain eligible.',
                extra={'follow_up_id': candidate.follow_up_id},
            )

    return RecoveryCycleResult(
        expiring_candidates=len(expiring),
        expired=expired,
        due_candidates=len(due),
        contacted=contacted,
        retention_progressed=retention_progressed,
        retention_blocked=retention_blocked,
        failed_candidates=failed_candidates,
    )
