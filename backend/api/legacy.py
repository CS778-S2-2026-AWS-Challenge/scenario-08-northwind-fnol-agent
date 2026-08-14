from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StringConstraints

from backend.core.auth import Principal, require_claimant

router = APIRouter(tags=['temporary-connectivity'])


class ClaimMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class ClaimMessageResponse(BaseModel):
    reply: str
    received_message: str


@router.post(
    '/api/claims/message',
    response_model=ClaimMessageResponse,
    deprecated=True,
)
def claim_message(
    data: ClaimMessage,
    _principal: Principal = Depends(require_claimant),
) -> ClaimMessageResponse:
    """Keep the connectivity shell working until the versioned routes replace it."""
    return ClaimMessageResponse(
        reply='I received your claim.',
        received_message=data.message,
    )
