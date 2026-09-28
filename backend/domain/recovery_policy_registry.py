"""Provider-neutral, versioned recovery policy and pure transition contracts."""

from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Literal

from pydantic import ConfigDict, Field

from backend.domain.model_gateway import ModelGatewayErrorCode
from backend.domain.models import ClaimantTurnRecovery, ContractModel

RecoverySource = Literal[
    'model',
    'tool',
    'retrieval',
    'repository',
    'external',
    'human',
    'timer',
    'retention',
]
RecoveryResponsibility = Literal['claimant', 'staff', 'system', 'external']
RuntimeDirective = Literal[
    'runtime.continue',
    'runtime.wait_for_user',
    'runtime.wait_for_external',
    'runtime.pause_for_review',
    'runtime.fail_safe',
]
RetryMode = Literal[
    'none',
    'claimant_initiated',
    'bounded_automatic',
    'same_operation',
    'reconcile_before_continue',
    'staff_decision',
]
RecoveryDecision = Literal[
    'wait',
    'retry',
    'reconcile',
    'review',
    'reload',
    'resume',
    'execute_follow_up',
    'block_follow_up',
    'expire',
    'retain',
    'deny',
    'no_op',
]


class RecoveryTrigger(ContractModel):
    """Normalised trigger used to select one immutable recovery policy."""

    source: RecoverySource
    outcome_code: str = Field(min_length=1, max_length=120)
    delivery_certain: bool | None = None
    side_effect_may_have_happened: bool = False
    blocking: bool | None = None


