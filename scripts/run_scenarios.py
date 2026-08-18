import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.repositories.fixture import FixtureRepository  # noqa: E402
from backend.repositories.scenario_loader import load_scenarios, seed_scenario  # noqa: E402

SCENARIO_DIRECTORY = REPOSITORY_ROOT / 'backend' / 'demo_data' / 'scenarios'


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario_id: str
    claim_id: str
    sessions: int
    evidence: int
    retrievals: int
    review_signals: int
    messages: int
    handoffs: int


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
                retrievals=len(
                    repository.list_retrieval_records(claim.claim_id, claim.customer_id)
                ),
                review_signals=len(
                    repository.list_review_signals(claim.claim_id, claim.customer_id)
                ),
                messages=len(
                    repository.list_messages(
                        claim.claim_id,
                        claim.active_session_id or '',
                        claim.customer_id,
                    )
                ),
                handoffs=len(repository.list_handoffs(claim.claim_id, claim.customer_id)),
            )
        )
    return results


if __name__ == '__main__':
    for result in run_scenarios():
        print(
            f'PASS {result.scenario_id}: claim={result.claim_id} '
            f'sessions={result.sessions} evidence={result.evidence} '
            f'retrievals={result.retrievals} review_signals={result.review_signals} '
            f'messages={result.messages} '
            f'handoffs={result.handoffs}'
        )
