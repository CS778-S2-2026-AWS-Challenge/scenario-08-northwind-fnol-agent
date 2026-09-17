"""Immutable Prompt Fragment Pack contracts."""

from typing import Literal

from pydantic import Field, model_validator

from backend.domain.agent_context_runtime import ContextLoadMode
from backend.domain.models import ContractModel


class PromptApplicability(ContractModel):
    product_family: list[Literal['motor', 'home', 'contents']] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list, max_length=20)
    capability_ids: list[str] = Field(default_factory=list, max_length=20)


class PromptFragmentDefinition(ContractModel):
    fragment_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=50)
    path: str = Field(min_length=1, max_length=240)
    kind: Literal['core', 'family', 'task', 'capability']
    load_mode: ContextLoadMode
    applies_when: PromptApplicability = Field(default_factory=PromptApplicability)
    requires: list[str] = Field(default_factory=list, max_length=20)
    conflicts_with: list[str] = Field(default_factory=list, max_length=20)
    priority: int = Field(ge=0, le=1000)
    max_tokens: int = Field(ge=1, le=3000)

    @model_validator(mode='after')
    def prevent_self_links(self) -> 'PromptFragmentDefinition':
        if self.fragment_id in self.requires or self.fragment_id in self.conflicts_with:
            raise ValueError('A Prompt fragment cannot require or conflict with itself.')
        return self


class PromptPackManifest(ContractModel):
    prompt_pack_version: str = Field(min_length=1, max_length=100)
    fragments: list[PromptFragmentDefinition] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def validate_graph(self) -> 'PromptPackManifest':
        by_id = {item.fragment_id: item for item in self.fragments}
        if len(by_id) != len(self.fragments):
            raise ValueError('Prompt fragment IDs must be unique.')
        for item in self.fragments:
            missing = (set(item.requires) | set(item.conflicts_with)) - set(by_id)
            if missing:
                raise ValueError(f'Prompt fragment {item.fragment_id} references an unknown ID.')

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(fragment_id: str) -> None:
            if fragment_id in visiting:
                raise ValueError('Prompt fragment requirements contain a cycle.')
            if fragment_id in visited:
                return
            visiting.add(fragment_id)
            for required in by_id[fragment_id].requires:
                visit(required)
            visiting.remove(fragment_id)
            visited.add(fragment_id)

        for fragment_id in by_id:
            visit(fragment_id)
        return self


class PromptFragmentRef(ContractModel):
    fragment_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=50)
    estimated_tokens: int = Field(ge=0)


class PromptBundle(ContractModel):
    prompt_bundle_id: str = Field(min_length=1, max_length=300)
    prompt_pack_version: str = Field(min_length=1, max_length=100)
    fragment_refs: list[PromptFragmentRef] = Field(min_length=1, max_length=30)
    compiled_instruction: str = Field(min_length=1, max_length=50_000)
    estimated_tokens: int = Field(ge=1)
