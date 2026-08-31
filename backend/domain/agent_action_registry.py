"""Provider-neutral registry for the target Agent action contract.

The registry is deliberately separate from ``AgentAction``. The latter is the
current HTTP compatibility enum; this module defines the namespaced target
vocabulary that Runtime validates before it executes anything.
"""

from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from types import MappingProxyType

from pydantic import ConfigDict, Field, model_validator

from backend.domain.models import ContractModel, WorkflowState


class ActionNamespace(str, Enum):
    CONVERSATION = 'conversation'
    CLAIM = 'claim'
    HUMAN = 'human'
    EXTERNAL = 'external'
    RUNTIME = 'runtime'


class ActionActorRole(str, Enum):
    """A role permitted to propose or request an action."""

    CLAIMANT = 'claimant'
    STAFF = 'staff'
    MODEL = 'model'
    RUNTIME = 'runtime'


class ExecutionAuthority(str, Enum):
    """Authority required before Runtime may execute an action."""

    RUNTIME_VALIDATION = 'runtime_validation'
    CLAIMANT_STAFF_OR_PUBLISHED_RULE = 'claimant_staff_or_published_rule'
    STAFF_DECISION = 'staff_decision'
    PUBLISHED_RULE = 'published_rule'
    STAFF_OR_PUBLISHED_RULE = 'staff_or_published_rule'


class ActionStateEffect(str, Enum):
    NONE = 'none'
    CLAIM_PROPOSAL = 'claim_proposal'
    CLAIM_MUTATION = 'claim_mutation'
    HANDOFF = 'handoff'
    EXTERNAL_SIDE_EFFECT = 'external_side_effect'
    RUNTIME_CONTROL = 'runtime_control'


class ActionSideEffectClass(str, Enum):
    NONE = 'none'
    INTERNAL_WRITE = 'internal_write'
    CUSTOMER_MESSAGE = 'customer_message'
    EXTERNAL_WRITE = 'external_write'
    HIGH_IMPACT = 'high_impact'


class ActionIdempotencyPolicy(str, Enum):
    NOT_REQUIRED = 'not_required'
    REQUIRED = 'required'
    RECONCILE_BEFORE_RETRY = 'reconcile_before_retry'


class ActionVisibility(str, Enum):
    CLAIMANT = 'claimant'
    STAFF = 'staff'
    INTERNAL = 'internal'


class ActionInputType(str, Enum):
    STRING = 'string'
    INTEGER = 'integer'
    BOOLEAN = 'boolean'
    OBJECT = 'object'
    ARRAY = 'array'


class ActionInputField(ContractModel):
    """One validated parameter in a registered action input schema."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    name: str = Field(pattern=r'^[a-z][a-z0-9_]*$')
    value_type: ActionInputType
    required: bool = True


class ActionInputSchema(ContractModel):
    """Closed input schema for one registered action."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    fields: tuple[ActionInputField, ...] = Field(min_length=1)
    additional_properties: bool = False

    @model_validator(mode='after')
    def _field_names_are_unique(self) -> 'ActionInputSchema':
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError('Action input field names must be unique.')
        return self


