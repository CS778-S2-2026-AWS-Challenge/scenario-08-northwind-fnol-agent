"""Provider-neutral immutable Recovery Policy Registry.

The registry maps normalised recovery events to actions over existing
authoritative records.  It is not a mutable RecoveryInstance and does not
replace Claim, Session, ExternalTask, RuntimeWorkItem, Handoff, FollowUp or
Audit authority.
"""

from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from backend.domain.model_gateway import ModelGatewayErrorCode
from backend.domain.models import ClaimantTurnRecovery, ContractModel

RECOVERY_POLICY_REGISTRY_VERSION = '2026-09-28.1'

INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_ID = 'incomplete_claim_follow_up'
INCOMPLETE_CLAIM_FOLLOW_UP_POLICY_VERSION = 1
INCOMPLETE_CLAIM_FOLLOW_UP_REGISTRY_VERSION = 'v1'
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
    'retention_eligible',
    'retention_hold',
    'retention_reconcile',
    'deny_access',
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
    'retention_operation',
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
    'retention.execute',
    'retention.reconcile',
    'access.deny',
]

RecoveryWorkItemKind = Literal[
    'question',
    'confirmation',
    'evidence',
    'professional_review',
    'external',
    'system',
]


RecoveryResponsibility = Literal['claimant', 'staff', 'system', 'external']
RuntimeDirective = Literal[
    'runtime.continue',
    'runtime.wait_for_user',
    'runtime.wait_for_external',
    'runtime.pause_for_review',
    'runtime.fail_safe',
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
    """Normalised trigger presented to the immutable policy registry."""

    source: RecoverySource
    outcome_code: str = Field(min_length=1, max_length=120)

    # New code should use delivery_state.  delivery_certain remains accepted so
    # historical callers/tests do not silently change meaning.
    delivery_state: RecoveryDeliveryState | None = None
    delivery_certain: bool | None = None

    retryable: bool | None = None
    blocking: bool | None = None
    side_effect_may_have_happened: bool = False

    @model_validator(mode='after')
    def validate_delivery_coordinates(self) -> 'RecoveryTrigger':
        if self.delivery_state is None or self.delivery_certain is None:
            return self

        if self.delivery_certain is True and self.delivery_state != 'submitted':
            raise ValueError('delivery_certain=true requires delivery_state=submitted.')

        if self.delivery_certain is False and self.delivery_state != 'not_submitted':
            raise ValueError('delivery_certain=false requires delivery_state=not_submitted.')

        return self

    def resolved_delivery_state(self) -> RecoveryDeliveryState:
        if self.source == 'external' and self.side_effect_may_have_happened:
            return 'unknown'
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

    policy_id: str = Field(default='', max_length=120)
    rule_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=30)

    trigger_source: RecoverySource
    outcome_codes: frozenset[str]
    delivery_states: frozenset[RecoveryDeliveryState] = frozenset({'not_applicable'})
    retryable: bool | None = None
    blocking: bool | None = None

    preservation: str = Field(min_length=1, max_length=240)

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

    audit_event_type: str
    retry_interval_seconds: int | None = Field(default=None, ge=1)
    deadline_seconds: int | None = Field(default=None, ge=1)
    permitted_events: frozenset[str] = frozenset()
    handoff_required: bool = False

    @property
    def reconciliation_required(self) -> bool:
        return self.requires_reconciliation

    @model_validator(mode='after')
    def validate_policy_contract(self) -> 'RecoveryRule':
        if not self.policy_id:
            coordinates = {
                'claimant_turn.model_timeout': 'recovery.model_timeout',
                'claimant_turn.model_invalid_response': 'recovery.model_malformed_response',
                'runtime.revision_conflict': 'recovery.revision_conflict',
                'external.not_submitted_retryable': 'recovery.external_not_submitted_retryable',
                'external.submitted_unknown': 'recovery.external_submitted_unknown',
                'external.terminal_failure': 'recovery.external_terminal_failure',
                'runtime.high_impact_review_required': 'recovery.high_impact_review_required',
                'incomplete_claim_follow_up.due': 'incomplete_claim_follow_up',
                'incomplete_claim_follow_up.contact_withdrawal': 'recovery.contact_withdrawal',
                'incomplete_claim_follow_up.attempt_exhaustion': 'recovery.attempt_exhaustion',
                'incomplete_claim_follow_up.recovery_expiry': 'recovery.incomplete_claim_expiry',
                'runtime.tool_unavailable.blocking': 'recovery.tool_unavailable',
                'runtime.retrieval_unavailable.blocking': 'recovery.retrieval_unavailable',
            }
            object.__setattr__(self, 'policy_id', coordinates.get(self.rule_id, self.rule_id))
        if not self.permitted_events:
            object.__setattr__(
                self, 'permitted_events', self.resume_triggers or frozenset(self.outcome_codes)
            )
        if not self.outcome_codes:
            raise ValueError('A recovery rule needs at least one outcome code.')

        if not self.delivery_states:
            raise ValueError('A recovery rule needs a delivery-state matcher.')

        if self.requires_reconciliation and self.retry_mode != 'reconcile_before_retry':
            raise ValueError('Reconciliation-required rules must use reconcile_before_retry.')

        if self.retry_mode == 'reconcile_before_retry' and not self.requires_reconciliation:
            raise ValueError('reconcile_before_retry must explicitly require reconciliation.')

        if self.max_auto_retry > 0 and self.retry_mode not in {
            'bounded_auto',
            'scheduled_policy',
        }:
            raise ValueError(
                'Automatic retry limits are valid only for bounded_auto or scheduled_policy rules.'
            )

        if self.retry_mode == 'none' and self.max_auto_retry != 0:
            raise ValueError('A no-retry rule cannot carry an automatic retry limit.')

        if self.requires_operation_identity and 'external_task' not in self.authoritative_records:
            raise ValueError('Operation-identity rules must retain ExternalTask authority.')

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


