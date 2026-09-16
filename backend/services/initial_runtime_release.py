"""Install the repository-defined initial Agent Runtime release."""

from collections.abc import Mapping, Sequence

from backend.core.config import Settings
from backend.domain.agent_action_registry import registered_actions
from backend.domain.agent_context_runtime import ContextBudgetPolicy
from backend.domain.configuration import (
    ApprovalDecision,
    ApprovalRequest,
    ConfigurationCreate,
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
    ModelRuntimeBinding,
    ModelRuntimeConfiguration,
    TransitionRequest,
    ValidationRequest,
    ValidationScenarioResult,
)
from backend.domain.release import (
    ConfigurationReference,
    ReleaseSetCreate,
    ReleaseSetRecord,
    ReleaseSetValidationRequest,
)
from backend.prompts import (
    CLAIMANT_V7_PROMPT_ID,
    MOTOR_CLAIMANT_PROMPT_ID,
    load_motor_claimant_prompt,
)
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.services import configuration as configuration_service
from backend.services import release_sets as release_set_service
from backend.services.prompt_composer import (
    load_fragment_contents,
    load_prompt_manifest,
    load_response_schemas,
)
from backend.services.provider_capability_registry import provider_capability
from backend.services.request_profile_registry import registered_request_profiles
from backend.services.runtime_agent_policy import registered_agent_tool_names

_AUTHOR = 'repository-initial-release-author'
_REVIEWER = 'repository-initial-release-reviewer'
_REQUIRED_MODEL_PROFILES = frozenset({'qwen-local', 'nowcoding-gpt55'})
_VALIDATION_EVIDENCE = (
    'Repository-defined initial Runtime release passed structural and binding validation.'
)


def _model_values(
    binding: ModelRuntimeBinding,
    *,
    prompt_version: str,
) -> dict[str, object]:
    values = binding.model_dump(mode='json')
    values.update(
        {
            'prompt_version': prompt_version,
            'evaluation_status': 'configured',
            'timeout_seconds': (
                120.0
                if prompt_version == CLAIMANT_V7_PROMPT_ID and binding.profile_id == 'qwen-local'
                else 90.0
                if prompt_version == CLAIMANT_V7_PROMPT_ID
                else 30.0
            ),
        }
    )
    return values


def repository_v6_values(
    bindings: Sequence[ModelRuntimeBinding],
) -> dict[str, dict[str, object]]:
    if {binding.prompt_version for binding in bindings} != {MOTOR_CLAIMANT_PROMPT_ID}:
        raise ValueError('A v6 Runtime release requires only v6 deployment bindings.')
    values: dict[str, dict[str, object]] = {
        'agent_instruction': {
            'prompt_version': MOTOR_CLAIMANT_PROMPT_ID,
            'purpose': 'claimant_agent',
            'composition_mode': 'single',
            'system_prompt': load_motor_claimant_prompt(),
        },
        'agent_tool_policy': {
            'policy_version': 'northwind-fnol-agent-tools-v1',
            'allowed_action_codes': list(registered_actions()),
            'allowed_tool_names': list(registered_agent_tool_names()),
        },
        'agent_rule': {
            'rules_version': 'northwind-fnol-controlled-rules-v1',
            'disabled_rule_ids': [],
            'observation_rule_ids': [],
        },
        'feature': {
            'feature_version': 'northwind-fnol-agent-features-v1',
            'model_assisted_turns': True,
            'knowledge_retrieval': True,
            'external_service_offers': True,
        },
    }
    for binding in bindings:
        values[f'model:{binding.profile_id}'] = _model_values(
            binding,
            prompt_version=MOTOR_CLAIMANT_PROMPT_ID,
        )
    return values


def repository_v7_values(
    bindings: Sequence[ModelRuntimeBinding],
) -> dict[str, dict[str, object]]:
    if {binding.prompt_version for binding in bindings} != {CLAIMANT_V7_PROMPT_ID}:
        raise ValueError('A v7 Runtime release requires only v7 deployment bindings.')
    manifest = load_prompt_manifest()
    fragment_contents = load_fragment_contents(manifest)
    model_values = {
        binding.profile_id: _model_values(binding, prompt_version=CLAIMANT_V7_PROMPT_ID)
        for binding in bindings
    }
    values: dict[str, dict[str, object]] = {
        'agent_instruction': {
            'prompt_version': CLAIMANT_V7_PROMPT_ID,
            'purpose': 'claimant_agent',
            'composition_mode': 'fragmented',
            'manifest_version': manifest.prompt_pack_version,
            'fragments': [
                {
                    **item.model_dump(mode='json'),
                    'content': fragment_contents[item.fragment_id],
                }
                for item in manifest.fragments
            ],
        },
        'agent_tool_policy': {
            'policy_version': 'northwind-fnol-agent-tools-v7',
            'allowed_action_codes': list(registered_actions()),
            'allowed_tool_names': list(registered_agent_tool_names()),
            'request_profiles': [
                item.model_dump(mode='json') for item in registered_request_profiles()
            ],
            'provider_capabilities': {
                profile_id: provider_capability(
                    ModelRuntimeConfiguration.model_validate(model_value)
                ).model_dump(mode='json')
                for profile_id, model_value in model_values.items()
            },
            'schema_registry': load_response_schemas(),
        },
        'agent_rule': {
            'rules_version': 'northwind-fnol-controlled-rules-v7',
            'disabled_rule_ids': [],
            'observation_rule_ids': [],
            'route_policy_version': 'northwind-turn-router-v7',
            'context_catalogue_version': 'northwind-context-catalogue-v7',
            'context_budget_policy': ContextBudgetPolicy().model_dump(mode='json'),
            'deterministic_responses': {
                'unresolved_family': (
                    'Please choose the single loss you want to report first: motor, home, or '
                    'contents.'
                ),
                'context_budget_exceeded': (
                    'I need one shorter detail before I can continue this report safely.'
                ),
            },
        },
        'feature': {
            'feature_version': 'northwind-fnol-agent-features-v7',
            'model_assisted_turns': True,
            'knowledge_retrieval': True,
            'external_service_offers': True,
            'fragmented_prompt': True,
            'budgeted_context': True,
            'narrow_schema': True,
            'verified_rolling_summary': True,
            'isolated_execution': True,
            'cache_layout_version': 'northwind-cache-layout-v1',
        },
    }
    for profile_id, model_value in model_values.items():
        values[f'model:{profile_id}'] = model_value
    return values


