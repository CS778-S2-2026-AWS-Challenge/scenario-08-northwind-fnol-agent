"""Backfill the immutable P17 Follow-up policy binding and deadline.

The script is a thin operator entry point over the repository migration
contract (``backfill_legacy_follow_up_record``), so the fixture, MongoDB and
operator paths share one decision rule:

- only genuinely unbound fields are filled; absent and explicit ``null`` are
  both treated as unbound;
- an existing contradictory ``policy_id``/``policy_version``/``deadline_at`` is
  never rewritten and the record fails closed as ``policy_binding_invalid``;
- the only recovery clock is ``SessionRecoveryContext.interrupted_at``; a
  missing or inconsistent source fails closed as ``source_state_inconsistent``;
- a concurrent change to the Follow-up or its source Session aborts that
  record's write, and a rerun re-decides from current state.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.errors import PyMongoError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.repositories.mongodb import (
    MongoDBConfigurationError,
    MongoDBConnectionConfig,
    MongoDBRepository,
)
from backend.repositories.protocols import IdempotencyConflict


def backfill_follow_ups(
    repository: MongoDBRepository,
    *,
    apply: bool = False,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Plan, and optionally apply, the P17.1 Follow-up policy backfill.

    Args:
        repository: MongoDB adapter bound to the target collection.
        apply: Write decisions when true; otherwise report only.
        recorded_at: Audit time for migration evidence. It is never used as
            the interruption time.

    Returns:
        A JSON-serialisable report of planned and applied outcomes.

    Raises:
        ValueError: ``recorded_at`` is naive.
    """
    audit_time = recorded_at or datetime.now(UTC)
    plan = repository.plan_incomplete_claim_recovery_backfill(recorded_at=audit_time)
    report: dict[str, Any] = {
        'mode': 'apply' if apply else 'dry_run',
        'candidate_count': len(plan),
        'bound': sorted(key for key, value in plan.items() if value == 'bound'),
        'fail_closed': sorted(key for key, value in plan.items() if value == 'failed'),
        'unreadable': sorted(key for key, value in plan.items() if value == 'unreadable'),
        'applied': {'bound': 0, 'fail_closed': 0},
        'conflict': False,
    }
    if not apply:
        return report
    try:
        bound, failed = repository.backfill_incomplete_claim_recovery(recorded_at=audit_time)
    except IdempotencyConflict:
        report['conflict'] = True
        return report
    report['applied'] = {'bound': bound, 'fail_closed': failed}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='apply conditional updates')
    args = parser.parse_args()
    client: MongoClient[Any] | None = None
    try:
        config = MongoDBConnectionConfig.from_environment()
        client = MongoClient(
            config.uri,
            serverSelectionTimeoutMS=config.server_selection_timeout_ms,
        )
        client.admin.command('ping')
        repository = MongoDBRepository(
            client, config.database_name, collection_name=config.collection_name
        )
        report = backfill_follow_ups(repository, apply=args.apply)
    except (MongoDBConfigurationError, PyMongoError, ValueError):
        print(json.dumps({'status': 'unavailable'}))
        return 2
    finally:
        if client is not None:
            client.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report['unreadable'] or report['conflict'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
