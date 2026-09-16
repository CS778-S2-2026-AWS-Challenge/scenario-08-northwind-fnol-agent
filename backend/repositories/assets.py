"""Persistence port for account assets and immutable Claim asset snapshots."""

from typing import Protocol

from backend.domain.assets import AssetRecord, ClaimAssetSnapshot
from backend.domain.models import BranchEvaluationRecord, WorkingClaim
from backend.repositories.protocols import IdempotencyRecord


class AssetRepository(Protocol):
    def create_asset(self, asset: AssetRecord, idempotency: IdempotencyRecord) -> None: ...

    def get_asset(self, asset_id: str, customer_id: str) -> AssetRecord | None: ...

    def list_assets(
        self,
        customer_id: str,
        *,
        include_inactive: bool = False,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[AssetRecord], bool]: ...

    def update_asset(self, asset: AssetRecord, expected_revision: int) -> None: ...

    def save_asset_selection(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        snapshot: ClaimAssetSnapshot,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord,
    ) -> None: ...

    def list_claim_asset_snapshots(
        self,
        claim_id: str,
        customer_id: str,
        *,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[ClaimAssetSnapshot], bool]: ...
