"""Rewrite stored MongoDB records to the current shapes, once.

Three stored shapes stopped being valid together:

- the incident photo was stored as ``incident_image`` or ``photo``; the only
  registered name is now ``incident_photo``;
- branch evaluations and replayed responses carry ``current_action_satisfied``,
  which the requirements projection no longer has (its models reject unknown
  fields);
- claims started before the rules were evaluated at creation have no applied
  branch evaluation, so their dynamic form is missing until their next change.

The script reports by default and writes only with ``--apply``. A successful
apply records a marker document; later runs see it and exit without touching
anything. Each record is also checked on its own, so a rerun without the marker
changes nothing that is already current. Stop the backend while applying.

An unfinished claim creation fingerprinted its evidence while it had an old kind; the apply
refuses, writing nothing, until those creations have finished.

A second, separately marked step renames the model profile ``openrouter-gpt4o-mini`` to
``openrouter-gpt-4o``, the model it has always called (``openai/gpt-4o``). Every record whose
``model_profile_id`` holds the old name is rewritten, so sessions and staff conversations
started before the rename keep working.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.claim_creation import ClaimCreationOperationStatus
from backend.domain.models import BranchEvaluationStatus, WorkingClaim
from backend.repositories.mongodb import MongoDBConfigurationError, MongoDBConnectionConfig
from backend.services.branching import build_applied_branch_evaluation

MIGRATION_ID = 'schema_migration:record-shapes-2026-10'
PROFILE_RENAME_ID = 'schema_migration:model-profile-rename-2026-10'
_OLD_PROFILE_ID = 'openrouter-gpt4o-mini'
_NEW_PROFILE_ID = 'openrouter-gpt-4o'
_REMOVED_KEY = 'current_action_satisfied'
_KIND_KEYS = frozenset({'kind', 'document_kind'})
_OLD_PHOTO_KINDS = frozenset({'incident_image', 'photo'})
_FINISHED_CREATION_STATUSES = frozenset(
    {
        ClaimCreationOperationStatus.ACCEPTED.value,
        ClaimCreationOperationStatus.TERMINAL_FAILURE.value,
    }
)


def _current_shape(value: Any, key: str | None = None) -> Any:
    """Return ``value`` with the superseded names and the removed field rewritten."""

    if isinstance(value, dict):
        return {
            item_key: _current_shape(item, item_key)
            for item_key, item in value.items()
            if item_key != _REMOVED_KEY
        }
    if isinstance(value, list):
        return [_current_shape(item, key) for item in value]
    if value == 'incident_image' or (key in _KIND_KEYS and value in _OLD_PHOTO_KINDS):
        return 'incident_photo'
    return value


def _claims_without_evaluation(documents: list[dict[str, Any]]) -> list[WorkingClaim]:
    evaluated = {
        document['claim_id']
        for document in documents
        if document['record_type'] == 'branch_evaluation'
        and document.get('status') == BranchEvaluationStatus.APPLIED.value
    }
    return [
        WorkingClaim.model_validate(
            {key: value for key, value in document.items() if key in WorkingClaim.model_fields}
        )
        for document in documents
        if document['record_type'] == 'claim' and document['claim_id'] not in evaluated
    ]


def _unfinished_creations_with_old_kinds(
    documents: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return unfinished claim creations whose evidence still has an old photo kind.

    Such an operation fingerprinted its evidence, kind included, when it was prepared, and
    compares that fingerprint again when its accepted outcome is saved, so rewriting the kind
    would make it fail. Only accepted and terminally failed operations are finished.
    """

    claims_with_old_kinds = {
        document.get('claim_id')
        for document in documents
        if document['record_type'] == 'evidence' and document.get('kind') in _OLD_PHOTO_KINDS
    }
    return sorted(
        (
            {
                'operation_id': document['operation_id'],
                'claim_id': document['claim_id'],
                'status': document['status'],
            }
            for document in documents
            if document['record_type'] == 'claim_creation_operation'
            and document.get('status') not in _FINISHED_CREATION_STATUSES
            and document.get('claim_id') in claims_with_old_kinds
        ),
        key=lambda item: item['operation_id'],
    )


