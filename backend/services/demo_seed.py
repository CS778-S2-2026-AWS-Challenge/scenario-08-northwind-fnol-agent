from pathlib import Path

from backend.repositories.protocols import PersistenceRepository
from backend.repositories.scenario_loader import load_scenario, seed_scenario

SCENARIO_DIRECTORY = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures' / 'scenarios'

# Stable identifiers for the handoff queue/context-card baseline (urgent, human-request,
# professional-review); see docs/day3-implementation-map.md.
HANDOFF_QUEUE_SCENARIO_IDS = (
    'AT-02-coverage-ambiguity',
    'AT-04-urgent',
    'AT-05-human-request',
)


def seed_handoff_queue_scenarios(repository: PersistenceRepository) -> list[str]:
    claim_ids: list[str] = []
    for scenario_id in HANDOFF_QUEUE_SCENARIO_IDS:
        scenario = load_scenario(SCENARIO_DIRECTORY / f'{scenario_id}.json')
        seed_scenario(repository, scenario)
        claim_ids.append(scenario.claim.claim_id)
    return claim_ids
