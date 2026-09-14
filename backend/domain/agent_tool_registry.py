"""Provider-neutral read tools exposed to the Agent Runtime.

Tool contracts are deliberately separate from the namespaced Action Registry. A tool
returns a bounded observation; it does not grant authority to mutate Claim State.
"""

from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field


class AgentToolContract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    name: str = Field(pattern=r'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$')
    description: str = Field(min_length=1, max_length=500)
    input_schema: dict[str, object]
    purpose: str = Field(min_length=1, max_length=120)
    read_only: bool = True


_NO_ARGUMENTS = {
    'type': 'object',
    'properties': {},
    'required': [],
    'additionalProperties': False,
}


def _tool(
    name: str,
    description: str,
    purpose: str,
    input_schema: dict[str, object] | None = None,
    *,
    read_only: bool = True,
) -> AgentToolContract:
    return AgentToolContract(
        name=name,
        description=description,
        purpose=purpose,
        input_schema=input_schema or _NO_ARGUMENTS,
        read_only=read_only,
    )


# This is the provider-neutral manifest.  Service handlers may be unavailable in
# a deployment, but the model can only request names present here and the active
# Runtime policy still decides which of them is exposed for a turn.
AGENT_TOOL_REGISTRY = MappingProxyType(
    {
        'claim.read': _tool(
            'claim.read',
            'Read the latest authorised Claim State for the current claimant session.',
            'claimant_status_and_context',
        ),
        'knowledge_search': _tool(
            'knowledge.search',
            'Search approved policy or product knowledge within the current jurisdiction.',
            'approved_knowledge_lookup',
            {
                'type': 'object',
                'properties': {'query': {'type': 'string', 'maxLength': 500}},
                'required': ['query'],
                'additionalProperties': False,
            },
        ),
        'policy_history': _tool(
            'policy.history',
            'Retrieve a bounded policy-history result for the current Claim.',
            'policy_history_lookup',
            {
                'type': 'object',
                'properties': {
                    'policy_reference': {'type': 'string', 'maxLength': 200},
                    'question': {'type': 'string', 'maxLength': 500},
                },
                'required': ['policy_reference'],
                'additionalProperties': False,
            },
        ),
        'claim_history': _tool(
            'claim.history',
            'Retrieve only the requested bounded prior-claim history reference.',
            'claim_history_lookup',
            {
                'type': 'object',
                'properties': {
                    'history_reference': {'type': 'string', 'maxLength': 200},
                    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50},
                },
                'required': ['history_reference'],
                'additionalProperties': False,
            },
        ),
        'evidence_registry': _tool(
            'evidence.registry',
            'Read evidence identity and processing state for the current Claim.',
            'evidence_status_lookup',
            {
                'type': 'object',
                'properties': {'evidence_id': {'type': 'string', 'maxLength': 100}},
                'required': [],
                'additionalProperties': False,
            },
        ),
        'professional_review': _tool(
            'review.professional',
            'Read whether a bounded professional-review request is already recorded.',
            'professional_review_lookup',
        ),
        'handoff_store': _tool(
            'handoff.read',
            'Read claimant-safe handoff status for the current Claim.',
            'handoff_status_lookup',
        ),
        'external_service': _tool(
            'external_service.status',
            'Read the status of an already-authorised external operation.',
            'external_operation_status',
            {
                'type': 'object',
                'properties': {'operation_id': {'type': 'string', 'maxLength': 120}},
                'required': ['operation_id'],
                'additionalProperties': False,
            },
        ),
        'claim_store': _tool(
            'claim_store.read',
            'Read revision and idempotency state before a Claim mutation.',
            'claim_mutation_preflight',
        ),
        # Action contracts use these explicit side-effect tool names.  They are
        # registered here as unavailable-by-default manifest entries so policy
        # validation cannot silently treat a raw string as an executable tool.
        'claim_store.compare_and_set': _tool(
            'claim_store.compare_and_set',
            'Apply one revision-checked Claim mutation through the repository boundary.',
            'claim_mutation',
            read_only=False,
        ),
        'claims_service.create_claim': _tool(
            'claims_service.create_claim',
            'Create a formal Claim through the authorised Claims service adapter.',
            'claim_creation',
            read_only=False,
        ),
        'handoff_store.create': _tool(
            'handoff_store.create',
            'Persist a source-preserving human handoff.',
            'handoff_creation',
            read_only=False,
        ),
        **{
            f'external_service.{operation}': _tool(
                f'external_service.{operation}',
                f'Execute the registered external operation: {operation}.',
                'external_operation',
                read_only=operation not in {'submit_request', 'retry_request', 'cancel_request'},
            )
            for operation in (
                'discover_capability',
                'load_requirements',
                'prepare_request',
                'classify_request',
                'check_authority',
                'submit_request',
                'track_request',
                'verify_response',
                'reconcile_response',
                'retry_request',
                'cancel_request',
                'escalate_failure',
            )
        },
    }
)


def tool_contract(name: str) -> AgentToolContract:
    try:
        return AGENT_TOOL_REGISTRY[name]
    except KeyError:
        # Compatibility callers historically used operation identifiers such
        # as ``knowledge_search``.  Accept the canonical namespaced contract
        # name as well, without adding a second registry entry.
        for contract in AGENT_TOOL_REGISTRY.values():
            if contract.name == name:
                return contract
        raise ValueError(f'Unknown Agent tool: {name}.') from None


def registered_tools() -> tuple[str, ...]:
    """Return the immutable, provider-neutral tool manifest in stable order."""

    return tuple(sorted(AGENT_TOOL_REGISTRY))
