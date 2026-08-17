from pathlib import Path

WORKBENCH = Path('employee/index.html')


def test_employee_workbench_wires_audited_staff_mutations() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert "requestMutation('/staff-actions', 'POST'" in page
    assert "requestMutation(`/staff-actions/${encodeURIComponent(actionId)}`, 'PATCH'" in page
    assert "requestMutation(`/signals/${encodeURIComponent(signalId)}/decisions`, 'POST'" in page
    assert "'Idempotency-Key': crypto.randomUUID()" in page
    assert "'If-Match': String(revision)" in page
    assert "path: 'claim_state.workflow_state'" in page
    assert 'customer_update:' in page


def test_employee_workbench_keeps_internal_and_claimant_text_separate() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert 'completeResultSummary' in page
    assert 'customerUpdateSummary' in page
    assert 'summary: customerSummary' in page
    assert 'reason_codes: reasonCodes' in page
    assert 'Internal reasons are never copied into the claimant update.' in page


def test_employee_workbench_renders_complete_handoff_outcome_and_never_auto_seeds() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    render_handoff = page[
        page.index('function renderHandoff') : page.index('function communicationHistory')
    ]
    render_context = page[
        page.index('function renderContext') : page.index('function renderHandoff')
    ]

    assert "{ label: 'Priority', value: handoff.priority }" in render_handoff
    assert "{ label: 'Reason', value: handoff.reason }" in render_handoff
    assert "{ label: 'Requested action', value: handoff.requested_action }" in render_handoff
    assert (
        "{ label: 'Missing items', value: handoff.packet?.missing_items || [] }" in render_handoff
    )
    assert "contextBlock('Structured facts and provenance'" in render_context
    assert 'Status: ${formatLabel(field.status)}' in render_context
    assert 'Load demo handoff queue' in page
    assert 'ensureDemoQueueSeeded' not in page
    assert 'loadClaims();' in page
