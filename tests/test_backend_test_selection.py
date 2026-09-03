from scripts.select_backend_tests import select_tests


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
