"""Resolve and enforce one published Agent policy for a complete turn."""

from dataclasses import dataclass, replace

from pydantic import ValidationError

from backend.core.errors import ApiError
from backend.domain.agent_action_registry import AGENT_ACTION_REGISTRY
from backend.domain.agent_runtime_configuration import (
    AgentFeatureSettingsConfiguration,
    AgentInstructionConfiguration,
    AgentRuntimeConfiguration,
    AgentToolPolicyConfiguration,
    ControlledRulesConfiguration,
)
from backend.domain.branch_registry import BranchRuleEvaluator, build_default_registry
from backend.domain.models import (
    AgentAction,
    ConfigurationRevisionReference,
    KnowledgeRevisionReference,
    RuntimeConfigurationProvenance,
)
from backend.services.agent import AgentProposal
from backend.services.runtime_configuration import (
    RuntimeConfigurationResolutionError,
    RuntimeConfigurationResolver,
    RuntimeConfigurationSnapshot,
)

AGENT_CONFIGURATION_DOMAINS = (
    'agent_instruction',
    'agent_tool_policy',
    'agent_rule',
    'feature',
)

PROPOSAL_TOOL_ACTIONS = {
    'knowledge_search': 'external.load_requirements',
    'policy_history': 'external.load_requirements',
    'claim_history': 'external.load_requirements',
    'evidence_registry': 'claim.set_evidence_state',
    'professional_review': 'human.request_professional_review',
}

_LEGACY_ACTION_CODES = {
    AgentAction.ASK: 'conversation.ask',
    AgentAction.CLARIFY: 'conversation.clarify',
    AgentAction.CONFIRM: 'conversation.confirm_material',
    AgentAction.PROCEED: 'runtime.continue',
    AgentAction.HANDOFF: 'human.create_handoff',
    AgentAction.CREATE_CLAIM: 'claim.create',
}

_REQUIRED_POLICY_ACTIONS = frozenset(
    {
        'conversation.state_limitation',
        'human.create_handoff',
        'runtime.fail_safe',
        'runtime.interrupt_urgent',
    }
)
_REQUIRED_POLICY_TOOLS = frozenset({'handoff_store.create'})

