"""Provider-neutral immutable Recovery Policy Registry.

The registry maps normalised recovery events to actions over existing
authoritative records.  It is not a mutable RecoveryInstance and does not
replace Claim, Session, ExternalTask, RuntimeWorkItem, Handoff, FollowUp or
Audit authority.
"""

from datetime import timedelta
from types import MappingProxyType
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from backend.domain.audit import AuditEventType
from backend.domain.model_gateway import ModelGatewayErrorCode
from backend.domain.models import ClaimantTurnRecovery, ContractModel

RECOVERY_POLICY_REGISTRY_VERSION = '2026-09-28.1'

INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_ID = 'incomplete_claim_follow_up'
INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION = 'v1'
INCOMPLETE_CLAIM_FOLLOW_UP_MAX_AUTO_ATTEMPTS = 3
INCOMPLETE_CLAIM_FOLLOW_UP_RETRY_INTERVAL = timedelta(hours=24)
INCOMPLETE_CLAIM_FOLLOW_UP_RECOVERY_DEADLINE = timedelta(days=7)


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

RecoveryDeliveryState = Literal[
    'not_applicable',
    'not_submitted',
    'submitted',
    'unknown',
]

RecoveryRetryMode = Literal[
    'none',
    'claimant_initiated',
    'bounded_auto',
    'same_operation',
    'reconcile_before_retry',
    'reload_authoritative',
    'staff_authorised',
    'scheduled_policy',
]

RecoveryContinuation = Literal[
    'runtime.continue',
    'runtime.wait_for_user',
    'runtime.wait_for_external',
    'runtime.pause_for_review',
    'runtime.fail_safe',
]

RecoveryDecisionCode = Literal[
    'continue_with_limitation',
    'fail_safe',
    'retry_same_operation',
    'reconcile_existing_operation',
    'reload_authoritative_state',
    'pause_for_review',
    'execute_follow_up',
    'block_follow_up',
    'expire_recovery',
]

RecoveryAuthority = Literal[
    'message',
    'session',
    'claim',
    'external_task',
    'work_item',
    'handoff',
    'follow_up',
    'audit',
]

RecoveryAction = Literal[
    'message.preserve_checkpoint',
    'claim.preserve_revision',
    'claim.reload',
    'external.retry_same_operation',
    'external.reconcile',
    'work_item.ensure',
    'handoff.ensure',
    'follow_up.execute',
    'follow_up.block',
    'claim.expire',
    'audit.append',
]

RecoveryWorkItemKind = Literal[
    'question',
    'confirmation',
    'evidence',
    'professional_review',
    'external',
    'system',
]


class RecoveryTrigger(ContractModel):
    """Normalised trigger presented to the immutable policy registry."""

    source: RecoverySource
    outcome_code: str = Field(min_length=1, max_length=120)

    # New code should use delivery_state.  delivery_certain remains accepted so
    # historical callers/tests do not silently change meaning.
    delivery_state: RecoveryDeliveryState | None = None
    delivery_certain: bool | None = None

    retryable: bool | None = None
    blocking: bool | None = None

    @model_validator(mode='after')
    def validate_delivery_coordinates(self) -> 'RecoveryTrigger':
        if self.delivery_state is None or self.delivery_certain is None:
            return self

        if self.delivery_certain is True and self.delivery_state != 'submitted':
            raise ValueError(
                'delivery_certain=true requires delivery_state=submitted.'
            )

        if self.delivery_certain is False and self.delivery_state != 'not_submitted':
            raise ValueError(
                'delivery_certain=false requires delivery_state=not_submitted.'
            )

        return self

    def resolved_delivery_state(self) -> RecoveryDeliveryState:
        if self.delivery_state is not None:
            return self.delivery_state

        if self.source == 'external':
            if self.delivery_certain is True:
                return 'submitted'
            if self.delivery_certain is False:
                return 'not_submitted'

        # Preserve the previous model-trigger meaning: omitted/false delivery
        # evidence is not itself an external-delivery fact.
        if self.delivery_certain is True:
            return 'submitted'

        return 'not_applicable'