def _published_exact(
    repository: ConfigurationRepository,
    domain: str,
    values: Mapping[str, object],
) -> ConfigurationRecord | None:
    for record in repository.list_configurations(domain):
        if record.state is ConfigurationState.PUBLISHED and record.values == values:
            return record
    return None


def _publish_configuration(
    repository: ConfigurationRepository,
    *,
    domain: str,
    values: dict[str, object],
    bindings: Sequence[ModelRuntimeBinding],
) -> ConfigurationRecord:
    existing = _published_exact(repository, domain, values)
    if existing is not None:
        return existing
    created = configuration_service.create(
        repository,
        ConfigurationCreate(
            domain=domain,
            impact=ConfigurationImpact.HIGH,
            values=values,
            reason='Install the repository-defined initial Runtime release.',
        ),
        _AUTHOR,
    )
    validated = configuration_service.validate(
        repository,
        created.configuration_id,
        ValidationRequest(
            scenario_results=[
                ValidationScenarioResult(
                    scenario_id='repository-initial-runtime-release',
                    outcome='passed',
                    evidence=_VALIDATION_EVIDENCE,
                )
            ]
        ),
        _AUTHOR,
        created.revision,
        model_runtime_bindings=bindings,
    )
    configuration_service.approve(
        repository,
        validated.configuration_id,
        ApprovalRequest(
            decision=ApprovalDecision.APPROVED,
            reason='Approve the reviewed repository initial Runtime contract.',
        ),
        _REVIEWER,
        validated.revision,
    )
    return configuration_service.publish(
        repository,
        validated.configuration_id,
        TransitionRequest(reason='Activate the repository initial Runtime configuration.'),
        _REVIEWER,
        validated.revision,
    )


def install_initial_runtime_release(
    settings: Settings,
    configurations: ConfigurationRepository,
    releases: ReleaseSetRepository,
    knowledge: KnowledgeAdminRepository,
) -> ReleaseSetRecord | None:
    """Install the reviewed initial Release Set only for a never-initialised scope.

    Existing Release Set history is authoritative, including an intentionally withdrawn
    or inactive history. This function never repairs or overrides that history.

    Args:
        settings: Runtime scope and repository-approved model bindings.
        configurations: Control Plane configuration repository.
        releases: Control Plane Release Set repository.
        knowledge: Control Plane knowledge repository used to validate release references.

    Returns:
        The active initial release, the existing active release, or ``None`` when the
        scope has inactive Release Set history that must remain under operator control.

    Raises:
        ValueError: If the repository model catalogue omits a required current profile.
    """

    existing = releases.list_release_sets(
        environment=settings.environment,
        runtime_profile=settings.data_runtime_profile.value,
    )
    if existing:
        return releases.active(settings.environment, settings.data_runtime_profile.value)

    bindings = settings.model_runtime_bindings
    profile_ids = {binding.profile_id for binding in bindings}
    if not _REQUIRED_MODEL_PROFILES.issubset(profile_ids):
        missing = ', '.join(sorted(_REQUIRED_MODEL_PROFILES - profile_ids))
        raise ValueError(f'The initial Runtime release is missing required models: {missing}.')

    prompt_versions = {binding.prompt_version for binding in bindings}
    if prompt_versions == {CLAIMANT_V7_PROMPT_ID}:
        release_values = repository_v7_values(bindings)
    elif prompt_versions == {MOTOR_CLAIMANT_PROMPT_ID}:
        release_values = repository_v6_values(bindings)
    else:
        raise ValueError('The initial Runtime release cannot mix Prompt versions.')

    records: dict[str, ConfigurationRecord] = {}
    for slot, values in release_values.items():
        domain = 'model' if slot.startswith('model:') else slot
        records[slot] = _publish_configuration(
            configurations,
            domain=domain,
            values=values,
            bindings=bindings,
        )

    created = release_set_service.create(
        releases,
        configurations,
        knowledge,
        ReleaseSetCreate(
            environment=settings.environment,
            runtime_profile=settings.data_runtime_profile.value,
            configuration_refs={
                slot: ConfigurationReference(
                    configuration_id=record.configuration_id,
                    revision=record.revision,
                )
                for slot, record in records.items()
            },
            reason='Install the repository-defined initial Agent Runtime release.',
        ),
        _AUTHOR,
    )
    validated = release_set_service.validate(
        releases,
        configurations,
        knowledge,
        created.release_set_id,
        ReleaseSetValidationRequest(
            scenario_results=[
                ValidationScenarioResult(
                    scenario_id='repository-initial-runtime-release',
                    outcome='passed',
                    evidence=_VALIDATION_EVIDENCE,
                )
            ]
        ),
        _AUTHOR,
        created.revision,
    )
    return release_set_service.publish(
        releases,
        validated.release_set_id,
        'Activate the repository-defined initial Agent Runtime release.',
        _AUTHOR,
        validated.revision,
    )
