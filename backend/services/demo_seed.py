from pathlib import Path

from backend.core.errors import ApiError
from backend.repositories.protocols import PersistenceRepository
from backend.repositories.scenario_loader import load_scenario, seed_scenario

SCENARIO_DIRECTORY = Path(__file__).resolve().parents[1] / 'demo_data' / 'scenarios'

# Stable canonical scenarios for the mixed staff-workbench demonstration queue.
WORKBENCH_DEMO_SCENARIO_IDS = (
    'AT-02-coverage-ambiguity',
    'AT-04-urgent',
    'AT-05-human-request',
    'AT-10-controlled-assessor',
)


def seed_workbench_demo_scenarios(repository: PersistenceRepository) -> list[str]:
    if repository.list_claims_internal():
        raise ApiError(
            status_code=409,
            code='DEMO_SEED_REQUIRES_EMPTY_QUEUE',
            message='Reset the local demo before loading the workbench scenario queue.',
        )

    claim_ids: list[str] = []
    for scenario_id in WORKBENCH_DEMO_SCENARIO_IDS:
        scenario = load_scenario(SCENARIO_DIRECTORY / f'{scenario_id}.json')
        seed_scenario(repository, scenario)
        claim_ids.append(scenario.claim.claim_id)
    return claim_ids
