"""Provider-neutral recovery policy contracts used by claimant Runtime turns."""

from typing import Literal

from pydantic import Field

from backend.domain.models import ContractModel


class RecoveryTrigger(ContractModel):
    source: Literal['model', 'tool', 'retrieval', 'repository', 'external', 'human']
    outcome_code: str = Field(min_length=1, max_length=120)
    delivery_certain: bool | None = None


class RecoveryRule(ContractModel):
    rule_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=30)
    trigger_source: Literal['model', 'tool', 'retrieval', 'repository', 'external', 'human']
    preservation: Literal['inbound_message_and_checkpoint']
    claim_effect: Literal['revision_unchanged_no_unapproved_write']
    continuation: Literal['runtime.fail_safe']
    retry_mode: Literal['claimant_initiated']
    max_auto_retry: int = Field(default=0, ge=0, le=1)
    responsibility: Literal['claimant', 'staff', 'system', 'external']
    claimant_projection: str = Field(min_length=1, max_length=500)
    staff_projection: str | None = Field(default=None, max_length=500)
    resume_triggers: frozenset[str] = frozenset({'claimant_reply', 'explicit_retry_request'})
    resume_entrypoint: Literal['submit_message'] = 'submit_message'
    audit_event_type: str = Field(min_length=1, max_length=120)


CLAIMANT_TURN_MODEL_FAILURE_RULE = RecoveryRule(
    rule_id='claimant_turn.model_dependency_failure',
    version='v1',
    trigger_source='model',
    preservation='inbound_message_and_checkpoint',
    claim_effect='revision_unchanged_no_unapproved_write',
    continuation='runtime.fail_safe',
    retry_mode='claimant_initiated',
    responsibility='claimant',
    claimant_projection='Your message is saved, but I could not respond just now. You can try again.',
    audit_event_type='AGENT_TURN_RECOVERY',
)

RECOVERY_RULES = {CLAIMANT_TURN_MODEL_FAILURE_RULE.rule_id: CLAIMANT_TURN_MODEL_FAILURE_RULE}


def classify_recovery(trigger: RecoveryTrigger) -> RecoveryRule:
    for rule in RECOVERY_RULES.values():
        if rule.trigger_source == trigger.source:
            return rule
    raise ValueError(f'No recovery policy is registered for {trigger.source}:{trigger.outcome_code}.')
