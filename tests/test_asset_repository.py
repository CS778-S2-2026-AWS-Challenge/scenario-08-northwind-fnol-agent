from dataclasses import replace
from datetime import UTC, datetime

import mongomock
import pytest

from backend.core.auth import Principal
from backend.domain.assets import (
    AssetRecord,
    AssetType,
    ClaimAssetSnapshot,
    SelectClaimAssetRequest,
    VehicleAssetDetails,
)
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.models import (
    ActorType,
    BranchEvaluationRecord,
    Channel,
    ClaimState,
    CustomerNextStep,
    ResponsibleParty,
    SessionRecord,
    SessionStatus,
    WorkingClaim,
)
from backend.repositories.assets import (
    AssetSelectionRevisionConflictError,
    AssetSelectionSnapshotConflictError,
    AssetSelectionUnavailableError,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    RevisionConflict,
)
from backend.services.assets import select_claim_asset
from backend.services.branching import build_applied_branch_evaluation


def _asset() -> AssetRecord:
    now = datetime.now(UTC)
    return AssetRecord(
        asset_id='ase_00000000000000000001',
        customer_id='cus_owner',
        asset_type=AssetType.VEHICLE,
        display_name='Synthetic vehicle',
        details=VehicleAssetDetails(registration='SYN123'),
        revision=1,
        active=True,
        created_at=now,
        updated_at=now,
    )


def _asset_audit(
    asset: AssetRecord,
    event_id: str,
    *,
    idempotency_key: str | None = None,
) -> AuditEventEnvelope:
    return AuditEventEnvelope(
        event_id=event_id,
        event_type=AuditEventType.ACTION_COMPLETED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.ASSET,
            subject_id=asset.asset_id,
        ),
        actor=AuditActor(
            actor_type=ActorType.CLAIMANT,
            actor_id=asset.customer_id,
            auth_source='test:claimant',
        ),
        reason='Test Asset mutation.',
        source_refs=[f'asset:{asset.asset_id}:revision:{asset.revision}'],
        visibility=AuditVisibility.AUDIT_ONLY,
        idempotency_key=idempotency_key,
        created_at=asset.updated_at,
    )


