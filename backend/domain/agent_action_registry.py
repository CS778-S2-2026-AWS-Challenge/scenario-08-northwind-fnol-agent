"""Provider-neutral registry for the target Agent action contract.

The registry is deliberately separate from ``AgentAction``.  The latter is the
current HTTP compatibility enum; this module defines the namespaced target
vocabulary that Runtime can validate before it executes anything.
"""

from collections.abc import Iterable, Mapping
from enum import Enum
from types import MappingProxyType

from pydantic import ConfigDict, Field, model_validator

from backend.domain.models import ContractModel


class ActionNamespace(str, Enum):
    CONVERSATION = 'conversation'
    CLAIM = 'claim'
    HUMAN = 'human'
    EXTERNAL = 'external'
    RUNTIME = 'runtime'


class ActionAuthority(str, Enum):
    MODEL_PROPOSAL = 'model_proposal'
    RUNTIME_VALIDATED = 'runtime_validated'
    STAFF_OR_RULE_REQUIRED = 'staff_or_rule_required'


class ActionStateEffect(str, Enum):
    NONE = 'none'
    CLAIM_PROPOSAL = 'claim_proposal'
    CLAIM_MUTATION = 'claim_mutation'
    HANDOFF = 'handoff'
    EXTERNAL_SIDE_EFFECT = 'external_side_effect'
    RUNTIME_CONTROL = 'runtime_control'


class ActionVisibility(str, Enum):
    CLAIMANT = 'claimant'
    STAFF = 'staff'
    INTERNAL = 'internal'


