"""Claimant account assets and Claim asset-selection routes."""

from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from backend.core.auth import Principal, require_claimant_session
from backend.domain.assets import (
    AssetListResponse,
    AssetProjection,
    ClaimAssetSelectionResponse,
    ClaimAssetSnapshotListResponse,
    CreateAssetRequest,
    SelectClaimAssetRequest,
    UpdateAssetRequest,
)
from backend.repositories.assets import AssetRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services.assets import (
    create_asset,
    deactivate_asset,
    get_asset,
    list_assets,
    list_claim_asset_snapshots,
    select_claim_asset,
    update_asset,
)

account_router = APIRouter(prefix='/account/assets', tags=['claimant assets'])
claim_router = APIRouter(tags=['claimant assets'])


def repositories_for(request: Request) -> tuple[AssetRepository, PersistenceRepository]:
    repository = request.app.state.claim_repository
    return cast(AssetRepository, repository), cast(PersistenceRepository, repository)


@account_router.post('', response_model=AssetProjection, status_code=status.HTTP_201_CREATED)
def create_account_asset(
    payload: CreateAssetRequest,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
) -> AssetProjection:
    assets, persistence = repositories_for(request)
    return create_asset(assets, persistence, principal, payload, idempotency_key)


@account_router.get('', response_model=AssetListResponse)
def read_account_assets(
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> AssetListResponse:
    assets, _ = repositories_for(request)
    return list_assets(
        assets,
        principal,
        include_inactive=include_inactive,
        limit=limit,
        cursor=cursor,
    )


@account_router.get('/{asset_id}', response_model=AssetProjection)
def read_account_asset(
    asset_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
) -> AssetProjection:
    assets, _ = repositories_for(request)
    return get_asset(assets, principal, asset_id)


@account_router.patch('/{asset_id}', response_model=AssetProjection)
def patch_account_asset(
    asset_id: str,
    payload: UpdateAssetRequest,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> AssetProjection:
    assets, _ = repositories_for(request)
    return update_asset(assets, principal, asset_id, payload, if_match)


@account_router.delete('/{asset_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_account_asset(
    asset_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> Response:
    assets, _ = repositories_for(request)
    deactivate_asset(assets, principal, asset_id, if_match)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@claim_router.post(
    '/{claim_id}/asset-selections',
    response_model=ClaimAssetSelectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_claim_asset_selection(
    claim_id: str,
    payload: SelectClaimAssetRequest,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> ClaimAssetSelectionResponse:
    assets, persistence = repositories_for(request)
    return select_claim_asset(
        assets, persistence, principal, claim_id, payload, idempotency_key, if_match
    )


@claim_router.get('/{claim_id}/asset-snapshots', response_model=ClaimAssetSnapshotListResponse)
def read_claim_asset_snapshots(
    claim_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> ClaimAssetSnapshotListResponse:
    assets, persistence = repositories_for(request)
    return list_claim_asset_snapshots(
        assets, persistence, principal, claim_id, limit=limit, cursor=cursor
    )
