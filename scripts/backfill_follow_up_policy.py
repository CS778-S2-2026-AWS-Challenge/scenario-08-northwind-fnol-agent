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
                    {'policy_id': {'$exists': False}},
                    {'policy_version': {'$exists': False}},
                    {'deadline_at': {'$exists': False}},
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
        'fail_closed': [],
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
            projection={'recovery_context.interrupted_at': 1},
        )
        try:
            interrupted_at = (session or {}).get('recovery_context', {}).get('interrupted_at')
            interrupted_at = _DATETIME.validate_python(interrupted_at)
            if interrupted_at.tzinfo is None or interrupted_at.utcoffset() is None:
                raise ValueError('interrupted_at must include a timezone offset.')
            deadline_at = interrupted_at + timedelta(days=7)
        except (AttributeError, TypeError, ValidationError, ValueError) as error:
            report['rejected'].append({'follow_up_id': follow_up_id, 'reason': str(error)})
            if not apply:
                continue
            fail_closed_update: dict[str, Any] = {
                'policy_id': 'incomplete_claim_follow_up',
                'policy_version': 1,
                'status': 'blocked',
                'due_at': None,
                'blocked_reason': 'policy_binding_invalid',
            }
            result = collection.update_one(
                {
                    '_id': follow_up.get('_id'),
                    'record_type': 'follow_up',
                    '$or': [
                        {'policy_id': {'$exists': False}},
                        {'policy_version': {'$exists': False}},
                        {'deadline_at': {'$exists': False}},
                    ],
                },
                {
                    '$set': fail_closed_update,
                    '$unset': {'deadline_at': ''},
                },
            )
            if result.matched_count != 1 or result.modified_count != 1:
                report['conflicts'].append(follow_up_id)
            else:
                report['fail_closed'].append(follow_up_id)
            continue

        update: dict[str, Any] = {
            'policy_id': 'incomplete_claim_follow_up',
            'policy_version': 1,
            'deadline_at': deadline_at.isoformat(),
        }
        if (
            follow_up.get('status') == 'blocked'
            and follow_up.get('contact_permission') == 'not_authorised'
            and 'blocked_reason' not in follow_up
        ):
            update['blocked_reason'] = 'contact_not_authorised'
        report['eligible'].append(follow_up_id)
        if not apply:
            continue
        result = collection.update_one(
            {
                '_id': follow_up.get('_id'),
                'record_type': 'follow_up',
                '$or': [
                    {'policy_id': {'$exists': False}},
                    {'policy_version': {'$exists': False}},
                    {'deadline_at': {'$exists': False}},
                ],
            },
            {'$set': update},
        )
        if result.matched_count != 1 or result.modified_count != 1:
            report['conflicts'].append(follow_up_id)
        else:
            report['applied'].append(follow_up_id)
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
