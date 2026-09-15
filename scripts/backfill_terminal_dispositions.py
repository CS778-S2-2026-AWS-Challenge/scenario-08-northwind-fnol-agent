"""Backfill provable terminal dispositions on pre-P17 MongoDB Claims."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from pydantic import TypeAdapter, ValidationError
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AuthorityOutcome,
    ClaimTerminalDisposition,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
)
from backend.repositories.mongodb import (
    MongoDBConfigurationError,
    MongoDBConnectionConfig,
)

_DATETIME = TypeAdapter(datetime)
_CREATION_REASON = 'CLAIM_CREATION_AUTHORISED'


class RejectedRecord(TypedDict):
    claim_id: str
    reason: str


class MigrationReport(TypedDict):
    mode: str
    candidate_count: int
    eligible: list[str]
    applied: list[str]
    rejected: list[RejectedRecord]
    conflicts: list[str]


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} is missing.')
    return value


def _required_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f'{field} is missing or invalid.')
    return value


def _required_timestamp(value: object, field: str) -> datetime:
    try:
        timestamp = _DATETIME.validate_python(value)
    except ValidationError as error:
        raise ValueError(f'{field} is missing or invalid.') from error
    if timestamp.utcoffset() is None:
        raise ValueError(f'{field} must include a timezone offset.')
    return timestamp


def _terminal_for_claim(
    collection: Collection[dict[str, Any]],
    claim: dict[str, Any],
) -> tuple[ClaimTerminalDisposition, str, str]:
    claim_id = _required_string(claim.get('claim_id'), 'claim_id')
    customer_id = _required_string(claim.get('customer_id'), 'customer_id')
    current_revision = _required_int(claim.get('revision'), 'revision')
    source_revision = _required_int(
        claim.get('external_claim_source_revision'),
        'external_claim_source_revision',
    )
    recorded_revision = source_revision + 1
    if recorded_revision > current_revision:
        raise ValueError('The Claim revision precedes the creation result.')

    external_claim = claim.get('external_claim')
    if not isinstance(external_claim, dict):
        raise ValueError('external_claim is missing or invalid.')
    external_ref = external_claim.get('external_claim_id') or external_claim.get('claim_number')
    external_ref = _required_string(external_ref, 'external_claim reference')
    recorded_at = _required_timestamp(external_claim.get('created_at'), 'external_claim.created_at')
    updated_at = _required_timestamp(claim.get('updated_at'), 'updated_at')
    if recorded_at > updated_at:
        raise ValueError('The external Claim time exceeds the Claim update time.')

    decisions = list(
        collection.find(
            {
                'record_type': 'agent_decision',
                'claim_id': claim_id,
                'customer_id': customer_id,
                'action': AgentAction.CREATE_CLAIM.value,
                'reason_codes': _CREATION_REASON,
                'authority.outcome': AuthorityOutcome.AUTHORISED.value,
                'resulting_revision': source_revision,
            }
        )
    )
    if len(decisions) != 1:
        raise ValueError('Exactly one matching authorised Claim-creation decision is required.')
    decision_id = _required_string(decisions[0].get('decision_id'), 'decision_id')
    decision_at = _required_timestamp(decisions[0].get('created_at'), 'decision.created_at')
    if decision_at > recorded_at:
        raise ValueError('The authorising decision post-dates the external Claim result.')

    disposition = ClaimTerminalDisposition(
        value=TerminalDispositionValue.COMPLETED,
        reason_code=TerminalDispositionReasonCode.CLAIM_CREATED,
        source_refs=[decision_id, external_ref],
        recorded_by=ActorReference(
            actor_type=ActorType.SYSTEM,
            actor_id='claims_service_integration',
        ),
        recorded_at=recorded_at,
        recorded_revision=recorded_revision,
    )
    return disposition, decision_id, external_ref


def backfill_terminal_dispositions(
    collection: Collection[dict[str, Any]],
    *,
    apply: bool = False,
) -> MigrationReport:
    """Inspect or repair pre-P17 created Claims with complete provenance.

    Args:
        collection: MongoDB collection containing Northwind typed records.
        apply: Write eligible dispositions when true; otherwise remain read-only.

    Returns:
        A non-sensitive report of eligible, applied, rejected, and conflicted Claim IDs.

    Raises:
        PyMongoError: MongoDB cannot complete a read or conditional update.
    """

    candidates = list(
        collection.find(
            {
                'record_type': 'claim',
                'terminal_disposition': None,
                'external_claim.creation_status': 'created',
            }
        ).sort('_id', 1)
    )
    report: MigrationReport = {
        'mode': 'apply' if apply else 'dry_run',
        'candidate_count': len(candidates),
        'eligible': [],
        'applied': [],
        'rejected': [],
        'conflicts': [],
    }
    for claim in candidates:
        claim_id = str(claim.get('claim_id') or claim.get('_id') or 'unknown')
        try:
            disposition, _decision_id, external_ref = _terminal_for_claim(collection, claim)
        except ValueError as error:
            report['rejected'].append({'claim_id': claim_id, 'reason': str(error)})
            continue
        report['eligible'].append(claim_id)
        if not apply:
            continue

        result = collection.update_one(
            {
                '_id': claim.get('_id'),
                'record_type': 'claim',
                'claim_id': claim.get('claim_id'),
                'customer_id': claim.get('customer_id'),
                'revision': claim.get('revision'),
                'terminal_disposition': None,
                'external_claim_source_revision': claim.get('external_claim_source_revision'),
                'external_claim.creation_status': 'created',
                'external_claim.created_at': claim.get('external_claim', {}).get('created_at'),
                '$or': [
                    {'external_claim.external_claim_id': external_ref},
                    {'external_claim.claim_number': external_ref},
                ],
            },
            {'$set': {'terminal_disposition': disposition.model_dump(mode='json')}},
        )
        if result.matched_count != 1 or result.modified_count != 1:
            report['conflicts'].append(claim_id)
            continue
        report['applied'].append(claim_id)
    return report


def main() -> int:
    """Run the migration from configured MongoDB environment values.

    Returns:
        Zero when every candidate is valid and conflict-free; two otherwise.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='apply conditional updates; without this flag the command is read-only',
    )
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
        report = backfill_terminal_dispositions(collection, apply=args.apply)
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
