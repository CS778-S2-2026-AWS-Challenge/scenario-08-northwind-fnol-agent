"""Versioned contracts for the budgeted Agent Context Runtime."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from backend.domain.models import ContractModel


class ContextLoadMode(StrEnum):
    ALWAYS = 'always'
    ROUTE_MATCH = 'route_match'
    AUTO_CANDIDATE = 'auto_candidate'
    EXPLICIT = 'explicit'
    REFERENCE = 'reference'
    COMPACTED = 'compacted'
    ISOLATED = 'isolated'


class ContextDisposition(StrEnum):
    INCLUDED = 'included'
    REFERENCED = 'referenced'
    COMPACTED = 'compacted'
    ISOLATED = 'isolated'
    OMITTED = 'omitted'


class TurnTask(StrEnum):
    INTAKE = 'intake'
    CORRECTION = 'correction'
    CONFIRMATION = 'confirmation'
    STATUS_QUESTION = 'status_question'
    CLAIM_CREATION = 'claim_creation'
    EVIDENCE_CURRENT = 'evidence_current'
    EVIDENCE_HISTORY = 'evidence_history'
    EXTERNAL_SUPPORT = 'external_support'
    HUMAN_HANDOFF = 'human_handoff'


class TurnRoute(ContractModel):
    product_family: Literal['motor', 'home', 'contents'] | None = None
    family_resolution: Literal['authoritative', 'inferred', 'unresolved']
    task: TurnTask
    capability_ids: list[str] = Field(default_factory=list, max_length=8)
    deterministic_response: str | None = Field(default=None, max_length=1000)
    model_required: bool = True

    @model_validator(mode='after')
    def validate_deterministic_route(self) -> 'TurnRoute':
        if not self.model_required and not self.deterministic_response:
            raise ValueError('A model-free route requires a deterministic response.')
        if self.family_resolution == 'unresolved' and self.product_family is not None:
            raise ValueError('An unresolved family route cannot select a product family.')
        return self


class ContextCatalogueEntry(ContractModel):
    resource_id: str = Field(min_length=1, max_length=160)
    resource_type: Literal[
        'claim_projection',
        'latest_message',
        'recent_messages',
        'rolling_summary',
        'evidence',
        'external_service',
        'knowledge',
        'policy',
        'claim_history',
    ]
    load_mode: ContextLoadMode
    priority: int = Field(ge=0, le=4)
    estimated_tokens: int = Field(ge=0)
    authority_scope: str = Field(min_length=1, max_length=200)
    cache_segment: str | None = Field(default=None, max_length=80)
    selectors: list[str] = Field(default_factory=list, max_length=20)


class ContextReference(ContractModel):
    ref: str = Field(min_length=1, max_length=200)
    resource_type: Literal[
        'message_range',
        'evidence',
        'knowledge_chunk',
        'policy_version',
        'claim_history',
        'external_service',
    ]
    version: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    available_selectors: list[str] = Field(min_length=1, max_length=20)
    max_resolve_tokens: int = Field(ge=1, le=1200)
    expires_with_turn: bool = True


class ContextLoadDecision(ContractModel):
    resource_id: str = Field(min_length=1, max_length=160)
    load_mode: ContextLoadMode
    selection_reason: str = Field(min_length=1, max_length=300)
    disposition: ContextDisposition
    estimated_tokens: int = Field(ge=0)
    authority_scope: str = Field(min_length=1, max_length=200)
    cache_segment: str | None = Field(default=None, max_length=80)


class ContextPlan(ContractModel):
    catalogue_entries: list[ContextCatalogueEntry] = Field(default_factory=list, max_length=100)
    selected_resource_ids: list[str] = Field(default_factory=list, max_length=100)
    inline_context: dict[str, Any] = Field(default_factory=dict)
    references: list[ContextReference] = Field(default_factory=list, max_length=50)
    permitted_resolvers: list[str] = Field(default_factory=list, max_length=20)
    isolated_tasks: list[str] = Field(default_factory=list, max_length=20)
    load_decisions: list[ContextLoadDecision] = Field(default_factory=list, max_length=100)
    omitted_sections: list[str] = Field(default_factory=list, max_length=100)
    estimated_tokens: int = Field(ge=0)
    budget_limit: int = Field(ge=1)
    summary_state_mismatch: bool = False


class ProviderCapability(ContractModel):
    capability_version: str = Field(min_length=1, max_length=120)
    protocol: str = Field(min_length=1, max_length=50)
    structured_output_method: Literal['json_schema', 'forced_tool']
    tool_call_support: bool
    tool_result_continuation: Literal['assistant_tool_message', 'tool_result_block'] | None = None
    supported_media_types: list[str] = Field(default_factory=list, max_length=20)
    prompt_cache_type: Literal['none', 'implicit', 'explicit'] = 'none'
    minimum_cache_tokens: int | None = Field(default=None, ge=1)
    maximum_cache_points: int | None = Field(default=None, ge=1)
    cache_usage_fields: list[str] = Field(default_factory=list, max_length=20)
    continuation_mechanism: str | None = Field(default=None, max_length=100)


class RequestProfile(ContractModel):
    profile_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=50)
    schema_id: str = Field(min_length=1, max_length=120)
    tool_names: list[str] = Field(default_factory=list, max_length=10)
    max_model_invocations: int = Field(ge=1, le=2)
    max_model_selected_tools: int = Field(ge=0, le=1)
    input_hard_limit: int = Field(ge=100)
    output_limit: int = Field(ge=1)
    requires_media_types: list[str] = Field(default_factory=list, max_length=20)
    requires_tool_continuation: bool = False
    isolated: bool = False

    @model_validator(mode='after')
    def validate_invocation_contract(self) -> 'RequestProfile':
        if self.tool_names and self.max_model_selected_tools == 0:
            raise ValueError('A tool profile must permit one selected tool.')
        if self.requires_tool_continuation and self.max_model_invocations < 2:
            raise ValueError('Tool continuation requires a second model invocation.')
        if not self.tool_names and self.max_model_selected_tools:
            raise ValueError('A tool-free profile cannot permit model-selected tools.')
        return self


class ContextBudgetPolicy(ContractModel):
    policy_version: str = 'northwind-context-budget-v1'
    ordinary_input_target: int = Field(default=1800, ge=100)
    ordinary_input_hard_limit: int = Field(default=3000, ge=100)
    ordinary_output_limit: int = Field(default=180, ge=1)
    tool_path_input_hard_limit: int = Field(default=3000, ge=100)
    tool_path_output_limit: int = Field(default=300, ge=1)
    max_model_invocations: int = Field(default=2, ge=1, le=2)
    max_model_selected_tools: int = Field(default=1, ge=0, le=1)
    soft_latency_target_ms: int = Field(default=10_000, ge=100)


class ModelRequestBudget(ContractModel):
    policy_version: str = Field(min_length=1, max_length=100)
    raw_input_tokens: int = Field(ge=0)
    uncached_input_tokens: int = Field(ge=0)
    cache_eligible_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    turn_cumulative_tokens: int = Field(ge=0)
    reserved_output_tokens: int = Field(ge=1)
    prompt_tokens: int = Field(ge=0)
    schema_tokens: int = Field(ge=0)
    context_tokens: int = Field(ge=0)
    tool_definition_tokens: int = Field(ge=0)
    recent_history_tokens: int = Field(ge=0)
    retrieved_context_tokens: int = Field(ge=0)
    hard_limit: int = Field(ge=100)
    estimate_method: Literal['provider_tokenizer', 'conservative_chars']

    @model_validator(mode='after')
    def enforce_hard_limit(self) -> 'ModelRequestBudget':
        if self.raw_input_tokens > self.hard_limit:
            raise ValueError('Model request exceeds the configured hard token limit.')
        if self.turn_cumulative_tokens > self.hard_limit:
            raise ValueError('Model turn exceeds the configured cumulative token limit.')
        return self


class CacheSegment(ContractModel):
    segment_id: str = Field(min_length=1, max_length=120)
    cache_key: str = Field(min_length=1, max_length=300)
    estimated_tokens: int = Field(ge=0)
    checkpoint: bool = False


class CachePlan(ContractModel):
    layout_version: str = Field(min_length=1, max_length=100)
    prefix_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    tool_manifest_id: str = Field(min_length=1, max_length=160)
    segments: list[CacheSegment] = Field(min_length=1, max_length=10)


class PlannedModelTurn(ContractModel):
    route: TurnRoute
    request_profile: RequestProfile
    provider_capability: ProviderCapability
    prompt_bundle_id: str = Field(min_length=1, max_length=300)
    fragment_refs: list[str] = Field(min_length=1, max_length=30)
    schema_id: str = Field(min_length=1, max_length=120)
    context_plan: ContextPlan
    request_budget: ModelRequestBudget
    cache_plan: CachePlan
    system_instruction: str = Field(min_length=1, max_length=50_000)
    context_payload: dict[str, Any]
    response_schema: dict[str, Any]


class VerifiedConversationSummary(ContractModel):
    summary_id: str = Field(min_length=1, max_length=120)
    claim_id: str = Field(min_length=1, max_length=120)
    session_id: str = Field(min_length=1, max_length=120)
    source_message_ids: list[str] = Field(min_length=1, max_length=2000)
    covered_message_range: str = Field(min_length=1, max_length=240)
    generator_profile_and_version: str = Field(min_length=1, max_length=200)
    claim_revision_at_generation: int = Field(ge=1)
    summary: str = Field(min_length=1, max_length=5000)
    verified_against_claim_revision: int = Field(ge=1)
    created_at: str = Field(min_length=1, max_length=80)


class IsolatedContextTask(ContractModel):
    task_id: str = Field(min_length=1, max_length=120)
    task_type: Literal['cross_claim', 'multi_evidence', 'long_document']
    authority_scope: str = Field(min_length=1, max_length=200)
    input_refs: list[ContextReference] = Field(min_length=1, max_length=50)
    permitted_resolvers: list[str] = Field(min_length=1, max_length=10)
    max_input_tokens: int = Field(ge=100, le=20_000)
    max_output_tokens: int = Field(ge=1, le=2000)
    mutation_allowed: Literal[False] = False
    consent_action_allowed: Literal[False] = False
    external_side_effect_allowed: Literal[False] = False


class IsolatedContextResult(ContractModel):
    task_id: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=10_000)
    source_refs: list[str] = Field(min_length=1, max_length=100)
    source_versions: dict[str, str] = Field(min_length=1, max_length=100)
    truncated: bool
    limitations: list[str] = Field(default_factory=list, max_length=20)
