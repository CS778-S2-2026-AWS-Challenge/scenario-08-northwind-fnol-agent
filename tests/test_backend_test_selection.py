import subprocess
import sys
from unittest.mock import patch

import pytest

from scripts import select_backend_tests as selector
from scripts.select_backend_tests import (
    changed_paths,
    changed_python_files,
    needs_audit_contract_check,
    needs_openapi_check,
    select_tests,
)


def test_docs_only_change_skips_backend_pytest() -> None:
    selection = select_tests(['docs/README.md'])

    assert selection.mode == 'skip'
    assert selection.tests == ()


def test_narrow_claim_api_change_selects_direct_consumers() -> None:
    selection = select_tests(['backend/api/claims.py'])

    assert selection.mode == 'scoped'
    assert 'tests/test_claim_api.py' in selection.tests
    assert 'tests/test_claim_creation_journey.py' in selection.tests


def test_asset_modules_select_asset_claim_branch_and_mongodb_contracts() -> None:
    selection = select_tests(
        [
            'backend/api/assets.py',
            'backend/domain/assets.py',
            'backend/repositories/assets.py',
            'backend/services/assets.py',
        ]
    )

    assert selection.mode == 'scoped'
    assert {
        'tests/test_asset_api.py',
        'tests/test_asset_repository.py',
        'tests/test_branch_registry.py',
        'tests/test_claim_api.py',
        'tests/test_mongodb_repository.py',
    } <= set(selection.tests)


def test_audit_contract_change_selects_audit_contract_tests() -> None:
    selection = select_tests(['backend/domain/audit.py'])

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/test_audit_contract.py',)


def test_shared_domain_model_change_uses_sentinel_and_complete_journey() -> None:
    selection = select_tests(['backend/domain/models.py'])

    assert selection.mode == 'scoped'
    assert selection.tests == (
        'tests/test_backend_test_selection.py',
        'tests/test_journey_runs.py',
    )


def test_unmapped_backend_change_never_returns_an_empty_selection() -> None:
    selection = select_tests(['backend/unknown_component.py'])

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/test_backend_test_selection.py',)


def test_ci_change_selects_the_selector_contract_without_full_suite() -> None:
    selection = select_tests(['.circleci/config.yml', '.github/workflows/ci.yml'])

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/test_backend_test_selection.py',)


def test_shared_test_fixture_change_uses_scoped_sentinel() -> None:
    selection = select_tests(['tests/conftest.py'])

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/test_backend_test_selection.py',)


def test_branch_registry_contract_test_runs_the_focused_suite() -> None:
    selection = select_tests(['tests/test_branch_registry.py'])

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/test_branch_registry.py',)


def test_pytest_suffix_test_module_runs_the_focused_suite() -> None:
    selection = select_tests(['tests/branch_registry_test.py'])

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/branch_registry_test.py',)


def test_journey_run_support_changes_select_their_consumer_suite() -> None:
    selection = select_tests(
        [
            'tests/journey_runs/__main__.py',
            'tests/journey_runs/engine.py',
            'tests/journey_runs/motor_collision.py',
        ]
    )

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/test_journey_runs.py',)


@pytest.mark.parametrize(
    'path',
    [
        'backend/app.py',
        'backend/api/claims.py',
        'backend/api/evidence.py',
        'backend/api/workbench.py',
        'backend/domain/branch_registry.py',
        'backend/services/messages.py',
        'backend/services/external_services.py',
        'backend/repositories/fixture.py',
    ],
)
def test_journey_critical_backend_change_selects_complete_journey(path: str) -> None:
    selection = select_tests([path])

    assert selection.mode == 'scoped'
    assert 'tests/test_journey_runs.py' in selection.tests


@pytest.mark.parametrize(
    'path',
    [
        'backend/api/admin.py',
        'backend/domain/audit.py',
        'backend/adapters/model_gateway.py',
        'backend/repositories/mongodb.py',
    ],
)
def test_unrelated_backend_change_does_not_select_complete_journey(path: str) -> None:
    selection = select_tests([path])

    assert selection.mode == 'scoped'
    assert 'tests/test_journey_runs.py' not in selection.tests


def test_unknown_test_support_module_uses_scoped_sentinel() -> None:
    selection = select_tests(['tests/custom_support/builders.py'])

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/test_backend_test_selection.py',)


def test_vp_mapping_document_runs_the_focused_contract_suite() -> None:
    selection = select_tests(['docs/vp-field-branch-mapping.md'])

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/test_branch_registry.py',)


def test_ci_selector_change_runs_its_contract_tests() -> None:
    selection = select_tests(['scripts/select_backend_tests.py'])

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/test_backend_test_selection.py',)


def test_agent_evidence_action_change_selects_runtime_action_consumers() -> None:
    selection = select_tests(
        [
            'backend/domain/agent_action_registry.py',
            'backend/domain/agent_tool_registry.py',
            'backend/services/agent_evidence_actions.py',
            'tests/test_agent_evidence_action_execution.py',
        ]
    )

    assert selection.mode == 'scoped'
    assert {
        'tests/test_agent_action_commands.py',
        'tests/test_agent_action_execution.py',
        'tests/test_agent_action_mapping.py',
        'tests/test_agent_action_registry.py',
        'tests/test_agent_evidence_action_execution.py',
        'tests/test_agent_evidence_tools.py',
        'tests/test_runtime_agent_policy.py',
        'tests/test_staff_tool_registry.py',
    } <= set(selection.tests)