def migrate_record_shapes(
    collection: Collection[dict[str, Any]], *, apply: bool = False
) -> dict[str, Any]:
    """Plan, and optionally apply, the record shape migration.

    Args:
        collection: The Northwind records collection.
        apply: Write the changes when true; otherwise report only.

    Returns:
        A JSON-serialisable report of what was, or would be, changed.
    """

    marker = collection.find_one({'_id': MIGRATION_ID})
    if marker is not None:
        return {'status': 'already_applied', 'applied_at': marker['applied_at']}

    stored = list(collection.find({}))
    blocking = _unfinished_creations_with_old_kinds(stored)
    current = [_current_shape(document) for document in stored]
    rewritten = [after for before, after in zip(stored, current, strict=True) if after != before]
    unevaluated = _claims_without_evaluation(current)
    report: dict[str, Any] = {
        'status': 'applied' if apply else 'dry_run',
        'rewritten_records': len(rewritten),
        'rewritten_by_type': _count_by_type(rewritten),
        'evaluations_added': len(unevaluated),
        'unfinished_claim_creations_with_old_kinds': blocking,
    }
    if not apply:
        return report
    if blocking:
        # Writing nothing keeps the run all-or-nothing; finish these creations and run again.
        report['status'] = 'refused'
        report['resolution'] = (
            'Retry the claim creation for each listed claim so the claims service reconciles it '
            'to accepted or failed, then run the migration again. An unknown outcome is never '
            'closed as failed here, because the claim may already exist in the claims service.'
        )
        return report

    for document in rewritten:
        collection.replace_one({'_id': document['_id']}, document)
    for claim in unevaluated:
        evaluation = build_applied_branch_evaluation(claim, recomputation_reason='claim_migrated')
        collection.insert_one(
            {
                **evaluation.model_dump(mode='json'),
                '_id': f'branch_evaluation:{evaluation.evaluation_id}',
                'record_type': 'branch_evaluation',
                'customer_id': claim.customer_id,
                'claim_id': claim.claim_id,
            }
        )
    applied_at = datetime.now(UTC).isoformat()
    collection.insert_one(
        {
            '_id': MIGRATION_ID,
            'record_type': 'schema_migration',
            'applied_at': applied_at,
            'rewritten_records': len(rewritten),
            'evaluations_added': len(unevaluated),
        }
    )
    report['applied_at'] = applied_at
    return report


def rename_model_profile(
    collection: Collection[dict[str, Any]], *, apply: bool = False
) -> dict[str, Any]:
    """Plan, and optionally apply, the model profile rename.

    Args:
        collection: The Northwind records collection.
        apply: Write the changes when true; otherwise report only.

    Returns:
        A JSON-serialisable report of what was, or would be, changed.
    """

    marker = collection.find_one({'_id': PROFILE_RENAME_ID})
    if marker is not None:
        return {'status': 'already_applied', 'applied_at': marker['applied_at']}
    stored = list(collection.find({'model_profile_id': _OLD_PROFILE_ID}))
    report: dict[str, Any] = {
        'status': 'applied' if apply else 'dry_run',
        'renamed_records': len(stored),
        'renamed_by_type': _count_by_type(stored),
    }
    if not apply:
        return report
    collection.update_many(
        {'model_profile_id': _OLD_PROFILE_ID}, {'$set': {'model_profile_id': _NEW_PROFILE_ID}}
    )
    applied_at = datetime.now(UTC).isoformat()
    collection.insert_one(
        {
            '_id': PROFILE_RENAME_ID,
            'record_type': 'schema_migration',
            'applied_at': applied_at,
            'renamed_records': len(stored),
        }
    )
    report['applied_at'] = applied_at
    return report


def _count_by_type(documents: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for document in documents:
        counts[document['record_type']] = counts.get(document['record_type'], 0) + 1
    return dict(sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='write the changes')
    args = parser.parse_args()
    client: MongoClient[Any] | None = None
    try:
        config = MongoDBConnectionConfig.from_environment()
        client = MongoClient(
            config.uri,
            serverSelectionTimeoutMS=config.server_selection_timeout_ms,
        )
        client.admin.command('ping')
        collection = client[config.database_name][config.collection_name]
        report = migrate_record_shapes(collection, apply=args.apply)
        report['model_profile_rename'] = rename_model_profile(collection, apply=args.apply)
    except (MongoDBConfigurationError, PyMongoError) as error:
        print(json.dumps({'status': 'unavailable', 'reason': str(error)}))
        return 2
    finally:
        if client is not None:
            client.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report['status'] == 'refused' else 0


if __name__ == '__main__':
    raise SystemExit(main())
