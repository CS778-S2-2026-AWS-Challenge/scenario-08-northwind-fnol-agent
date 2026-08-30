from pathlib import Path

WORKBENCH = Path('employee/index.html')


def test_employee_workbench_wires_audited_staff_mutations() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert "requestMutation('/staff-actions', 'POST'" in page
    assert "requestMutation(`/staff-actions/${encodeURIComponent(actionId)}`, 'PATCH'" in page
    assert '`/signals/${encodeURIComponent(signalId)}/decisions`' in page
    assert 'function prepareSelectedSignal()' in page
    assert 'function saveAllSignalDecisions(button)' in page
    assert 'decision: draft.decision' in page
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
    assert 'evidence_refs: [...new Set(evidenceRefs)]' in page
    assert 'the internal result and reason codes stay in the staff record' in page
    assert 'Only the update immediately above is shown to the claimant.' in page


def test_employee_professional_review_connects_evidence_uncertainty_and_results() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert "contextBlock('Policy and claim history'" in page
    assert 'detail.retrievals || []' in page
    assert 'Uncertainty — ${value.code}: ${value.detail}' in page
    assert 'signal.source_evidence || []' in page
    assert 'decision.actor_id' in page
    assert 'decision.summary' in page
    assert "decision.reason_codes?.join(', ')" in page
    assert 'No actionable review signals' in page
    assert 'signal.summary || signal.reason || formatLabel' in page
    assert 'id="signalActionStatus"' in page
    assert 'id="signalDraftList"' in page
    assert 'Save all signal decisions' in page
    assert 'Edit all findings' in page
    assert 'function editAllSignalFindings()' in page
    assert 'draft.locked = false' in page
    assert 'latestDecision.reason_codes?.[0]' in page
    assert 'dirty: false' in page
    assert 'if (!draft.dirty) continue' in page
    assert "button.textContent = draft.locked ? 'Edit finding' : 'Save finding'" in page
    assert "? 'Professional review workspace'" in page
    assert ": 'Claim review workspace'" in page
    assert "controlsAlreadyOpen ? 'Hide review controls' : 'Review and decide'" in page
    assert "action.setAttribute('aria-controls', 'detailStaffActions')" in page
    assert 'const shouldOpen = reviewControlsOpenClaimId !== detail.claim_id' in page
    assert 'reviewControlsOpenClaimId = shouldOpen ? detail.claim_id : null' in page
    assert "action.textContent = shouldOpen ? 'Hide review controls' : 'Review and decide'" in page
    assert 'controls.scrollIntoView' not in page
    assert "detail.route === 'standard_motor_intake'" in page
    assert 'const isReviewEligible = isProfessionalReview || isStandardIntakeReview' in page
    assert (
        'const showReviewControls = isReviewEligible '
        '&& reviewControlsOpenClaimId === detail.claim_id' in page
    )
    assert (
        "byId('detailStaffActions').style.display = showReviewControls ? 'block' : 'none'" in page
    )
    assert '#detailStaffActions.integrated-review-controls > summary { display:none; }' in page
    assert '.detail-panel > #detailStaffActions { order:1; }' in page
    assert 'Create a review task if none is open' not in page
    assert 'Review task to finish' not in page
    assert 'Start this review before saving its final outcome.' in page
    assert "actionSelect.value = activeAction?.action_id || ''" in page
    assert "byId('reviewRecordBar').hidden = !activeClaimDetail || hasOpenReviewTask" in page
    assert 'Choose the next claim stage' in page
    assert 'placeholder="For example: Policy section 4.2 applies' in page
    assert (
        'result: { outcome: outcomeCode, summary: persistedResultSummary, '
        'reason_codes: reasonCodes, source_refs: sourceRefs }' in page
    )
    assert 'id="evidenceReviewList"' in page
    assert "<h3>Review the claimant's existing evidence</h3>" in page
    assert page.index('id="evidenceReviewList"') < page.index('id="signalDecisionSelect"')
    assert "new Option('Credible — can be relied on', 'accepted')" in page
    assert "new Option('Cannot verify — request resubmission', 'resubmission_required')" in page
    assert "'AI credibility · Future assessment'" in page
    assert 'Staff remain responsible for the finding.' in page
    assert 'function deriveWorkflowFromEvidenceFindings()' in page
    assert "'<strong>No evidence files submitted.</strong>" in page
    assert "heading.textContent = 'Outstanding materials'" in page
    assert 'const submittedItems = evidenceItems.filter' in page
    assert "['Evidence sources', retrievals.length + submittedEvidence.length]" in page
    assert "['Outstanding materials', outstandingEvidence.length]" in page