class RecoveryRule(ContractModel):
    """Immutable policy coordinates and decisions for one recovery class."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    policy_id: str = Field(min_length=1, max_length=120)
    rule_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=30)
    trigger_source: RecoverySource
    outcome_codes: frozenset[str] = Field(min_length=1)
    delivery_condition: Literal['any', 'not_submitted', 'submitted_or_unknown'] = 'any'
    preservation: str = Field(min_length=1, max_length=240)
    claim_effect: Literal['revision_unchanged_no_unapproved_write']
    continuation: RuntimeDirective
    retry_mode: RetryMode
    max_auto_retry: int = Field(default=0, ge=0, le=3)
    retry_interval_seconds: int | None = Field(default=None, ge=1)
    deadline_seconds: int | None = Field(default=None, ge=1)
    reconciliation_required: bool = False
    responsibility: RecoveryResponsibility
    work_item_kind: Literal[
        'question',
        'confirmation',
        'evidence',
        'professional_review',
        'external',
        'system',
    ] | None = None
    blocks_action: str | None = Field(default=None, max_length=120)
    handoff_required: bool = False
    claimant_projection: str = Field(min_length=1, max_length=500)
    staff_projection: str | None = Field(default=None, max_length=500)
    resume_triggers: frozenset[str] = frozenset()
    resume_entrypoint: str = Field(min_length=1, max_length=120)
    permitted_events: frozenset[str] = Field(min_length=1)
    audit_event_type: str = Field(min_length=1, max_length=120)


class RecoverySnapshot(ContractModel):
    """Authoritative facts supplied to the pure reducer by an orchestration caller."""

    claim_revision: int = Field(ge=1)
    follow_up_status: Literal['pending', 'blocked', 'resolved'] | None = None
    follow_up_attempt_count: int = Field(default=0, ge=0)
    contact_authorised: bool | None = None
    due_at: datetime | None = None
    deadline_at: datetime | None = None
    terminal: bool = False
    external_operation_state: Literal[
        'not_submitted',
        'submitted_unknown',
        'terminal_failure',
        'verified',
    ] | None = None
    retention_hold: bool = False
    access_closed: bool = False
    source_refs: list[str] = Field(default_factory=list, max_length=100)


class RecoveryEvent(ContractModel):
    """One event delivered after caller-side identity deduplication."""

    code: str = Field(min_length=1, max_length=120)
    expected_claim_revision: int | None = Field(default=None, ge=1)
    source_refs: list[str] = Field(default_factory=list, max_length=100)


class RecoveryTransition(ContractModel):
    """Typed, side-effect-free plan returned by reduce_recovery."""

    policy_id: str
    policy_version: str
    decision: RecoveryDecision
    runtime_directive: RuntimeDirective
    preserve_claim_revision: int = Field(ge=1)
    responsibility: RecoveryResponsibility
    work_item_kind: str | None = None
    blocks_action: str | None = None
    next_follow_up_status: Literal['pending', 'blocked', 'resolved'] | None = None
    blocked_reason: Literal[
        'contact_not_authorised',
        'attempt_limit_reached',
        'policy_binding_invalid',
        'source_state_inconsistent',
    ] | None = None
    resolution_code: Literal[
        'claimant_resumed',
        'recovery_expired',
        'staff_abandoned',
        'authorised_closure',
    ] | None = None
    attempt_count_delta: int = Field(default=0, ge=0, le=1)
    next_due_at: datetime | None = None
    operation_action: Literal[
        'none',
        'reserve_and_commit',
        'retry_same',
        'reconcile_same',
        'cancel_pending',
    ] = 'none'
    claimant_projection: str
    staff_projection: str | None = None
    audit_event_type: str
    source_refs: list[str] = Field(default_factory=list, max_length=100)


class UnknownRecoveryTrigger(ValueError):
    """Raised when no explicitly published recovery policy matches a trigger."""


class UnknownRecoveryTransition(ValueError):
    """Raised when an event is not permitted by the selected recovery policy."""


_MODEL_COMPATIBILITY_RULE_ID = 'claimant_turn.model_dependency_failure'
_MODEL_OTHER_CODES = frozenset(
    code.value
    for code in ModelGatewayErrorCode
    if code not in {ModelGatewayErrorCode.TIMEOUT, ModelGatewayErrorCode.MALFORMED_RESPONSE}
)


def _rule(
    *,
    policy_id: str,
    trigger_source: RecoverySource,
    outcome_codes: frozenset[str],
    preservation: str,
    continuation: RuntimeDirective,
    retry_mode: RetryMode,
    responsibility: RecoveryResponsibility,
    claimant_projection: str,
    permitted_events: frozenset[str],
    resume_entrypoint: str,
    version: str = 'v1',
    rule_id: str | None = None,
    delivery_condition: Literal['any', 'not_submitted', 'submitted_or_unknown'] = 'any',
    max_auto_retry: int = 0,
    retry_interval_seconds: int | None = None,
    deadline_seconds: int | None = None,
    reconciliation_required: bool = False,
    work_item_kind: Literal[
        'question',
        'confirmation',
        'evidence',
        'professional_review',
        'external',
        'system',
    ] | None = None,
    blocks_action: str | None = None,
    handoff_required: bool = False,
    staff_projection: str | None = None,
    resume_triggers: frozenset[str] = frozenset(),
    audit_event_type: str = 'RECOVERY_DECISION',
) -> RecoveryRule:
    return RecoveryRule(
        policy_id=policy_id,
        rule_id=rule_id or policy_id,
        version=version,
        trigger_source=trigger_source,
        outcome_codes=outcome_codes,
        delivery_condition=delivery_condition,
        preservation=preservation,
        claim_effect='revision_unchanged_no_unapproved_write',
        continuation=continuation,
        retry_mode=retry_mode,
        max_auto_retry=max_auto_retry,
        retry_interval_seconds=retry_interval_seconds,
        deadline_seconds=deadline_seconds,
        reconciliation_required=reconciliation_required,
        responsibility=responsibility,
        work_item_kind=work_item_kind,
        blocks_action=blocks_action,
        handoff_required=handoff_required,
        claimant_projection=claimant_projection,
        staff_projection=staff_projection,
        resume_triggers=resume_triggers,
        resume_entrypoint=resume_entrypoint,
        permitted_events=permitted_events,
        audit_event_type=audit_event_type,
    )


MODEL_TIMEOUT_RULE = _rule(
    policy_id='recovery.model_timeout',
    rule_id=_MODEL_COMPATIBILITY_RULE_ID,
    trigger_source='model',
    outcome_codes=frozenset({'timeout'}),
    preservation='inbound_message_and_checkpoint',
    continuation='runtime.fail_safe',
    retry_mode='claimant_initiated',
    responsibility='claimant',
    claimant_projection='Your message is saved, but I could not respond just now. You can try again.',
    permitted_events=frozenset({'claimant_reply', 'explicit_retry_request'}),
    resume_triggers=frozenset({'claimant_reply', 'explicit_retry_request'}),
    resume_entrypoint='submit_message',
    audit_event_type='AGENT_TURN_RECOVERY',
)

MODEL_MALFORMED_RULE = _rule(
    policy_id='recovery.model_malformed_response',
    rule_id=_MODEL_COMPATIBILITY_RULE_ID,
    trigger_source='model',
    outcome_codes=frozenset({'malformed_response'}),
    preservation='inbound_message_checkpoint_and_invalid_proposal_evidence',
    continuation='runtime.fail_safe',
    retry_mode='bounded_automatic',
    max_auto_retry=1,
    responsibility='system',
    claimant_projection='Your message is saved, but I could not produce a safe response just now.',
    permitted_events=frozenset({'automatic_retry', 'claimant_reply', 'explicit_retry_request'}),
    resume_triggers=frozenset({'claimant_reply', 'explicit_retry_request'}),
    resume_entrypoint='submit_message',
    audit_event_type='AGENT_TURN_RECOVERY',
)

CLAIMANT_TURN_MODEL_FAILURE_RULE = _rule(
    policy_id='recovery.model_dependency_failure',
    rule_id=_MODEL_COMPATIBILITY_RULE_ID,
    trigger_source='model',
    outcome_codes=_MODEL_OTHER_CODES,
    preservation='inbound_message_and_checkpoint',
    continuation='runtime.fail_safe',
    retry_mode='claimant_initiated',
    responsibility='claimant',
    claimant_projection='Your message is saved, but I could not respond just now. You can try again.',
    permitted_events=frozenset({'claimant_reply', 'explicit_retry_request'}),
    resume_triggers=frozenset({'claimant_reply', 'explicit_retry_request'}),
    resume_entrypoint='submit_message',
    audit_event_type='AGENT_TURN_RECOVERY',
)

TOOL_UNAVAILABLE_RULE = _rule(
    policy_id='recovery.tool_unavailable',
    trigger_source='tool',
    outcome_codes=frozenset({'unavailable'}),
    preservation='tool_request_failure_limitation_and_source_refs',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='system',
    work_item_kind='system',
    claimant_projection='A supporting service is unavailable. Your confirmed Claim information is saved.',
    staff_projection='The requested tool is unavailable; inspect its source references and blocker.',
    permitted_events=frozenset({'tool_available', 'staff_action'}),
    resume_entrypoint='reload_authoritative_context',
)

RETRIEVAL_UNAVAILABLE_RULE = TOOL_UNAVAILABLE_RULE.model_copy(
    update={
        'policy_id': 'recovery.retrieval_unavailable',
        'rule_id': 'recovery.retrieval_unavailable',
        'trigger_source': 'retrieval',
    }
)

REVISION_CONFLICT_RULE = _rule(
    policy_id='recovery.revision_conflict',
    trigger_source='repository',
    outcome_codes=frozenset({'revision_conflict'}),
    preservation='stale_proposal_rejected_and_current_revision_preserved',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='system',
    work_item_kind='system',
    claimant_projection=(
        'The Claim changed while this step was being prepared. '
        'I will use the latest saved information.'
    ),
    staff_projection='Reload authoritative Claim, Session, WorkItem and external records.',
    permitted_events=frozenset({'reload_authoritative_state'}),
    resume_entrypoint='reload_authoritative_context',
)

EXTERNAL_NOT_SUBMITTED_RULE = _rule(
    policy_id='recovery.external_not_submitted_retryable',
    trigger_source='external',
    outcome_codes=frozenset({'retryable_failure'}),
    delivery_condition='not_submitted',
    preservation='external_task_operation_identity_request_fingerprint_and_delivery_evidence',
    continuation='runtime.wait_for_external',
    retry_mode='same_operation',
    responsibility='system',
    work_item_kind='external',
    claimant_projection=(
        'The external request was not submitted. Northwind can retry the same request safely.'
    ),
    staff_projection='Retry the same ExternalTask operation identity; do not allocate a second task.',
    permitted_events=frozenset({'worker_retry', 'staff_action'}),
    resume_entrypoint='external_task_retry',
)

EXTERNAL_UNKNOWN_RULE = _rule(
    policy_id='recovery.external_submitted_unknown',
    trigger_source='external',
    outcome_codes=frozenset({'unknown_outcome'}),
    delivery_condition='submitted_or_unknown',
    preservation='external_task_operation_identity_delivery_evidence_and_unknown_outcome',
    continuation='runtime.wait_for_external',
    retry_mode='reconcile_before_continue',
    reconciliation_required=True,
    responsibility='staff',
    work_item_kind='external',
    blocks_action='external.retry',
    claimant_projection=(
        'The external request result is not yet confirmed. '
        'Northwind needs to check it before retrying.'
    ),
    staff_projection='Reconcile the same ExternalTask operation; blind resubmission is blocked.',
    permitted_events=frozenset({'provider_result', 'scheduled_reconciliation', 'staff_action'}),
    resume_entrypoint='external_task_reconcile',
)

EXTERNAL_TERMINAL_RULE = _rule(
    policy_id='recovery.external_terminal_failure',
    trigger_source='external',
    outcome_codes=frozenset({'terminal_failure'}),
    preservation='external_task_terminal_evidence_and_source_refs',
    continuation='runtime.wait_for_external',
    retry_mode='staff_decision',
    responsibility='staff',
    work_item_kind='external',
    blocks_action='external.retry',
    claimant_projection=(
        'The external service could not complete this request. '
        'Northwind staff will review the next step.'
    ),
    staff_projection='Review the terminal ExternalTask evidence before any new business operation.',
    permitted_events=frozenset({'staff_action'}),
    resume_entrypoint='workbench_external_review',
)

HIGH_IMPACT_REVIEW_RULE = _rule(
    policy_id='recovery.high_impact_review_required',
    trigger_source='human',
    outcome_codes=frozenset({'high_impact_review_required'}),
    preservation='reviewable_proposal_evidence_and_source_refs',
    continuation='runtime.pause_for_review',
    retry_mode='staff_decision',
    responsibility='staff',
    work_item_kind='professional_review',
    blocks_action='high_impact.execute',
    handoff_required=True,
    claimant_projection='This step needs review by a claims professional before it can continue.',
    staff_projection='Review the saved proposal and evidence; execution remains paused.',
    permitted_events=frozenset({'authorised_staff_decision'}),
    resume_entrypoint='workbench_review',
)

INCOMPLETE_CLAIM_FOLLOW_UP_RULE = _rule(
    policy_id='incomplete_claim_follow_up',
    trigger_source='timer',
    outcome_codes=frozenset({'follow_up_due'}),
    preservation='follow_up_obligation_checkpoint_policy_coordinate_and_operation_identity',
    continuation='runtime.wait_for_user',
    retry_mode='bounded_automatic',
    max_auto_retry=3,
    retry_interval_seconds=24 * 60 * 60,
    deadline_seconds=7 * 24 * 60 * 60,
    responsibility='claimant',
    claimant_projection='Your incomplete Claim is saved and can still be resumed.',
    staff_projection='The incomplete-Claim recovery obligation remains open.',
    permitted_events=frozenset(
        {
            'follow_up_due',
            'follow_up_committed_no_response',
            'claimant_resume',
            'contact_withdrawn',
            'recovery_deadline',
        }
    ),
    resume_entrypoint='resume_claim',
    version='v1',
    audit_event_type='INCOMPLETE_CLAIM_RECOVERY',
)

CONTACT_WITHDRAWAL_RULE = _rule(
    policy_id='recovery.contact_withdrawal',
    trigger_source='human',
    outcome_codes=frozenset({'contact_withdrawn'}),
    preservation='follow_up_obligation_and_contact_authority_change',
    continuation='runtime.wait_for_user',
    retry_mode='none',
    responsibility='claimant',
    claimant_projection='Automatic follow-up has stopped. Your incomplete Claim remains saved.',
    staff_projection='Contact authority was withdrawn; the Claim was not withdrawn.',
    permitted_events=frozenset({'claimant_resume', 'staff_action', 'recovery_deadline'}),
    resume_entrypoint='resume_claim',
)

ATTEMPT_EXHAUSTION_RULE = _rule(
    policy_id='recovery.attempt_exhaustion',
    trigger_source='timer',
    outcome_codes=frozenset({'attempt_limit_reached'}),
    preservation='follow_up_obligation_committed_operation_count_and_policy_coordinate',
    continuation='runtime.wait_for_user',
    retry_mode='none',
    responsibility='claimant',
    claimant_projection=(
        'Automatic follow-up has ended, but your incomplete Claim remains saved '
        'until its recovery deadline.'
    ),
    staff_projection='Automatic attempt limit reached; do not infer Claim abandonment.',
    permitted_events=frozenset({'claimant_resume', 'staff_action', 'recovery_deadline'}),
    resume_entrypoint='resume_claim',
)

RECOVERY_EXPIRY_RULE = _rule(
    policy_id='recovery.incomplete_claim_expiry',
    trigger_source='timer',
    outcome_codes=frozenset({'recovery_expired'}),
    preservation='expiry_policy_coordinate_claim_revision_and_terminal_source_refs',
    continuation='runtime.wait_for_user',
    retry_mode='staff_decision',
    responsibility='staff',
    claimant_projection=(
        'This saved recovery period has ended. Contact Northwind if you need to continue the Claim.'
    ),
    staff_projection='Recovery expired; use the registered reopen contract for continuation.',
    permitted_events=frozenset({'staff_action'}),
    resume_entrypoint='claim.reopen',
    audit_event_type='INCOMPLETE_CLAIM_RECOVERY_EXPIRED',
)

RETENTION_ELIGIBLE_RULE = _rule(
    policy_id='retention.eligible',
    trigger_source='retention',
    outcome_codes=frozenset({'eligible'}),
    preservation='source_expiry_terminal_ref_policy_coordinate_claim_revision_and_hold_evidence',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='system',
    work_item_kind='system',
    claimant_projection='This Claim is no longer available through the previous recovery session.',
    staff_projection='Retention is eligible only from the authoritative expiry/terminal source.',
    permitted_events=frozenset({'retention_execute', 'retention_hold'}),
    resume_entrypoint='retention_worker',
    audit_event_type='RETENTION_ELIGIBLE',
)

RETENTION_HOLD_RULE = _rule(
    policy_id='retention.hold',
    trigger_source='retention',
    outcome_codes=frozenset({'hold'}),
    preservation='retention_hold_authority_reason_source_and_release_condition',
    continuation='runtime.fail_safe',
    retry_mode='staff_decision',
    responsibility='staff',
    work_item_kind='system',
    claimant_projection='This Claim is not available through the previous recovery session.',
    staff_projection='A source-linked retention hold blocks destructive cleanup.',
    permitted_events=frozenset({'retention_hold_released'}),
    resume_entrypoint='retention_worker',
    audit_event_type='RETENTION_HELD',
)

RETENTION_FAILURE_RULE = _rule(
    policy_id='retention.reconciliation_required',
    trigger_source='retention',
    outcome_codes=frozenset({'failed', 'unknown'}),
    preservation='retention_operation_targets_completed_steps_failed_steps_and_diagnostics',
    continuation='runtime.fail_safe',
    retry_mode='reconcile_before_continue',
    reconciliation_required=True,
    responsibility='system',
    work_item_kind='system',
    claimant_projection='This Claim is not available through the previous recovery session.',
    staff_projection='Retention is incomplete; reconcile and retry only unfinished steps.',
    permitted_events=frozenset({'scheduled_reconciliation', 'staff_action'}),
    resume_entrypoint='retention_reconcile',
    audit_event_type='RETENTION_RECONCILIATION_REQUIRED',
)

OLD_SESSION_DENIED_RULE = _rule(
    policy_id='retention.old_session_denied',
    trigger_source='retention',
    outcome_codes=frozenset({'old_session_denied'}),
    preservation='retention_access_closure_tombstone_and_minimum_audit_evidence',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='system',
    claimant_projection='This previous recovery session is no longer available.',
    staff_projection='Retention access closure denied the stale session or recovery credential.',
    permitted_events=frozenset({'access_denied'}),
    resume_entrypoint='none',
    audit_event_type='RETENTION_ACCESS_DENIED',
)

_RULE_SEQUENCE = (
    MODEL_TIMEOUT_RULE,
    MODEL_MALFORMED_RULE,
    CLAIMANT_TURN_MODEL_FAILURE_RULE,
    TOOL_UNAVAILABLE_RULE,
    RETRIEVAL_UNAVAILABLE_RULE,
    REVISION_CONFLICT_RULE,
    EXTERNAL_NOT_SUBMITTED_RULE,
    EXTERNAL_UNKNOWN_RULE,
    EXTERNAL_TERMINAL_RULE,
    HIGH_IMPACT_REVIEW_RULE,
    INCOMPLETE_CLAIM_FOLLOW_UP_RULE,
    CONTACT_WITHDRAWAL_RULE,
    ATTEMPT_EXHAUSTION_RULE,
    RECOVERY_EXPIRY_RULE,
    RETENTION_ELIGIBLE_RULE,
    RETENTION_HOLD_RULE,
    RETENTION_FAILURE_RULE,
    OLD_SESSION_DENIED_RULE,
)

RECOVERY_RULES = MappingProxyType(
    {f'{rule.policy_id}.{rule.version}': rule for rule in _RULE_SEQUENCE}
)


def _delivery_matches(rule: RecoveryRule, trigger: RecoveryTrigger) -> bool:
    if rule.delivery_condition == 'any':
        return True
    if rule.delivery_condition == 'not_submitted':
        return trigger.delivery_certain is False and not trigger.side_effect_may_have_happened
    return trigger.delivery_certain is not False or trigger.side_effect_may_have_happened


def classify_recovery(trigger: RecoveryTrigger) -> RecoveryRule:
    """Return the single registered policy for a normalised trigger.

    Args:
        trigger: Provider-neutral failure or lifecycle trigger.

    Returns:
        The immutable policy that owns the recovery decision.

    Raises:
        UnknownRecoveryTrigger: No published policy matches the trigger.
    """

    for rule in _RULE_SEQUENCE:
        if (
            rule.trigger_source == trigger.source
            and trigger.outcome_code in rule.outcome_codes
            and _delivery_matches(rule, trigger)
        ):
            return rule
    raise UnknownRecoveryTrigger(
        f'No recovery policy is registered for {trigger.source}:{trigger.outcome_code}.'
    )


def recovery_policy(policy_id: str, version: str = 'v1') -> RecoveryRule:
    """Resolve one immutable policy coordinate.

    Args:
        policy_id: Stable recovery policy identifier.
        version: Immutable published version.

    Returns:
        The matching policy.

    Raises:
        UnknownRecoveryTrigger: The coordinate is not registered.
    """

    rule = RECOVERY_RULES.get(f'{policy_id}.{version}')
    if rule is None:
        raise UnknownRecoveryTrigger(f'Unknown recovery policy coordinate {policy_id}.{version}.')
    return rule


def preservation_requirements(rule: RecoveryRule) -> str:
    """Return the preservation contract from the selected policy.

    Args:
        rule: Selected immutable recovery policy.

    Returns:
        The policy preservation requirement.
    """

    return rule.preservation


def retry_decision(rule: RecoveryRule, trigger: str) -> bool:
    """Return whether this trigger may initiate a retry.

    Args:
        rule: Selected immutable recovery policy.
        trigger: Candidate resume or retry event.

    Returns:
        True only when the event is authorised by the policy retry contract.
    """

    if trigger not in rule.resume_triggers and trigger not in rule.permitted_events:
        return False
    return rule.retry_mode in {'claimant_initiated', 'bounded_automatic', 'same_operation'}


def resume_entrypoint(rule: RecoveryRule) -> str:
    """Return the authoritative re-entry boundary for a recovery policy.

    Args:
        rule: Selected immutable recovery policy.

    Returns:
        Stable service or action entrypoint name.
    """

    return rule.resume_entrypoint


def claimant_recovery_projection(rule_id: str | None) -> ClaimantTurnRecovery | None:
    """Project compatibility recovery metadata for claimant message history.

    Args:
        rule_id: Compatibility rule identifier stored on a claimant Agent message.

    Returns:
        A safe claimant projection, or None when the identifier is not published.
    """

    rule = next((item for item in _RULE_SEQUENCE if item.rule_id == (rule_id or '')), None)
    if rule is None:
        return None
    return ClaimantTurnRecovery(
        rule_id=rule.rule_id,
        continuation=rule.continuation,
        claimant_projection=rule.claimant_projection,
        resume_triggers=sorted(rule.resume_triggers),
        resume_entrypoint=rule.resume_entrypoint,
    )


def _base_transition(
    rule: RecoveryRule,
    snapshot: RecoverySnapshot,
    *,
    decision: RecoveryDecision,
    source_refs: list[str],
    **updates: object,
) -> RecoveryTransition:
    payload: dict[str, object] = {
        'policy_id': rule.policy_id,
        'policy_version': rule.version,
        'decision': decision,
        'runtime_directive': rule.continuation,
        'preserve_claim_revision': snapshot.claim_revision,
        'responsibility': rule.responsibility,
        'work_item_kind': rule.work_item_kind,
        'blocks_action': rule.blocks_action,
        'claimant_projection': rule.claimant_projection,
        'staff_projection': rule.staff_projection,
        'audit_event_type': rule.audit_event_type,
        'source_refs': source_refs,
    }
    payload.update(updates)
    return RecoveryTransition.model_validate(payload)


def _reduce_incomplete_claim(
    rule: RecoveryRule,
    event: RecoveryEvent,
    snapshot: RecoverySnapshot,
    now: datetime,
    source_refs: list[str],
) -> RecoveryTransition:
    if snapshot.follow_up_status == 'resolved':
        return _base_transition(rule, snapshot, decision='no_op', source_refs=source_refs)
    if snapshot.deadline_at is None:
        return _base_transition(
            rule,
            snapshot,
            decision='block_follow_up',
            source_refs=source_refs,
            next_follow_up_status='blocked',
            blocked_reason='policy_binding_invalid',
        )
    if now >= snapshot.deadline_at or event.code == 'recovery_deadline':
        return _base_transition(
            rule,
            snapshot,
            decision='expire',
            source_refs=source_refs,
            next_follow_up_status='resolved',
            resolution_code='recovery_expired',
            operation_action='cancel_pending',
        )
    if event.code == 'claimant_resume':
        return _base_transition(
            rule,
            snapshot,
            decision='resume',
            source_refs=source_refs,
            next_follow_up_status='resolved',
            resolution_code='claimant_resumed',
            operation_action='cancel_pending',
        )
    if event.code == 'contact_withdrawn' or snapshot.contact_authorised is False:
        return _base_transition(
            rule,
            snapshot,
            decision='block_follow_up',
            source_refs=source_refs,
            next_follow_up_status='blocked',
            blocked_reason='contact_not_authorised',
        )
    if snapshot.follow_up_attempt_count >= rule.max_auto_retry:
        return _base_transition(
            rule,
            snapshot,
            decision='block_follow_up',
            source_refs=source_refs,
            next_follow_up_status='blocked',
            blocked_reason='attempt_limit_reached',
        )
    if event.code == 'follow_up_due':
        if snapshot.follow_up_status != 'pending' or snapshot.due_at is None:
            return _base_transition(
                rule,
                snapshot,
                decision='block_follow_up',
                source_refs=source_refs,
                next_follow_up_status='blocked',
                blocked_reason='source_state_inconsistent',
            )
        if now < snapshot.due_at:
            raise UnknownRecoveryTransition('Follow-up due event arrived before its due time.')
        return _base_transition(
            rule,
            snapshot,
            decision='execute_follow_up',
            source_refs=source_refs,
            next_follow_up_status='pending',
            operation_action='reserve_and_commit',
        )
    if event.code == 'follow_up_committed_no_response':
        next_count = snapshot.follow_up_attempt_count + 1
        if next_count >= rule.max_auto_retry:
            return _base_transition(
                rule,
                snapshot,
                decision='block_follow_up',
                source_refs=source_refs,
                next_follow_up_status='blocked',
                blocked_reason='attempt_limit_reached',
                attempt_count_delta=1,
            )
        if snapshot.due_at is None or rule.retry_interval_seconds is None:
            return _base_transition(
                rule,
                snapshot,
                decision='block_follow_up',
                source_refs=source_refs,
                next_follow_up_status='blocked',
                blocked_reason='source_state_inconsistent',
                attempt_count_delta=1,
            )
        next_due_at = snapshot.due_at + timedelta(seconds=rule.retry_interval_seconds)
        if next_due_at >= snapshot.deadline_at:
            return _base_transition(
                rule,
                snapshot,
                decision='block_follow_up',
                source_refs=source_refs,
                next_follow_up_status='blocked',
                blocked_reason='attempt_limit_reached',
                attempt_count_delta=1,
            )
        return _base_transition(
            rule,
            snapshot,
            decision='retry',
            source_refs=source_refs,
            next_follow_up_status='pending',
            attempt_count_delta=1,
            next_due_at=next_due_at,
        )
    raise UnknownRecoveryTransition(f'Unsupported incomplete-Claim event {event.code}.')


def reduce_recovery(
    policy: RecoveryRule,
    recovery_state: RecoverySnapshot,
    incoming_event: RecoveryEvent,
    authoritative_snapshot: RecoverySnapshot,
    now: datetime,
) -> RecoveryTransition:
    """Reduce one recovery event into a deterministic transition plan.

    The function performs no I/O and reads no global clock. recovery_state is
    the caller's previously loaded coordination view; authoritative_snapshot is
    the fresh commit-time source snapshot. A mismatch therefore fails closed
    instead of replaying stale work.

    Args:
        policy: Immutable policy selected from the Registry.
        recovery_state: Previously loaded recovery coordination facts.
        incoming_event: Deduplicated event being evaluated.
        authoritative_snapshot: Fresh authoritative facts for commit-time decisions.
        now: Explicit UTC comparison time supplied by the caller.

    Returns:
        A typed transition plan containing no executed side effects.

    Raises:
        UnknownRecoveryTransition: The event is not permitted or the policy is incomplete.
    """

    if incoming_event.code not in policy.permitted_events:
        raise UnknownRecoveryTransition(
            f'Event {incoming_event.code} is not permitted by {policy.policy_id}.{policy.version}.'
        )

    source_refs = list(
        dict.fromkeys(
            [
                *recovery_state.source_refs,
                *authoritative_snapshot.source_refs,
                *incoming_event.source_refs,
            ]
        )
    )

    if authoritative_snapshot.access_closed:
        return _base_transition(
            OLD_SESSION_DENIED_RULE,
            authoritative_snapshot,
            decision='deny',
            source_refs=source_refs,
        )

    if (
        incoming_event.expected_claim_revision is not None
        and incoming_event.expected_claim_revision != authoritative_snapshot.claim_revision
    ):
        return _base_transition(
            REVISION_CONFLICT_RULE,
            authoritative_snapshot,
            decision='reload',
            source_refs=source_refs,
        )

    if recovery_state.claim_revision != authoritative_snapshot.claim_revision:
        return _base_transition(
            REVISION_CONFLICT_RULE,
            authoritative_snapshot,
            decision='reload',
            source_refs=source_refs,
        )

    if policy.policy_id == INCOMPLETE_CLAIM_FOLLOW_UP_RULE.policy_id:
        return _reduce_incomplete_claim(
            policy,
            incoming_event,
            authoritative_snapshot,
            now,
            source_refs,
        )

    if policy.reconciliation_required:
        return _base_transition(
            policy,
            authoritative_snapshot,
            decision='reconcile',
            source_refs=source_refs,
            operation_action='reconcile_same' if policy.trigger_source == 'external' else 'none',
        )

    if policy.policy_id == REVISION_CONFLICT_RULE.policy_id:
        return _base_transition(
            policy,
            authoritative_snapshot,
            decision='reload',
            source_refs=source_refs,
        )

    if policy.retry_mode == 'same_operation':
        return _base_transition(
            policy,
            authoritative_snapshot,
            decision='retry',
            source_refs=source_refs,
            operation_action='retry_same',
        )

    if policy.retry_mode == 'staff_decision':
        return _base_transition(
            policy,
            authoritative_snapshot,
            decision='review',
            source_refs=source_refs,
        )

    if policy.policy_id == RETENTION_ELIGIBLE_RULE.policy_id:
        if authoritative_snapshot.retention_hold:
            return _base_transition(
                RETENTION_HOLD_RULE,
                authoritative_snapshot,
                decision='wait',
                source_refs=source_refs,
            )
        return _base_transition(
            policy,
            authoritative_snapshot,
            decision='retain',
            source_refs=source_refs,
        )

    if policy.retry_mode in {'claimant_initiated', 'bounded_automatic'}:
        return _base_transition(
            policy,
            authoritative_snapshot,
            decision='retry',
            source_refs=source_refs,
        )

    return _base_transition(
        policy,
        authoritative_snapshot,
        decision='wait',
        source_refs=source_refs,
    )


def recovery_policy_manifest() -> dict[str, object]:
    """Return a machine-readable projection generated from the typed Registry.

    Returns:
        Registry version metadata and every immutable policy entry.
    """

    return {
        'registry_version': 'recovery-policy-registry.v2',
        'policies': [
            rule.model_dump(mode='json')
            for rule in sorted(_RULE_SEQUENCE, key=lambda item: (item.policy_id, item.version))
        ],
    }
