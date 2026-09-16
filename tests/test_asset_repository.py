from datetime import UTC, datetime

import mongomock
import pytest

from backend.domain.assets import (
    AssetRecord,
    AssetType,
    ClaimAssetSnapshot,
    VehicleAssetDetails,
)
from backend.domain.models import (
    Channel,
    ClaimState,
    CustomerNextStep,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import IdempotencyRecord, RevisionConflict
from backend.services.branching import build_applied_branch_evaluation


def _asset() -> AssetRecord:
    now = datetime.now(UTC)
    return AssetRecord(
        asset_id='ast_00000000000000000001',
        customer_id='cus_owner',
        asset_type=AssetType.VEHICLE,
        display_name='Synthetic vehicle',
        details=VehicleAssetDetails(registration='SYN123'),
        revision=1,
        active=True,
        created_at=now,
        updated_at=now,
    )


def test_fixture_asset_repository_enforces_owner_and_compare_and_set() -> None:
    repository = FixtureRepository()
    asset = _asset()
    repository.create_asset(
        asset,
        IdempotencyRecord(
            actor_id='cus_owner',
            route='/api/v1/account/assets',
            key='create-1',
            request_fingerprint='fingerprint',
            claim_id=asset.asset_id,
            session_id='',
        ),
    )

    assert repository.get_asset(asset.asset_id, 'cus_other') is None
    assert repository.list_assets('cus_owner') == ([asset], False)

    updated = asset.model_copy(update={'revision': 2, 'display_name': 'Updated'})
    repository.update_asset(updated, expected_revision=1)
    with pytest.raises(RevisionConflict) as conflict:
        repository.update_asset(updated.model_copy(update={'revision': 3}), expected_revision=1)
    assert conflict.value.current_revision == 2


def test_mongodb_asset_selection_is_atomic_and_snapshot_is_immutable() -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'asset_repository_test')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    asset = _asset()
    repository.create_asset(
        asset,
        IdempotencyRecord(
            actor_id=asset.customer_id,
            route='/api/v1/account/assets',
            key='mongo-create',
            request_fingerprint='mongo-create-fingerprint',
            claim_id=asset.asset_id,
            session_id='',
        ),
    )
    timestamp = datetime.now(UTC)
    claim = WorkingClaim(
        claim_id='clm_asset_mongo',
        customer_id=asset.customer_id,
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id='ses_asset_mongo',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the synthetic incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    session = SessionRecord(
        session_id='ses_asset_mongo',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=claim.revision,
        started_at=timestamp,
        last_active_at=timestamp,
        status=SessionStatus.ACTIVE,
    )
    repository.create_claim(claim, session)
    updated_claim = claim.model_copy(update={'revision': 2, 'updated_at': timestamp})
    snapshot = ClaimAssetSnapshot(
        snapshot_id='cas_00000000000000000001',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        asset_id=asset.asset_id,
        asset_revision=asset.revision,
        asset_type=asset.asset_type,
        display_name=asset.display_name,
        details=asset.details,
        captured_at=timestamp,
        resulting_claim_revision=2,
        source_refs=['asset:ast_00000000000000000001:revision:1'],
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/asset-selections',
        key='mongo-select',
        request_fingerprint='mongo-select-fingerprint',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
    )
    evaluation = build_applied_branch_evaluation(
        updated_claim,
        repository=repository,
        recomputation_reason='claim_asset_selected',
        created_at=timestamp,
    )

    repository.save_asset_selection(
        updated_claim, claim.revision, snapshot, idempotency, evaluation
    )
    repository.update_asset(
        asset.model_copy(
            update={
                'revision': 2,
                'details': VehicleAssetDetails(registration='NEW456'),
            }
        ),
        expected_revision=1,
    )

    stored, has_more = repository.list_claim_asset_snapshots(claim.claim_id, claim.customer_id)
    assert stored == [snapshot]
    assert has_more is False
    assert stored[0].details == VehicleAssetDetails(registration='SYN123')
    assert repository.get_asset(asset.asset_id, 'cus_other') is None


def test_mongodb_rejects_stale_asset_during_selection_without_partial_claim_write() -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'asset_atomicity_test')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
    asset = _asset()
    repository.create_asset(
        asset,
        IdempotencyRecord(
            actor_id=asset.customer_id,
            route='/api/v1/account/assets',
            key='atomic-create',
            request_fingerprint='atomic-create-fingerprint',
            claim_id=asset.asset_id,
            session_id='',
        ),
    )
    now = datetime.now(UTC)
    claim = WorkingClaim(
        claim_id='clm_asset_atomic',
        customer_id=asset.customer_id,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id='ses_asset_atomic',
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the synthetic incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=now,
        updated_at=now,
    )
    repository.create_claim(
        claim,
        SessionRecord(
            session_id='ses_asset_atomic',
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            context_revision=1,
            started_at=now,
            last_active_at=now,
            status=SessionStatus.ACTIVE,
        ),
    )
    updated_claim = claim.model_copy(update={'revision': 2})
    stale_snapshot = ClaimAssetSnapshot(
        snapshot_id='cas_00000000000000000002',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        asset_id=asset.asset_id,
        asset_revision=2,
        asset_type=asset.asset_type,
        display_name=asset.display_name,
        details=asset.details,
        captured_at=now,
        resulting_claim_revision=2,
        source_refs=['asset:ast_00000000000000000001:revision:2'],
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/asset-selections',
        key='atomic-select',
        request_fingerprint='atomic-select-fingerprint',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
    )
    evaluation = build_applied_branch_evaluation(
        updated_claim,
        repository=repository,
        recomputation_reason='claim_asset_selected',
        created_at=now,
    )

    with pytest.raises(KeyError):
        repository.save_asset_selection(updated_claim, 1, stale_snapshot, idempotency, evaluation)

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_claim_asset_snapshots(claim.claim_id, claim.customer_id) == ([], False)
    assert (
        repository.find_idempotency(claim.customer_id, idempotency.route, idempotency.key) is None
    )