def test_employee_workbench_loads_linked_records_from_the_claim_api() -> None:
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


def test_employee_pending_evidence_surfaces_responsibility_timing_and_context() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert 'item.pending_evidence_count' in page
    assert 'item.pending_evidence || []' in page
    assert "claimant: 'Waiting on claimant'" in page
    assert "external_agency: 'Waiting on external agency'" in page
    assert "internal: 'Waiting on Northwind'" in page
    assert 'item.responsible_party' in page
    assert 'item.expected_by' in page
    assert 'item.expected_timing' in page
    assert 'item.context_summary' in page
    assert 'Timing not provided' in page


def test_employee_workbench_groups_detail_with_progressive_disclosure() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert '<h2>Internal view</h2>' not in page
    assert '<h2>Shared state</h2>' not in page
    assert '<h2>Internal information</h2>' not in page
    assert 'id="detailEvidence"' in page
    assert 'Evidence and claim facts' in page
    assert 'id="detailReview"' in page
    assert 'Handoffs and internal review' in page
    assert 'id="detailHistory"' in page
    assert 'History and continuity' in page
    assert (
        '<details class="detail-section integrated-review-controls" id="detailStaffActions"' in page
    )
    assert "byId('detailReview').open = hasReviewWork" in page


def test_employee_workbench_uses_accessible_claim_detail_tabs() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert 'id="claimDetailTabs"' in page
    assert 'data-detail-tab="overview"' in page
    assert 'data-detail-tab="evidence"' in page
    assert 'data-detail-tab="review"' in page
    assert 'data-detail-tab="history"' in page
    assert 'data-detail-page="overview"' in page
    assert 'data-detail-page="evidence"' in page
    assert 'data-detail-page="review"' in page
    assert 'data-detail-page="history"' in page
    assert 'id="detailNextStep" data-detail-page="history"' in page
    assert 'function selectClaimDetailTab(tab, focus = false)' in page
    assert 'section.inert = section.hidden' in page
    assert "section.setAttribute('aria-hidden', String(section.hidden))" in page
    assert '.claim-detail-tabs { position:sticky;' in page
    assert "['ArrowLeft', 'ArrowRight', 'Home', 'End']" in page


def test_employee_workbench_exposes_pending_queue_and_demo_recovery() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert 'id="pendingEvidenceNav"' in page
    assert "selectQueue('awaiting_evidence')" in page
    assert "'Pending evidence queue'" in page
    assert 'id="resetDemoQueue"' in page
    assert "error.code === 'DEMO_SEED_REQUIRES_EMPTY_QUEUE'" in page
    assert "API_BASE.replace('/claims', '/demo/reset')" in page
    assert 'Reset all local demo claims' in page


def test_employee_queue_cards_keep_details_in_an_accessible_hover_preview() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert "hoverDetails.className = 'claim-hover-details'" in page
    assert "button.setAttribute('aria-describedby', hoverDetails.id)" in page
    assert '.claim-list button:hover .claim-hover-details' in page
    assert '.claim-list button:focus .claim-hover-details' in page
    assert '.claim-list button:hover, .claim-list button:focus { z-index:30;' in page
    assert '.claim-detail-tabs { position:sticky; top:12px; z-index:20;' in page
    assignment = (
        'assignment.textContent = item.assignee_id '
        "? `Assigned to ${item.assignee_id}` : 'Not assigned'"
    )
    assert assignment in page
    assert "previewRow('Route'" in page
    assert "previewRow('Evidence'" in page
    assert 'function evidencePreview(item)' in page
    assert 'claim-card-footer' not in page


