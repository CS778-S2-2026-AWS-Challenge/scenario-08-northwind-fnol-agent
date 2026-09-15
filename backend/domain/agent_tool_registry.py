"""Provider-neutral read tools exposed to the Agent Runtime.

Tool contracts are deliberately separate from the namespaced Action Registry. A tool
returns a bounded observation; it does not grant authority to mutate Claim State.
"""

from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.domain import staff_agent_tools as staff_tool_models

STAFF_TOOL_INPUT_MODELS = staff_tool_models.STAFF_TOOL_INPUT_MODELS
STAFF_TOOL_OUTPUT_MODELS = staff_tool_models.STAFF_TOOL_OUTPUT_MODELS
StaffToolResult = staff_tool_models.StaffToolResult
StaffToolResultStatus = staff_tool_models.StaffToolResultStatus


class AgentToolContract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    name: str = Field(pattern=r'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$')
    description: str = Field(min_length=1, max_length=500)
    input_schema: dict[str, object]
    purpose: str = Field(min_length=1, max_length=120)
    read_only: bool = True


class StaffToolContract(AgentToolContract):
    """Versioned metadata for a bounded Staff Agent read capability."""

    name: str = Field(pattern=r'^staff\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$')
    registry_version: str = Field(pattern=r'^v\d+\.\d+$')
    actor_types: frozenset[str] = frozenset({'staff'})
    allowed_staff_roles: frozenset[str] = frozenset({'claims_professional'})
    required_scopes: frozenset[str] = frozenset({'workbench:read'})
    claim_scope: str = Field(min_length=1, max_length=120)
    customer_scope: str = 'claim-owned-customer'
    tenant_scope: str = 'server-resolved-tenant'
    data_classification: str = Field(min_length=1, max_length=80)
    visibility: frozenset[str] = frozenset({'staff', 'internal'})
    effect: Literal['read'] = 'read'
    timeout_ms: int = Field(ge=1, le=30_000)
    max_results: int = Field(ge=1, le=100)
    pagination: Literal['bounded-no-cursor'] = 'bounded-no-cursor'
    retry_policy: Literal['never', 'transient-only'] = 'transient-only'
    source_refs_required: bool = True
    audit_required: bool = True
    unavailable_behavior: str = 'Return a typed unavailable result without substitute data.'
    denied_behavior: str = 'Return a typed denied result without confirming record existence.'
    follow_up_tools: tuple[str, ...] = ()
    disclose_to_model: bool = True
    release_status: Literal['read-only-runtime-executable', 'reserved-unavailable'] = (
        'read-only-runtime-executable'
    )
    output_schema: dict[str, object]


