import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.repositories.scenario_loader import (  # noqa: E402
    load_evidence_lifecycle_fixtures,
)

FIXTURE_PATH = REPOSITORY_ROOT / 'tests' / 'fixtures' / 'evidence' / 'evidence-lifecycle.json'


if __name__ == '__main__':
    fixture_set = load_evidence_lifecycle_fixtures(FIXTURE_PATH)
    for fixture in fixture_set.fixtures:
        print(
            f'PASS {fixture.fixture_id}: stage={fixture.lifecycle_stage.value} '
            f'source={fixture.evidence.source.value} visibility={fixture.visibility.value} '
            f'next={fixture.expected_state_change.evidence_status.value}'
        )
