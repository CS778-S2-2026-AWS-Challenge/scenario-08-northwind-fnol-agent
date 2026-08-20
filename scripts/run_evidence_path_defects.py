import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.services.evidence_visibility_check import (  # noqa: E402
    check_path_evidence,
    describe,
    paths_checked,
)


def main() -> int:
    defects = check_path_evidence()
    print(f'Checked {paths_checked()} business paths.')
    print(describe(defects))
    return 1 if defects else 0


if __name__ == '__main__':
    raise SystemExit(main())
