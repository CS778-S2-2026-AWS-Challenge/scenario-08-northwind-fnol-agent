from pathlib import Path


EMPLOYEE_WORKBENCH = (
    Path(__file__).resolve().parents[1] / 'employee' / 'index.html'
)


def test_employee_workbench_uses_rich_detail_contract() -> None:
    source = EMPLOYEE_WORKBENCH.read_text(encoding='utf-8')

    assert 'detail.handoffs' in source
    assert 'detail.signals' in source
    assert 'detail.messages' in source
    assert 'detail.assigned_to' not in source
    assert 'detail.internal_flags' not in source
    assert 'detail.internal_notes' not in source
