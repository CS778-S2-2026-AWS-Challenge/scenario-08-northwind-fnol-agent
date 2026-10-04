from datetime import UTC, datetime
from typing import Any

import mongomock

from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    ResponsibleParty,
    WorkingClaim,
)
from scripts.migrate_record_shapes import MIGRATION_ID, migrate_record_shapes


def _claim(claim_id: str) -> WorkingClaim:
    timestamp = datetime(2026, 10, 1, tzinfo=UTC)
    return WorkingClaim(
        claim_id=claim_id,
        customer_id='cus_migration',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type='motor',
        claim_state=ClaimState(),
        active_session_id=f'ses_{claim_id}',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Tell me what happened.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def _claim_document(claim: WorkingClaim) -> dict[str, Any]:
    return {
        **claim.model_dump(mode='json'),
        '_id': f'claim:{claim.claim_id}',
        'record_type': 'claim',
        'customer_id': claim.customer_id,
        'claim_id': claim.claim_id,
        'staff_search': {'claim_id': claim.claim_id},
    }


def _stored_records() -> Any:
    collection: Any = mongomock.MongoClient()['northwind']['northwind_records']
    collection.insert_many(
        [
            _claim_document(_claim('clm_unevaluated')),
            _claim_document(_claim('clm_evaluated')),
            {
                '_id': 'branch_evaluation:brn_1',
                'record_type': 'branch_evaluation',
                'claim_id': 'clm_evaluated',
                'status': 'applied',
                'requirements': {'current_action_total': 4, 'current_action_satisfied': 2},
            },
            {'_id': 'evidence:evd_1', 'record_type': 'evidence', 'kind': 'incident_image'},
            {'_id': 'evidence:evd_2', 'record_type': 'evidence', 'kind': 'photo'},
            {'_id': 'evidence:evd_3', 'record_type': 'evidence', 'kind': 'repair_quote'},
            {
                '_id': 'idempotency:1',
                'record_type': 'idempotency',
                'payload': {
                    'response_payload': {
                        'dynamic_form': {'requirements': {'current_action_satisfied': 1}},
                        'opened_items': [{'document_kind': 'photo', 'wanted': ['incident_image']}],
                    }
                },
            },
            {'_id': 'message:1', 'record_type': 'message', 'text': 'a photo of the car'},
        ]
    )
    return collection


def test_a_dry_run_reports_every_change_and_writes_nothing() -> None:
    collection = _stored_records()
    before = list(collection.find({}))

    report = migrate_record_shapes(collection)

    assert report == {
        'status': 'dry_run',
        'rewritten_records': 4,
        'rewritten_by_type': {'branch_evaluation': 1, 'evidence': 2, 'idempotency': 1},
        'evaluations_added': 1,
        'unfinished_claim_creations_with_old_kinds': [],
    }
    assert list(collection.find({})) == before


def test_apply_rewrites_old_shapes_backfills_evaluations_and_runs_once() -> None:
    collection = _stored_records()

    report = migrate_record_shapes(collection, apply=True)

    assert report['status'] == 'applied'
    kinds = {item['_id']: item['kind'] for item in collection.find({'record_type': 'evidence'})}
    assert kinds == {
        'evidence:evd_1': 'incident_photo',
        'evidence:evd_2': 'incident_photo',
        'evidence:evd_3': 'repair_quote',
    }
    assert collection.find_one({'_id': 'branch_evaluation:brn_1'})['requirements'] == {
        'current_action_total': 4
    }
    payload = collection.find_one({'_id': 'idempotency:1'})['payload']['response_payload']
    assert payload == {
        'dynamic_form': {'requirements': {}},
        'opened_items': [{'document_kind': 'incident_photo', 'wanted': ['incident_photo']}],
    }
    assert collection.find_one({'_id': 'message:1'})['text'] == 'a photo of the car'
    added = collection.find_one({'record_type': 'branch_evaluation', 'claim_id': 'clm_unevaluated'})
    assert (added['status'], added['recomputation_reason']) == ('applied', 'claim_migrated')

    snapshot = list(collection.find({}))
    assert migrate_record_shapes(collection, apply=True)['status'] == 'already_applied'
    assert list(collection.find({})) == snapshot

    # Without the marker, every record is already current, so nothing changes either.
    collection.delete_one({'_id': MIGRATION_ID})
    rerun = migrate_record_shapes(collection, apply=True)
    assert (rerun['rewritten_records'], rerun['evaluations_added']) == (0, 0)


def test_apply_refuses_while_an_unfinished_claim_creation_covers_an_old_kind() -> None:
    collection = _stored_records()
    collection.update_one({'_id': 'evidence:evd_1'}, {'$set': {'claim_id': 'clm_evaluated'}})
    collection.insert_many(
        [
            {
                '_id': 'claim_creation_operation:cco_open',
                'record_type': 'claim_creation_operation',
                'operation_id': 'cco_open',
                'claim_id': 'clm_evaluated',
                'status': 'prepared',
            },
            {
                '_id': 'claim_creation_operation:cco_retry',
                'record_type': 'claim_creation_operation',
                'operation_id': 'cco_retry',
                'claim_id': 'clm_evaluated',
                'status': 'retryable_failure',
            },
            {
                '_id': 'claim_creation_operation:cco_done',
                'record_type': 'claim_creation_operation',
                'operation_id': 'cco_done',
                'claim_id': 'clm_evaluated',
                'status': 'accepted',
            },
        ]
    )
    before = list(collection.find({}))

    report = migrate_record_shapes(collection, apply=True)

    assert report['status'] == 'refused'
    assert report['unfinished_claim_creations_with_old_kinds'] == ['cco_open', 'cco_retry']
    assert list(collection.find({})) == before
