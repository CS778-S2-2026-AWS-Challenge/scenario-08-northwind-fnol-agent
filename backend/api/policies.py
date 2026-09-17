"""Claimant account Policy Summary routes."""

from typing import cast

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from backend.core.auth import Principal, require_claimant_session
from backend.domain.policies import (
    CreatePolicySummaryRequest,
    PolicySummaryListResponse,
    PolicySummaryProjection,
    UpdatePolicySummaryRequest,
)
from backend.repositories.policies import PolicySummaryRepository
from backend.repositories.protocols import PersistenceRepository
from backend.services.policies import (
    create_policy_summary,
    deactivate_policy_summary,
    get_policy_summary,
    list_policy_summaries,
    update_policy_summary,
)

router = APIRouter(prefix='/account/policies', tags=['claimant policies'])


def repositories_for(request: Request) -> tuple[PolicySummaryRepository, PersistenceRepository]:
    repository = request.app.state.claim_repository
    return cast(PolicySummaryRepository, repository), cast(PersistenceRepository, repository)


@router.post('', response_model=PolicySummaryProjection, status_code=status.HTTP_201_CREATED)
def create_account_policy_summary(
    payload: CreatePolicySummaryRequest,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
) -> PolicySummaryProjection:
    policies, persistence = repositories_for(request)
    return create_policy_summary(policies, persistence, principal, payload, idempotency_key)


@router.get('', response_model=PolicySummaryListResponse)
def read_account_policy_summaries(
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> PolicySummaryListResponse:
    policies, _ = repositories_for(request)
    return list_policy_summaries(
        policies,
        principal,
        include_inactive=include_inactive,
        limit=limit,
        cursor=cursor,
    )


@router.get('/{policy_id}', response_model=PolicySummaryProjection)
def read_account_policy_summary(
    policy_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
) -> PolicySummaryProjection:
    policies, _ = repositories_for(request)
    return get_policy_summary(policies, principal, policy_id)


@router.patch('/{policy_id}', response_model=PolicySummaryProjection)
def patch_account_policy_summary(
    policy_id: str,
    payload: UpdatePolicySummaryRequest,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> PolicySummaryProjection:
    policies, _ = repositories_for(request)
    return update_policy_summary(policies, principal, policy_id, payload, if_match)


@router.delete('/{policy_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_account_policy_summary(
    policy_id: str,
    request: Request,
    principal: Principal = Depends(require_claimant_session),
    if_match: str | None = Header(default=None, alias='If-Match'),
) -> Response:
    policies, _ = repositories_for(request)
    deactivate_policy_summary(policies, principal, policy_id, if_match)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
