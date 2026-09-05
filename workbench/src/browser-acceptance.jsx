import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { assertWorkbenchFixtureContract } from './browser-acceptance-fixture.js'
import ClaimWorkspace from './components/ClaimWorkspace.jsx'
import './styles.css'

const missingInformation = Array.from({ length: 8 }, (_, index) => ({
  kind: 'field',
  code: `missing.item_${index + 1}`,
  label: `Missing item ${index + 1}`,
  attention: index < 2 ? 'required_now' : 'needed_next',
  responsible_party: index % 2 ? 'external_party' : 'claimant',
  source_refs: [`msg_${index + 1}`, `field:item_${index + 1}`],
  blocked_action: index === 7 ? 'human.resolve_handoff' : null,
}))

const primaryAction = {
  action_code: 'ownership.request_cowork',
  target_type: 'claim',
  target_ref: 'clm_browser_acceptance',
  label: 'Request cowork access',
  purpose: 'Ask the Claim owner to collaborate.',
  availability: 'confirmation_required',
  result_state: 'awaiting_input',
  based_on_revision: 8,
  expected_effects: ['collaboration_request.create'],
  source_refs: ['claim:clm_browser_acceptance'],
  confirmation: { message: 'The owner will receive this request.' },
  payload_defaults: {},
  inputs: [{ field_code: 'reason', label: 'Reason', control: 'textarea', required: true, choices: [] }],
}

const detail = assertWorkbenchFixtureContract({
  claim_id: 'clm_browser_acceptance',
  display_reference: 'NW-BROWSER-08',
  revision: 8,
  claimant: { customer_id: 'cus_browser', display_name: 'Browser Acceptance Claimant' },
  incident: { family: 'motor', summary: 'A deliberately long Claim-detail fixture for responsive acceptance coverage.' },
  lifecycle_state: 'professional_review',
  workflow_state: 'professional_review',
  updated_at: '2026-09-05T01:00:00Z',
  ownership: { state: 'assigned', current_staff_access: 'read_only', primary_assignee: { staff_id: 'stf_owner', display_name: 'Claim Owner' } },
  priority_projection: { level: 'high' },
  work_summary: {
    queue_key: 'professional_review',
    primary_action_code: primaryAction.action_code,
    primary_action_target_ref: primaryAction.target_ref,
    missing_information: missingInformation,
    risk_signals: Array.from({ length: 5 }, (_, index) => ({ signal_id: `sig_${index + 1}`, label: `Review signal ${index + 1}`, attention_level: 'review_required', summary: 'Source-linked review context.' })),
  },
  allowed_actions: [primaryAction],
  customer_next_step: { responsible_party: 'claims_professional', summary: 'A claims professional is reviewing the reported information.' },
  section_summaries: {
    fields: { status: 'available', total: 18, needs_attention: 8 },
    conversation: { status: 'available', total: 12, unread_count: 2 },
    evidence: { status: 'available', total: 6, needs_attention: 2 },
    reference_checks: { status: 'available', total: 9, needs_attention: 1 },
    external_services: { status: 'available', total: 3, needs_attention: 1 },
    activity: { status: 'available', total: 27 },
  },
  tags: Array.from({ length: 8 }, (_, index) => ({ code: `tag_${index + 1}`, label: `Claim tag ${index + 1}`, category: 'progress', basis: 'derived', source_refs: [`field:tag_${index + 1}`] })),
})

function noop() {}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <div className="open-claim-panel browser-acceptance-panel" style={{ height: '100vh' }}>
      <ClaimWorkspace
        detail={detail}
        resources={{ handoffs: { items: [] }, collaborationRequests: { items: [] } }}
        section="summary"
        draft=""
        profile={{ staff_id: 'stf_reviewer' }}
        onSection={noop}
        onDraft={noop}
        onAccept={noop}
        onResolve={noop}
        onSignalDecision={noop}
        onUpdateAction={noop}
        onLoadEvidence={noop}
        onSend={noop}
        onOwnershipAction={noop}
      />
    </div>
  </StrictMode>,
)