_PROTECTED_RULE_IDS = frozenset(
    {
        'BR-FAMILY-MOTOR-001',
        'BR-FAMILY-HOME-001',
        'BR-FAMILY-CONTENTS-001',
        'BR-SAFETY-001',
        'BR-REVIEW-001',
        'BR-HUMAN-SUPPORT-001',
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeAgentPolicySnapshot:
    """Typed Agent policy and provenance selected from one Release Set snapshot."""

    runtime_snapshot: RuntimeConfigurationSnapshot
    instruction: AgentInstructionConfiguration
    tool_policy: AgentToolPolicyConfiguration
    controlled_rules: ControlledRulesConfiguration
    features: AgentFeatureSettingsConfiguration

    def branch_evaluator(self) -> BranchRuleEvaluator:
        """Build an evaluator carrying the published controlled-rule version."""

        registry = replace(
            build_default_registry(),
            branch_rules_version=self.controlled_rules.rules_version,
        )
        return BranchRuleEvaluator(
            registry,
            disabled_rule_ids=frozenset(self.controlled_rules.disabled_rule_ids),
            observation_rule_ids=frozenset(self.controlled_rules.observation_rule_ids),
        )

    def provenance(self) -> RuntimeConfigurationProvenance:
        """Return the immutable configuration coordinates persisted for this turn."""

        snapshot = self.runtime_snapshot
        return RuntimeConfigurationProvenance(
            release_set_id=snapshot.release_set_id,
            environment=snapshot.environment,
            runtime_profile=snapshot.runtime_profile,
            configurations={
                domain: ConfigurationRevisionReference(
                    configuration_id=record.configuration_id,
                    revision=record.revision,
                )
                for domain, record in snapshot.configurations.items()
            },
            knowledge={
                product: KnowledgeRevisionReference(
                    knowledge_id=record.knowledge_id,
                    revision=record.revision,
                    version=record.version,
                )
                for product, record in snapshot.knowledge.items()
            },
        )


def _registered_rule_ids() -> frozenset[str]:
    return frozenset(branch.rule_id for branch in build_default_registry().branches)


def _registered_tool_names() -> frozenset[str]:
    contract_tools = {
        tool for contract in AGENT_ACTION_REGISTRY.values() for tool in contract.permitted_tools
    }
    return frozenset(contract_tools | set(PROPOSAL_TOOL_ACTIONS))


def registered_agent_tool_names() -> tuple[str, ...]:
    """Return every server-registered tool name a policy may reference."""

    return tuple(sorted(_registered_tool_names()))


def parse_agent_configuration(
    domain: str,
    values: dict[str, object],
) -> AgentRuntimeConfiguration:
    """Validate one Agent configuration domain against its closed runtime schema."""

    parsed: AgentRuntimeConfiguration
    if domain == 'agent_instruction':
        parsed = AgentInstructionConfiguration.model_validate(values)
    elif domain == 'agent_tool_policy':
        parsed = AgentToolPolicyConfiguration.model_validate(values)
    elif domain == 'agent_rule':
        parsed = ControlledRulesConfiguration.model_validate(values)
    elif domain == 'feature':
        parsed = AgentFeatureSettingsConfiguration.model_validate(values)
    else:
        raise ValueError(f'{domain!r} is not an Agent runtime configuration domain.')
    if isinstance(parsed, AgentToolPolicyConfiguration):
        unknown_actions = sorted(set(parsed.allowed_action_codes) - set(AGENT_ACTION_REGISTRY))
        unknown_tools = sorted(set(parsed.allowed_tool_names) - _registered_tool_names())
        if unknown_actions:
            raise ValueError(f'Unknown registered Agent actions: {", ".join(unknown_actions)}.')
        if unknown_tools:
            raise ValueError(f'Unknown registered Agent tools: {", ".join(unknown_tools)}.')
        missing_required_actions = sorted(
            _REQUIRED_POLICY_ACTIONS - set(parsed.allowed_action_codes)
        )
        missing_required_tools = sorted(_REQUIRED_POLICY_TOOLS - set(parsed.allowed_tool_names))
        if missing_required_actions or missing_required_tools:
            raise ValueError(
                'Agent tool policy cannot disable the registered safety, human-support, '
                'or fail-safe baseline.'
            )
    if isinstance(parsed, ControlledRulesConfiguration):
        configured = set(parsed.disabled_rule_ids) | set(parsed.observation_rule_ids)
        unknown_rules = sorted(configured - _registered_rule_ids())
        protected_rules = sorted(configured & _PROTECTED_RULE_IDS)
        if unknown_rules:
            raise ValueError(f'Unknown controlled rules: {", ".join(unknown_rules)}.')
        if protected_rules:
            raise ValueError(
                'Safety, human-support, professional-review, and claim-family rules '
                'cannot be disabled or reduced to observation.'
            )
    return parsed


class RuntimeAgentPolicyResolver:
    """Load all Agent policy domains from one active Release Set snapshot."""

    def __init__(self, resolver: RuntimeConfigurationResolver) -> None:
        self._resolver = resolver

    def resolve_for_turn(self) -> RuntimeAgentPolicySnapshot | None:
        """Return one coherent policy, or the explicit no-release bootstrap path."""

        snapshot = self._resolver.snapshot()
        if snapshot.release_set_id is None:
            return None
        parsed: dict[str, AgentRuntimeConfiguration] = {}
        try:
            for domain in AGENT_CONFIGURATION_DOMAINS:
                record = snapshot.get(domain)
                assert record is not None
                parsed[domain] = parse_agent_configuration(domain, record.values)
        except (RuntimeConfigurationResolutionError, ValidationError, ValueError) as error:
            raise RuntimeConfigurationResolutionError(
                'The active Release Set does not contain a valid complete Agent policy.'
            ) from error

        instruction = parsed['agent_instruction']
        tool_policy = parsed['agent_tool_policy']
        controlled_rules = parsed['agent_rule']
        features = parsed['feature']
        assert isinstance(instruction, AgentInstructionConfiguration)
        assert isinstance(tool_policy, AgentToolPolicyConfiguration)
        assert isinstance(controlled_rules, ControlledRulesConfiguration)
        assert isinstance(features, AgentFeatureSettingsConfiguration)

        model_record = snapshot.configurations.get('model')
        if model_record is not None:
            model_prompt_version = model_record.values.get('prompt_version')
            if model_prompt_version != instruction.prompt_version:
                raise RuntimeConfigurationResolutionError(
                    'The selected model and Agent instruction use different prompt versions.'
                )
        return RuntimeAgentPolicySnapshot(
            runtime_snapshot=snapshot,
            instruction=instruction,
            tool_policy=tool_policy,
            controlled_rules=controlled_rules,
            features=features,
        )


def required_action_codes(proposal: AgentProposal) -> frozenset[str]:
    """Translate the compatibility proposal to its registered target-action boundary."""

    if proposal.action is AgentAction.URGENT_HANDOFF:
        actions = {'human.create_handoff', 'runtime.interrupt_urgent'}
    elif proposal.action is AgentAction.UPDATE:
        base = 'claim.propose_fact_patch' if proposal.form_changes else 'conversation.acknowledge'
        actions = {base}
    else:
        base = _LEGACY_ACTION_CODES[proposal.action]
        actions = {base}
    for tool_request in proposal.required_tools:
        tool_name = tool_request.get('tool')
        if isinstance(tool_name, str) and tool_name in PROPOSAL_TOOL_ACTIONS:
            actions.add(PROPOSAL_TOOL_ACTIONS[tool_name])
    return frozenset(actions)


def enforce_agent_proposal(
    policy: RuntimeAgentPolicySnapshot,
    proposal: AgentProposal,
) -> None:
    """Reject a proposal that exceeds the selected published action or tool policy."""

    allowed_actions = set(policy.tool_policy.allowed_action_codes)
    disallowed_actions = sorted(required_action_codes(proposal) - allowed_actions)
    if disallowed_actions:
        raise ApiError(
            status_code=503,
            code='AGENT_ACTION_NOT_PERMITTED',
            message='The active Agent policy does not permit the proposed action.',
            retryable=False,
        )
    allowed_tools = set(policy.tool_policy.allowed_tool_names)
    requested_tools = {
        tool_name
        for request in proposal.required_tools
        if isinstance((tool_name := request.get('tool')), str)
    }
    unregistered_tools = requested_tools - set(PROPOSAL_TOOL_ACTIONS)
    if unregistered_tools or requested_tools - allowed_tools:
        raise ApiError(
            status_code=503,
            code='AGENT_TOOL_NOT_PERMITTED',
            message='The active Agent policy does not permit the proposed tool request.',
            retryable=False,
        )
