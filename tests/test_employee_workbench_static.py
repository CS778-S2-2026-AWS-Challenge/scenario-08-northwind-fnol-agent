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
    assert 'formatLabel(handoff.trigger)' in render_handoff
    assert "{ label: 'Reason', value: handoff.reason }" in render_handoff
    assert "{ label: 'Requested action', value: handoff.requested_action }" in render_handoff
    assert (
        "{ label: 'Missing items', value: handoff.packet?.missing_items || [] }" in render_handoff
    )
    assert "contextBlock('Structured facts and provenance'" in render_context
    assert 'Status: ${formatLabel(field.status)}' in render_context
    assert 'Load workbench demo queue' in page
    assert 'ensureDemoQueueSeeded' not in page
    assert 'loadClaims();' in page


def test_employee_workbench_surfaces_created_and_routed_operational_summary() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    render_claims = page[page.index('function renderClaims') : page.index('function renderContext')]
    render_detail = page[
        page.index('function renderDetail') : page.index('async function refreshDetail')
    ]

    assert 'item.route' in render_claims
    assert 'item.evidence_state' in render_claims
    assert 'item.next_action_summary' in render_claims
    assert 'item.responsible_party' in render_claims
    assert 'operationalSummary(detail)' in render_detail
    assert "section.setAttribute('aria-label', 'Operational summary')" in page
    assert 'detail.customer_next_step.responsible_party' in page
    assert 'detail.external_claim.creation_status' in page
    assert 'detail.assessor_routing.routing_status' in page


def test_employee_queue_cards_keep_details_in_an_accessible_hover_preview() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert "hoverDetails.className = 'claim-hover-details'" in page
    assert "button.setAttribute('aria-describedby', hoverDetails.id)" in page
    assert '.claim-list button:hover .claim-hover-details' in page
    assert '.claim-list button:focus .claim-hover-details' in page
    assignment = (
        'assignment.textContent = item.assignee_id '
        "? `Assigned to ${item.assignee_id}` : 'Not assigned'"
    )
    assert assignment in page
    assert "previewRow('Route'" in page
    assert "previewRow('Evidence'" in page
    assert 'function evidencePreview(item)' in page
    assert 'claim-card-footer' not in page


def test_employee_queue_uses_simple_bounded_pagination() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert 'const CLAIMS_PER_PAGE = 6' in page
    assert 'list.slice(firstItem, firstItem + CLAIMS_PER_PAGE)' in page
    assert 'function renderQueuePagination(totalPages)' in page
    assert 'function changeQueuePage(change)' in page
    assert 'aria-label="Claim queue pages"' in page
    assert 'queuePage = 1;\n      loadClaims();' in page
