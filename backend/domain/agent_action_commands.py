"""Translate approved target Agent actions into bounded Claim Context commands.

The backend validates execution safety here; it does not choose Agent behaviour or
execute provider adapters.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from backend.domain.agent_action_registry import (
    ActionActorRole,
    ActionIdempotencyPolicy,
    ActionInputSchema,
    ActionInputType,
    ActionNamespace,
    ActionStateEffect,
    ActionVisibility,
    ExecutionAuthority,
    action_contract,
)
from backend.domain.models import WorkflowState


class AgentActionCommandError(ValueError):
    """An approved action cannot safely become a Claim Context command."""


class UnknownAgentActionError(AgentActionCommandError):
    """The action is outside the published Agent Action Registry."""


_CLAIM_CONTEXT_NAMESPACES = frozenset({ActionNamespace.CLAIM, ActionNamespace.HUMAN})
_CLAIM_CONTEXT_EFFECTS = frozenset(
    {
        ActionStateEffect.CLAIM_PROPOSAL,
        ActionStateEffect.CLAIM_MUTATION,
        ActionStateEffect.HANDOFF,
    }
)
_REVISIONED_EFFECTS = frozenset({ActionStateEffect.CLAIM_MUTATION, ActionStateEffect.HANDOFF})


@dataclass(frozen=True, slots=True)
class ClaimContextCommand:
    """Provider-neutral execution intent for one approved Agent action."""

    action_code: str
    contract_version: str
    payload: Mapping[str, object]
    proposer_role: ActionActorRole
    authority_requirement: ExecutionAuthority
    authority_reference: str
    workflow_state: WorkflowState
    state_effect: ActionStateEffect
    expected_revision: int | None
    idempotency_key: str | None
    idempotency_policy: ActionIdempotencyPolicy
    permitted_tools: tuple[str, ...]
    visibility: tuple[ActionVisibility, ...]
    failure_policy: str

    @property
    def claim_id(self) -> str | None:
        """Return the claim identifier carried by the command, when present.

        Returns:
            The claim identifier from the validated payload, or ``None`` for an action
            such as ``claim.open_draft`` that does not target an existing claim.
        """

        value = self.payload.get('claim_id')
        return value if isinstance(value, str) else None


def _matches_type(value: object, value_type: ActionInputType) -> bool:
    match value_type:
        case ActionInputType.STRING:
            return isinstance(value, str)
        case ActionInputType.INTEGER:
            return isinstance(value, int) and not isinstance(value, bool)
        case ActionInputType.BOOLEAN:
            return isinstance(value, bool)
        case ActionInputType.OBJECT:
            return isinstance(value, Mapping)
        case ActionInputType.ARRAY:
            return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)
    return False


def _freeze_payload_value(value: object) -> object:
    if isinstance(value, Mapping):
        frozen_mapping: dict[object, object] = {}
        for key, item in value.items():
            frozen_mapping[key] = _freeze_payload_value(item)
        return MappingProxyType(frozen_mapping)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        frozen_items: list[object] = []
        for item in value:
            frozen_items.append(_freeze_payload_value(item))
        return tuple(frozen_items)
    return value


def _freeze_payload(payload: Mapping[str, object]) -> Mapping[str, object]:
    frozen_payload: dict[str, object] = {}
    for key, value in payload.items():
        frozen_payload[key] = _freeze_payload_value(value)
    return MappingProxyType(frozen_payload)


def _validate_payload(schema: ActionInputSchema, payload: Mapping[str, object]) -> None:
    fields = {field.name: field for field in schema.fields}
    missing = sorted(
        field.name for field in schema.fields if field.required and field.name not in payload
    )
    if missing:
        raise AgentActionCommandError(f"Missing action input: {', '.join(missing)}.")
    unexpected = sorted(set(payload) - set(fields))
    if not schema.additional_properties and unexpected:
        raise AgentActionCommandError(f"Unexpected action input: {', '.join(unexpected)}.")
    for name, value in payload.items():
        field = fields.get(name)
        if field is not None and not _matches_type(value, field.value_type):
            raise AgentActionCommandError(f'Action input {name} must be {field.value_type.value}.')


def _revision(payload: Mapping[str, object], supplied: int | None) -> int | None:
    value = payload.get('expected_revision')
    if value is None:
        revision = supplied
    elif isinstance(value, int) and not isinstance(value, bool):
        if supplied is not None and supplied != value:
            raise AgentActionCommandError('expected_revision metadata does not match payload.')
        revision = value
    else:
        raise AgentActionCommandError('expected_revision must be an integer.')
    if revision is not None and revision < 0:
        raise AgentActionCommandError('expected_revision must not be negative.')
    return revision


def _idempotency_key(payload: Mapping[str, object], supplied: str | None) -> str | None:
    value = payload.get('idempotency_key')
    if value is None:
        key = supplied
    elif isinstance(value, str):
        if supplied is not None and supplied != value:
            raise AgentActionCommandError('idempotency_key metadata does not match payload.')
        key = value
    else:
        raise AgentActionCommandError('idempotency_key must be a string.')
    if key is not None and not key.strip():
        raise AgentActionCommandError('idempotency_key must not be blank.')
    return key


def build_claim_context_command(
    action_code: str,
    payload: Mapping[str, object],
    *,
    proposer_role: ActionActorRole,
    approved_authority: ExecutionAuthority,
    authority_reference: str,
    workflow_state: WorkflowState,
    expected_revision: int | None = None,
    idempotency_key: str | None = None,
) -> ClaimContextCommand:
    """Validate an approved action and produce side-effect-free execution intent.

    Args:
        action_code: Stable namespaced action code from the approved registry.
        payload: Proposed action inputs to validate against the published closed schema.
        proposer_role: Server-validated role that proposed or requested the action.
        approved_authority: Authority that was satisfied before command translation.
        authority_reference: Source-preserving reference proving the approved authority.
        workflow_state: Current authoritative workflow state used for lifecycle validation.
        expected_revision: Optional compare-and-set revision supplied as execution metadata.
        idempotency_key: Optional stable request key supplied as execution metadata.

    Returns:
        A provider-neutral command that preserves the registered tools, visibility,
        idempotency policy, and failure policy without executing a side effect.

    Raises:
        UnknownAgentActionError: The action code is not present in the registry.
        AgentActionCommandError: The action is outside the Claim Context boundary or fails
            schema, role, authority, lifecycle, revision, or idempotency validation.
    """

    try:
        contract = action_contract(action_code)
    except ValueError as error:
        raise UnknownAgentActionError(str(error)) from error

    if (
        contract.namespace not in _CLAIM_CONTEXT_NAMESPACES
        or contract.state_effect not in _CLAIM_CONTEXT_EFFECTS
    ):
        raise AgentActionCommandError(f'{action_code} is not a Claim Context command.')
    if proposer_role not in contract.allowed_actor_roles:
        raise AgentActionCommandError(f'Role {proposer_role.value} may not propose {action_code}.')
    if approved_authority is not contract.authority_requirement:
        raise AgentActionCommandError(
            f'{action_code} requires {contract.authority_requirement.value} authority.'
        )
    if not authority_reference.strip():
        raise AgentActionCommandError('Approved actions require an authority reference.')
    if workflow_state not in contract.allowed_lifecycle_states:
        raise AgentActionCommandError(
            f'{action_code} is not allowed while the claim is {workflow_state.value}.'
        )

    _validate_payload(contract.input_schema, payload)
    revision = _revision(payload, expected_revision)
    key = _idempotency_key(payload, idempotency_key)
    if (
        contract.state_effect in _REVISIONED_EFFECTS
        and action_code != 'claim.open_draft'
        and revision is None
    ):
        raise AgentActionCommandError(f'{action_code} requires expected_revision metadata.')
    if contract.idempotency_policy is not ActionIdempotencyPolicy.NOT_REQUIRED and key is None:
        raise AgentActionCommandError(f'{action_code} requires idempotency_key metadata.')

    return ClaimContextCommand(
        action_code=contract.action_code,
        contract_version=contract.version,
        payload=_freeze_payload(payload),
        proposer_role=proposer_role,
        authority_requirement=contract.authority_requirement,
        authority_reference=authority_reference.strip(),
        workflow_state=workflow_state,
        state_effect=contract.state_effect,
        expected_revision=revision,
        idempotency_key=key,
        idempotency_policy=contract.idempotency_policy,
        permitted_tools=contract.permitted_tools,
        visibility=contract.visibility,
        failure_policy=contract.failure_policy,
    )