class RecoverySnapshot(ContractModel):
    """Authoritative facts supplied to the pure reducer by an orchestration caller."""

    claim_revision: int = Field(ge=1)
    follow_up_status: Literal['pending', 'blocked', 'resolved'] | None = None
    follow_up_attempt_count: int = Field(default=0, ge=0)
    contact_authorised: bool | None = None
    due_at: datetime | None = None
    deadline_at: datetime | None = None
    terminal: bool = False
    external_operation_state: (
        Literal[
            'not_submitted',
            'submitted_unknown',
            'terminal_failure',
            'verified',
        ]
        | None
    ) = None
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
    blocked_reason: (
        Literal[
            'contact_not_authorised',
            'attempt_limit_reached',
            'policy_binding_invalid',
            'source_state_inconsistent',
        ]
        | None
    ) = None
    resolution_code: (
        Literal[
            'claimant_resumed',
            'recovery_expired',
            'staff_abandoned',
            'authorised_closure',
        ]
        | None
    ) = None
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


class UnknownRecoveryTransition(ValueError):
    """An event is unavailable under the immutable policy contract."""


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
        'Sorry, something tripped me up on my side. Your message is saved, so please send it again.'
    ),
    resume_triggers=frozenset({'claimant_reply', 'explicit_retry_request'}),
    resume_entrypoint='submit_message',
    audit_event_type='AGENT_TURN_RECOVERY',
)


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
        "Sorry, that took me too long. Your message is saved; send it again and I'll pick it up."
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
        "I couldn't put together a proper answer that time. Your message is saved, so please "
        'try sending it again.'
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
        "A lot of people are reporting right now, so I'm a little behind. Your message is "
        'saved; try again in a moment.'
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
        'I lost my connection for a moment. Your message is saved, so please send it again.'
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
    authoritative_records=frozenset({'message', 'claim', 'audit'}),
    required_actions=(
        'message.preserve_checkpoint',
        'claim.preserve_revision',
        'audit.append',
    ),
    claimant_projection=(
        "I can't carry on with this step right now. Your message is saved; please come back "
        'to it a little later.'
    ),
    staff_projection=('The model dependency cannot safely continue without system remediation.'),
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
    authoritative_records=frozenset({'message', 'claim', 'audit'}),
    required_actions=(
        'message.preserve_checkpoint',
        'claim.preserve_revision',
        'audit.append',
    ),
    claimant_projection=(
        'My assistant service is down at the moment. Your message is saved; please come back '
        'to it a little later.'
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
        "One of my helper tools isn't available right now, so I'll carry on without it."
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
        "A tool I need for this step isn't available right now. Your details are saved; "
        'please try again a little later.'
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
        "I can't look up some background information right now, so I'll carry on with what "
        "you've told me."
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
        "I can't look up the information this step needs right now. Your details are saved; "
        'please try again a little later.'
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
        'Your claim was updated somewhere else while I was working. Refresh to see the latest '
        'version, then carry on.'
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
        "That request didn't go through and nothing was sent. You can safely try it again."
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
    authoritative_records=frozenset({'claim', 'external_task', 'work_item', 'audit'}),
    required_actions=(
        'external.reconcile',
        'work_item.ensure',
        'audit.append',
    ),
    claimant_projection=(
        "That request may already have reached the service. We're checking before sending "
        'anything again, so nothing is doubled up.'
    ),
    staff_projection=(
        'Reconcile the existing external operation. Blind resubmission is prohibited.'
    ),
    resume_triggers=frozenset(
        {
            'provider_result',
            'provider_reconciled',
            'staff_reconciled',
            'scheduled_reconciliation',
            'staff_action',
        }
    ),
    resume_entrypoint='external_reconcile',
    audit_event_type='action.unknown_outcome',
)


