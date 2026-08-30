from dataclasses import dataclass
from pathlib import Path

from backend.core.errors import ApiError
from backend.repositories.protocols import PersistenceRepository
from backend.repositories.scenario_loader import (
    ScenarioFixture,
    load_mvp_journey_scenarios,
    load_scenario,
    seed_scenario,
)

SCENARIO_DIRECTORY = Path(__file__).resolve().parents[1] / 'demo_data' / 'scenarios'

ADDITIONAL_WORKBENCH_DEMO_SCENARIO_IDS = ('AT-10-controlled-assessor',)


@dataclass(frozen=True, slots=True)
class DemoScenarioSeedResult:
    scenario_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]


def load_workbench_demo_scenarios(
    directory: Path = SCENARIO_DIRECTORY,
) -> tuple[ScenarioFixture, ...]:
    """Load the five canonical MVP paths plus bounded integration demonstrations."""

    journey_scenarios = load_mvp_journey_scenarios(directory)
    additional_scenarios = [
        load_scenario(directory / f'{scenario_id}.json')
        for scenario_id in ADDITIONAL_WORKBENCH_DEMO_SCENARIO_IDS
    ]
    return (*journey_scenarios, *additional_scenarios)


def seed_workbench_demo_scenarios(repository: PersistenceRepository) -> DemoScenarioSeedResult:
    if repository.list_claims_internal():
        raise ApiError(
            status_code=409,
            code='DEMO_SEED_REQUIRES_EMPTY_QUEUE',
            message='Reset the local demo before loading the workbench scenario queue.',
        )

    scenarios = load_workbench_demo_scenarios()
    claim_ids: list[str] = []
    for scenario in scenarios:
        seed_scenario(repository, scenario)
        claim_ids.append(scenario.claim.claim_id)
    return DemoScenarioSeedResult(
        scenario_ids=tuple(scenario.scenario_id for scenario in scenarios),
        claim_ids=tuple(claim_ids),
    )
