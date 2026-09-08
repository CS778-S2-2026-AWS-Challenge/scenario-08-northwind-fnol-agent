from scripts.select_backend_tests import (
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


def test_audit_contract_change_selects_audit_contract_tests() -> None:
    selection = select_tests(['backend/domain/audit.py'])

    assert selection.mode == 'scoped'
    assert selection.tests == ('tests/test_audit_contract.py',)


def test_shared_domain_model_change_runs_the_complete_suite() -> None:
    selection = select_tests(['backend/domain/models.py'])

    assert selection.mode == 'full'
    assert selection.tests == ('tests',)


def test_unmapped_backend_change_never_returns_an_empty_selection() -> None:
    selection = select_tests(['backend/unknown_component.py'])

    assert selection.mode == 'full'
    assert selection.tests == ('tests',)


def test_main_branch_forces_the_complete_suite() -> None:
    selection = select_tests(['docs/README.md'], full=True)

    assert selection.mode == 'full'
    assert selection.tests == ('tests',)


def test_shared_test_fixture_change_runs_the_complete_suite() -> None:
    selection = select_tests(['tests/conftest.py'])

    assert selection.mode == 'full'
    assert selection.tests == ('tests',)


def test_branch_registry_contract_test_runs_the_complete_suite() -> None:
    selection = select_tests(['tests/test_branch_registry.py'])

    assert selection.mode == 'full'
    assert selection.tests == ('tests',)


def test_ci_selector_change_runs_the_complete_suite() -> None:
    selection = select_tests(['scripts/select_backend_tests.py'])

    assert selection.mode == 'full'
    assert selection.tests == ('tests',)


def test_static_checks_use_only_changed_python_files_for_scoped_prs() -> None:
    assert changed_python_files(['backend/api/claims.py', 'docs/README.md']) == (
        'backend/api/claims.py',
    )


def test_contract_checks_follow_their_own_impact() -> None:
    assert needs_openapi_check(['backend/api/claims.py'])
    assert needs_openapi_check(['backend/domain/models.py'])
    assert not needs_openapi_check(['backend/services/claims.py'])
    assert needs_audit_contract_check(['backend/domain/audit.py'])
    assert not needs_audit_contract_check(['backend/services/claims.py'])