EXTERNAL_TERMINAL_FAILURE_RULE = RecoveryRule(
    rule_id='external.terminal_failure',
    version='v1',
    trigger_source='external',
    outcome_codes=frozenset({'terminal_failure'}),
    delivery_states=frozenset({'not_submitted', 'submitted', 'unknown'}),
    preservation='external_operation_and_delivery_evidence',
    claim_effect='existing_authority_only',
    decision_code='pause_for_review',
    continuation='runtime.pause_for_review',
    retry_mode='staff_authorised',
    responsibility='staff',
    requires_operation_identity=True,
    work_item_kind='external',
    blocks_action='external.retry',
    authoritative_records=frozenset({'claim', 'external_task', 'work_item', 'audit'}),
    required_actions=('work_item.ensure', 'audit.append'),
    claimant_projection=(
        "The service couldn't complete that request. Someone from the claims team will look "
        'at what to do next.'
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
    authoritative_records=frozenset({'claim', 'handoff', 'audit'}),
    required_actions=(
        'handoff.ensure',
        'audit.append',
    ),
    claimant_projection=(
        'This step needs a member of the claims team to check it before it goes ahead.'
    ),
    staff_projection='Review the proposed high-impact action and its supporting evidence.',
    resume_triggers=frozenset({'staff_approved', 'staff_rejected'}),
    resume_entrypoint='staff_review',
    audit_event_type='action.prepared',
)


P17_FOLLOW_UP_DUE_RULE = RecoveryRule(
    rule_id='incomplete_claim_follow_up.due',
    version=INCOMPLETE_CLAIM_FOLLOW_UP_REGISTRY_VERSION,
    trigger_source='timer',
    outcome_codes=frozenset({'follow_up_due'}),
    preservation='follow_up_obligation_and_operation_history',
    claim_effect='existing_authority_only',
    decision_code='execute_follow_up',
    continuation='runtime.wait_for_user',
    retry_mode='scheduled_policy',
    max_auto_retry=INCOMPLETE_CLAIM_FOLLOW_UP_MAX_AUTO_ATTEMPTS,
    retry_interval_seconds=86400,
    deadline_seconds=604800,
    permitted_events=frozenset(
        {
            'follow_up_due',
            'follow_up_committed_no_response',
            'claimant_resume',
            'contact_withdrawn',
            'recovery_deadline',
        }
    ),
    responsibility='system',
    authoritative_records=frozenset({'claim', 'session', 'follow_up', 'audit'}),
    required_actions=('follow_up.execute', 'audit.append'),
    claimant_projection=(
        "Your claim is still saved. You can pick up where you left off whenever you're ready."
    ),
    staff_projection='The published P17 follow-up obligation is due.',
    resume_triggers=frozenset({'claimant_resumed', 'next_policy_due'}),
    resume_entrypoint='follow_up_worker',
    audit_event_type='action.completed',
)


P17_CONTACT_WITHDRAWAL_RULE = RecoveryRule(
    rule_id='incomplete_claim_follow_up.contact_withdrawal',
    version=INCOMPLETE_CLAIM_FOLLOW_UP_REGISTRY_VERSION,
    trigger_source='human',
    outcome_codes=frozenset({'contact_authority_withdrawn', 'contact_withdrawn'}),
    preservation='follow_up_obligation_and_operation_history',
    claim_effect='existing_authority_only',
    decision_code='block_follow_up',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='claimant',
    authoritative_records=frozenset({'claim', 'session', 'follow_up', 'audit'}),
    required_actions=('follow_up.block', 'audit.append'),
    claimant_projection=("We won't send you any more reminders about this claim."),
    staff_projection='The recovery obligation remains open but automatic contact is blocked.',
    resume_entrypoint='start_session',
    audit_event_type='permission.rejected',
)


P17_ATTEMPT_EXHAUSTION_RULE = RecoveryRule(
    rule_id='incomplete_claim_follow_up.attempt_exhaustion',
    version=INCOMPLETE_CLAIM_FOLLOW_UP_REGISTRY_VERSION,
    trigger_source='timer',
    outcome_codes=frozenset({'attempt_limit_reached'}),
    preservation='follow_up_obligation_and_operation_history',
    claim_effect='existing_authority_only',
    decision_code='block_follow_up',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='claimant',
    authoritative_records=frozenset({'claim', 'session', 'follow_up', 'audit'}),
    required_actions=('follow_up.block', 'audit.append'),
    claimant_projection=(
        "We've stopped sending reminders, but your claim is still saved and you can come back "
        'to it.'
    ),
    staff_projection='Automatic contact attempts are exhausted; the Claim is not abandoned.',
    resume_triggers=frozenset({'claimant_resumed', 'staff_abandoned'}),
    resume_entrypoint='start_session',
    audit_event_type='action.completed',
)


P17_RECOVERY_EXPIRY_RULE = RecoveryRule(
    rule_id='incomplete_claim_follow_up.recovery_expiry',
    version=INCOMPLETE_CLAIM_FOLLOW_UP_REGISTRY_VERSION,
    trigger_source='timer',
    outcome_codes=frozenset({'recovery_expired'}),
    preservation='follow_up_obligation_and_operation_history',
    claim_effect='terminal_transition_via_existing_contract',
    decision_code='expire_recovery',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='system',
    authoritative_records=frozenset({'claim', 'session', 'follow_up', 'audit'}),
    required_actions=('claim.expire', 'audit.append'),
    claimant_projection=(
        'This unfinished claim has expired. Please start a new report if you still need to claim.'
    ),
    staff_projection='Recovery expiry must use the existing terminal-disposition contract.',
    resume_triggers=frozenset({'claim_reopened'}),
    resume_entrypoint='claim.reopen',
    audit_event_type='action.completed',
)


def _retention_rule(
    *,
    policy_id: str,
    trigger_source: RecoverySource,
    outcome_codes: frozenset[str],
    preservation: str,
    continuation: RecoveryContinuation,
    retry_mode: str,
    responsibility: str,
    claimant_projection: str,
    permitted_events: frozenset[str],
    resume_entrypoint: str,
    **metadata: object,
) -> RecoveryRule:
    retry = {
        'staff_decision': 'staff_authorised',
        'reconcile_before_continue': 'reconcile_before_retry',
    }.get(retry_mode, retry_mode)
    decision = {
        'retention.eligible': 'retention_eligible',
        'retention.hold': 'retention_hold',
        'retention.reconciliation_required': 'retention_reconcile',
        'retention.old_session_denied': 'deny_access',
    }[policy_id]
    payload: dict[str, object] = dict(metadata)
    payload.pop('reconciliation_required', None)
    payload.update(
        policy_id=policy_id,
        rule_id=policy_id,
        version='v1',
        trigger_source=trigger_source,
        outcome_codes=outcome_codes,
        preservation=preservation,
        continuation=continuation,
        retry_mode=retry,
        responsibility=responsibility,
        claimant_projection=claimant_projection,
        permitted_events=permitted_events,
        resume_entrypoint=resume_entrypoint,
        decision_code=decision,
        claim_effect='existing_authority_only',
        requires_reconciliation=retry == 'reconcile_before_retry',
        authoritative_records=frozenset({'claim', 'session', 'retention_operation', 'audit'}),
        required_actions=('audit.append',),
        audit_event_type=metadata.get('audit_event_type', 'action.completed'),
    )
    return RecoveryRule.model_validate(payload)


RETENTION_ELIGIBLE_RULE = _retention_rule(
    policy_id='retention.eligible',
    trigger_source='retention',
    outcome_codes=frozenset({'eligible'}),
    preservation='source_expiry_terminal_ref_policy_coordinate_claim_revision_and_hold_evidence',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='system',
    work_item_kind='system',
    claimant_projection=('This earlier claim can no longer be opened from this link.'),
    staff_projection='Retention is eligible only from the authoritative expiry/terminal source.',
    permitted_events=frozenset({'retention_execute', 'retention_hold'}),
    resume_entrypoint='retention_worker',
    audit_event_type='RETENTION_ELIGIBLE',
)

RETENTION_HOLD_RULE = _retention_rule(
    policy_id='retention.hold',
    trigger_source='retention',
    outcome_codes=frozenset({'hold'}),
    preservation='retention_hold_authority_reason_source_and_release_condition',
    continuation='runtime.fail_safe',
    retry_mode='staff_decision',
    responsibility='staff',
    work_item_kind='system',
    claimant_projection=("This claim can't be opened from this link right now."),
    staff_projection='A source-linked retention hold blocks destructive cleanup.',
    permitted_events=frozenset({'retention_hold_released'}),
    resume_entrypoint='retention_worker',
    audit_event_type='RETENTION_HELD',
)

RETENTION_FAILURE_RULE = _retention_rule(
    policy_id='retention.reconciliation_required',
    trigger_source='retention',
    outcome_codes=frozenset({'failed', 'unknown'}),
    preservation='retention_operation_targets_completed_steps_failed_steps_and_diagnostics',
    continuation='runtime.fail_safe',
    retry_mode='reconcile_before_continue',
    reconciliation_required=True,
    responsibility='system',
    work_item_kind='system',
    claimant_projection=(
        "We're finishing some record keeping on this claim, so it can't be opened from this "
        'link yet.'
    ),
    staff_projection='Retention is incomplete; reconcile and retry only unfinished steps.',
    permitted_events=frozenset({'scheduled_reconciliation', 'staff_action'}),
    resume_entrypoint='retention_reconcile',
    audit_event_type='RETENTION_RECONCILIATION_REQUIRED',
)

OLD_SESSION_DENIED_RULE = _retention_rule(
    policy_id='retention.old_session_denied',
    trigger_source='retention',
    outcome_codes=frozenset({'old_session_denied'}),
    preservation='retention_access_closure_tombstone_and_minimum_audit_evidence',
    continuation='runtime.fail_safe',
    retry_mode='none',
    responsibility='system',
    claimant_projection=('This link has expired. Please sign in to see your claims.'),
    staff_projection='Retention access closure denied the stale session or recovery credential.',
    permitted_events=frozenset({'access_denied'}),
    resume_entrypoint='none',
    audit_event_type='RETENTION_ACCESS_DENIED',
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
    RETENTION_ELIGIBLE_RULE,
    RETENTION_HOLD_RULE,
    RETENTION_FAILURE_RULE,
    OLD_SESSION_DENIED_RULE,
)

RECOVERY_RULES = MappingProxyType({rule.rule_id: rule for rule in _PUBLISHED_RULES})

if len(RECOVERY_RULES) != len(_PUBLISHED_RULES):
    raise RuntimeError('Recovery policy rule identifiers must be unique.')


# Stable backend symbols resolve to the same published rule objects.
INCOMPLETE_CLAIM_FOLLOW_UP_RULE = P17_FOLLOW_UP_DUE_RULE
EXTERNAL_UNKNOWN_RULE = EXTERNAL_SUBMITTED_UNKNOWN_RULE
EXTERNAL_NOT_SUBMITTED_RULE = EXTERNAL_NOT_SUBMITTED_RETRYABLE_RULE
EXTERNAL_TERMINAL_RULE = EXTERNAL_TERMINAL_FAILURE_RULE
MODEL_MALFORMED_RULE = MODEL_INVALID_RESPONSE_RULE
TOOL_UNAVAILABLE_RULE = TOOL_UNAVAILABLE_BLOCKING_RULE
RETRIEVAL_UNAVAILABLE_RULE = RETRIEVAL_UNAVAILABLE_BLOCKING_RULE
CONTACT_WITHDRAWAL_RULE = P17_CONTACT_WITHDRAWAL_RULE
ATTEMPT_EXHAUSTION_RULE = P17_ATTEMPT_EXHAUSTION_RULE
RECOVERY_EXPIRY_RULE = P17_RECOVERY_EXPIRY_RULE


def recovery_policy(policy_id: str, version: str = 'v1') -> RecoveryRule:
    matches = [
        rule
        for rule in RECOVERY_RULES.values()
        if rule.policy_id == policy_id and rule.version == version
    ]
    if len(matches) != 1:
        raise UnknownRecoveryTrigger(f'Unknown recovery policy coordinate {policy_id}.{version}.')
    return matches[0]


def reduce_recovery(
    policy: RecoveryRule,
    recovery_state: RecoverySnapshot,
    incoming_event: RecoveryEvent,
    authoritative_snapshot: RecoverySnapshot,
    now: datetime,
) -> RecoveryTransition:
    """Compatibility entrypoint to the canonical pure recovery module."""
    from backend.domain.recovery import reduce_lifecycle_recovery

    return reduce_lifecycle_recovery(
        policy, recovery_state, incoming_event, authoritative_snapshot, now
    )


def classify_recovery(trigger: RecoveryTrigger) -> RecoveryRule:
    """Return exactly one published rule or fail closed."""

    matches = [rule for rule in RECOVERY_RULES.values() if rule.matches(trigger)]

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        raise AmbiguousRecoveryTrigger(
            f'Multiple recovery policies match {trigger.source}:{trigger.outcome_code}.'
        )

    raise UnknownRecoveryTrigger(
        f'No recovery policy is registered for {trigger.source}:{trigger.outcome_code}.'
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
            'permitted_events',
        ):
            value = payload.get(key)
            if isinstance(value, list):
                payload[key] = sorted(value)

        rules.append(payload)

    return {
        'registry_version': RECOVERY_POLICY_REGISTRY_VERSION,
        'rules': rules,
        'policies': rules,
    }