def test_employee_evidence_files_use_the_authorised_staff_viewer() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert 'async function viewEvidenceFile(item)' in page
    assert '/evidence/${encodeURIComponent(item.evidence_id)}/content`' in page
    assert '{ headers: { Authorization: `Bearer ${STAFF_TOKEN}` } }' in page
    assert 'label: `View ${item.original_filename}`' in page
    assert "['uploaded', 'processing', 'ready'].includes(item.file_status)" in page
    assert 'id="evidencePreviewDialog"' in page
    assert '.evidence-preview-body [hidden] { display:none !important; }' in page
    assert "const isPdf = item.media_type === 'application/pdf'" in page
    assert 'pdfPreview.location.replace(evidencePreviewUrl)' in page
    assert 'image.src = imageDataUrl' in page
    assert "byId('evidencePreviewDialog').showModal()" in page
    assert "addEventListener('close', clearEvidencePreview)" in page
    assert 'async function downloadEvidenceFile(item)' in page
    assert 'label: `Download ${item.original_filename}`' in page
    assert '/content-data`' in page
    assert '`data:${file.media_type};base64,${file.base64_data}`' in page
    assert "className: 'evidence-download-button'" in page
    assert ".evidence-download-button::before { margin-right:6px; content:'↓';" in page


def test_employee_queue_uses_simple_bounded_pagination() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert 'const CLAIMS_PER_PAGE = 3' in page
    assert 'list.slice(firstItem, firstItem + CLAIMS_PER_PAGE)' in page
    assert 'function renderQueuePagination(totalPages)' in page
    assert 'function changeQueuePage(change)' in page
    assert 'aria-label="Claim queue pages"' in page
    assert 'queuePage = 1;\n      loadClaims();' in page


def test_employee_queue_keeps_card_widths_stable_on_partial_pages() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert 'grid-template-columns:repeat(3,minmax(0,1fr))' in page
    assert 'grid-template-columns:repeat(2,minmax(0,1fr))' in page
    assert '@media (max-width: 680px) { .claim-list { grid-template-columns:1fr; }' in page
    assert 'repeat(auto-fit,minmax(230px,1fr))' not in page


def test_employee_workbench_explains_when_the_local_api_cannot_be_reached() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert 'Cannot reach the Workbench API at http://127.0.0.1:8000.' in page
    assert 'Start the backend and keep it running, then refresh this page.' in page


def test_employee_workbench_prevents_duplicate_updates_and_restores_back_navigation() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert 'This claimant update has already been recorded.' in page
    assert 'pendingCustomerMessage' in page
    assert "window.location.hash !== '#customer-chat'" in page
    assert "window.addEventListener('popstate', restoreViewFromHistory)" in page
    assert "window.addEventListener('hashchange', restoreViewFromHistory)" in page
    assert 'customerChatHistoryEntryCreated' in page


def test_employee_messaging_defines_delivery_retry_and_template_states() -> None:
    page = WORKBENCH.read_text(encoding='utf-8')

    assert 'Sender: ${formatLabel(item.actor)} · Audience: Claimant · Delivered' in page
    assert 'Delivery outcome unknown · Retry to reconcile' in page
    assert 'Rejected before delivery · Ready to retry' in page
    assert "button.textContent = 'Retry message'" in page
    assert 'Retry with the same safe request key to reconcile' in page
    assert 'id="agentSuggestionStatus"' in page
    for state in ('generating', 'suggested', 'accepted', 'edited', 'rejected', 'failed'):
        assert f"setAgentSuggestionState('{state}'" in page
    assert 'Internal draft only; nothing will be sent' in page
    assert 'Copied for staff review; not sent' in page
    assert '>Reply template<' in page
    assert '>Agent reply suggestion<' not in page


def test_employee_workbench_ships_no_embedded_staff_credential() -> None:
    """The page must not carry a working credential.

    Issue #247 deliverable 10 and the identity contract's migration rules require
    browser synthetic-token access to be an explicit local opt-in, not a default
    baked into the static asset.
    """

    page = WORKBENCH.read_text(encoding='utf-8')

    for synthetic_token in (
        'synthetic-staff',
        'synthetic-claimant',
        'synthetic-admin',
        'synthetic-integration',
    ):
        assert synthetic_token not in page

    assert "localStorage.getItem('northwind.staffToken')" in page
    assert "const STAFF_TOKEN = '" not in page
