from dataclasses import dataclass
from pathlib import Path

from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import load_scenarios, seed_scenario

SCENARIO_DIRECTORY = Path(__file__).parents[1] / 'tests' / 'fixtures' / 'scenarios'


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario_id: str
    claim_id: str
    sessions: int
    evidence: int
    messages: int


def run_scenarios(directory: Path = SCENARIO_DIRECTORY) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for scenario in load_scenarios(directory):
        repository = FixtureRepository()
        seed_scenario(repository, scenario)
        claim = repository.get_claim(scenario.claim.claim_id, scenario.claim.customer_id)
        if claim is None:
            raise RuntimeError(f'{scenario.scenario_id} did not create its claim.')
        results.append(
            ScenarioResult(
                scenario_id=scenario.scenario_id,
                claim_id=claim.claim_id,
                sessions=len(repository.list_sessions_for_claim(claim.claim_id, claim.customer_id)),
                evidence=len(repository.list_evidence(claim.claim_id, claim.customer_id)),
                messages=len(
                    repository.list_messages(
                        claim.claim_id,
                        claim.active_session_id or '',
                        claim.customer_id,
                    )
                ),
            )
        )
    return results


if __name__ == '__main__':
    for result in run_scenarios():
        print(
            f'PASS {result.scenario_id}: claim={result.claim_id} '
            f'sessions={result.sessions} evidence={result.evidence} messages={result.messages}'
        )
