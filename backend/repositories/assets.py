"""Persistence port for account assets and immutable Claim asset snapshots."""

from typing import Protocol

from backend.domain.assets import AssetRecord, AssetType, ClaimAssetSnapshot
from backend.domain.audit import (
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.models import ActorType, BranchEvaluationRecord, WorkingClaim
from backend.domain.policies import PolicyProductFamily, PolicySummaryRecord
from backend.repositories.protocols import IdempotencyRecord, RepositoryConflict


class AssetSelectionUnavailableError(RepositoryConflict):
    """The selected asset is unavailable inside the authoritative write."""


class AssetSelectionRevisionConflictError(RepositoryConflict):
    """The selected asset changed before the authoritative write completed."""

    def __init__(self, current_revision: int) -> None:
        super().__init__(f'Current asset revision is {current_revision}.')
        self.current_revision = current_revision


class AssetSelectionSnapshotConflictError(RepositoryConflict):
    """The proposed snapshot does not copy the authoritative Asset exactly."""


class PolicyAssociationUnavailableError(RepositoryConflict):
    """The associated Policy Summary is not selectable by this claimant."""


class PolicyAssociationRevisionConflictError(RepositoryConflict):
    """The associated Policy Summary changed before the write completed."""

    def __init__(self, current_revision: int) -> None:
        super().__init__(f'Current policy summary revision is {current_revision}.')
        self.current_revision = current_revision


class PolicyAssociationMismatchError(RepositoryConflict):
    """The Policy Summary does not match the Asset or snapshot contract."""


def policy_family_for_asset(asset_type: AssetType) -> PolicyProductFamily:
    return {
        AssetType.VEHICLE: PolicyProductFamily.MOTOR,
        AssetType.PROPERTY: PolicyProductFamily.HOME,
        AssetType.CONTENTS: PolicyProductFamily.CONTENTS,
    }[asset_type]


def asset_policy_matches(asset: AssetRecord, policy: PolicySummaryRecord | None) -> bool:
    if asset.policy_id is None:
        return policy is None
    return (
        policy is not None
        and policy.policy_id == asset.policy_id
        and policy.customer_id == asset.customer_id
        and policy.active
        and policy.product_family is policy_family_for_asset(asset.asset_type)
    )


def asset_matches_snapshot(asset: AssetRecord, snapshot: ClaimAssetSnapshot) -> bool:
    """Return whether a snapshot copies the selection-relevant Asset fields exactly."""

    return (
        asset.asset_type == snapshot.asset_type
        and asset.display_name == snapshot.display_name
        and asset.details == snapshot.details
        and asset.policy_id == (snapshot.policy.policy_id if snapshot.policy is not None else None)
    )


def policy_matches_snapshot(
    policy: PolicySummaryRecord | None, snapshot: ClaimAssetSnapshot
) -> bool:
    if snapshot.policy is None:
        return policy is None
    return (
        policy is not None
        and policy.active
        and policy.customer_id == snapshot.customer_id
        and policy.policy_id == snapshot.policy.policy_id
        and policy.revision == snapshot.policy.policy_revision
        and policy.policy_number == snapshot.policy.policy_number
        and policy.product_family is snapshot.policy.product_family
        and policy.verification_status is snapshot.policy.verification_status
        and policy.product_family is policy_family_for_asset(snapshot.asset_type)
    )


def asset_audit_matches(asset: AssetRecord, event: AuditEventEnvelope) -> bool:
    """Return whether an account-level audit event belongs to this Asset mutation."""

    return (
        event.event_type is AuditEventType.ACTION_COMPLETED
        and event.outcome is AuditOutcome.SUCCEEDED
        and event.subject.subject_type is AuditSubjectType.ASSET
        and event.subject.subject_id == asset.asset_id
        and event.subject.claim_id is None
        and event.actor.actor_type is ActorType.CLAIMANT
        and event.actor.actor_id == asset.customer_id
        and event.claim_revision is None
        and event.source_refs == [f'asset:{asset.asset_id}:revision:{asset.revision}']
        and event.visibility is AuditVisibility.AUDIT_ONLY
        and event.created_at == asset.updated_at
    )


def asset_selection_audit_matches(
    claim: WorkingClaim,
    snapshot: ClaimAssetSnapshot,
    idempotency: IdempotencyRecord,
    event: AuditEventEnvelope,
) -> bool:
    """Return whether a Claim audit event belongs to this Asset selection."""

    asset_source = f'asset:{snapshot.asset_id}:revision:{snapshot.asset_revision}'
    source_refs = [asset_source]
    if snapshot.policy is not None:
        source_refs.append(
            f'policy:{snapshot.policy.policy_id}:revision:{snapshot.policy.policy_revision}'
        )
    source_refs.append(snapshot.snapshot_id)
    return (
        event.event_type is AuditEventType.ACTION_COMPLETED
        and event.outcome is AuditOutcome.SUCCEEDED
        and event.subject.subject_type is AuditSubjectType.CLAIM
        and event.subject.subject_id == claim.claim_id
        and event.subject.claim_id == claim.claim_id
        and event.actor.actor_type is ActorType.CLAIMANT
        and event.actor.actor_id == claim.customer_id
        and event.claim_revision == claim.revision
        and event.idempotency_key == idempotency.key
        and event.visibility is AuditVisibility.AUDIT_ONLY
        and event.created_at == snapshot.captured_at
        and event.source_refs == source_refs
    )


class AssetRepository(Protocol):
    def create_asset(
        self,
        asset: AssetRecord,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
        policy: PolicySummaryRecord | None = None,
    ) -> None: ...

    def get_asset(self, asset_id: str, customer_id: str) -> AssetRecord | None: ...

    def list_assets(
        self,
        customer_id: str,
        *,
        include_inactive: bool = False,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[AssetRecord], bool]: ...

    def update_asset(
        self,
        asset: AssetRecord,
        expected_revision: int,
        audit_event: AuditEventEnvelope,
        policy: PolicySummaryRecord | None = None,
    ) -> None: ...

    def save_asset_selection(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        snapshot: ClaimAssetSnapshot,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord,
        audit_event: AuditEventEnvelope,
    ) -> None: ...

    def list_claim_asset_snapshots(
        self,
        claim_id: str,
        customer_id: str,
        *,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[ClaimAssetSnapshot], bool]: ...