class RecoveryRule(ContractModel):
    """One immutable policy mapping, never live recovery state."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    rule_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=30)

    trigger_source: RecoverySource
    outcome_codes: frozenset[str]
    delivery_states: frozenset[RecoveryDeliveryState] = frozenset(
        {'not_applicable'}
    )
    retryable: bool | None = None
    blocking: bool | None = None

    preservation: Literal[
        'inbound_message_and_checkpoint',
        'authoritative_records_only',
        'external_operation_and_delivery_evidence',
        'review_request_and_evidence',
        'follow_up_obligation_and_operation_history',
    ]

    claim_effect: Literal[
        'revision_unchanged_no_unapproved_write',
        'existing_authority_only',
        'reload_authoritative_state',
        'terminal_transition_via_existing_contract',
    ]

    decision_code: RecoveryDecisionCode
    continuation: RecoveryContinuation
    retry_mode: RecoveryRetryMode
    max_auto_retry: int = Field(default=0, ge=0, le=3)

    responsibility: Literal['claimant', 'staff', 'system', 'external']
    requires_reconciliation: bool = False
    requires_operation_identity: bool = False

    work_item_kind: RecoveryWorkItemKind | None = None
    blocks_action: str | None = Field(default=None, max_length=120)

    authoritative_records: frozenset[RecoveryAuthority]
    required_actions: tuple[RecoveryAction, ...]

    claimant_projection: str = Field(min_length=1, max_length=500)
    staff_projection: str | None = Field(default=None, max_length=500)

    resume_triggers: frozenset[str] = frozenset()
    resume_entrypoint: str = Field(min_length=1, max_length=120)

    audit_event_type: AuditEventType

    @model_validator(mode='after')
    def validate_policy_contract(self) -> 'RecoveryRule':
        if not self.outcome_codes:
            raise ValueError('A recovery rule needs at least one outcome code.')

        if not self.delivery_states:
            raise ValueError('A recovery rule needs a delivery-state matcher.')

        if self.requires_reconciliation and self.retry_mode != 'reconcile_before_retry':
            raise ValueError(
                'Reconciliation-required rules must use reconcile_before_retry.'
            )

        if self.retry_mode == 'reconcile_before_retry' and not self.requires_reconciliation:
            raise ValueError(
                'reconcile_before_retry must explicitly require reconciliation.'
            )

        if self.max_auto_retry > 0 and self.retry_mode not in {
            'bounded_auto',
            'scheduled_policy',
        }:
            raise ValueError(
                'Automatic retry limits are valid only for bounded_auto or '
                'scheduled_policy rules.'
            )

        if self.retry_mode == 'none' and self.max_auto_retry != 0:
            raise ValueError('A no-retry rule cannot carry an automatic retry limit.')

        if self.requires_operation_identity and 'external_task' not in self.authoritative_records:
            raise ValueError(
                'Operation-identity rules must retain ExternalTask authority.'
            )

        return self

    def matches(self, trigger: RecoveryTrigger) -> bool:
        if trigger.source != self.trigger_source:
            return False

        if trigger.outcome_code not in self.outcome_codes:
            return False

        if trigger.resolved_delivery_state() not in self.delivery_states:
            return False

        if self.retryable is not None and trigger.retryable is not self.retryable:
            return False

        return self.blocking is None or trigger.blocking == self.blocking


class UnknownRecoveryTrigger(ValueError):
    """Raised when no explicitly published recovery policy matches."""


class AmbiguousRecoveryTrigger(ValueError):
    """Raised if policy publication accidentally creates overlapping rules."""


# ---------------------------------------------------------------------------
# Historical coordinate.
#
# Existing persisted claimant messages may already reference this rule_id.
# Keep it immutable for projection/replay, but new ModelGatewayError values are
# classified into the more specific rules below.
# ---------------------------------------------------------------------------

LEGACY_CLAIMANT_TURN_MODEL_FAILURE_RULE = RecoveryRule(
    rule_id='claimant_turn.model_dependency_failure',
    version='v1',
    trigger_source='model',
    outcome_codes=frozenset({'legacy_model_dependency_failure'}),
    preservation='inbound_message_and_checkpoint',
    claim_effect='revision_unchanged_no_unapproved_write',
    decision_code='fail_safe',
    continuation='runtime.fail_safe',
    retry_mode='claimant_initiated',
    responsibility='claimant',
    authoritative_records=frozenset({'message', 'claim', 'audit'}),
    required_actions=(
        'message.preserve_checkpoint',
        'claim.preserve_revision',
        'audit.append',
    ),
    claimant_projection=(
        'Your message is saved, but I could not respond just now. You can try again.'
    ),
    resume_triggers=frozenset({'claimant_reply', 'explicit_retry_request'}),
    resume_entrypoint='submit_message',
    audit_event_type='AGENT_TURN_RECOVERY',
)

# Backward-compatible symbol for code/tests that imported the old name.
CLAIMANT_TURN_MODEL_FAILURE_RULE = LEGACY_CLAIMANT_TURN_MODEL_FAILURE_RULE


MODEL_TIMEOUT_RULE = RecoveryRule(
    rule_id='claimant_turn.model_timeout',
    version='v1',
    trigger_source='model',
    outcome_codes=frozenset({ModelGatewayErrorCode.TIMEOUT.value}),
    preservation='inbound_message_and_checkpoint',
    claim_effect='revision_unchanged_no_unapproved_write',
    decision_code='fail_safe',
    continuation='runtime.fail_safe',
    retry_mode='claimant_initiated',
    responsibility='claimant',
    authoritative_records=frozenset({'message', 'claim', 'audit'}),
    required_actions=(
        'message.preserve_checkpoint',
        'claim.preserve_revision',
        'audit.append',
    ),
    claimant_projection=(
        'Your message is saved, but I could not respond just now. You can try again.'
    ),
    staff_projection='The model timed out before an approved Claim mutation was committed.',
    resume_triggers=frozenset({'claimant_reply', 'explicit_retry_request'}),
    resume_entrypoint='submit_message',
    audit_event_type='AGENT_TURN_RECOVERY',
)


MODEL_INVALID_RESPONSE_RULE = RecoveryRule(
    rule_id='claimant_turn.model_invalid_response',
    version='v1',
    trigger_source='model',
    outcome_codes=frozenset(
        {
            ModelGatewayErrorCode.MALFORMED_RESPONSE.value,
            ModelGatewayErrorCode.INCOMPLETE_RESPONSE.value,
            ModelGatewayErrorCode.REFUSED_RESPONSE.value,
        }
    ),
    preservation='inbound_message_and_checkpoint',
    claim_effect='revision_unchanged_no_unapproved_write',
    decision_code='fail_safe',
    continuation='runtime.fail_safe',
    retry_mode='claimant_initiated',
    responsibility='claimant',
    authoritative_records=frozenset({'message', 'claim', 'audit'}),
    required_actions=(
        'message.preserve_checkpoint',
        'claim.preserve_revision',
        'audit.append',
    ),
    claimant_projection=(
        'Your message is saved, but I could not produce a safe response. You can try again.'
    ),
    staff_projection=(
        'The model result was incomplete, refused or malformed and no proposed fact was accepted.'
    ),
    resume_triggers=frozenset({'claimant_reply', 'explicit_retry_request'}),
    resume_entrypoint='submit_message',
    audit_event_type='AGENT_TURN_RECOVERY',
)


MODEL_RATE_LIMIT_RULE = RecoveryRule(
    rule_id='claimant_turn.model_rate_limited',
    version='v1',
    trigger_source='model',
    outcome_codes=frozenset({ModelGatewayErrorCode.RATE_LIMIT.value}),
    preservation='inbound_message_and_checkpoint',
    claim_effect='revision_unchanged_no_unapproved_write',
    decision_code='fail_safe',
    continuation='runtime.fail_safe',
    retry_mode='claimant_initiated',
    responsibility='claimant',
    authoritative_records=frozenset({'message', 'claim', 'audit'}),
    required_actions=(
        'message.preserve_checkpoint',
        'claim.preserve_revision',
        'audit.append',
    ),
    claimant_projection=(
        'Your message is saved, but the service is temporarily busy. You can try again.'
    ),
    staff_projection='The model provider rate-limited this turn before Claim mutation.',
    resume_triggers=frozenset({'claimant_reply', 'explicit_retry_request'}),
    resume_entrypoint='submit_message',
    audit_event_type='AGENT_TURN_RECOVERY',
)


MODEL_PROVIDER_RETRYABLE_RULE = RecoveryRule(
    rule_id='claimant_turn.model_provider_retryable',
    version='v1',
    trigger_source='model',
    outcome_codes=frozenset({ModelGatewayErrorCode.PROVIDER.value}),
    retryable=True,
    preservation='inbound_message_and_checkpoint',
    claim_effect='revision_unchanged_no_unapproved_write',
    decision_code='fail_safe',
    continuation='runtime.fail_safe',
    retry_mode='claimant_initiated',
    responsibility='claimant',
    authoritative_records=frozenset({'message', 'claim', 'audit'}),
    required_actions=(
        'message.preserve_checkpoint',
        'claim.preserve_revision',
        'audit.append',
    ),
    claimant_projection=(
        'Your message is saved, but the service is temporarily unavailable. You can try again.'
    ),
    staff_projection='A retryable model-provider failure occurred before Claim mutation.',
    resume_triggers=frozenset({'claimant_reply', 'explicit_retry_request'}),
    resume_entrypoint='submit_message',
    audit_event_type='AGENT_TURN_RECOVERY',
)


MODEL_TERMINAL_DEPENDENCY_RULE = RecoveryRule(
    rule_id='claimant_turn.model_dependency_terminal',
    version='v1',
    trigger_source='model',
    outcome_codes=frozenset(
        {
            ModelGatewayErrorCode.AUTHENTICATION.value,
            ModelGatewayErrorCode.UNSUPPORTED_CAPABILITY.value,
            ModelGatewayErrorCode.EVIDENCE_UNAVAILABLE.value,
            ModelGatewayErrorCode.CONFIGURATION.value,
        }
    ),
    preservation='inbound_message_and_checkpoint',
    claim_effect='revision_unchanged_no_unapproved_write',
    decision_code='fail_safe',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='system',
    blocks_action='runtime.continue',
    authoritative_records=frozenset(
        {'message', 'claim', 'audit'}
    ),
    required_actions=(
        'message.preserve_checkpoint',
        'claim.preserve_revision',
        'audit.append',
    ),
    claimant_projection=(
        'Your message is saved, but this step is currently unavailable.'
    ),
    staff_projection=(
        'The model dependency cannot safely continue without system remediation.'
    ),
    resume_entrypoint='submit_message',
    audit_event_type='AGENT_TURN_RECOVERY',
)


MODEL_PROVIDER_TERMINAL_RULE = RecoveryRule(
    rule_id='claimant_turn.model_provider_terminal',
    version='v1',
    trigger_source='model',
    outcome_codes=frozenset({ModelGatewayErrorCode.PROVIDER.value}),
    retryable=False,
    preservation='inbound_message_and_checkpoint',
    claim_effect='revision_unchanged_no_unapproved_write',
    decision_code='fail_safe',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='system',
    blocks_action='runtime.continue',
    authoritative_records=frozenset(
        {'message', 'claim', 'audit'}
    ),
    required_actions=(
        'message.preserve_checkpoint',
        'claim.preserve_revision',
        'audit.append',
    ),
    claimant_projection=(
        'Your message is saved, but this step is currently unavailable.'
    ),
    staff_projection='The provider returned a non-retryable model failure.',
    resume_entrypoint='submit_message',
    audit_event_type='AGENT_TURN_RECOVERY',
)


TOOL_UNAVAILABLE_NON_BLOCKING_RULE = RecoveryRule(
    rule_id='runtime.tool_unavailable.non_blocking',
    version='v1',
    trigger_source='tool',
    outcome_codes=frozenset({'unavailable'}),
    blocking=False,
    preservation='authoritative_records_only',
    claim_effect='existing_authority_only',
    decision_code='continue_with_limitation',
    continuation='runtime.continue',
    retry_mode='none',
    responsibility='system',
    authoritative_records=frozenset({'claim', 'audit'}),
    required_actions=('claim.preserve_revision', 'audit.append'),
    claimant_projection=(
        'One supporting capability is unavailable, but the safe parts of your Claim can continue.'
    ),
    staff_projection='A non-blocking tool dependency is unavailable.',
    resume_entrypoint='reload_authoritative_state',
    audit_event_type='action.failed',
)


TOOL_UNAVAILABLE_BLOCKING_RULE = RecoveryRule(
    rule_id='runtime.tool_unavailable.blocking',
    version='v1',
    trigger_source='tool',
    outcome_codes=frozenset({'unavailable'}),
    blocking=True,
    preservation='authoritative_records_only',
    claim_effect='existing_authority_only',
    decision_code='fail_safe',
    continuation='runtime.fail_safe',
    retry_mode='staff_authorised',
    responsibility='system',
    work_item_kind='system',
    blocks_action='runtime.continue',
    authoritative_records=frozenset({'claim', 'work_item', 'audit'}),
    required_actions=(
        'claim.preserve_revision',
        'work_item.ensure',
        'audit.append',
    ),
    claimant_projection=(
        'A required capability is unavailable, so this step cannot safely continue yet.'
    ),
    staff_projection='A blocking tool dependency requires recovery before continuation.',
    resume_triggers=frozenset({'system_recovered', 'staff_retry'}),
    resume_entrypoint='reload_authoritative_state',
    audit_event_type='action.failed',
)


RETRIEVAL_UNAVAILABLE_NON_BLOCKING_RULE = RecoveryRule(
    rule_id='runtime.retrieval_unavailable.non_blocking',
    version='v1',
    trigger_source='retrieval',
    outcome_codes=frozenset({'unavailable'}),
    blocking=False,
    preservation='authoritative_records_only',
    claim_effect='existing_authority_only',
    decision_code='continue_with_limitation',
    continuation='runtime.continue',
    retry_mode='none',
    responsibility='system',
    authoritative_records=frozenset({'claim', 'audit'}),
    required_actions=('claim.preserve_revision', 'audit.append'),
    claimant_projection=(
        'Some supporting information is unavailable, but the safe parts of your Claim can continue.'
    ),
    staff_projection='A non-blocking retrieval dependency is unavailable.',
    resume_entrypoint='reload_authoritative_state',
    audit_event_type='action.failed',
)


RETRIEVAL_UNAVAILABLE_BLOCKING_RULE = RecoveryRule(
    rule_id='runtime.retrieval_unavailable.blocking',
    version='v1',
    trigger_source='retrieval',
    outcome_codes=frozenset({'unavailable'}),
    blocking=True,
    preservation='authoritative_records_only',
    claim_effect='existing_authority_only',
    decision_code='fail_safe',
    continuation='runtime.fail_safe',
    retry_mode='staff_authorised',
    responsibility='system',
    work_item_kind='system',
    blocks_action='runtime.continue',
    authoritative_records=frozenset({'claim', 'work_item', 'audit'}),
    required_actions=(
        'claim.preserve_revision',
        'work_item.ensure',
        'audit.append',
    ),
    claimant_projection=(
        'Required supporting information is unavailable, so this step cannot safely continue yet.'
    ),
    staff_projection='A blocking retrieval dependency requires recovery before continuation.',
    resume_triggers=frozenset({'system_recovered', 'staff_retry'}),
    resume_entrypoint='reload_authoritative_state',
    audit_event_type='action.failed',
)


REVISION_CONFLICT_RULE = RecoveryRule(
    rule_id='runtime.revision_conflict',
    version='v1',
    trigger_source='repository',
    outcome_codes=frozenset({'revision_conflict'}),
    preservation='authoritative_records_only',
    claim_effect='reload_authoritative_state',
    decision_code='reload_authoritative_state',
    continuation='runtime.fail_safe',
    retry_mode='reload_authoritative',
    responsibility='system',
    authoritative_records=frozenset({'claim', 'session', 'audit'}),
    required_actions=('claim.reload', 'audit.append'),
    claimant_projection=(
        'Your Claim changed while this step was being processed. The latest state must be reloaded.'
    ),
    staff_projection=(
        'Discard the stale proposal and recompute from the current authoritative revision.'
    ),
    resume_triggers=frozenset({'authoritative_state_reloaded'}),
    resume_entrypoint='reload_authoritative_state',
    audit_event_type='action.failed',
)


EXTERNAL_NOT_SUBMITTED_RETRYABLE_RULE = RecoveryRule(
    rule_id='external.not_submitted_retryable',
    version='v1',
    trigger_source='external',
    outcome_codes=frozenset({'retryable_failure'}),
    delivery_states=frozenset({'not_submitted'}),
    preservation='external_operation_and_delivery_evidence',
    claim_effect='existing_authority_only',
    decision_code='retry_same_operation',
    continuation='runtime.wait_for_user',
    retry_mode='same_operation',
    responsibility='claimant',
    requires_operation_identity=True,
    authoritative_records=frozenset({'claim', 'external_task', 'audit'}),
    required_actions=('external.retry_same_operation', 'audit.append'),
    claimant_projection=(
        'The request was not submitted. You can retry the same request safely.'
    ),
    staff_projection='Retry is permitted only under the existing external operation identity.',
    resume_triggers=frozenset({'claimant_retry', 'staff_retry'}),
    resume_entrypoint='external_retry',
    audit_event_type='action.failed',
)


EXTERNAL_SUBMITTED_UNKNOWN_RULE = RecoveryRule(
    rule_id='external.submitted_unknown',
    version='v1',
    trigger_source='external',
    outcome_codes=frozenset({'unknown_outcome'}),
    delivery_states=frozenset({'submitted', 'unknown'}),
    preservation='external_operation_and_delivery_evidence',
    claim_effect='existing_authority_only',
    decision_code='reconcile_existing_operation',
    continuation='runtime.wait_for_external',
    retry_mode='reconcile_before_retry',
    responsibility='staff',
    requires_reconciliation=True,
    requires_operation_identity=True,
    work_item_kind='external',
    blocks_action='external.retry',
    authoritative_records=frozenset(
        {'claim', 'external_task', 'work_item', 'audit'}
    ),
    required_actions=(
        'external.reconcile',
        'work_item.ensure',
        'audit.append',
    ),
    claimant_projection=(
        'The provider may already have received the request. Northwind is '
        'checking the existing request before anything is sent again.'
    ),
    staff_projection=(
        'Reconcile the existing external operation. Blind resubmission is prohibited.'
    ),
    resume_triggers=frozenset(
        {'provider_result', 'provider_reconciled', 'staff_reconciled'}
    ),
    resume_entrypoint='external_reconcile',
    audit_event_type='action.unknown_outcome',
)


EXTERNAL_TERMINAL_FAILURE_RULE = RecoveryRule(
    rule_id='external.terminal_failure',
    version='v1',
    trigger_source='external',
    outcome_codes=frozenset({'terminal_failure'}),
    delivery_states=frozenset(
        {'not_submitted', 'submitted', 'unknown'}
    ),
    preservation='external_operation_and_delivery_evidence',
    claim_effect='existing_authority_only',
    decision_code='pause_for_review',
    continuation='runtime.pause_for_review',
    retry_mode='staff_authorised',
    responsibility='staff',
    requires_operation_identity=True,
    work_item_kind='external',
    blocks_action='external.retry',
    authoritative_records=frozenset(
        {'claim', 'external_task', 'work_item', 'audit'}
    ),
    required_actions=('work_item.ensure', 'audit.append'),
    claimant_projection=(
        'The external service could not complete this request. Northwind '
        'needs to review the next step.'
    ),
    staff_projection='The external operation ended terminally and requires authorised review.',
    resume_triggers=frozenset({'staff_decision'}),
    resume_entrypoint='staff_review',
    audit_event_type='action.failed',
)


HIGH_IMPACT_REVIEW_RULE = RecoveryRule(
    rule_id='runtime.high_impact_review_required',
    version='v1',
    trigger_source='human',
    outcome_codes=frozenset({'high_impact_review_required'}),
    preservation='review_request_and_evidence',
    claim_effect='existing_authority_only',
    decision_code='pause_for_review',
    continuation='runtime.pause_for_review',
    retry_mode='staff_authorised',
    responsibility='staff',
    blocks_action='high_impact_action',
    authoritative_records=frozenset(
        {'claim', 'handoff', 'audit'}
    ),
    required_actions=(
        'handoff.ensure',
        'audit.append',
    ),
    claimant_projection=(
        'This step needs authorised staff review before it can continue.'
    ),
    staff_projection='Review the proposed high-impact action and its supporting evidence.',
    resume_triggers=frozenset({'staff_approved', 'staff_rejected'}),
    resume_entrypoint='staff_review',
    audit_event_type='action.prepared',
)


P17_FOLLOW_UP_DUE_RULE = RecoveryRule(
    rule_id='incomplete_claim_follow_up.due',
    version=INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION,
    trigger_source='timer',
    outcome_codes=frozenset({'follow_up_due'}),
    preservation='follow_up_obligation_and_operation_history',
    claim_effect='existing_authority_only',
    decision_code='execute_follow_up',
    continuation='runtime.wait_for_user',
    retry_mode='scheduled_policy',
    max_auto_retry=INCOMPLETE_CLAIM_FOLLOW_UP_MAX_AUTO_ATTEMPTS,
    responsibility='system',
    authoritative_records=frozenset(
        {'claim', 'session', 'follow_up', 'audit'}
    ),
    required_actions=('follow_up.execute', 'audit.append'),
    claimant_projection='Your incomplete Claim can still be resumed.',
    staff_projection='The published P17 follow-up obligation is due.',
    resume_triggers=frozenset({'claimant_resumed', 'next_policy_due'}),
    resume_entrypoint='follow_up_worker',
    audit_event_type='action.completed',
)


P17_CONTACT_WITHDRAWAL_RULE = RecoveryRule(
    rule_id='incomplete_claim_follow_up.contact_withdrawal',
    version=INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION,
    trigger_source='human',
    outcome_codes=frozenset({'contact_authority_withdrawn'}),
    preservation='follow_up_obligation_and_operation_history',
    claim_effect='existing_authority_only',
    decision_code='block_follow_up',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='claimant',
    authoritative_records=frozenset(
        {'claim', 'session', 'follow_up', 'audit'}
    ),
    required_actions=('follow_up.block', 'audit.append'),
    claimant_projection='Automatic follow-up contact is no longer authorised.',
    staff_projection='The recovery obligation remains open but automatic contact is blocked.',
    resume_entrypoint='start_session',
    audit_event_type='permission.rejected',
)


P17_ATTEMPT_EXHAUSTION_RULE = RecoveryRule(
    rule_id='incomplete_claim_follow_up.attempt_exhaustion',
    version=INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION,
    trigger_source='timer',
    outcome_codes=frozenset({'attempt_limit_reached'}),
    preservation='follow_up_obligation_and_operation_history',
    claim_effect='existing_authority_only',
    decision_code='block_follow_up',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='claimant',
    authoritative_records=frozenset(
        {'claim', 'session', 'follow_up', 'audit'}
    ),
    required_actions=('follow_up.block', 'audit.append'),
    claimant_projection='Automatic follow-up has stopped, but the Claim may still be resumed.',
    staff_projection='Automatic contact attempts are exhausted; the Claim is not abandoned.',
    resume_triggers=frozenset({'claimant_resumed', 'staff_abandoned'}),
    resume_entrypoint='start_session',
    audit_event_type='action.completed',
)


P17_RECOVERY_EXPIRY_RULE = RecoveryRule(
    rule_id='incomplete_claim_follow_up.recovery_expiry',
    version=INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION,
    trigger_source='timer',
    outcome_codes=frozenset({'recovery_expired'}),
    preservation='follow_up_obligation_and_operation_history',
    claim_effect='terminal_transition_via_existing_contract',
    decision_code='expire_recovery',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='system',
    authoritative_records=frozenset(
        {'claim', 'session', 'follow_up', 'audit'}
    ),
    required_actions=('claim.expire', 'audit.append'),
    claimant_projection='This recovery window has expired.',
    staff_projection='Recovery expiry must use the existing terminal-disposition contract.',
    resume_triggers=frozenset({'claim_reopened'}),
    resume_entrypoint='claim.reopen',
    audit_event_type='action.completed',
)


_PUBLISHED_RULES = (
    LEGACY_CLAIMANT_TURN_MODEL_FAILURE_RULE,
    MODEL_TIMEOUT_RULE,
    MODEL_INVALID_RESPONSE_RULE,
    MODEL_RATE_LIMIT_RULE,
    MODEL_PROVIDER_RETRYABLE_RULE,
    MODEL_TERMINAL_DEPENDENCY_RULE,
    MODEL_PROVIDER_TERMINAL_RULE,
    TOOL_UNAVAILABLE_NON_BLOCKING_RULE,
    TOOL_UNAVAILABLE_BLOCKING_RULE,
    RETRIEVAL_UNAVAILABLE_NON_BLOCKING_RULE,
    RETRIEVAL_UNAVAILABLE_BLOCKING_RULE,
    REVISION_CONFLICT_RULE,
    EXTERNAL_NOT_SUBMITTED_RETRYABLE_RULE,
    EXTERNAL_SUBMITTED_UNKNOWN_RULE,
    EXTERNAL_TERMINAL_FAILURE_RULE,
    HIGH_IMPACT_REVIEW_RULE,
    P17_FOLLOW_UP_DUE_RULE,
    P17_CONTACT_WITHDRAWAL_RULE,
    P17_ATTEMPT_EXHAUSTION_RULE,
    P17_RECOVERY_EXPIRY_RULE,
)

RECOVERY_RULES = MappingProxyType(
    {rule.rule_id: rule for rule in _PUBLISHED_RULES}
)

if len(RECOVERY_RULES) != len(_PUBLISHED_RULES):
    raise RuntimeError('Recovery policy rule identifiers must be unique.')


def classify_recovery(trigger: RecoveryTrigger) -> RecoveryRule:
    """Return exactly one published rule or fail closed."""

    matches = [
        rule
        for rule in RECOVERY_RULES.values()
        if rule.matches(trigger)
    ]

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        raise AmbiguousRecoveryTrigger(
            'Multiple recovery policies match '
            f'{trigger.source}:{trigger.outcome_code}.'
        )

    raise UnknownRecoveryTrigger(
        f'No recovery policy is registered for '
        f'{trigger.source}:{trigger.outcome_code}.'
    )


def preservation_requirements(rule: RecoveryRule) -> str:
    return rule.preservation


def retry_decision(rule: RecoveryRule, trigger: str) -> bool:
    if rule.retry_mode == 'none':
        return False
    return trigger in rule.resume_triggers


def resume_entrypoint(rule: RecoveryRule) -> str:
    return rule.resume_entrypoint


def claimant_recovery_projection(
    rule_id: str | None,
) -> ClaimantTurnRecovery | None:
    """Project only claimant message-turn recovery rules.

    Other recovery classes use their existing subsystem projections.
    """

    rule = RECOVERY_RULES.get(rule_id or '')

    if (
        rule is None
        or rule.trigger_source != 'model'
        or rule.continuation != 'runtime.fail_safe'
        or rule.resume_entrypoint != 'submit_message'
    ):
        return None

    return ClaimantTurnRecovery(
        rule_id=rule.rule_id,
        continuation='runtime.fail_safe',
        claimant_projection=rule.claimant_projection,
        resume_triggers=sorted(rule.resume_triggers),
        resume_entrypoint='submit_message',
    )


def recovery_policy_manifest() -> dict[str, object]:
    """Return a deterministic machine-readable registry projection."""

    rules: list[dict[str, object]] = []

    for rule in sorted(
        RECOVERY_RULES.values(),
        key=lambda item: (item.rule_id, item.version),
    ):
        payload = rule.model_dump(mode='json')

        for key in (
            'outcome_codes',
            'delivery_states',
            'authoritative_records',
            'resume_triggers',
        ):
            value = payload.get(key)
            if isinstance(value, list):
                payload[key] = sorted(value)

        rules.append(payload)

    return {
        'registry_version': RECOVERY_POLICY_REGISTRY_VERSION,
        'rules': rules,
    }
