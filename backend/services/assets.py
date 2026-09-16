"""Ownership-safe application behavior for reusable claimant assets."""

from typing import cast

from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.assets import (
    AssetListResponse,
    AssetProjection,
    AssetRecord,
    AssetType,
    ClaimAssetSelectionResponse,
    ClaimAssetSnapshot,
    ClaimAssetSnapshotListResponse,
    CreateAssetRequest,
    PropertyAssetDetails,
    SelectClaimAssetRequest,
    UpdateAssetRequest,
    VehicleAssetDetails,
    project_asset,
    project_snapshot,
)
from backend.domain.branch_registry import validate_registered_field_value
from backend.domain.ids import new_id
from backend.domain.models import (
    ActorReference,
    ActorType,
    FormSource,
    FormStatus,
    NeededFor,
    PageInfo,
    ProposedFormChange,
    StructuredFormField,
)
from backend.repositories.assets import AssetRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.branching import build_applied_branch_evaluation
from backend.services.fact_resolution import resolve_form_change
from backend.services.support import (
    decode_cursor,
    encode_cursor,
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)

CREATE_ROUTE = '/api/v1/account/assets'


def _not_found(resource: str) -> ApiError:
    return ApiError(
        status_code=404, code='RESOURCE_NOT_FOUND', message=f'The {resource} was not found.'
    )


def _revision_conflict(current_revision: int) -> ApiError:
    return ApiError(
        status_code=409,
        code='REVISION_CONFLICT',
        message='The resource changed after this page was loaded.',
        retryable=True,
        current_revision=current_revision,
    )


def _idempotency_conflict() -> ApiError:
    return ApiError(
        status_code=409,
        code='IDEMPOTENCY_CONFLICT',
        message='The Idempotency-Key was already used with a different request.',
    )