def test_static_checks_use_only_changed_python_files_for_scoped_prs() -> None:
    assert changed_python_files(
        ['backend/api/claims.py', 'backend/removed.py', 'docs/README.md']
    ) == ('backend/api/claims.py',)


def test_contract_checks_follow_their_own_impact() -> None:
    assert needs_openapi_check(['backend/api/claims.py'])
    assert needs_openapi_check(['backend/domain/models.py'])
    assert not needs_openapi_check(['backend/services/claims.py'])
    assert needs_audit_contract_check(['backend/domain/audit.py'])
    assert not needs_audit_contract_check(['backend/services/claims.py'])


def test_main_change_detection_uses_first_parent_and_includes_deletions() -> None:
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout='customer/src/App.jsx\nbackend/removed.py\n'
    )
    with patch('scripts.select_backend_tests.subprocess.run', return_value=completed) as run:
        paths = changed_paths(main_branch=True)

    assert paths == ('customer/src/App.jsx', 'backend/removed.py')
    run.assert_called_once_with(
        ['git', 'diff', '--name-only', '--diff-filter=ACMRD', 'HEAD^1..HEAD'],
        check=True,
        capture_output=True,
        text=True,
    )


def test_pull_request_change_detection_uses_merge_base() -> None:
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout='backend/api/claims.py\n')
    with patch('scripts.select_backend_tests.subprocess.run', return_value=completed) as run:
        paths = changed_paths()

    assert paths == ('backend/api/claims.py',)
    run.assert_called_once_with(
        ['git', 'diff', '--name-only', '--diff-filter=ACMRD', 'origin/main...HEAD'],
        check=True,
        capture_output=True,
        text=True,
    )


def test_main_frontend_change_uses_impact_selection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def frontend_main_paths(*, main_branch: bool) -> tuple[str, ...]:
        assert main_branch
        return ('customer/src/App.jsx',)

    monkeypatch.setattr(selector, 'running_on_main', lambda: True)
    monkeypatch.setattr(selector, 'changed_paths', frontend_main_paths)
    monkeypatch.setattr(sys, 'argv', ['select_backend_tests.py', '--mode'])

    assert selector.main() == 0
    assert capsys.readouterr().out.strip() == 'skip'


@pytest.mark.parametrize('flag', ['--needs-openapi', '--needs-audit-contract'])
def test_main_frontend_change_skips_backend_contract_checks(
    flag: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def frontend_main_paths(*, main_branch: bool) -> tuple[str, ...]:
        assert main_branch
        return ('customer/src/App.jsx',)

    monkeypatch.setattr(selector, 'running_on_main', lambda: True)
    monkeypatch.setattr(selector, 'changed_paths', frontend_main_paths)
    monkeypatch.setattr(sys, 'argv', ['select_backend_tests.py', flag])

    assert selector.main() == 0
    assert capsys.readouterr().out.strip() == 'false'


def test_workbench_domain_change_selects_workbench_consumers() -> None:
    selection = select_tests(['backend/domain/workbench.py', 'backend/services/workbench.py'])

    assert selection.mode == 'scoped'
    assert 'tests/test_workbench_api.py' in selection.tests
    assert 'tests/test_workbench_action_registry.py' in selection.tests


def test_agent_gateway_change_selects_agent_consumers() -> None:
    selection = select_tests(
        [
            'backend/domain/model_gateway.py',
            'backend/services/agent.py',
            'backend/services/messages.py',
        ]
    )

    assert selection.mode == 'scoped'
    assert 'tests/test_model_gateway.py' in selection.tests
    assert 'tests/test_staff_agent.py' in selection.tests


def test_external_registry_change_selects_lifecycle_consumers() -> None:
    selection = select_tests(['backend/domain/external_service_registry.py'])

    assert selection.mode == 'scoped'
    assert 'tests/test_external_service_registry.py' in selection.tests
    assert 'tests/test_agent_external_lifecycle.py' in selection.tests
    assert 'tests/test_model_gateway.py' in selection.tests


def test_staff_agent_service_change_selects_staff_consumers() -> None:
    selection = select_tests(['backend/services/staff_agent.py'])

    assert selection.mode == 'scoped'
    assert 'tests/test_staff_agent.py' in selection.tests
    assert 'tests/test_staff_agent_gateway.py' in selection.tests
    assert 'tests/test_mongodb_repository.py' in selection.tests


def test_unknown_backend_module_stays_scoped() -> None:
    selection = select_tests(['backend/services/new_unmapped_service.py'])

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/test_backend_test_selection.py',)


def test_backend_file_rules_do_not_match_longer_similar_names() -> None:
    selection = select_tests(['backend/services/agent.py.backup'])

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/test_backend_test_selection.py',)
