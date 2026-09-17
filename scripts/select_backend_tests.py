"""Select backend checks from the files changed by one commit or pull request.

The remote backend quality gate is always diff-scoped. Known implementation
paths select their direct consumers. Unmapped backend and quality-tooling paths
select the selector contract sentinel, while changed-line coverage requires
the pull request's own tests to execute its changed backend lines.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SELECTOR_TEST_PATH = 'tests/test_backend_test_selection.py'
TOOLING_CONSUMER_RULES: dict[str, tuple[str, ...]] = {
    '.circleci/config.yml': (SELECTOR_TEST_PATH,),
    '.github/workflows/ci.yml': (SELECTOR_TEST_PATH,),
    'backend/requirements-dev.txt': (SELECTOR_TEST_PATH,),
    'pyproject.toml': (SELECTOR_TEST_PATH,),
    'scripts/check_diff_coverage.py': ('tests/test_diff_coverage.py',),
    'scripts/select_backend_tests.py': (SELECTOR_TEST_PATH,),
}
TEST_SUPPORT_CONSUMERS: dict[str, tuple[str, ...]] = {
    'tests/journey_runs/': ('tests/test_journey_runs.py',),
}
BACKEND_CONSUMER_RULES = (
    (
        ('backend/api/claims.py', 'backend/services/claims.py'),
        (
            'tests/test_claim_api.py',
            'tests/test_claim_creation_journey.py',
            'tests/test_claim_transaction_boundary.py',
        ),
    ),
    (
        (
            'backend/api/evidence.py',
            'backend/domain/evidence.py',
            'backend/services/evidence.py',
        ),
        (
            'tests/test_evidence_api.py',
            'tests/test_evidence_condition_contract.py',
            'tests/test_evidence_fixtures.py',
            'tests/test_evidence_handoff_packet.py',
            'tests/test_evidence_storage_boundary.py',
            'tests/test_evidence_visibility_check.py',
        ),
    ),
    (
        (
            'backend/api/handoffs.py',
            'backend/api/workbench.py',
            'backend/domain/workbench.py',
            'backend/services/workbench.py',
        ),
        (
            'tests/test_evidence_storage_boundary.py',
            'tests/test_handoff_api.py',
            'tests/test_handoff_dispatch.py',
            'tests/test_handoff_persistence_ownership.py',
            'tests/test_model_gateway.py',
            'tests/test_workbench_action_registry.py',
            'tests/test_workbench_api.py',
            'tests/test_workbench_terminal_reopen.py',
        ),
    ),
    (
        (
            'backend/api/admin.py',
            'backend/domain/configuration.py',
            'backend/services/configuration.py',
        ),
        ('tests/test_admin_api.py',),
    ),
    (
        (
            'backend/adapters/identity.py',
            'backend/api/identity.py',
            'backend/services/identity.py',
        ),
        ('tests/test_identity_api.py', 'tests/test_identity_runtime.py'),
    ),
    (
        (
            'backend/domain/external_service_registry.py',
            'backend/domain/external_services.py',
            'backend/services/external_services.py',
            'backend/services/integrations.py',
        ),
        (
            'tests/test_external_service_entry.py',
            'tests/test_external_service_registry.py',
            'tests/test_external_service_validation.py',
            'tests/test_external_task_api.py',
            'tests/test_external_task_request.py',
            'tests/test_external_task_result.py',
            'tests/test_external_task_result_verification.py',
            'tests/test_external_task_retry.py',
            'tests/test_external_task_status.py',
            'tests/test_external_task_transition.py',
            'tests/test_integrations.py',
            'tests/test_agent_external_lifecycle.py',
            'tests/test_model_gateway.py',
        ),
    ),
    (
        ('backend/repositories/',),
        (
            'tests/test_claim_save_transaction_boundary.py',
            'tests/test_claim_transaction_boundary.py',
            'tests/test_mongodb_repository.py',
            'tests/test_persistence_integration.py',
            'tests/test_repository.py',
        ),
    ),
    (
        ('backend/domain/audit.py', 'scripts/export_audit_contract.py'),
        ('tests/test_audit_contract.py',),
    ),
    (
        (
            'backend/core/model_gateway.py',
            'backend/domain/model_gateway.py',
            'backend/services/model_agent.py',
        ),
        (
            'tests/test_agent_evidence_tools.py',
            'tests/test_model_agent_product_scope.py',
            'tests/test_model_gateway.py',
            'tests/test_namespaced_runtime.py',
            'tests/test_runtime_agent_policy.py',
            'tests/test_runtime_configuration.py',
            'tests/test_staff_agent.py',
            'tests/test_staff_agent_gateway.py',
            'tests/test_verify_model_gateway_live.py',
            'tests/test_week5_api_rag_provider_control_integration.py',
        ),
    ),
    (
        (
            'backend/domain/runtime.py',
            'backend/services/agent.py',
            'backend/services/agent_external_lifecycle.py',
            'backend/services/agent_tools.py',
            'backend/services/messages.py',
            'backend/services/runtime_agent_policy.py',
            'backend/services/runtime_work_items.py',
            'backend/services/staff_agent.py',
        ),
        (
            'tests/test_agent.py',
            'tests/test_agent_action_execution.py',
            'tests/test_agent_action_mapping.py',
            'tests/test_agent_evidence_tools.py',
            'tests/test_agent_external_lifecycle.py',
            'tests/test_claim_api.py',
            'tests/test_external_task_awaited_material.py',
            'tests/test_fact_resolution.py',
            'tests/test_model_gateway.py',
            'tests/test_mongodb_repository.py',
            'tests/test_namespaced_runtime.py',
            'tests/test_runtime_agent_policy.py',
            'tests/test_runtime_work_items.py',
            'tests/test_staff_agent.py',
            'tests/test_staff_agent_gateway.py',
        ),
    ),
    (
        (
            'backend/domain/agent_action_commands.py',
            'backend/domain/agent_action_registry.py',
            'backend/domain/agent_actions.py',
            'backend/domain/agent_tool_registry.py',
            'backend/domain/branch_registry.py',
            'backend/services/agent_action_execution.py',
            'backend/services/agent_evidence_actions.py',
            'backend/services/agent_action_mapping.py',
        ),
        (
            'tests/test_agent_action_commands.py',
            'tests/test_agent_action_execution.py',
            'tests/test_agent_action_mapping.py',
            'tests/test_agent_action_registry.py',
            'tests/test_agent_evidence_action_execution.py',
            'tests/test_agent_evidence_tools.py',
            'tests/test_branch_registry.py',
            'tests/test_namespaced_runtime.py',
            'tests/test_runtime_agent_policy.py',
            'tests/test_staff_tool_registry.py',
        ),
    ),
)


@dataclass(frozen=True)
class TestSelection:
    """Selected pytest paths and the reason for the selection."""

    mode: str
    tests: tuple[str, ...]
    reason: str


def select_tests(changed_paths: Sequence[str]) -> TestSelection:
    """Select tests from repository-relative changed paths.

    Args:
        changed_paths: Paths changed relative to the target branch.
    Returns:
        A deterministic selection with ``scoped`` or ``skip`` mode.
    """

    paths = tuple(sorted(set(_normalise_path(path) for path in changed_paths)))
    if not paths:
        return TestSelection('skip', (), 'no changed paths')

    selected: set[str] = set()
    backend_changed = False
    guarded_unmapped_change = False
    for raw_path in paths:
        path = PurePosixPath(raw_path.replace('\\', '/'))
        path_text = path.as_posix()
        if consumers := TOOLING_CONSUMER_RULES.get(path_text):
            selected.update(consumers)
        if path_text == 'docs/vp-field-branch-mapping.md':
            selected.add('tests/test_branch_registry.py')
        if path_text.startswith('backend/'):
            backend_changed = True
        if path_text.startswith('tests/') and path_text.endswith('.py'):
            if _is_pytest_module(path):
                selected.add(path_text)
            elif path_text == 'tests/conftest.py' or path_text.startswith(
                ('tests/fixtures/', 'tests/helpers/', 'tests/support/')
            ):
                guarded_unmapped_change = True
            elif consumers := _test_support_consumers(path_text):
                selected.update(consumers)
            else:
                guarded_unmapped_change = True

        if consumers := _backend_consumers(path_text):
            selected.update(consumers)
        elif path_text.startswith('backend/'):
            guarded_unmapped_change = True

    if guarded_unmapped_change or (backend_changed and not selected):
        selected.add(SELECTOR_TEST_PATH)
    if selected:
        reason = (
            'direct consumers plus unmapped-change sentinel'
            if guarded_unmapped_change
            else 'direct consumers of changed paths'
        )
        return TestSelection('scoped', tuple(sorted(selected)), reason)
    return TestSelection('skip', (), 'no backend behavior changed')


def _normalise_path(path: str) -> str:
    return PurePosixPath(path.replace('\\', '/')).as_posix()


def _is_pytest_module(path: PurePosixPath) -> bool:
    """Return whether pytest treats the path as a test module by default."""

    return path.name.startswith('test_') or path.name.endswith('_test.py')


def _test_support_consumers(path: str) -> tuple[str, ...]:
    """Return the durable test modules that exercise a support-module path."""

    for prefix, consumers in TEST_SUPPORT_CONSUMERS.items():
        if path.startswith(prefix):
            return consumers
    return ()


def _backend_consumers(path: str) -> tuple[str, ...]:
    """Return the focused tests for a mapped backend implementation path."""

    selected: set[str] = set()
    for prefixes, consumers in BACKEND_CONSUMER_RULES:
        if any(
            path.startswith(prefix) if prefix.endswith('/') else path == prefix
            for prefix in prefixes
        ):
            selected.update(consumers)
    return tuple(sorted(selected))


def changed_python_files(changed: Sequence[str]) -> tuple[str, ...]:
    """Return changed Python files for scoped static checks."""

    return tuple(
        sorted(
            {
                normalised
                for path in changed
                if (normalised := _normalise_path(path)).endswith('.py')
                and Path(normalised).is_file()
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


def changed_paths(*, main_branch: bool = False) -> tuple[str, ...]:
    """Read the paths affected by the current pull request or main commit.

    Args:
        main_branch: Compare a main-branch commit with its first parent when true.

    Returns:
        Repository-relative added, copied, modified, renamed, or deleted paths.
    """

    comparison = 'HEAD^1..HEAD' if main_branch else 'origin/main...HEAD'
    completed = subprocess.run(
        ['git', 'diff', '--name-only', '--diff-filter=ACMRD', comparison],
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
    args = parser.parse_args()
    on_main = running_on_main()
    paths = changed_paths(main_branch=on_main)
    selection = select_tests(paths)
    if args.mode:
        print(selection.mode)
    elif args.tests:
        print('\n'.join(selection.tests))
    elif args.python_files:
        print('\n'.join(changed_python_files(paths)))
    elif args.needs_openapi:
        print(str(needs_openapi_check(paths)).lower())
    elif args.needs_audit_contract:
        print(str(needs_audit_contract_check(paths)).lower())
    else:
        print(f'{selection.mode}: {selection.reason}')
        print('\n'.join(selection.tests))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