class AgentActionContract(ContractModel):
    """The validation boundary for one registered target action."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    name: str = Field(pattern=r'^[a-z]+\.[a-z][a-z0-9_]*$')
    namespace: ActionNamespace
    purpose: str = Field(min_length=1, max_length=500)
    authority: ActionAuthority
    state_effect: ActionStateEffect
    visibility: tuple[ActionVisibility, ...] = Field(min_length=1)
    requires_confirmation: bool = False
    idempotent: bool = False
    failure_policy: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def namespace_matches_name(self) -> 'AgentActionContract':
        name_namespace = self.name.split('.', 1)[0]
        if name_namespace != self.namespace.value:
            raise ValueError('Action namespace must match the namespaced action name.')
        if self.state_effect is ActionStateEffect.EXTERNAL_SIDE_EFFECT and not self.idempotent:
            raise ValueError('External side-effect actions must be idempotent.')
        if (
            self.state_effect
            in {
                ActionStateEffect.CLAIM_MUTATION,
                ActionStateEffect.HANDOFF,
                ActionStateEffect.EXTERNAL_SIDE_EFFECT,
            }
            and self.authority is ActionAuthority.MODEL_PROPOSAL
        ):
            raise ValueError('State-changing actions cannot grant authority to the model.')
        return self


def _spec(
    name: str,
    purpose: str,
    authority: ActionAuthority,
    effect: ActionStateEffect,
    *,
    visibility: tuple[ActionVisibility, ...] = (ActionVisibility.CLAIMANT,),
    confirmation: bool = False,
    idempotent: bool = False,
) -> AgentActionContract:
    return AgentActionContract(
        name=name,
        namespace=ActionNamespace(name.split('.', 1)[0]),
        purpose=purpose,
        authority=authority,
        state_effect=effect,
        visibility=visibility,
        requires_confirmation=confirmation,
        idempotent=idempotent,
        failure_policy=(
            'Reject before side effects and preserve Claim State; expose only a bounded '
            'role-safe limitation.'
        ),
    )


def _build_registry() -> dict[str, AgentActionContract]:
    conversation = [
        ('conversation.acknowledge', 'Recognise the claimant situation.', False),
        ('conversation.answer', 'Answer a general or current-status question.', False),
        (
            'conversation.explain',
            'Explain a process, term, evidence reason, or limitation.',
            False,
        ),
        (
            'conversation.ask',
            'Ask for one item with current value for the next safe action.',
            False,
        ),
        ('conversation.clarify', 'Resolve a material ambiguity or conflict.', True),
        (
            'conversation.confirm_material',
            'Confirm a material fact, declaration, or choice.',
            True,
        ),
        (
            'conversation.summarise',
            'Summarise known facts, unresolved work, and the next step.',
            False,
        ),
        (
            'conversation.present_options',
            'Present real continuation or support options.',
            False,
        ),
        (
            'conversation.state_limitation',
            'State a bounded capability or data limitation.',
            False,
        ),
    ]
    claim = [
        ('claim.open_draft', 'Open a working claim when credible claim intent exists.', False),
        (
            'claim.propose_fact_patch',
            'Propose source-aware fact changes without applying them.',
            False,
        ),
        (
            'claim.apply_fact_patch',
            'Apply an approved revision-checked fact patch.',
            False,
        ),
        (
            'claim.correct_fact',
            'Correct a fact while retaining prior value and provenance.',
            False,
        ),
        (
            'claim.recompute_form',
            'Recalculate branches and field selection from Claim State.',
            False,
        ),
        (
            'claim.register_evidence',
            'Register evidence identity and processing state.',
            False,
        ),
        ('claim.set_evidence_state', 'Record a validated evidence lifecycle state.', False),
        ('claim.upsert_work_item', 'Create or update bounded unresolved work.', False),
        ('claim.save_progress', 'Persist draft progress and a resume point.', False),
        ('claim.resume_draft', 'Resume from the latest authoritative Claim State.', False),
        (
            'claim.prepare_creation',
            'Check whether the current creation action is ready.',
            False,
        ),
        ('claim.create', 'Create and route a formal claim through its adapter.', False),
    ]
    human = [
        ('human.offer_support', 'Offer support options when policy permits.', False),
        ('human.create_handoff', 'Create a source-preserving support handoff.', False),
        (
            'human.request_professional_review',
            'Request professional judgement for a high-impact issue.',
            False,
        ),
        (
            'human.request_approval',
            'Request authorised approval for a high-impact action.',
            False,
        ),
        ('human.record_decision', 'Record an authorised staff decision and its basis.', False),
    ]
    external = [
        ('external.discover_capability', 'Discover eligible participant capabilities.', False),
        ('external.load_requirements', 'Load requirements for a bounded request type.', False),
        (
            'external.prepare_request',
            'Prepare a reviewable request and disclosure manifest.',
            False,
        ),
        ('external.classify_request', 'Classify a request using registered values.', False),
        ('external.check_authority', 'Verify consent, permission, and disclosure scope.', False),
        ('external.submit_request', 'Submit an approved idempotent external request.', False),
        ('external.track_request', 'Track a provider request status.', False),
        (
            'external.verify_response',
            'Verify response provenance and completeness.',
            False,
        ),
        (
            'external.reconcile_response',
            'Turn a verified result into a Claim proposal.',
            False,
        ),
        ('external.retry_request', 'Retry only when an idempotent retry is safe.', False),
        (
            'external.cancel_request',
            'Cancel a request when provider and authority permit.',
            False,
        ),
        (
            'external.escalate_failure',
            'Escalate an unknown or unresolvable external result.',
            False,
        ),
    ]
    runtime = [
        ('runtime.continue', 'Continue when the next step is safe.', False),
        (
            'runtime.wait_for_user',
            'Wait for claimant information, confirmation, or choice.',
            False,
        ),
        (
            'runtime.wait_for_external',
            'Wait for an external result while unrelated work continues.',
            False,
        ),
        (
            'runtime.pause_for_review',
            'Pause a high-impact action for professional review.',
            False,
        ),
        (
            'runtime.interrupt_urgent',
            'Interrupt ordinary intake for an explicit safety signal.',
            False,
        ),
        (
            'runtime.stop_no_claim',
            'Stop claim creation when no credible claim intent exists.',
            False,
        ),
        ('runtime.fail_safe', 'Preserve progress and offer a bounded recovery path.', False),
    ]

    registry: dict[str, AgentActionContract] = {}
    for name, purpose, confirmation in conversation:
        registry[name] = _spec(
            name,
            purpose,
            ActionAuthority.RUNTIME_VALIDATED,
            ActionStateEffect.NONE,
            confirmation=confirmation,
        )
    for name, purpose, confirmation in claim:
        effect = ActionStateEffect.CLAIM_PROPOSAL
        authority = ActionAuthority.MODEL_PROPOSAL
        if name in {'claim.apply_fact_patch', 'claim.correct_fact', 'claim.create'}:
            effect = ActionStateEffect.CLAIM_MUTATION
            authority = ActionAuthority.STAFF_OR_RULE_REQUIRED
        registry[name] = _spec(name, purpose, authority, effect, confirmation=confirmation)
    for name, purpose, confirmation in human:
        effect = (
            ActionStateEffect.HANDOFF if name == 'human.create_handoff' else ActionStateEffect.NONE
        )
        authority = (
            ActionAuthority.STAFF_OR_RULE_REQUIRED
            if name in {'human.request_approval', 'human.record_decision'}
            else ActionAuthority.RUNTIME_VALIDATED
        )
        registry[name] = _spec(
            name,
            purpose,
            authority,
            effect,
            visibility=(ActionVisibility.CLAIMANT, ActionVisibility.STAFF),
            confirmation=confirmation,
        )
    for name, purpose, confirmation in external:
        is_side_effect = name in {'external.submit_request', 'external.cancel_request'}
        registry[name] = _spec(
            name,
            purpose,
            ActionAuthority.STAFF_OR_RULE_REQUIRED
            if is_side_effect
            else ActionAuthority.RUNTIME_VALIDATED,
            ActionStateEffect.EXTERNAL_SIDE_EFFECT
            if is_side_effect
            else ActionStateEffect.CLAIM_PROPOSAL,
            visibility=(ActionVisibility.STAFF, ActionVisibility.INTERNAL),
            confirmation=confirmation,
            idempotent=is_side_effect,
        )
    for name, purpose, confirmation in runtime:
        registry[name] = _spec(
            name,
            purpose,
            ActionAuthority.RUNTIME_VALIDATED,
            ActionStateEffect.RUNTIME_CONTROL,
            visibility=(ActionVisibility.INTERNAL,),
            confirmation=confirmation,
        )
    return registry


AGENT_ACTION_REGISTRY: Mapping[str, AgentActionContract] = MappingProxyType(_build_registry())


def action_contract(name: str) -> AgentActionContract:
    """Return a registered action or reject unknown model output."""

    try:
        return AGENT_ACTION_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f'Unknown Agent action: {name}.') from exc


def registered_actions(namespace: ActionNamespace | None = None) -> tuple[str, ...]:
    """Return a stable, immutable view for prompts and Runtime validation."""

    names: Iterable[str] = AGENT_ACTION_REGISTRY
    if namespace is not None:
        names = (name for name in names if name.startswith(f'{namespace.value}.'))
    return tuple(names)
