from pathlib import Path


WORKBENCH = Path('employee/index.html')


def test_employee_workbench_loads_structured_mvp_records_from_claim_api() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert 'fetchClaims(view)' in page
    assert 'fetchClaimDetail(claimId)' in page
    assert 'detail.retrievals || []' in page
    assert 'detail.messages || []' in page
    assert 'detail.evidence || []' in page
    assert 'detail.handoffs || []' in page
    for fixture_identifier in (
        'clm_fixture_at02',
        'ret_fixture_at02_policy',
        'ret_fixture_at02_history',
        'POL-MVP-HOME-2048',
        'HIST-MVP-2024-017',
    ):
        assert fixture_identifier not in page
