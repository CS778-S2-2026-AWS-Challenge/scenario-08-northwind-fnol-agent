"""Decide which CircleCI workflows a pipeline creates, before any quality job starts.

The setup workflow runs this script and passes its JSON output as pipeline parameters to
``.circleci/continue_config.yml``. A job that is not needed is never created.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Sequence

from scripts.select_backend_tests import FULL_SUITE_PATHS, FULL_SUITE_PREFIXES

# Each area runs when a changed path matches its pattern.
AREAS: dict[str, re.Pattern[str]] = {
    'run-backend': re.compile(
        r'^(backend/|tests/|scripts/.*\.py$|pyproject\.toml$|'
        r'docs/openapi\.snapshot\.json$|docs/contracts/audit-event\.schema\.json$)'
    ),
    'run-customer': re.compile(r'^(customer/|frontend/shared/)'),
    'run-workbench': re.compile(r'^(workbench/|frontend/shared/)'),
    'run-admin': re.compile(r'^(admin/|frontend/shared/)'),
    'run-browser-evidence': re.compile(
        r'^(customer/|workbench/|backend/api/realtime\.py$|backend/api/workbench|'
        r'backend/services/|tests/browser/)'
    ),
    'run-automation': re.compile(r'^(automation/github-automation/|\.github/scripts/)'),
    'run-docs': re.compile(r'(\.md$|^docs/)'),
}
# A change to the CI definition itself exercises every job.
CI_DEFINITION = re.compile(r'^(\.circleci/|scripts/ci_plan\.py$)')


def plan(changed: Sequence[str], *, branch: str, scheduled: bool) -> dict[str, bool]:
    """Return the continuation pipeline parameters for one pipeline.

    Args:
        changed: Paths changed relative to the merge base with ``main``.
        branch: Branch the pipeline runs on.
        scheduled: Whether the daily schedule triggered the pipeline.
    """

    if scheduled:
        areas = {area: False for area in AREAS} | {'run-backend': True}
        return areas | {'backend-full': True, 'scheduled': True}
    if branch == 'main':
        return {area: True for area in AREAS} | {'backend-full': True, 'scheduled': False}
    paths = [path.replace('\\', '/') for path in changed]
    if any(CI_DEFINITION.match(path) for path in paths):
        return {area: True for area in AREAS} | {'backend-full': True, 'scheduled': False}
    areas = {area: any(pattern.search(path) for path in paths) for area, pattern in AREAS.items()}
    # Shared test infrastructure can change any test outcome: run the suite in parallel.
    full = any(path in FULL_SUITE_PATHS or path.startswith(FULL_SUITE_PREFIXES) for path in paths)
    return areas | {'backend-full': full, 'scheduled': False}


def _changed_paths() -> list[str]:
    base = subprocess.run(
        ['git', 'merge-base', 'origin/main', 'HEAD'], check=True, capture_output=True, text=True
    ).stdout.strip()
    output = subprocess.run(
        ['git', 'diff', '--name-only', base, 'HEAD'], check=True, capture_output=True, text=True
    ).stdout
    return [line for line in output.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--branch', required=True)
    parser.add_argument('--scheduled', choices=('true', 'false'), default='false')
    parser.add_argument('--out', required=True, help='parameters JSON path')
    args = parser.parse_args()
    scheduled = args.scheduled == 'true'
    changed = [] if scheduled or args.branch == 'main' else _changed_paths()
    parameters = plan(changed, branch=args.branch, scheduled=scheduled)
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump(parameters, handle)
    print(json.dumps(parameters, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