class AgentActionContract(ContractModel):
    """The immutable validation boundary for one registered target action."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    action_code: str = Field(pattern=r'^[a-z]+\.[a-z][a-z0-9_]*$')
    namespace: ActionNamespace
    version: str = Field(pattern=r'^\d+\.\d+\.\d+$')
    purpose: str = Field(min_length=1, max_length=500)
    input_schema: ActionInputSchema
    allowed_actor_roles: tuple[ActionActorRole, ...] = Field(min_length=1)
    authority_requirement: ExecutionAuthority
    allowed_lifecycle_states: tuple[WorkflowState, ...] = Field(min_length=1)
    precondition_rules: tuple[str, ...] = Field(min_length=1)
    permitted_tools: tuple[str, ...]
    side_effect_class: ActionSideEffectClass
    idempotency_policy: ActionIdempotencyPolicy
    response_obligations: tuple[str, ...] = Field(min_length=1)
    prohibited_outcomes: tuple[str, ...] = Field(min_length=1)
    state_effect: ActionStateEffect
    visibility: tuple[ActionVisibility, ...] = Field(min_length=1)
    requires_confirmation: bool = False
    failure_policy: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def _validate_contract_boundaries(self) -> 'AgentActionContract':
        name_namespace = self.action_code.split('.', 1)[0]
        if name_namespace != self.namespace.value:
            raise ValueError('Action namespace must match the namespaced action code.')
        for values, label in (
            (self.allowed_actor_roles, 'allowed actor roles'),
            (self.allowed_lifecycle_states, 'allowed lifecycle states'),
            (self.precondition_rules, 'precondition rules'),
            (self.permitted_tools, 'permitted tools'),
            (self.response_obligations, 'response obligations'),
            (self.prohibited_outcomes, 'prohibited outcomes'),
            (self.visibility, 'visibility values'),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f'Action {label} must not contain duplicates.')
        if (
            self.side_effect_class
            in {
                ActionSideEffectClass.INTERNAL_WRITE,
                ActionSideEffectClass.EXTERNAL_WRITE,
                ActionSideEffectClass.HIGH_IMPACT,
            }
            and self.idempotency_policy is ActionIdempotencyPolicy.NOT_REQUIRED
        ):
            raise ValueError('State-changing and external-write actions require idempotency.')
        if (
            self.side_effect_class is ActionSideEffectClass.EXTERNAL_WRITE
            and not self.permitted_tools
        ):
            raise ValueError('External-write actions require an allow-listed tool.')
        if (
            self.side_effect_class is ActionSideEffectClass.HIGH_IMPACT
            and self.authority_requirement
            not in {
                ExecutionAuthority.STAFF_DECISION,
                ExecutionAuthority.STAFF_OR_PUBLISHED_RULE,
            }
        ):
            raise ValueError('High-impact actions require staff or published-rule authority.')
        return self


_ALL_WORKFLOW_STATES = tuple(WorkflowState)
_MUTABLE_WORKFLOW_STATES = (
    WorkflowState.COLLECTING,
    WorkflowState.READY_FOR_NEXT,
    WorkflowState.AWAITING_EVIDENCE,
    WorkflowState.PROFESSIONAL_REVIEW,
)
_MODEL_RUNTIME_ROLES = (ActionActorRole.MODEL, ActionActorRole.RUNTIME)
_CLAIM_ROLES = (ActionActorRole.MODEL, ActionActorRole.RUNTIME, ActionActorRole.STAFF)
_HUMAN_ROLES = (
    ActionActorRole.CLAIMANT,
    ActionActorRole.MODEL,
    ActionActorRole.RUNTIME,
    ActionActorRole.STAFF,
)


def _field(
    name: str,
    value_type: ActionInputType,
    *,
    required: bool = True,
) -> ActionInputField:
    return ActionInputField(name=name, value_type=value_type, required=required)


def _schema(*fields: ActionInputField) -> ActionInputSchema:
    return ActionInputSchema(fields=fields)


def _input_schema_for(action_code: str) -> ActionInputSchema:
    if action_code == 'conversation.ask':
        return _schema(
            _field('field_code', ActionInputType.STRING),
            _field('question', ActionInputType.STRING),
        )
    if action_code == 'conversation.clarify':
        return _schema(
            _field('ambiguity_refs', ActionInputType.ARRAY),
            _field('question', ActionInputType.STRING),
        )
    if action_code == 'conversation.confirm_material':
        return _schema(
            _field('fact_refs', ActionInputType.ARRAY),
            _field('prompt', ActionInputType.STRING),
        )
    if action_code.startswith('conversation.'):
        return _schema(_field('content', ActionInputType.STRING))

    if action_code == 'claim.open_draft':
        return _schema(
            _field('claimant_id', ActionInputType.STRING),
            _field('claim_intent', ActionInputType.OBJECT),
            _field('idempotency_key', ActionInputType.STRING),
        )
    if action_code in {
        'claim.propose_fact_patch',
        'claim.apply_fact_patch',
        'claim.correct_fact',
    }:
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('fact_patches', ActionInputType.ARRAY),
            _field('expected_revision', ActionInputType.INTEGER),
        )
    if action_code == 'claim.register_evidence':
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('evidence', ActionInputType.OBJECT),
            _field('expected_revision', ActionInputType.INTEGER),
        )
    if action_code == 'claim.set_evidence_state':
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('evidence_id', ActionInputType.STRING),
            _field('evidence_state', ActionInputType.STRING),
            _field('expected_revision', ActionInputType.INTEGER),
        )
    if action_code == 'claim.upsert_work_item':
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('work_item', ActionInputType.OBJECT),
            _field('expected_revision', ActionInputType.INTEGER),
        )
    if action_code == 'claim.create':
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('expected_revision', ActionInputType.INTEGER),
            _field('authorised_decision_ref', ActionInputType.STRING),
            _field('idempotency_key', ActionInputType.STRING),
        )
    if action_code.startswith('claim.'):
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('expected_revision', ActionInputType.INTEGER, required=False),
        )

    if action_code == 'human.create_handoff':
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('reason_codes', ActionInputType.ARRAY),
            _field('handoff_packet', ActionInputType.OBJECT),
            _field('expected_revision', ActionInputType.INTEGER),
        )
    if action_code == 'human.record_decision':
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('decision', ActionInputType.OBJECT),
            _field('expected_revision', ActionInputType.INTEGER),
        )
    if action_code.startswith('human.'):
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('reason_codes', ActionInputType.ARRAY),
            _field('source_refs', ActionInputType.ARRAY, required=False),
        )

    if action_code in {'external.discover_capability', 'external.load_requirements'}:
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('request_type', ActionInputType.STRING),
        )
    if action_code == 'external.prepare_request':
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('request_type', ActionInputType.STRING),
            _field('disclosure_manifest', ActionInputType.OBJECT),
        )
    if action_code in {
        'external.submit_request',
        'external.retry_request',
        'external.cancel_request',
    }:
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('operation_id', ActionInputType.STRING),
            _field('idempotency_key', ActionInputType.STRING),
        )
    if action_code.startswith('external.'):
        return _schema(
            _field('claim_id', ActionInputType.STRING),
            _field('operation_id', ActionInputType.STRING),
            _field('result', ActionInputType.OBJECT, required=False),
        )

    return _schema(
        _field('reason_codes', ActionInputType.ARRAY),
        _field('work_item_refs', ActionInputType.ARRAY, required=False),
    )


def _spec(
    action_code: str,
    purpose: str,
    *,
    actor_roles: tuple[ActionActorRole, ...],
    authority: ExecutionAuthority,
    lifecycle_states: tuple[WorkflowState, ...],
    preconditions: tuple[str, ...],
    tools: tuple[str, ...] = (),
    side_effect: ActionSideEffectClass = ActionSideEffectClass.NONE,
    idempotency: ActionIdempotencyPolicy = ActionIdempotencyPolicy.NOT_REQUIRED,
    state_effect: ActionStateEffect = ActionStateEffect.NONE,
    visibility: tuple[ActionVisibility, ...] = (ActionVisibility.CLAIMANT,),
    confirmation: bool = False,
    response_obligations: tuple[str, ...] = (
        'State the actual outcome, material limitation, and next safe step.',
    ),
    prohibited_outcomes: tuple[str, ...] = (
        'Do not present a proposal, request, or unknown outcome as completed work.',
    ),
) -> AgentActionContract:
    return AgentActionContract(
        action_code=action_code,
        namespace=ActionNamespace(action_code.split('.', 1)[0]),
        version='1.0.0',
        purpose=purpose,
        input_schema=_input_schema_for(action_code),
        allowed_actor_roles=actor_roles,
        authority_requirement=authority,
        allowed_lifecycle_states=lifecycle_states,
        precondition_rules=preconditions,
        permitted_tools=tools,
        side_effect_class=side_effect,
        idempotency_policy=idempotency,
        response_obligations=response_obligations,
        prohibited_outcomes=prohibited_outcomes,
        state_effect=state_effect,
        visibility=visibility,
        requires_confirmation=confirmation,
        failure_policy=(
            'Reject before side effects and preserve Claim State; expose only a bounded '
            'role-safe limitation.'
        ),
    )


def _conversation_specs() -> list[AgentActionContract]:
    actions = (
        ('conversation.acknowledge', 'Recognise the claimant situation.', False),
        ('conversation.answer', 'Answer a general or current-status question.', False),
        ('conversation.explain', 'Explain a process, term, evidence reason, or limitation.', False),
        (
            'conversation.ask',
            'Ask for one item with current value for the next safe action.',
            False,
        ),
        ('conversation.clarify', 'Resolve a material ambiguity or conflict.', True),
        ('conversation.confirm_material', 'Confirm a material fact, declaration, or choice.', True),
        (
            'conversation.summarise',
            'Summarise known facts, unresolved work, and the next step.',
            False,
        ),
        ('conversation.present_options', 'Present real continuation or support options.', False),
        ('conversation.state_limitation', 'State a bounded capability or data limitation.', False),
    )
    return [
        _spec(
            code,
            purpose,
            actor_roles=_MODEL_RUNTIME_ROLES,
            authority=ExecutionAuthority.RUNTIME_VALIDATION,
            lifecycle_states=_ALL_WORKFLOW_STATES,
            preconditions=('authorised_role_projection', 'role_safe_response'),
            confirmation=confirmation,
            prohibited_outcomes=(
                'Do not change Claim State or expose staff-only or audit-only information.',
            ),
        )
        for code, purpose, confirmation in actions
    ]


def _claim_specs() -> list[AgentActionContract]:
    actions = (
        ('claim.open_draft', 'Open a working claim when credible claim intent exists.'),
        ('claim.propose_fact_patch', 'Propose source-aware fact changes without applying them.'),
        ('claim.apply_fact_patch', 'Apply an approved revision-checked fact patch.'),
        ('claim.correct_fact', 'Correct a fact while retaining prior value and provenance.'),
        ('claim.recompute_form', 'Recalculate branches and field selection from Claim State.'),
        ('claim.register_evidence', 'Register evidence identity and processing state.'),
        ('claim.set_evidence_state', 'Record a validated evidence lifecycle state.'),
        ('claim.upsert_work_item', 'Create or update bounded unresolved work.'),
        ('claim.save_progress', 'Persist draft progress and a resume point.'),
        ('claim.resume_draft', 'Resume from the latest authoritative Claim State.'),
        ('claim.prepare_creation', 'Check whether the current creation action is ready.'),
        ('claim.create', 'Create and route a formal claim through its adapter.'),
    )
    writes = {
        'claim.open_draft',
        'claim.apply_fact_patch',
        'claim.correct_fact',
        'claim.register_evidence',
        'claim.set_evidence_state',
        'claim.upsert_work_item',
        'claim.save_progress',
        'claim.create',
    }
    specs: list[AgentActionContract] = []
    for code, purpose in actions:
        is_create = code == 'claim.create'
        is_write = code in writes
        tools: tuple[str, ...] = ()
        if is_create:
            tools = ('claims_service.create_claim',)
        elif is_write:
            tools = ('claim_store.compare_and_set',)
        lifecycle_states: tuple[WorkflowState, ...] = _MUTABLE_WORKFLOW_STATES
        if code == 'claim.create':
            lifecycle_states = (WorkflowState.READY_FOR_NEXT,)
        elif code == 'claim.resume_draft':
            lifecycle_states = _MUTABLE_WORKFLOW_STATES
        preconditions: tuple[str, ...] = (
            'authorised_claim_scope',
            'current_claim_revision',
        )
        if is_create:
            preconditions = (
                'authorised_claim_scope',
                'current_claim_revision',
                'creation_required_facts_confirmed',
                'authorised_creation_decision',
            )
        specs.append(
            _spec(
                code,
                purpose,
                actor_roles=_CLAIM_ROLES,
                authority=(
                    ExecutionAuthority.STAFF_OR_PUBLISHED_RULE
                    if is_create
                    else ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE
                    if is_write
                    else ExecutionAuthority.RUNTIME_VALIDATION
                ),
                lifecycle_states=lifecycle_states,
                preconditions=preconditions,
                tools=tools,
                side_effect=(
                    ActionSideEffectClass.EXTERNAL_WRITE
                    if is_create
                    else ActionSideEffectClass.INTERNAL_WRITE
                    if is_write
                    else ActionSideEffectClass.NONE
                ),
                idempotency=(
                    ActionIdempotencyPolicy.REQUIRED
                    if is_write
                    else ActionIdempotencyPolicy.NOT_REQUIRED
                ),
                state_effect=(
                    ActionStateEffect.CLAIM_MUTATION
                    if is_write
                    else ActionStateEffect.CLAIM_PROPOSAL
                ),
                prohibited_outcomes=(
                    'Do not overwrite confirmed facts, lose provenance, or bypass revision checks.',
                    'Do not imply claim approval, coverage, liability, or fraud determination.',
                ),
            )
        )
    return specs


def _human_specs() -> list[AgentActionContract]:
    actions = (
        ('human.offer_support', 'Offer support options when policy permits.'),
        ('human.create_handoff', 'Create a source-preserving support handoff.'),
        (
            'human.request_professional_review',
            'Request professional judgement for a high-impact issue.',
        ),
        ('human.request_approval', 'Request authorised approval for a high-impact action.'),
        ('human.record_decision', 'Record an authorised staff decision and its basis.'),
    )
    writes = {
        'human.create_handoff',
        'human.request_professional_review',
        'human.request_approval',
        'human.record_decision',
    }
    specs: list[AgentActionContract] = []
    for code, purpose in actions:
        is_decision = code == 'human.record_decision'
        is_handoff = code == 'human.create_handoff'
        is_internal_request = code in {
            'human.request_professional_review',
            'human.request_approval',
        }
        tools: tuple[str, ...] = ()
        if is_handoff:
            tools = ('handoff_store.create',)
        elif code in writes:
            tools = ('claim_store.compare_and_set',)
        specs.append(
            _spec(
                code,
                purpose,
                actor_roles=_HUMAN_ROLES,
                authority=(
                    ExecutionAuthority.STAFF_DECISION
                    if is_decision
                    else ExecutionAuthority.CLAIMANT_STAFF_OR_PUBLISHED_RULE
                    if is_handoff
                    else ExecutionAuthority.RUNTIME_VALIDATION
                ),
                lifecycle_states=_ALL_WORKFLOW_STATES,
                preconditions=('authorised_claim_scope', 'source_preserving_reason'),
                tools=tools,
                side_effect=(
                    ActionSideEffectClass.HIGH_IMPACT
                    if is_decision
                    else ActionSideEffectClass.INTERNAL_WRITE
                    if code in writes
                    else ActionSideEffectClass.NONE
                ),
                idempotency=(
                    ActionIdempotencyPolicy.REQUIRED
                    if code in writes
                    else ActionIdempotencyPolicy.NOT_REQUIRED
                ),
                state_effect=(
                    ActionStateEffect.HANDOFF
                    if is_handoff
                    else ActionStateEffect.CLAIM_MUTATION
                    if code in writes
                    else ActionStateEffect.NONE
                ),
                visibility=(
                    (ActionVisibility.STAFF, ActionVisibility.INTERNAL)
                    if is_decision or is_internal_request
                    else (ActionVisibility.CLAIMANT, ActionVisibility.STAFF)
                ),
                prohibited_outcomes=(
                    'Do not expose internal signals or represent a request as an '
                    'accepted decision.',
                ),
            )
        )
    return specs


def _external_specs() -> list[AgentActionContract]:
    actions = (
        ('external.discover_capability', 'Discover eligible participant capabilities.'),
        ('external.load_requirements', 'Load requirements for a bounded request type.'),
        ('external.prepare_request', 'Prepare a reviewable request and disclosure manifest.'),
        ('external.classify_request', 'Classify a request using registered values.'),
        ('external.check_authority', 'Verify consent, permission, and disclosure scope.'),
        ('external.submit_request', 'Submit an approved idempotent external request.'),
        ('external.track_request', 'Track a provider request status.'),
        ('external.verify_response', 'Verify response provenance and completeness.'),
        ('external.reconcile_response', 'Turn a verified result into a Claim proposal.'),
        ('external.retry_request', 'Retry only after reconciling an unknown outcome.'),
        ('external.cancel_request', 'Cancel a request when provider and authority permit.'),
        ('external.escalate_failure', 'Escalate an unknown or unresolvable external result.'),
    )
    writes = {
        'external.submit_request',
        'external.retry_request',
        'external.cancel_request',
    }
    specs: list[AgentActionContract] = []
    for code, purpose in actions:
        is_write = code in writes
        is_retry = code == 'external.retry_request'
        preconditions: tuple[str, ...] = (
            'authorised_claim_scope',
            'minimum_disclosure_scope',
        )
        if is_write:
            preconditions += ('authority_and_consent_valid', 'stable_operation_identity')
        if is_retry:
            preconditions += ('unknown_outcome_reconciled', 'retry_class_allows_retry')
        specs.append(
            _spec(
                code,
                purpose,
                actor_roles=_CLAIM_ROLES,
                authority=(
                    ExecutionAuthority.STAFF_OR_PUBLISHED_RULE
                    if is_write
                    else ExecutionAuthority.RUNTIME_VALIDATION
                ),
                lifecycle_states=_ALL_WORKFLOW_STATES,
                preconditions=preconditions,
                tools=(f'external_service.{code.split(".", 1)[1]}',),
                side_effect=(
                    ActionSideEffectClass.EXTERNAL_WRITE if is_write else ActionSideEffectClass.NONE
                ),
                idempotency=(
                    ActionIdempotencyPolicy.RECONCILE_BEFORE_RETRY
                    if is_retry
                    else ActionIdempotencyPolicy.REQUIRED
                    if is_write
                    else ActionIdempotencyPolicy.NOT_REQUIRED
                ),
                state_effect=(
                    ActionStateEffect.EXTERNAL_SIDE_EFFECT
                    if is_write
                    else ActionStateEffect.CLAIM_PROPOSAL
                ),
                visibility=(ActionVisibility.STAFF, ActionVisibility.INTERNAL),
                response_obligations=(
                    'State the verified provider status, limitations, ownership, and next step.',
                ),
                prohibited_outcomes=(
                    'Do not widen disclosure, duplicate provider work, or call an '
                    'unknown outcome a failure.',
                ),
            )
        )
    return specs


def _runtime_specs() -> list[AgentActionContract]:
    actions = (
        ('runtime.continue', 'Continue when the next step is safe.'),
        ('runtime.wait_for_user', 'Wait for claimant information, confirmation, or choice.'),
        ('runtime.wait_for_external', 'Wait while unrelated safe work may continue.'),
        ('runtime.pause_for_review', 'Pause a high-impact action for professional review.'),
        ('runtime.interrupt_urgent', 'Interrupt ordinary intake for an explicit safety signal.'),
        ('runtime.stop_no_claim', 'Stop claim creation when no credible claim intent exists.'),
        ('runtime.fail_safe', 'Preserve progress and offer a bounded recovery path.'),
    )
    return [
        _spec(
            code,
            purpose,
            actor_roles=_MODEL_RUNTIME_ROLES,
            authority=(
                ExecutionAuthority.PUBLISHED_RULE
                if code == 'runtime.interrupt_urgent'
                else ExecutionAuthority.RUNTIME_VALIDATION
            ),
            lifecycle_states=_ALL_WORKFLOW_STATES,
            preconditions=('authorised_claim_scope', 'single_primary_runtime_directive'),
            state_effect=ActionStateEffect.RUNTIME_CONTROL,
            visibility=(ActionVisibility.INTERNAL,),
            prohibited_outcomes=(
                'Do not mutate Claim State or represent unexecuted work as completed.',
            ),
        )
        for code, purpose in actions
    ]


def _build_registry() -> dict[str, AgentActionContract]:
    contracts: Sequence[AgentActionContract] = (
        *_conversation_specs(),
        *_claim_specs(),
        *_human_specs(),
        *_external_specs(),
        *_runtime_specs(),
    )
    return {contract.action_code: contract for contract in contracts}


AGENT_ACTION_REGISTRY: Mapping[str, AgentActionContract] = MappingProxyType(_build_registry())


def action_contract(action_code: str) -> AgentActionContract:
    """Return the registered contract for an action code.

    Args:
        action_code: Stable namespaced action code supplied by a validated proposal.

    Returns:
        The immutable registered action contract.

    Raises:
        ValueError: The action code is not present in the published registry.
    """

    try:
        return AGENT_ACTION_REGISTRY[action_code]
    except KeyError as exc:
        raise ValueError(f'Unknown Agent action: {action_code}.') from exc


def registered_actions(namespace: ActionNamespace | None = None) -> tuple[str, ...]:
    """Return registered action codes, optionally filtered by namespace.

    Args:
        namespace: Optional namespace used to filter the registry view.

    Returns:
        A stable tuple of registered action codes in publication order.
    """

    names: Iterable[str] = AGENT_ACTION_REGISTRY
    if namespace is not None:
        names = (name for name in names if name.startswith(f'{namespace.value}.'))
    return tuple(names)