def _staff_tool(
    name: str,
    description: str,
    purpose: str,
    *,
    claim_scope: str,
    max_results: int = 25,
    follow_up_tools: tuple[str, ...] = (),
    release_status: Literal[
        'read-only-runtime-executable', 'reserved-unavailable'
    ] = 'read-only-runtime-executable',
) -> StaffToolContract:
    return StaffToolContract(
        name=name,
        description=description,
        purpose=purpose,
        input_schema=STAFF_TOOL_INPUT_MODELS[name].model_json_schema(),
        registry_version='v1.0',
        claim_scope=claim_scope,
        data_classification='staff_operational',
        timeout_ms=5_000,
        max_results=max_results,
        follow_up_tools=follow_up_tools,
        release_status=release_status,
        output_schema=STAFF_TOOL_OUTPUT_MODELS[name].model_json_schema(),
    )


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
        'knowledge.search': _tool(
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
        'policy.history': _tool(
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
        'claim.history': _tool(
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
        'evidence.registry': _tool(
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
        'evidence.history': AgentToolContract(
            name='evidence.history',
            description=(
                "Read the authenticated claimant's bounded Evidence history across Claims."
            ),
            purpose='claimant_evidence_reuse_and_removal',
            input_schema={
                'type': 'object',
                'properties': {
                    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50},
                    'cursor': {'type': 'string', 'minLength': 1},
                },
                'required': [],
                'additionalProperties': False,
            },
        ),
        'evidence.reuse': _tool(
            'evidence.reuse',
            'Attach an existing claimant-owned Evidence identity to the current Claim.',
            'confirmed_evidence_reuse',
            {
                'type': 'object',
                'properties': {
                    'claim_id': {'type': 'string', 'maxLength': 120},
                    'evidence_id': {'type': 'string', 'maxLength': 100},
                    'source_claim_id': {'type': 'string', 'maxLength': 120},
                    'expected_revision': {'type': 'integer', 'minimum': 1},
                },
                'required': [
                    'claim_id',
                    'evidence_id',
                    'source_claim_id',
                    'expected_revision',
                ],
                'additionalProperties': False,
            },
            read_only=False,
        ),
        'evidence.remove': _tool(
            'evidence.remove',
            'Apply a confirmed persisted-Evidence removal under retention and audit policy.',
            'confirmed_evidence_removal',
            {
                'type': 'object',
                'properties': {
                    'claim_id': {'type': 'string', 'maxLength': 120},
                    'evidence_id': {'type': 'string', 'maxLength': 100},
                    'source_claim_id': {'type': 'string', 'maxLength': 120},
                    'expected_revision': {'type': 'integer', 'minimum': 1},
                },
                'required': [
                    'claim_id',
                    'evidence_id',
                    'source_claim_id',
                    'expected_revision',
                ],
                'additionalProperties': False,
            },
            read_only=False,
        ),
        'review.professional': _tool(
            'review.professional',
            'Read whether a bounded professional-review request is already recorded.',
            'professional_review_lookup',
        ),
        'handoff.read': _tool(
            'handoff.read',
            'Read claimant-safe handoff status for the current Claim.',
            'handoff_status_lookup',
        ),
        'external_service.status': _tool(
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
        'claim_store.read': _tool(
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


# Operation identifiers used by the compatibility proposal are aliases only;
# they are never returned by ``registered_tools`` or exposed as canonical
# manifest entries.
AGENT_TOOL_COMPATIBILITY_ALIASES = MappingProxyType(
    {
        'knowledge_search': 'knowledge.search',
        'policy_history': 'policy.history',
        'claim_history': 'claim.history',
        'evidence_registry': 'evidence.registry',
        'professional_review': 'review.professional',
        'handoff_store': 'handoff.read',
        'external_service': 'external_service.status',
        'claim_store': 'claim_store.read',
    }
)


STAFF_TOOL_REGISTRY = MappingProxyType(
    {
        'staff.claim.search': _staff_tool(
            'staff.claim.search',
            'Search authorised Claims using bounded operational filters.',
            'staff_claim_lookup',
            claim_scope='staff-authorised-search',
            follow_up_tools=('staff.claim.read',),
        ),
        'staff.claim.read': _staff_tool(
            'staff.claim.read',
            'Read one authorised Claim projection.',
            'staff_claim_context',
            claim_scope='explicit-claim',
            max_results=1,
        ),
        'staff.session.search': _staff_tool(
            'staff.session.search',
            'Search sessions within authorised Claim or staff scope.',
            'staff_session_lookup',
            claim_scope='staff-authorised-search',
            follow_up_tools=('staff.session.read',),
        ),
        'staff.session.read': _staff_tool(
            'staff.session.read',
            'Read a bounded authorised session projection.',
            'staff_session_context',
            claim_scope='explicit-session',
            max_results=50,
        ),
        'staff.evidence.list': _staff_tool(
            'staff.evidence.list',
            'List Evidence metadata within authorised Claim scope.',
            'staff_evidence_lookup',
            claim_scope='explicit-claim-or-customer',
            max_results=50,
            follow_up_tools=('staff.evidence.read',),
        ),
        'staff.evidence.read': _staff_tool(
            'staff.evidence.read',
            'Read one authorised Evidence metadata projection.',
            'staff_evidence_context',
            claim_scope='explicit-evidence',
            max_results=1,
        ),
        'staff.knowledge.search': _staff_tool(
            'staff.knowledge.search',
            'Search the published knowledge source selected by the active release.',
            'staff_knowledge_lookup',
            claim_scope='release-scoped',
            max_results=10,
        ),
        'staff.policy.history': _staff_tool(
            'staff.policy.history',
            'Read applicable policy revisions by bounded product and effective date.',
            'staff_policy_lookup',
            claim_scope='release-scoped',
        ),
        'staff.handoff.read': _staff_tool(
            'staff.handoff.read',
            'Read an authorised handoff without changing it.',
            'staff_handoff_context',
            claim_scope='explicit-claim',
            max_results=50,
        ),
        'staff.review_signal.read': _staff_tool(
            'staff.review_signal.read',
            'Read staff-visible review signals.',
            'staff_review_context',
            claim_scope='explicit-claim',
            max_results=50,
        ),
        'staff.work_item.list': _staff_tool(
            'staff.work_item.list',
            'List WorkItems within authorised Claim or queue scope.',
            'staff_work_item_lookup',
            claim_scope='explicit-claim-or-queue',
            max_results=50,
        ),
        'staff.external_task.status': _staff_tool(
            'staff.external_task.status',
            'Read the canonical external task status projection.',
            'staff_external_status_lookup',
            claim_scope='explicit-claim-or-task',
            max_results=1,
            release_status='reserved-unavailable',
        ),
        'staff.customer_update.read': _staff_tool(
            'staff.customer_update.read',
            'Read claimant-safe customer update delivery state.',
            'staff_customer_update_context',
            claim_scope='explicit-claim',
            max_results=50,
        ),
    }
)


def tool_contract(name: str) -> AgentToolContract:
    canonical_name = AGENT_TOOL_COMPATIBILITY_ALIASES.get(name, name)
    try:
        return AGENT_TOOL_REGISTRY[canonical_name]
    except KeyError:
        raise ValueError(f'Unknown Agent tool: {name}.') from None


def staff_tool_contract(name: str) -> StaffToolContract:
    try:
        return STAFF_TOOL_REGISTRY[name]
    except KeyError as error:
        raise ValueError(f'Unknown Staff Agent tool: {name}.') from error


def registered_tools() -> tuple[str, ...]:
    """Return the immutable, provider-neutral tool manifest in stable order."""

    return tuple(sorted(AGENT_TOOL_REGISTRY))