def create_asset(
    repository: AssetRepository,
    idempotency_repository: PersistenceRepository,
    principal: Principal,
    payload: CreateAssetRequest,
    idempotency_key: str | None,
) -> AssetProjection:
    key = require_idempotency_key(idempotency_key)
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    existing = idempotency_repository.find_idempotency(principal.subject, CREATE_ROUTE, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint or existing.response_payload is None:
            raise _idempotency_conflict()
        return AssetProjection.model_validate(existing.response_payload)

    timestamp = now_utc()
    asset = AssetRecord(
        asset_id=new_id('ast'),
        customer_id=principal.subject,
        revision=1,
        active=True,
        created_at=timestamp,
        updated_at=timestamp,
        **payload.model_dump(),
    )
    projection = project_asset(asset)
    record = IdempotencyRecord(
        actor_id=principal.subject,
        route=CREATE_ROUTE,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=asset.asset_id,
        session_id='',
        response_payload=projection.model_dump(mode='json'),
    )
    try:
        repository.create_asset(asset, record)
    except IdempotencyConflict as error:
        replay = idempotency_repository.find_idempotency(principal.subject, CREATE_ROUTE, key)
        if (
            replay is None
            or replay.request_fingerprint != fingerprint
            or replay.response_payload is None
        ):
            raise _idempotency_conflict() from error
        return AssetProjection.model_validate(replay.response_payload)
    return projection


def get_asset(repository: AssetRepository, principal: Principal, asset_id: str) -> AssetProjection:
    asset = repository.get_asset(asset_id, principal.subject)
    if asset is None:
        raise _not_found('asset')
    return project_asset(asset)


def list_assets(
    repository: AssetRepository,
    principal: Principal,
    *,
    include_inactive: bool,
    limit: int,
    cursor: str | None,
) -> AssetListResponse:
    offset = decode_cursor(cursor)
    records, has_more = repository.list_assets(
        principal.subject,
        include_inactive=include_inactive,
        offset=offset,
        limit=limit,
    )
    page = PageInfo(next_cursor=encode_cursor(offset + len(records)) if has_more else None)
    return AssetListResponse(items=[project_asset(item) for item in records], page=page)


def update_asset(
    repository: AssetRepository,
    principal: Principal,
    asset_id: str,
    payload: UpdateAssetRequest,
    if_match: str | None,
) -> AssetProjection:
    expected_revision = parse_if_match(if_match)
    current = repository.get_asset(asset_id, principal.subject)
    if current is None:
        raise _not_found('asset')
    if current.revision != expected_revision:
        raise _revision_conflict(current.revision)
    changes = payload.model_dump(exclude_unset=True)
    updated_payload = current.model_dump()
    updated_payload.update(changes)
    updated_payload.update({'revision': current.revision + 1, 'updated_at': now_utc()})
    updated = AssetRecord.model_validate(updated_payload)
    try:
        repository.update_asset(updated, expected_revision)
    except RevisionConflict as error:
        raise _revision_conflict(error.current_revision) from error
    return project_asset(updated)


def deactivate_asset(
    repository: AssetRepository,
    principal: Principal,
    asset_id: str,
    if_match: str | None,
) -> None:
    expected_revision = parse_if_match(if_match)
    current = repository.get_asset(asset_id, principal.subject)
    if current is None:
        raise _not_found('asset')
    if current.revision != expected_revision:
        raise _revision_conflict(current.revision)
    if not current.active:
        return
    updated = current.model_copy(
        update={'active': False, 'revision': current.revision + 1, 'updated_at': now_utc()}
    )
    try:
        repository.update_asset(updated, expected_revision)
    except RevisionConflict as error:
        raise _revision_conflict(error.current_revision) from error


def _prefill_values(asset: AssetRecord) -> dict[str, object]:
    family = {
        AssetType.VEHICLE: 'motor',
        AssetType.PROPERTY: 'home',
        AssetType.CONTENTS: 'contents',
    }[asset.asset_type]
    values: dict[str, object] = {'claim.product_family': family}
    if asset.asset_type is AssetType.VEHICLE:
        vehicle = cast(VehicleAssetDetails, asset.details)
        values['vehicle.registration'] = vehicle.registration
    elif asset.asset_type is AssetType.PROPERTY:
        property_details = cast(PropertyAssetDetails, asset.details)
        values['property.address'] = property_details.address
    if asset.policy_reference is not None:
        values['policy.policy_number'] = asset.policy_reference.policy_number
    return values


def select_claim_asset(
    repository: AssetRepository,
    claim_repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: SelectClaimAssetRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> ClaimAssetSelectionResponse:
    key = require_idempotency_key(idempotency_key)
    route = f'/api/v1/claims/{claim_id}/asset-selections'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = claim_repository.find_idempotency(principal.subject, route, key)
    if replay is not None:
        if replay.request_fingerprint != fingerprint or replay.response_payload is None:
            raise _idempotency_conflict()
        return ClaimAssetSelectionResponse.model_validate(replay.response_payload)

    expected_revision = parse_if_match(if_match)
    claim = claim_repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _not_found('claim')
    if claim.revision != expected_revision:
        raise _revision_conflict(claim.revision)
    asset = repository.get_asset(payload.asset_id, principal.subject)
    if asset is None or not asset.active:
        raise _not_found('asset')

    timestamp = now_utc()
    source_ref = f'asset:{asset.asset_id}:revision:{asset.revision}'
    proposed_fields: dict[str, StructuredFormField] = {}
    for field_code, value in _prefill_values(asset).items():
        try:
            validate_registered_field_value(field_code, value, status=FormStatus.PROPOSED)
        except ValueError as error:
            raise ApiError(
                status_code=422,
                code='VALIDATION_ERROR',
                message='The selected asset cannot prefill a registered Claim field.',
                details=[ErrorDetail(field=field_code, reason=str(error))],
            ) from error
        proposed_fields[field_code] = resolve_form_change(
            field_code=field_code,
            existing=claim.form.get(field_code),
            proposal=ProposedFormChange(
                field_code=field_code,
                value=value,
                source=FormSource.CLAIMANT,
                status=FormStatus.PROPOSED,
                needed_for=NeededFor.CURRENT_ACTION,
                reported_text=f'Selected registered asset {asset.display_name}.',
            ),
            source_ref=source_ref,
            message_text=None,
            timestamp=timestamp,
            accepted_status=FormStatus.PROPOSED,
            updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id=principal.subject),
        )

    updated_claim = claim.model_copy(
        update={
            'form': {**claim.form, **proposed_fields},
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    snapshot = ClaimAssetSnapshot(
        snapshot_id=new_id('cas'),
        claim_id=claim.claim_id,
        customer_id=principal.subject,
        asset_id=asset.asset_id,
        asset_revision=asset.revision,
        asset_type=asset.asset_type,
        display_name=asset.display_name,
        details=asset.details,
        policy_reference=asset.policy_reference,
        captured_at=timestamp,
        resulting_claim_revision=updated_claim.revision,
        source_refs=[source_ref, f'claim:{claim.claim_id}:revision:{updated_claim.revision}'],
    )
    response = ClaimAssetSelectionResponse(
        claim_id=claim.claim_id,
        revision=updated_claim.revision,
        proposed_fields=proposed_fields,
        snapshot=project_snapshot(snapshot),
    )
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim.claim_id,
        session_id=claim.active_session_id or '',
        response_payload=response.model_dump(mode='json'),
    )
    evaluation = build_applied_branch_evaluation(
        updated_claim,
        repository=claim_repository,
        recomputation_reason='claim_asset_selected',
        trigger_source_refs=[source_ref],
        created_at=timestamp,
    )
    try:
        repository.save_asset_selection(
            updated_claim,
            expected_revision,
            snapshot,
            idempotency,
            evaluation,
        )
    except RevisionConflict as error:
        raise _revision_conflict(error.current_revision) from error
    except IdempotencyConflict as error:
        replay = claim_repository.find_idempotency(principal.subject, route, key)
        if (
            replay is None
            or replay.request_fingerprint != fingerprint
            or replay.response_payload is None
        ):
            raise _idempotency_conflict() from error
        return ClaimAssetSelectionResponse.model_validate(replay.response_payload)
    return response


def list_claim_asset_snapshots(
    repository: AssetRepository,
    claim_repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    *,
    limit: int,
    cursor: str | None,
) -> ClaimAssetSnapshotListResponse:
    if claim_repository.get_claim(claim_id, principal.subject) is None:
        raise _not_found('claim')
    offset = decode_cursor(cursor)
    records, has_more = repository.list_claim_asset_snapshots(
        claim_id,
        principal.subject,
        offset=offset,
        limit=limit,
    )
    page = PageInfo(next_cursor=encode_cursor(offset + len(records)) if has_more else None)
    return ClaimAssetSnapshotListResponse(
        items=[project_snapshot(item) for item in records], page=page
    )
