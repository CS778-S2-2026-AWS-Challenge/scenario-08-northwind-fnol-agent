"""Load and compile immutable v7 Prompt fragments in stable order."""

import json
from importlib.resources import files
from math import ceil

from backend.domain.agent_context_runtime import TurnRoute
from backend.domain.prompt_pack import (
    PromptBundle,
    PromptFragmentDefinition,
    PromptFragmentRef,
    PromptPackManifest,
)

_KIND_ORDER = {'core': 0, 'family': 1, 'task': 2, 'capability': 3}
_SCHEMA_FILES = {
    'claimant.answer.v1': 'answer.json',
    'claimant.intake-patch.v1': 'intake.json',
    'claimant.external-offer.v1': 'external-offer.json',
    'claimant.evidence-action.v1': 'evidence-action.json',
    'claimant.handoff.v1': 'handoff.json',
    'claimant.claim-creation.v1': 'claim-creation.json',
    'claimant.sourced-summary.v1': 'sourced-summary.json',
}


def estimate_tokens(value: str) -> int:
    """Return a conservative provider-neutral estimate with no tokenizer dependency."""

    return max(1, ceil(len(value.encode('utf-8')) / 3))


def load_prompt_manifest() -> PromptPackManifest:
    payload = json.loads(
        files('backend.prompts').joinpath('v7/manifest.json').read_text(encoding='utf-8')
    )
    return PromptPackManifest.model_validate(payload)


def load_response_schema(schema_id: str) -> dict[str, object]:
    try:
        filename = _SCHEMA_FILES[schema_id]
    except KeyError as error:
        raise ValueError(f'Unknown v7 response schema: {schema_id}.') from error
    payload = json.loads(
        files('backend.prompts').joinpath(f'v7/schema/{filename}').read_text(encoding='utf-8')
    )
    if not isinstance(payload, dict):
        raise ValueError('A v7 response schema must be a JSON object.')
    return payload


def load_response_schemas() -> dict[str, dict[str, object]]:
    return {schema_id: load_response_schema(schema_id) for schema_id in sorted(_SCHEMA_FILES)}


def load_fragment_contents(
    manifest: PromptPackManifest | None = None,
) -> dict[str, str]:
    selected_manifest = manifest or load_prompt_manifest()
    return {
        definition.fragment_id: (
            files('backend.prompts')
            .joinpath(f'v7/{definition.path}')
            .read_text(encoding='utf-8')
            .strip()
        )
        for definition in selected_manifest.fragments
    }


def _initial_fragment_ids(route: TurnRoute) -> set[str]:
    family = route.product_family or 'unresolved-family'
    fragment_ids = {
        'core.authority',
        'core.safety',
        'core.response-style',
        'core.provenance',
        f'family.{family}',
        f'task.{route.task.value.replace("_", "-")}',
    }
    fragment_ids.update(f'capability.{item}' for item in route.capability_ids)
    return fragment_ids


def _validate_applicability(
    definition: PromptFragmentDefinition,
    route: TurnRoute,
) -> None:
    applicability = definition.applies_when
    if applicability.product_family and route.product_family not in applicability.product_family:
        raise ValueError(
            f'Prompt fragment {definition.fragment_id} does not apply to product family '
            f'{route.product_family!r}.'
        )
    if applicability.tasks and route.task.value not in applicability.tasks:
        raise ValueError(
            f'Prompt fragment {definition.fragment_id} does not apply to task {route.task.value!r}.'
        )
    if applicability.capability_ids and not set(applicability.capability_ids).intersection(
        route.capability_ids
    ):
        raise ValueError(
            f'Prompt fragment {definition.fragment_id} does not apply to the selected capabilities.'
        )


def compose_prompt(
    route: TurnRoute,
    manifest: PromptPackManifest | None = None,
    fragment_contents: dict[str, str] | None = None,
) -> PromptBundle:
    selected_manifest = manifest or load_prompt_manifest()
    by_id = {item.fragment_id: item for item in selected_manifest.fragments}
    selected_ids = _initial_fragment_ids(route)
    missing = selected_ids - set(by_id)
    if missing:
        raise ValueError(f'Prompt route references unknown fragments: {sorted(missing)}.')

    def include_requirements(fragment: PromptFragmentDefinition) -> None:
        for required_id in fragment.requires:
            if required_id not in selected_ids:
                selected_ids.add(required_id)
                include_requirements(by_id[required_id])

    for fragment_id in tuple(selected_ids):
        include_requirements(by_id[fragment_id])

    for fragment_id in selected_ids:
        _validate_applicability(by_id[fragment_id], route)
        conflicts = set(by_id[fragment_id].conflicts_with) & selected_ids
        if conflicts:
            raise ValueError(f'Prompt fragments conflict: {fragment_id} and {sorted(conflicts)}.')

    selected = sorted(
        (by_id[fragment_id] for fragment_id in selected_ids),
        key=lambda item: (_KIND_ORDER[item.kind], -item.priority, item.fragment_id),
    )
    contents: list[str] = []
    refs: list[PromptFragmentRef] = []
    for definition in selected:
        content = (
            fragment_contents[definition.fragment_id]
            if fragment_contents is not None
            else files('backend.prompts')
            .joinpath(f'v7/{definition.path}')
            .read_text(encoding='utf-8')
            .strip()
        )
        token_count = estimate_tokens(content)
        if token_count > definition.max_tokens:
            raise ValueError(f'Prompt fragment {definition.fragment_id} exceeds its token limit.')
        contents.append(f'[{definition.fragment_id}@{definition.version}]\n{content}')
        refs.append(
            PromptFragmentRef(
                fragment_id=definition.fragment_id,
                version=definition.version,
                estimated_tokens=token_count,
            )
        )
    family = route.product_family or 'unresolved-family'
    suffix = ':'.join(route.capability_ids)
    bundle_id = f'claimant-v7:{family}:{route.task.value}' + (f':{suffix}' if suffix else '')
    instruction = '\n\n'.join(contents)
    return PromptBundle(
        prompt_bundle_id=bundle_id,
        prompt_pack_version=selected_manifest.prompt_pack_version,
        fragment_refs=refs,
        compiled_instruction=instruction,
        estimated_tokens=sum(item.estimated_tokens for item in refs),
    )
