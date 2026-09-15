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

    name: str = Field(pattern=r'^[a-z]+\.[a-z][a-z0-9_]*$')
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


AGENT_TOOL_REGISTRY = MappingProxyType(
    {
        'claim.read': AgentToolContract(
            name='claim.read',
            description='Read the latest authorised Claim State for the current claimant session.',
            purpose='claimant_status_and_context',
            input_schema={
                'type': 'object',
                'properties': {},
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
    try:
        return AGENT_TOOL_REGISTRY[name]
    except KeyError as error:
        raise ValueError(f'Unknown Agent tool: {name}.') from error


def staff_tool_contract(name: str) -> StaffToolContract:
    try:
        return STAFF_TOOL_REGISTRY[name]
    except KeyError as error:
        raise ValueError(f'Unknown Staff Agent tool: {name}.') from error
