import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.repositories.scenario_loader import (  # noqa: E402
    claimant_evidence_for,
    load_evidence_path_fixtures,
)

FIXTURE_PATH = REPOSITORY_ROOT / 'tests' / 'fixtures' / 'evidence' / 'path-entry-visibility.json'


if __name__ == '__main__':
    fixture_set = load_evidence_path_fixtures(FIXTURE_PATH)
    for entry in fixture_set.entries:
        print(
            f'PASS {entry.scenario_id}: path={entry.business_path.value} '
            f'evidence={len(entry.evidence)} state={entry.claim_state.evidence.value} '
            f'received={entry.evidence_summary.received} '
            f'pending={entry.evidence_summary.pending} '
            f'attention={entry.evidence_summary.needs_attention} '
            f'claimant={len(claimant_evidence_for(entry))}'
        )
