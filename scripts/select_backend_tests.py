"""Select the smallest safe backend test set for a pull request.

The selector is intentionally conservative: shared contracts and composition
changes select the complete suite, while narrow changes select their direct
consumer tests. It never returns an empty set for a backend change.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

FULL_TESTS = ('tests',)
TOOLING_FULL_PATHS = {
    '.circleci/config.yml',
    '.github/workflows/ci.yml',
    'pyproject.toml',
    'backend/requirements-dev.txt',
    'scripts/select_backend_tests.py',
}


@dataclass(frozen=True)
class TestSelection:
    """Selected pytest paths and the reason for the selection."""

    mode: str
    tests: tuple[str, ...]
    reason: str


def select_tests(changed_paths: Sequence[str], *, full: bool = False) -> TestSelection:
    """Select tests from repository-relative changed paths.

    Args:
        changed_paths: Paths changed relative to the target branch.
        full: Force the complete backend suite, used for ``main`` and shared changes.

    Returns:
        A deterministic selection with ``full``, ``scoped``, or ``skip`` mode.
    """

    paths = tuple(sorted(set(_normalise_path(path) for path in changed_paths)))
    if full:
        return TestSelection('full', FULL_TESTS, 'main branch or explicitly forced full suite')

    if not paths:
        return TestSelection('skip', (), 'no changed paths')

    if set(paths) & TOOLING_FULL_PATHS:
        return TestSelection('full', FULL_TESTS, 'CI, selector, dependency, or test-tooling change')

    selected: set[str] = set()
    backend_changed = False
    shared_change = False
    for raw_path in paths:
        path = PurePosixPath(raw_path.replace('\\', '/'))
        path_text = path.as_posix()
        if path_text == 'docs/vp-field-branch-mapping.md':
            selected.add('tests/test_branch_registry.py')
        if path_text in {'backend/requirements-dev.txt', 'pyproject.toml'}:
            shared_change = True
        if path_text.startswith(('backend/domain/', 'backend/repositories/protocols.py')):
            backend_changed = True
        if path_text in {
            'backend/app.py',
            'backend/main.py',
            'backend/core/runtime_profiles.py',
            'backend/core/config.py',
            'backend/repositories/protocols.py',
            'backend/domain/models.py',
        }:
            shared_change = True
        if path_text.startswith('backend/'):
            backend_changed = True
        if path_text.startswith('tests/') and path_text.endswith('.py'):
            selected.add(path_text)
        if path_text == 'tests/conftest.py' or path_text.startswith(
            ('tests/fixtures/', 'tests/helpers/', 'tests/support/')
        ):
            shared_change = True

        if path_text.startswith(('backend/api/claims.py', 'backend/services/claims.py')):
            selected.update(
                {
                    'tests/test_claim_api.py',
                    'tests/test_claim_creation_journey.py',
                    'tests/test_claim_transaction_boundary.py',
                }
            )
        elif path_text.startswith(('backend/api/evidence.py', 'backend/services/evidence.py')):
            selected.update(
                {
                    'tests/test_evidence_api.py',
                    'tests/test_evidence_storage_boundary.py',
                    'tests/test_evidence_visibility_check.py',
                }
            )
        elif path_text.startswith(('backend/api/workbench.py', 'backend/api/handoffs.py')):
            selected.update(
                {
                    'tests/test_workbench_api.py',
                    'tests/test_handoff_api.py',
                    'tests/test_handoff_dispatch.py',
                    'tests/test_handoff_persistence_ownership.py',
                }
            )
        elif path_text.startswith(
            (
                'backend/api/admin.py',
                'backend/domain/configuration.py',
                'backend/services/configuration.py',
            )
        ):
            selected.add('tests/test_admin_api.py')
        elif path_text.startswith(
            (
                'backend/api/identity.py',
                'backend/adapters/identity.py',
                'backend/services/identity.py',
            )
        ):
            selected.update({'tests/test_identity_api.py', 'tests/test_identity_runtime.py'})
        elif path_text.startswith(
            (
                'backend/services/external_services.py',
                'backend/services/integrations.py',
                'backend/domain/external_services.py',
            )
        ):
            selected.update(
                {
                    'tests/test_integrations.py',
                    'tests/test_external_service_entry.py',
                    'tests/test_external_service_validation.py',
                    'tests/test_external_task_api.py',
                    'tests/test_external_task_request.py',
                    'tests/test_external_task_result.py',
                    'tests/test_external_task_result_verification.py',
                    'tests/test_external_task_retry.py',
                    'tests/test_external_task_status.py',
                    'tests/test_external_task_transition.py',
                }
            )
        elif path_text.startswith('backend/repositories/'):
            selected.update(
                {
                    'tests/test_repository.py',
                    'tests/test_persistence_integration.py',
                    'tests/test_mongodb_repository.py',
                    'tests/test_claim_save_transaction_boundary.py',
                    'tests/test_claim_transaction_boundary.py',
                }
            )
        elif (
            path_text == 'backend/domain/audit.py'
            or path_text == 'scripts/export_audit_contract.py'
        ):
            selected.add('tests/test_audit_contract.py')
        elif path_text.startswith(
            ('backend/core/', 'backend/adapters/', 'backend/services/', 'backend/domain/')
        ):
            shared_change = True

    if shared_change:
        return TestSelection(
            'full', FULL_TESTS, 'shared contract, runtime, dependency, or domain change'
        )
    if backend_changed and not selected:
        return TestSelection('full', FULL_TESTS, 'backend change has no safe narrow mapping')
    if selected:
        return TestSelection('scoped', tuple(sorted(selected)), 'direct consumers of changed paths')
    return TestSelection('skip', (), 'no backend behavior changed')


def _normalise_path(path: str) -> str:
    return PurePosixPath(path.replace('\\', '/')).as_posix()


def changed_python_files(changed: Sequence[str]) -> tuple[str, ...]:
    """Return changed Python files for scoped static checks."""

    return tuple(
        sorted(
            {
                normalised
                for path in changed
                if (normalised := _normalise_path(path)).endswith('.py')
            }
        )
    )


def needs_openapi_check(changed: Sequence[str]) -> bool:
    """Return whether the changed paths can alter the generated OpenAPI schema."""

    paths = {_normalise_path(path) for path in changed}
    return bool(
        paths & {'backend/app.py', 'backend/main.py', 'scripts/export_openapi.py'}
        or any(path.startswith('backend/api/') for path in paths)
        or any(path.startswith('backend/domain/') for path in paths)
        or 'docs/openapi.snapshot.json' in paths
    )


def needs_audit_contract_check(changed: Sequence[str]) -> bool:
    """Return whether the AuditEvent contract or its snapshot changed."""

    paths = {_normalise_path(path) for path in changed}
    return bool(
        paths
        & {
            'backend/domain/audit.py',
            'scripts/export_audit_contract.py',
            'docs/contracts/audit-event.schema.json',
        }
    )


def changed_paths() -> tuple[str, ...]:
    """Read changed paths against the target branch from the local checkout."""

    completed = subprocess.run(
        ['git', 'diff', '--name-only', '--diff-filter=ACMR', 'origin/main...HEAD'],
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in completed.stdout.splitlines() if line)


def running_on_main() -> bool:
    """Return whether CI is testing the main branch rather than a pull request."""

    github_main = (
        os.getenv('GITHUB_REF') == 'refs/heads/main'
        and os.getenv('GITHUB_EVENT_NAME') != 'pull_request'
    )
    circle_main = os.getenv('CIRCLE_BRANCH') == 'main' and not os.getenv('CIRCLE_PULL_REQUEST')
    return github_main or circle_main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', action='store_true', help='print only the selection mode')
    parser.add_argument('--tests', action='store_true', help='print selected pytest paths')
    parser.add_argument('--python-files', action='store_true', help='print changed Python files')
    parser.add_argument('--needs-openapi', action='store_true', help='print OpenAPI check need')
    parser.add_argument(
        '--needs-audit-contract', action='store_true', help='print AuditEvent check need'
    )
    parser.add_argument('--full', action='store_true', help='force the complete suite')
    args = parser.parse_args()
    paths = changed_paths()
    on_main = args.full or running_on_main()
    selection = select_tests(paths, full=on_main)
    if args.mode:
        print(selection.mode)
    elif args.tests:
        print('\n'.join(selection.tests))
    elif args.python_files:
        print('\n'.join(changed_python_files(paths)))
    elif args.needs_openapi:
        print(str(on_main or needs_openapi_check(paths)).lower())
    elif args.needs_audit_contract:
        print(str(on_main or needs_audit_contract_check(paths)).lower())
    else:
        print(f'{selection.mode}: {selection.reason}')
        print('\n'.join(selection.tests))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
