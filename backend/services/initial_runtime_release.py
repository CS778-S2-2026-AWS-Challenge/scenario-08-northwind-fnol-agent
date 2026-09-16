"""Install the repository-defined initial Agent Runtime release."""

from collections.abc import Mapping, Sequence

from backend.core.config import Settings
from backend.domain.agent_action_registry import registered_actions
from backend.domain.configuration import (
    ApprovalDecision,
    ApprovalRequest,
    ConfigurationCreate,
    ConfigurationImpact,
    ConfigurationRecord,
    ConfigurationState,
    ModelRuntimeBinding,
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
from backend.prompts import MOTOR_CLAIMANT_PROMPT_ID, load_motor_claimant_prompt
from backend.repositories.configuration import ConfigurationRepository
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.repositories.release_set import ReleaseSetRepository
from backend.services import configuration as configuration_service
from backend.services import release_sets as release_set_service
from backend.services.runtime_agent_policy import registered_agent_tool_names

_AUTHOR = 'repository-initial-release-author'
_REVIEWER = 'repository-initial-release-reviewer'
_REQUIRED_MODEL_PROFILES = frozenset({'qwen-local', 'nowcoding-gpt55'})
_VALIDATION_EVIDENCE = (
    'Repository-defined initial Runtime release passed structural and binding validation.'
)


def _model_values(binding: ModelRuntimeBinding) -> dict[str, object]:
    values = binding.model_dump(mode='json')
    values.update({'evaluation_status': 'configured', 'timeout_seconds': 30.0})
    return values


def _initial_values(bindings: Sequence[ModelRuntimeBinding]) -> dict[str, dict[str, object]]:
    values: dict[str, dict[str, object]] = {
        'agent_instruction': {
            'prompt_version': MOTOR_CLAIMANT_PROMPT_ID,
            'purpose': 'claimant_agent',
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
        values[f'model:{binding.profile_id}'] = _model_values(binding)
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

    records: dict[str, ConfigurationRecord] = {}
    for slot, values in _initial_values(bindings).items():
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