def _selection_audit(
    claim: WorkingClaim,
    snapshot: ClaimAssetSnapshot,
    idempotency: IdempotencyRecord,
    event_id: str,
) -> AuditEventEnvelope:
    return AuditEventEnvelope(
        event_id=event_id,
        event_type=AuditEventType.ACTION_COMPLETED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim.claim_id,
            claim_id=claim.claim_id,
        ),
        actor=AuditActor(
            actor_type=ActorType.CLAIMANT,
            actor_id=claim.customer_id,
            auth_source='test:claimant',
        ),
        reason='Test Asset selection.',
        source_refs=[
            f'asset:{snapshot.asset_id}:revision:{snapshot.asset_revision}',
            snapshot.snapshot_id,
        ],
        visibility=AuditVisibility.AUDIT_ONLY,
        idempotency_key=idempotency.key,
        claim_revision=claim.revision,
        created_at=snapshot.captured_at,
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
        _asset_audit(asset, 'aud_fixture_create', idempotency_key='create-1'),
    )

    assert repository.get_asset(asset.asset_id, 'cus_other') is None
    assert repository.list_assets('cus_owner') == ([asset], False)

    updated = asset.model_copy(update={'revision': 2, 'display_name': 'Updated'})
    repository.update_asset(
        updated,
        expected_revision=1,
        audit_event=_asset_audit(updated, 'aud_fixture_update'),
    )
    with pytest.raises(RevisionConflict) as conflict:
        stale = updated.model_copy(update={'revision': 3})
        repository.update_asset(
            stale,
            expected_revision=1,
            audit_event=_asset_audit(stale, 'aud_fixture_stale'),
        )
    assert conflict.value.current_revision == 2


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
@pytest.mark.parametrize('mutation', ['update', 'deactivate'])
def test_asset_audit_conflict_leaves_account_asset_unchanged(
    adapter: str,
    mutation: str,
) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(mongomock.MongoClient(), f'asset_audit_{adapter}_{mutation}')
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo

    asset = _asset()
    repository.create_asset(
        asset,
        IdempotencyRecord(
            actor_id=asset.customer_id,
            route='/api/v1/account/assets',
            key=f'audit-create-{adapter}-{mutation}',
            request_fingerprint=f'audit-create-fingerprint-{adapter}-{mutation}',
            claim_id=asset.asset_id,
            session_id='',
        ),
        _asset_audit(
            asset,
            f'aud_account_create_{adapter}_{mutation}',
            idempotency_key=f'audit-create-{adapter}-{mutation}',
        ),
    )
    updated = asset.model_copy(
        update={
            'revision': 2,
            'display_name': 'Updated synthetic vehicle',
            'active': mutation != 'deactivate',
        }
    )
    incoming = _asset_audit(updated, f'aud_account_conflict_{adapter}_{mutation}')
    conflicting = incoming.model_copy(update={'reason': 'Existing unrelated audit fact.'})
    repository.append_audit_event(conflicting)

    with pytest.raises(IdempotencyConflict):
        repository.update_asset(updated, expected_revision=1, audit_event=incoming)

    assert repository.get_asset(asset.asset_id, asset.customer_id) == asset
    stored_events = repository.list_audit_events_internal(incoming.subject)
    assert conflicting in stored_events
    assert incoming not in stored_events


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
def test_create_asset_audit_conflict_leaves_no_asset_or_retry_record(adapter: str) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(mongomock.MongoClient(), f'asset_create_audit_{adapter}')
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo

    asset = _asset()
    idempotency = IdempotencyRecord(
        actor_id=asset.customer_id,
        route='/api/v1/account/assets',
        key=f'create-audit-conflict-{adapter}',
        request_fingerprint=f'create-audit-conflict-fingerprint-{adapter}',
        claim_id=asset.asset_id,
        session_id='',
    )
    incoming = _asset_audit(
        asset,
        f'aud_create_conflict_{adapter}',
        idempotency_key=f'create-audit-conflict-{adapter}',
    )
    conflicting = incoming.model_copy(update={'reason': 'Existing unrelated audit fact.'})
    repository.append_audit_event(conflicting)

    with pytest.raises(IdempotencyConflict):
        repository.create_asset(asset, idempotency, incoming)

    assert repository.get_asset(asset.asset_id, asset.customer_id) is None
    assert (
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )
        is None
    )
    assert repository.list_audit_events_internal(incoming.subject) == [conflicting]


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
        _asset_audit(asset, 'aud_mongo_create', idempotency_key='mongo-create'),
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
        source_refs=['asset:ase_00000000000000000001:revision:1'],
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
        updated_claim,
        claim.revision,
        snapshot,
        idempotency,
        evaluation,
        _selection_audit(updated_claim, snapshot, idempotency, 'aud_mongo_select'),
    )
    changed_asset = asset.model_copy(
        update={
            'revision': 2,
            'details': VehicleAssetDetails(registration='NEW456'),
        }
    )
    repository.update_asset(
        changed_asset,
        expected_revision=1,
        audit_event=_asset_audit(changed_asset, 'aud_mongo_update'),
    )

    stored, has_more = repository.list_claim_asset_snapshots(claim.claim_id, claim.customer_id)
    assert stored == [snapshot]
    assert has_more is False
    assert stored[0].details == VehicleAssetDetails(registration='SYN123')
    assert repository.get_asset(asset.asset_id, 'cus_other') is None
    asset_events = repository.list_audit_events_internal(
        AuditSubject(subject_type=AuditSubjectType.ASSET, subject_id=asset.asset_id)
    )
    assert len(asset_events) == 2
    claim_events = repository.list_audit_events_internal(
        AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim.claim_id,
            claim_id=claim.claim_id,
        )
    )
    assert len(claim_events) == 1


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
        _asset_audit(asset, 'aud_atomic_create', idempotency_key='atomic-create'),
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
        source_refs=['asset:ase_00000000000000000001:revision:2'],
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

    with pytest.raises(AssetSelectionRevisionConflictError) as conflict:
        repository.save_asset_selection(
            updated_claim,
            1,
            stale_snapshot,
            idempotency,
            evaluation,
            _selection_audit(
                updated_claim,
                stale_snapshot,
                idempotency,
                'aud_atomic_stale_selection',
            ),
        )
    assert conflict.value.current_revision == asset.revision

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_claim_asset_snapshots(claim.claim_id, claim.customer_id) == ([], False)
    assert (
        repository.find_idempotency(claim.customer_id, idempotency.route, idempotency.key) is None
    )

    inactive_asset = asset.model_copy(update={'revision': 2, 'active': False})
    repository.update_asset(
        inactive_asset,
        expected_revision=1,
        audit_event=_asset_audit(inactive_asset, 'aud_atomic_deactivate'),
    )
    unavailable_snapshot = stale_snapshot.model_copy(
        update={
            'snapshot_id': 'cas_00000000000000000003',
            'asset_revision': 2,
            'source_refs': ['asset:ase_00000000000000000001:revision:2'],
        }
    )
    unavailable_idempotency = replace(
        idempotency,
        key='atomic-select-unavailable',
        request_fingerprint='atomic-select-unavailable-fingerprint',
    )
    with pytest.raises(AssetSelectionUnavailableError):
        repository.save_asset_selection(
            updated_claim,
            1,
            unavailable_snapshot,
            unavailable_idempotency,
            evaluation,
            _selection_audit(
                updated_claim,
                unavailable_snapshot,
                unavailable_idempotency,
                'aud_atomic_unavailable_selection',
            ),
        )
    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_claim_asset_snapshots(claim.claim_id, claim.customer_id) == ([], False)
    assert (
        repository.find_idempotency(
            claim.customer_id, unavailable_idempotency.route, unavailable_idempotency.key
        )
        is None
    )


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
def test_asset_selection_adapters_reject_mismatched_snapshot_without_partial_write(
    adapter: str,
) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(mongomock.MongoClient(), f'asset_snapshot_parity_{adapter}')
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo

    asset = _asset()
    repository.create_asset(
        asset,
        IdempotencyRecord(
            actor_id=asset.customer_id,
            route='/api/v1/account/assets',
            key=f'parity-create-{adapter}',
            request_fingerprint=f'parity-create-fingerprint-{adapter}',
            claim_id=asset.asset_id,
            session_id='',
        ),
        _asset_audit(
            asset,
            f'aud_parity_create_{adapter}',
            idempotency_key=f'parity-create-{adapter}',
        ),
    )
    now = datetime.now(UTC)
    claim = WorkingClaim(
        claim_id=f'clm_asset_parity_{adapter}',
        customer_id=asset.customer_id,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id=f'ses_asset_parity_{adapter}',
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
            session_id=claim.active_session_id or '',
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            context_revision=claim.revision,
            started_at=now,
            last_active_at=now,
            status=SessionStatus.ACTIVE,
        ),
    )
    updated_claim = claim.model_copy(update={'revision': 2, 'updated_at': now})
    snapshot = ClaimAssetSnapshot(
        snapshot_id='cas_00000000000000000004',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        asset_id=asset.asset_id,
        asset_revision=asset.revision,
        asset_type=asset.asset_type,
        display_name='Mismatched copied name',
        details=asset.details,
        captured_at=now,
        resulting_claim_revision=2,
        source_refs=[f'asset:{asset.asset_id}:revision:{asset.revision}'],
    )
    idempotency = IdempotencyRecord(
        actor_id=claim.customer_id,
        route=f'/api/v1/claims/{claim.claim_id}/asset-selections',
        key=f'parity-select-{adapter}',
        request_fingerprint=f'parity-select-fingerprint-{adapter}',
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
    )
    evaluation = build_applied_branch_evaluation(
        updated_claim,
        repository=repository,
        recomputation_reason='claim_asset_selected',
        created_at=now,
    )

    with pytest.raises(AssetSelectionSnapshotConflictError):
        repository.save_asset_selection(
            updated_claim,
            1,
            snapshot,
            idempotency,
            evaluation,
            _selection_audit(
                updated_claim,
                snapshot,
                idempotency,
                f'aud_parity_select_{adapter}',
            ),
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_claim_asset_snapshots(claim.claim_id, claim.customer_id) == ([], False)
    assert repository.list_branch_evaluations(claim.claim_id, claim.customer_id) == []
    assert (
        repository.find_idempotency(claim.customer_id, idempotency.route, idempotency.key) is None
    )

    matching_snapshot = snapshot.model_copy(update={'display_name': asset.display_name})
    incoming_audit = _selection_audit(
        updated_claim,
        matching_snapshot,
        idempotency,
        f'aud_selection_conflict_{adapter}',
    )
    conflicting_audit = incoming_audit.model_copy(
        update={'reason': 'Existing unrelated Claim audit fact.'}
    )
    repository.append_audit_event(conflicting_audit)

    with pytest.raises(IdempotencyConflict):
        repository.save_asset_selection(
            updated_claim,
            1,
            matching_snapshot,
            idempotency,
            evaluation,
            incoming_audit,
        )

    assert repository.get_claim(claim.claim_id, claim.customer_id) == claim
    assert repository.list_claim_asset_snapshots(claim.claim_id, claim.customer_id) == ([], False)
    assert repository.list_branch_evaluations(claim.claim_id, claim.customer_id) == []
    assert (
        repository.find_idempotency(claim.customer_id, idempotency.route, idempotency.key) is None
    )
    assert repository.list_audit_events_internal(incoming_audit.subject) == [conflicting_audit]


@pytest.mark.parametrize('adapter', ['fixture', 'mongodb'])
def test_concurrent_exact_asset_selection_retry_restores_one_persisted_response(
    adapter: str,
) -> None:
    repository: FixtureRepository | MongoDBRepository
    if adapter == 'fixture':
        repository = FixtureRepository()
    else:
        mongo = MongoDBRepository(mongomock.MongoClient(), f'asset_retry_parity_{adapter}')
        mongo._atomic = lambda operation: operation(None)  # type: ignore[method-assign]
        repository = mongo

    asset = _asset()
    create_idempotency = IdempotencyRecord(
        actor_id=asset.customer_id,
        route='/api/v1/account/assets',
        key=f'retry-create-{adapter}',
        request_fingerprint=f'retry-create-fingerprint-{adapter}',
        claim_id=asset.asset_id,
        session_id='',
    )
    repository.create_asset(
        asset,
        create_idempotency,
        _asset_audit(
            asset,
            f'aud_retry_create_{adapter}',
            idempotency_key=f'retry-create-{adapter}',
        ),
    )
    now = datetime.now(UTC)
    claim = WorkingClaim(
        claim_id=f'clm_asset_retry_{adapter}',
        customer_id=asset.customer_id,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id=f'ses_asset_retry_{adapter}',
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
            session_id=claim.active_session_id or '',
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            context_revision=claim.revision,
            started_at=now,
            last_active_at=now,
            status=SessionStatus.ACTIVE,
        ),
    )
    original_save = repository.save_asset_selection
    save_calls = 0

    def concurrent_save(
        updated_claim: WorkingClaim,
        expected_revision: int,
        snapshot: ClaimAssetSnapshot,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord,
        audit_event: AuditEventEnvelope,
    ) -> None:
        nonlocal save_calls
        save_calls += 1
        original_save(
            updated_claim,
            expected_revision,
            snapshot,
            idempotency,
            branch_evaluation,
            audit_event,
        )
        original_save(
            updated_claim,
            expected_revision,
            snapshot,
            idempotency,
            branch_evaluation,
            audit_event,
        )

    repository.save_asset_selection = concurrent_save  # type: ignore[method-assign]
    response = select_claim_asset(
        repository,
        repository,
        Principal(
            subject=asset.customer_id,
            actor_type='claimant',
            auth_source='test:claimant',
        ),
        claim.claim_id,
        SelectClaimAssetRequest(asset_id=asset.asset_id),
        f'exact-retry-{adapter}',
        str(claim.revision),
    )

    assert save_calls == 1
    assert response.revision == claim.revision + 1
    stored = repository.get_claim_internal(claim.claim_id)
    assert stored is not None
    assert stored.revision == claim.revision + 1
    snapshots, has_more = repository.list_claim_asset_snapshots(claim.claim_id, claim.customer_id)
    assert len(snapshots) == 1
    assert has_more is False
    assert len(repository.list_branch_evaluations(claim.claim_id, claim.customer_id)) == 1
    claim_events = repository.list_audit_events_internal(
        AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim.claim_id,
            claim_id=claim.claim_id,
        )
    )
    assert len(claim_events) == 1
