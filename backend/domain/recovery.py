"""Pure provider-neutral recovery decision boundary.

This module contains no repository, clock, provider, model or queue access.
It maps one published policy plus authoritative input facts into a typed plan.
The plan is executed by the subsystem that already owns those facts.
"""

from datetime import datetime

from pydantic import Field

from backend.domain.models import ContractModel
from backend.domain.recovery_policy_registry import (
    RecoveryAction,
    RecoveryAuthority,
    RecoveryContinuation,
    RecoveryDecisionCode,
    RecoveryRetryMode,
    RecoveryRule,
    RecoveryTrigger,
    RecoveryWorkItemKind,
    classify_recovery,
)


class NormalizedRecoveryEvent(ContractModel):
    event_id: str = Field(min_length=1, max_length=160)
    trigger: RecoveryTrigger
    expected_claim_revision: int | None = Field(default=None, ge=1)
    operation_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_refs: list[str] = Field(default_factory=list, max_length=100)


class RecoveryAuthoritativeSnapshot(ContractModel):
    """Read-only reducer input, not a persisted recovery state object."""

    claim_id: str = Field(min_length=1, max_length=120)
    claim_revision: int = Field(ge=1)

    accepted_state_preserved: bool = True
    operation_id: str | None = Field(default=None, min_length=1, max_length=160)

    terminal: bool = False
    source_refs: list[str] = Field(default_factory=list, max_length=100)


class RecoveryTransition(ContractModel):
    """Typed plan returned by the pure reducer."""

    event_id: str
    rule_id: str
    policy_version: str

    decision_code: RecoveryDecisionCode
    continuation: RecoveryContinuation
    retry_mode: RecoveryRetryMode
    responsibility: str

    max_auto_retry: int
    requires_reconciliation: bool
    requires_operation_identity: bool

    work_item_kind: RecoveryWorkItemKind | None = None
    blocks_action: str | None = None

    claim_effect: str
    expected_claim_revision: int
    operation_id: str | None = None

    authoritative_records: frozenset[RecoveryAuthority]
    required_actions: tuple[RecoveryAction, ...]

    claimant_projection: str
    staff_projection: str | None = None

    resume_triggers: frozenset[str]
    resume_entrypoint: str

    audit_event_type: str
    source_refs: list[str]

    decided_at: datetime


class RecoveryReductionRejected(ValueError):
    """The event/snapshot cannot safely produce the requested transition."""


def reduce_recovery(
    policy: RecoveryRule,
    event: NormalizedRecoveryEvent,
    authoritative_snapshot: RecoveryAuthoritativeSnapshot,
    now: datetime,
) -> RecoveryTransition:
    """Reduce one normalised event without performing any side effect."""

    if now.tzinfo is None:
        raise RecoveryReductionRejected(
            'Recovery decision time must be timezone-aware.'
        )

    published = classify_recovery(event.trigger)

    if (
        published.rule_id != policy.rule_id
        or published.version != policy.version
    ):
        raise RecoveryReductionRejected(
            'The supplied policy coordinate does not match the published event policy.'
        )

    expected_revision = event.expected_claim_revision

    if policy.rule_id == 'runtime.revision_conflict':
        if expected_revision is None:
            raise RecoveryReductionRejected(
                'Revision-conflict recovery requires the stale expected revision.'
            )

        if expected_revision == authoritative_snapshot.claim_revision:
            raise RecoveryReductionRejected(
                'A revision-conflict event must name a stale revision.'
            )

    elif (
        expected_revision is not None
        and expected_revision != authoritative_snapshot.claim_revision
    ):
        raise RecoveryReductionRejected(
            'The recovery event is stale against authoritative Claim state.'
        )

    if (
        policy.preservation == 'inbound_message_and_checkpoint'
        and not authoritative_snapshot.accepted_state_preserved
    ):
        raise RecoveryReductionRejected(
            'The accepted claimant input/checkpoint must be durable before recovery.'
        )

    operation_id = event.operation_id or authoritative_snapshot.operation_id

    if policy.requires_operation_identity and operation_id is None:
        raise RecoveryReductionRejected(
            'This recovery policy requires the existing logical operation identity.'
        )

    if policy.requires_reconciliation and operation_id is None:
        raise RecoveryReductionRejected(
            'Reconciliation cannot proceed without the original operation identity.'
        )

    source_refs = list(
        dict.fromkeys(
            [
                *authoritative_snapshot.source_refs,
                *event.source_refs,
                f'recovery-policy:{policy.rule_id}@{policy.version}',
            ]
        )
    )

    return RecoveryTransition(
        event_id=event.event_id,
        rule_id=policy.rule_id,
        policy_version=policy.version,
        decision_code=policy.decision_code,
        continuation=policy.continuation,
        retry_mode=policy.retry_mode,
        responsibility=policy.responsibility,
        max_auto_retry=policy.max_auto_retry,
        requires_reconciliation=policy.requires_reconciliation,
        requires_operation_identity=policy.requires_operation_identity,
        work_item_kind=policy.work_item_kind,
        blocks_action=policy.blocks_action,
        claim_effect=policy.claim_effect,
        expected_claim_revision=authoritative_snapshot.claim_revision,
        operation_id=operation_id,
        authoritative_records=policy.authoritative_records,
        required_actions=policy.required_actions,
        claimant_projection=policy.claimant_projection,
        staff_projection=policy.staff_projection,
        resume_triggers=policy.resume_triggers,
        resume_entrypoint=policy.resume_entrypoint,
        audit_event_type=policy.audit_event_type,
        source_refs=source_refs,
        decided_at=now,
    )
