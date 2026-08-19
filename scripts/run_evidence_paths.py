import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.services.evidence_fixtures import (  # noqa: E402
    EvidenceFixtureService,
    check_paths,
    describe_paths,
)


def main() -> int:
    service = EvidenceFixtureService()
    for line in describe_paths(service):
        print(line)

    violations = check_paths(service)
    for violation in violations:
        print(f'FAIL {violation.origin} {violation.evidence_id}: {violation.reason}')
    return 1 if violations else 0


if __name__ == '__main__':
    raise SystemExit(main())
