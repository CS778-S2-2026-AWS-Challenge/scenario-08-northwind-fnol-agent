"""Backfill the immutable P17 Follow-up policy binding and deadline."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

from pydantic import TypeAdapter, ValidationError
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.repositories.mongodb import MongoDBConfigurationError, MongoDBConnectionConfig

_DATETIME = TypeAdapter(datetime)


class RejectedRecord(TypedDict):
    follow_up_id: str
    reason: str


def backfill_follow_ups(
    collection: Collection[dict[str, Any]],
    *,
    apply: bool = False,
) -> dict[str, Any]:
    candidates = list(
        collection.find(
            {
                'record_type': 'follow_up',
                '$or': [
                    {'policy_id': None},
                    {'policy_version': None},
                    {'deadline_at': None},
                ],
            }
        ).sort('_id', 1)
    )
    report: dict[str, Any] = {
        'mode': 'apply' if apply else 'dry_run',
        'candidate_count': len(candidates),
        'eligible': [],
        'applied': [],
        'rejected': [],
        'conflicts': [],
    }
    for follow_up in candidates:
        follow_up_id = str(follow_up.get('follow_up_id') or follow_up.get('_id') or 'unknown')
        session = collection.find_one(
            {
                'record_type': 'session',
                'session_id': follow_up.get('source_session_id'),
                'claim_id': follow_up.get('claim_id'),
            },
        )
        try:
            interrupted_at = (session or {}).get('recovery_context', {}).get('interrupted_at')
            interrupted_at = _DATETIME.validate_python(interrupted_at)
            if interrupted_at.tzinfo is None or interrupted_at.utcoffset() is None:
                raise ValueError('interrupted_at must include a timezone offset.')
            deadline_at = interrupted_at + timedelta(days=7)
            for field, expected in (
                ('policy_id', 'incomplete_claim_follow_up'),
                ('policy_version', 1),
            ):
                if follow_up.get(field) is not None and follow_up[field] != expected:
                    raise ValueError('Existing policy binding contradicts the approved policy.')
            if follow_up.get('deadline_at') is not None and (
                _DATETIME.validate_python(follow_up['deadline_at']) != deadline_at
            ):
                raise ValueError('Existing deadline contradicts the original interruption.')
        except (AttributeError, TypeError, ValidationError, ValueError) as error:
            report['rejected'].append({'follow_up_id': follow_up_id, 'reason': str(error)})
            continue

        update: dict[str, Any] = {
            'policy_id': 'incomplete_claim_follow_up',
            'policy_version': 1,
            'deadline_at': deadline_at.isoformat(),
        }
        update = {key: value for key, value in update.items() if follow_up.get(key) is None}
        if (
            follow_up.get('status') == 'blocked'
            and follow_up.get('contact_permission') == 'not_authorised'
            and follow_up.get('blocked_reason') is None
        ):
            update['blocked_reason'] = 'contact_not_authorised'
        report['eligible'].append(follow_up_id)
        if not apply:
            continue
        assert session is not None
        if not _apply_backfill(collection, follow_up, session, update):
            report['conflicts'].append(follow_up_id)
        else:
            report['applied'].append(follow_up_id)
    return report


class BackfillConflictError(ValueError):
    """A migration source or target changed after discovery."""


def _apply_backfill(
    collection: Collection[dict[str, Any]],
    original: dict[str, Any],
    source: dict[str, Any],
    update: dict[str, Any],
) -> bool:
    # Apply requires a transaction-capable Mongo deployment. The source fence is
    # adapter metadata, not a Session revision or a change to recovery evidence.
    predicate: dict[str, Any] = dict(original)
    for field in ('policy_id', 'policy_version', 'deadline_at', 'blocked_reason'):
        if field not in original:
            predicate[field] = {'$exists': False}

    def apply(mongo_session: Any) -> None:
        guard = collection.update_one(
            dict(source), {'$inc': {'recovery_backfill_fence': 1}}, session=mongo_session
        )
        if guard.matched_count != 1:
            raise BackfillConflictError('Source changed during backfill.')
        result = collection.update_one(predicate, {'$set': update}, session=mongo_session)
        if result.matched_count != 1 or result.modified_count != 1:
            raise BackfillConflictError('Target changed during backfill.')

    try:
        with collection.database.client.start_session() as mongo_session:
            mongo_session.with_transaction(apply)
    except BackfillConflictError:
        return False
    return True


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
        report = backfill_follow_ups(
            client[config.database_name][config.collection_name],
            apply=args.apply,
        )
    except (MongoDBConfigurationError, PyMongoError, ValueError):
        print(json.dumps({'status': 'unavailable'}))
        return 2
    finally:
        if client is not None:
            client.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report['rejected'] or report['conflicts'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
