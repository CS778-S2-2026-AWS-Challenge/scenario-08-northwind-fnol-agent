import { readFileSync } from 'node:fs'

import { waitFor } from '@testing-library/dom'
import { JSDOM } from 'jsdom'
import { expect, it, vi } from 'vitest'


const employeeHtml = readFileSync('../employee/index.html', 'utf8')

function response(body, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function fillProfessionalReviewCompletion(document) {
  document.querySelector('#completeResultSummary').value =
    'Policy section 4.2 applies to the confirmed incident facts, so the claim can continue.'
  document.querySelector('#completeWorkflowState').value = 'ready_for_next'
  document.querySelector('#customerUpdateSummary').value =
    'We completed the policy review. Your report can continue and Northwind will prepare the next step.'
}

function queueItem(number, overrides = {}) {
  return {
    claim_id: `clm_page_${number}`,
    revision: 1,
    customer_reference: `customer-${number}`,
    incident_type: 'motor',
    workflow_state: 'professional_review',
    queue: 'professional_review',
    priority: 'standard',
    next_action: 'HANDOFF',
    route: 'motor_review',
    evidence_state: 'received',
    evidence_summary: { received: 1, pending: 0, needs_attention: 0 },
    next_action_summary: 'Review the saved claim.',
    responsible_party: 'claims_professional',
    claim_creation_status: null,
    assessor_routing_status: null,
    open_handoff_count: 0,
    assignee_id: null,
    created_at: '2026-08-13T00:00:00Z',
    updated_at: '2026-08-13T00:01:00Z',
    ...overrides,
  }
}

function queueDetail(item) {
  return {
    ...item,
    channel: 'web_agent',
    locale: 'en-NZ',
    claim_state: { workflow_state: item.workflow_state, evidence: item.evidence_state },
    form: {},
    active_session_id: null,
    evidence: [],
    sessions: [],
    messages: [],
    decisions: [],
    signals: [],
    handoffs: [],
    staff_actions: [],
    customer_updates: [],
    external_claim: null,
    assessor_routing: null,
    customer_next_step: {
      status: 'review',
      summary: item.next_action_summary,
      responsible_party: item.responsible_party,
      required_items: [],
    },
  }
}

it('toggles professional review controls without navigating away from the claim', async () => {
  const item = queueItem(90)
  const fetchMock = vi.fn((url) => {
    if (String(url).endsWith(`/${item.claim_id}`)) return response(queueDetail(item))
    return response({ items: [item], page: { next_cursor: null } })
  })
  const dom = new JSDOM(employeeHtml, {
    runScripts: 'dangerously', url: 'http://127.0.0.1:8002/',
    beforeParse(window) { window.fetch = fetchMock },
  })

  await waitFor(() => expect(dom.window.document.querySelector('[aria-controls="detailStaffActions"]')).not.toBeNull())
  const toggle = dom.window.document.querySelector('[aria-controls="detailStaffActions"]')
  const controls = dom.window.document.querySelector('#detailStaffActions')
  expect(controls.style.display).toBe('none')
  expect(toggle.getAttribute('aria-expanded')).toBe('false')

  toggle.click()
  expect(controls.style.display).toBe('block')
  expect(controls.open).toBe(true)
  expect(toggle.textContent).toBe('Hide review controls')
  expect(toggle.getAttribute('aria-expanded')).toBe('true')

  toggle.click()
  expect(controls.style.display).toBe('none')
  expect(controls.open).toBe(false)
  expect(toggle.textContent).toBe('Review and decide')
  expect(toggle.getAttribute('aria-expanded')).toBe('false')
  dom.window.close()
})

it('opens a standard intake review workspace for an assigned created claim', async () => {
  const item = queueItem(91, {
    workflow_state: 'created', queue: 'created_routed', next_action: 'PROCEED',
    route: 'standard_motor_intake', claim_creation_status: 'created', assignee_id: 'stf_demo',
  })
  const detail = {
    ...queueDetail(item),
    external_claim: {
      external_claim_id: 'ext_91', claim_number: 'NW-91', creation_status: 'created',
      route: 'standard_motor_intake', next_step: 'Claims intake review', expected_by: null,
      limitations: [],
    },
  }
  const fetchMock = vi.fn((url) => String(url).endsWith(`/${item.claim_id}`)
    ? response(detail)
    : response({ items: [item], page: { next_cursor: null } }))
  const dom = new JSDOM(employeeHtml, {
    runScripts: 'dangerously', url: 'http://127.0.0.1:8002/',
    beforeParse(window) { window.fetch = fetchMock },
  })

  await waitFor(() => expect(dom.window.document.querySelector('.review-workspace h3')?.textContent)
    .toBe('Claim review workspace'))
  const toggle = dom.window.document.querySelector('[aria-controls="detailStaffActions"]')
  expect(toggle).not.toBeNull()
  toggle.click()
  expect(dom.window.document.querySelector('#detailStaffActions').style.display).toBe('block')
  expect(dom.window.document.querySelector('#createStaffActionBtn').disabled).toBe(false)
  dom.window.close()
})

it('shows missing material as outstanding instead of submitted evidence', async () => {
  const item = queueItem(92, {
    workflow_state: 'created', queue: 'created_routed', route: 'standard_motor_intake',
    claim_creation_status: 'created', assignee_id: 'stf_demo', evidence_state: 'incomplete',
  })
  const detail = {
    ...queueDetail(item),
    external_claim: { external_claim_id: 'ext_92', claim_number: 'NW-92', creation_status: 'created', route: 'standard_motor_intake', next_step: 'Claims intake review', expected_by: null, limitations: [] },
    evidence: [{
      evidence_id: 'evd_missing_image', kind: 'incident_image', status: 'incomplete',
      file_status: 'not_available', original_filename: null, source: 'claimant',
      responsible_party: 'claimant', wait_type: 'claimant', needed_for: ['later_action'],
      claimant_note: 'No supporting material was available when the claim was submitted.',
    }],
  }
  const dom = new JSDOM(employeeHtml, {
    runScripts: 'dangerously', url: 'http://127.0.0.1:8002/',
    beforeParse(window) { window.fetch = vi.fn((url) => String(url).endsWith(`/${item.claim_id}`) ? response(detail) : response({ items: [item], page: { next_cursor: null } })) },
  })
  await waitFor(() => expect(dom.window.document.querySelector('#evidenceReviewList').textContent)
    .toContain('No evidence files submitted'))
  const evidenceList = dom.window.document.querySelector('#evidenceReviewList')
  expect(evidenceList.textContent).toContain('Outstanding materials')
  expect(evidenceList.textContent).toContain('Incident Image')
  expect(evidenceList.querySelectorAll('.evidence-review-card')).toHaveLength(0)
  const workspace = dom.window.document.querySelector('.review-workspace')
  expect(workspace.textContent).toContain('0Evidence sources')
  expect(workspace.textContent).toContain('1Outstanding materials')
  dom.window.close()
})

it('paginates a large queue, resets on filter change, and keeps handoff facts visible', async () => {
  const items = Array.from({ length: 8 }, (_, index) => queueItem(index + 1))
  items[0] = queueItem(1, { priority: 'high', open_handoff_count: 2 })

  const fetchMock = vi.fn((url) => {
    const claim = items.find((item) => String(url).endsWith(`/${item.claim_id}`))
    if (claim) return response(queueDetail(claim))
    return response({ items, page: { next_cursor: null } })
  })
  const dom = new JSDOM(employeeHtml, {
    runScripts: 'dangerously',
    url: 'http://127.0.0.1:8002/',
    beforeParse(window) {
      window.fetch = fetchMock
    },
  })

  await waitFor(() => {
    expect(dom.window.document.querySelectorAll('#claimList > button')).toHaveLength(3)
    expect(dom.window.document.querySelector('#queuePageStatus').textContent).toBe('Page 1 of 3')
    expect(dom.window.document.querySelector('#allQueueCount').textContent).toBe('8')
  })
  const firstCard = dom.window.document.querySelector('#claimList > button')
  expect(firstCard.textContent).toContain('Priority: High')
  expect(firstCard.textContent).toContain('2 open handoffs')
  expect(firstCard.getAttribute('aria-label')).toContain('priority high, 2 open handoffs')

  dom.window.document.querySelector('#nextQueuePage').click()
  await waitFor(() => {
    const cards = dom.window.document.querySelectorAll('#claimList > button')
    expect(cards).toHaveLength(3)
    expect(cards[0].textContent).toContain('customer-4')
    expect(dom.window.document.querySelector('#queuePageStatus').textContent).toBe('Page 2 of 3')
  })

  const filter = dom.window.document.querySelector('#viewSelect')
  filter.value = 'professional_review'
  filter.dispatchEvent(new dom.window.Event('change'))
  await waitFor(() => {
    expect(dom.window.document.querySelector('#queuePageStatus').textContent).toBe('Page 1 of 3')
    expect(dom.window.document.querySelector('#claimList').textContent).toContain('customer-1')
  })

  dom.window.document.querySelector('#urgentQueueCard').click()
  await waitFor(() => {
    expect(dom.window.document.querySelector('#viewSelect').value).toBe('urgent')
    expect(dom.window.document.querySelector('#queueTitle').textContent).toBe('Urgent request queue')
    expect(dom.window.document.querySelector('#urgentQueueCard').getAttribute('aria-pressed')).toBe('true')
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('view=urgent'),
      expect.any(Object),
    )
  })
  dom.window.close()
})

it('renders persisted claim context and uses the handoff accept endpoint', async () => {
  let handoffStatus = 'queued'
  let claimRevision = 4
  const listItem = {
    claim_id: 'clm_employee',
    revision: 4,
    customer_reference: 'cus_demo',
    incident_type: 'motor',
    workflow_state: 'professional_review',
    queue: 'professional_review',
    priority: 'standard',
    next_action: 'HANDOFF',
    evidence_summary: { received: 0, pending: 1, needs_attention: 0 },
    open_handoff_count: 1,
    assignee_id: null,
    created_at: '2026-08-13T00:00:00Z',
    updated_at: '2026-08-13T00:04:00Z',
  }
  const detail = () => ({
    ...listItem,
    revision: claimRevision,
    channel: 'web_agent',
    locale: 'en-NZ',
    claim_state: { workflow_state: 'professional_review' },
    form: {
      'incident.location': {
        value: 'Queen Street',
        status: 'confirmed',
        source: 'claimant',
        source_refs: ['msg_claimant'],
      },
    },
    route: null,
    active_session_id: 'ses_employee',
    evidence: [{
      evidence_id: 'evd_police',
      kind: 'police_report',
      status: 'pending_generation',
      source: 'claimant',
      needed_for: ['later_action'],
      claimant_note: 'Expected next week.',
    }],
    sessions: [{
      summary: 'Rear-end collision with confirmed core facts.',
      unresolved_questions: [],
      pending_items: ['evd_police'],
      prior_commitments: ['The police report can be added later.'],
    }],
    messages: [{
      actor: 'claimant',
      content: { type: 'text', text: 'Another car hit mine.' },
      created_at: '2026-08-13T00:01:00Z',
    }],
    decisions: [],
    signals: [{ signal_id: 'sig_internal', status: 'review_required' }],
    handoffs: [{
      handoff_id: 'hnd_employee',
      claim_id: 'clm_employee',
      type: 'human_support',
      status: handoffStatus,
      priority: 'standard',
      queue: 'claimant_support',
      support_need: 'human_requested',
      trigger: 'claimant_support_request',
      reason: 'The claimant requested a person.',
      requested_action: 'Continue with the saved report.',
      assigned_to: handoffStatus === 'accepted' ? 'stf_demo' : null,
      packet: {
        incident_summary: 'A rear-end collision with confirmed core facts.',
        form_snapshot: {
          'incident.location': {
            value: 'Queen Street',
            status: 'confirmed',
            source: 'claimant',
            source_refs: ['msg_claimant'],
          },
        },
        promised_next_step: 'A staff member will review the report.',
        pending_items: ['evd_police'],
        missing_items: ['vehicle.drivable'],
        conflicts: [],
        low_confidence_items: [],
      },
    }],
    staff_actions: [],
    customer_updates: [],
    external_claim: null,
    assessor_routing: null,
    customer_next_step: {
      status: 'human_support_queued',
      summary: 'A support request is queued.',
      responsible_party: 'northwind',
    },
  })
  const fetchMock = vi.fn((url, options = {}) => {
    if (options.method === 'POST' && String(url).endsWith('/handoffs/hnd_employee/accept')) {
      handoffStatus = 'accepted'
      claimRevision = 5
      listItem.revision = claimRevision
      listItem.assignee_id = 'stf_demo'
      return response({ handoff: detail().handoffs[0], revision: claimRevision })
    }
    if (String(url).endsWith('/clm_employee')) return response(detail())
    return response({ items: [listItem], page: { next_cursor: null } })
  })
  const dom = new JSDOM(employeeHtml, {
    runScripts: 'dangerously',
    url: 'http://127.0.0.1:8002/',
    beforeParse(window) {
      window.fetch = fetchMock
    },
  })

  await waitFor(() => {
    expect(dom.window.document.body.textContent).toContain('Queen Street')
    expect(dom.window.document.body.textContent).toContain('Pending Generation')
    expect(dom.window.document.body.textContent).toContain('The police report can be added later.')
    expect(dom.window.document.body.textContent).toContain('sig_internal')
    expect(dom.window.document.body.textContent).toContain('Confirmed incident')
    expect(dom.window.document.body.textContent).toContain('A rear-end collision with confirmed core facts.')
    expect(dom.window.document.body.textContent).toContain('Incident / Location: Queen Street')
    expect(dom.window.document.body.textContent).toContain('Missing: vehicle.drivable')
    expect(dom.window.document.body.textContent).toContain('Continue with the saved report.')
  })
  const accept = [...dom.window.document.querySelectorAll('button')]
    .find((button) => button.textContent === 'Accept handoff')
  expect(accept).toBeDefined()
  accept.click()

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/handoffs/hnd_employee/accept'),
      expect.objectContaining({ method: 'POST' }),
    )
    expect(dom.window.document.body.textContent).toContain('Claimant Support Request · Accepted')
  })
  dom.window.close()
})

it('clears stale detail and keeps write-back controls disabled when a mutation empties the queue', async () => {
  let queueIsEmpty = false
  const listItem = {
    claim_id: 'clm_review',
    revision: 7,
    customer_reference: 'customer-review',
    incident_type: 'motor',
    workflow_state: 'professional_review',
    queue: 'professional_review',
    priority: 'standard',
    next_action: 'REVIEW',
    evidence_summary: { received: 1, pending: 0, needs_attention: 0 },
    open_handoff_count: 0,
    assignee_id: 'stf_demo',
    created_at: '2026-08-13T00:00:00Z',
    updated_at: '2026-08-13T00:07:00Z',
  }
  const detail = {
    ...listItem,
    channel: 'web_agent',
    locale: 'en-NZ',
    claim_state: { workflow_state: 'professional_review' },
    form: {},
    route: null,
    active_session_id: null,
    evidence: [],
    sessions: [],
    messages: [],
    decisions: [],
    signals: [{ signal_id: 'sig_review', code: 'manual_review', status: 'review_required', decisions: [] }],
    handoffs: [],
    staff_actions: [{ action_id: 'act_review', action_type: 'professional_review', status: 'open', assigned_to: 'stf_demo' }],
    customer_updates: [],
    external_claim: null,
    assessor_routing: null,
    customer_next_step: { status: 'under_review', summary: 'A professional is reviewing the claim.', responsible_party: 'northwind' },
  }
  const fetchMock = vi.fn((url, options = {}) => {
    if (options.method === 'PATCH' && String(url).endsWith('/staff-actions/act_review')) {
      queueIsEmpty = true
      return response({ revision: 8 })
    }
    if (String(url).endsWith('/clm_review')) return response(detail)
    return response({ items: queueIsEmpty ? [] : [listItem], page: { next_cursor: null } })
  })
  const dom = new JSDOM(employeeHtml, {
    runScripts: 'dangerously',
    url: 'http://127.0.0.1:8002/',
    beforeParse(window) {
      window.fetch = fetchMock
      window.crypto.randomUUID = () => 'mutation-test-key'
    },
  })

  await waitFor(() => {
    expect(dom.window.document.querySelector('#completeActionSelect').value).toBe('act_review')
    expect([...dom.window.document.querySelector('#signalDecisionSelect').options]
      .some(option => option.value === 'sig_review')).toBe(true)
  })
  fillProfessionalReviewCompletion(dom.window.document)
  dom.window.document.querySelector('#completeStaffActionBtn').click()

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/staff-actions/act_review'),
      expect.objectContaining({ method: 'PATCH' }),
    )
    expect(dom.window.document.querySelector('#claimCount').textContent).toBe('0 claims')
    expect(dom.window.document.querySelector('#detailContent').textContent).toContain('Select a claim')
    expect(dom.window.document.querySelector('#detailStaffActions').style.display).toBe('none')
    expect(dom.window.document.querySelector('#createStaffActionBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#completeStaffActionBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#saveAllSignalDecisionsBtn').disabled).toBe(true)
  })
  dom.window.close()
})

it('disables exhausted action and signal controls when the claim remains in the queue', async () => {
  let mutated = false
  const listItem = {
    claim_id: 'clm_same_queue', revision: 4, customer_reference: 'customer-same-queue',
    incident_type: 'motor', workflow_state: 'professional_review', queue: 'professional_review',
    priority: 'standard', next_action: 'REVIEW', evidence_summary: {}, open_handoff_count: 0,
    assignee_id: 'stf_demo', created_at: '2026-08-13T00:00:00Z', updated_at: '2026-08-13T00:04:00Z',
  }
  const detail = () => ({
    ...listItem,
    revision: mutated ? 5 : 4,
    channel: 'web_agent', locale: 'en-NZ', claim_state: { workflow_state: 'professional_review' },
    form: {}, route: null, active_session_id: null, evidence: [], sessions: [], messages: [], decisions: [],
    signals: [{
      signal_id: 'sig_same_queue', code: 'manual_review', status: 'review_required',
      decisions: mutated ? [{ decision: 'resolved' }] : [],
    }],
    handoffs: [],
    staff_actions: [{
      action_id: 'act_same_queue', action_type: 'professional_review',
      status: mutated ? 'completed' : 'open', assigned_to: 'stf_demo',
    }],
    customer_updates: [], external_claim: null, assessor_routing: null,
    customer_next_step: {
      status: 'under_review', summary: 'A professional is reviewing the claim.', responsible_party: 'northwind',
    },
  })
  const fetchMock = vi.fn((url, options = {}) => {
    if (options.method === 'PATCH' && String(url).endsWith('/staff-actions/act_same_queue')) {
      mutated = true
      listItem.revision = 5
      return response({ revision: 5 })
    }
    if (String(url).endsWith('/clm_same_queue')) return response(detail())
    return response({ items: [listItem], page: { next_cursor: null } })
  })
  const dom = new JSDOM(employeeHtml, {
    runScripts: 'dangerously', url: 'http://127.0.0.1:8002/',
    beforeParse(window) {
      window.fetch = fetchMock
      window.crypto.randomUUID = () => 'same-queue-key'
    },
  })

  await waitFor(() => expect(dom.window.document.querySelector('#completeActionSelect').value).toBe('act_same_queue'))
  fillProfessionalReviewCompletion(dom.window.document)
  dom.window.document.querySelector('#completeStaffActionBtn').click()

  await waitFor(() => {
    expect(dom.window.document.querySelector('#claimCount').textContent).toBe('1 claim')
    expect(dom.window.document.querySelector('#detailStaffActions').style.display).toBe('none')
    expect(dom.window.document.querySelector('#completeActionSelect').value).toBe('')
    expect(dom.window.document.querySelector('#signalDecisionSelect').value).toBe('')
    expect(dom.window.document.querySelector('#completeStaffActionBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#saveAllSignalDecisionsBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#mutationStatus').textContent).toContain('persisted')
  })
  dom.window.close()
})

it('clears stale write-back state when the post-mutation refresh fails', async () => {
  let mutated = false
  const listItem = {
    claim_id: 'clm_refresh_failure', revision: 2, customer_reference: 'customer-refresh-failure',
    incident_type: 'motor', workflow_state: 'professional_review', queue: 'professional_review',
    priority: 'standard', next_action: 'REVIEW', evidence_summary: {}, open_handoff_count: 0,
    assignee_id: 'stf_demo', created_at: '2026-08-13T00:00:00Z', updated_at: '2026-08-13T00:02:00Z',
  }
  const detail = {
    ...listItem,
    channel: 'web_agent', locale: 'en-NZ', claim_state: { workflow_state: 'professional_review' },
    form: {}, route: null, active_session_id: null, evidence: [], sessions: [], messages: [], decisions: [],
    signals: [{ signal_id: 'sig_refresh_failure', decisions: [] }], handoffs: [],
    staff_actions: [{ action_id: 'act_refresh_failure', action_type: 'professional_review', status: 'open' }],
    customer_updates: [], external_claim: null, assessor_routing: null,
    customer_next_step: {
      status: 'under_review', summary: 'A professional is reviewing the claim.', responsible_party: 'northwind',
    },
  }
  const fetchMock = vi.fn((url, options = {}) => {
    if (options.method === 'PATCH' && String(url).endsWith('/staff-actions/act_refresh_failure')) {
      mutated = true
      return response({ revision: 3 })
    }
    if (String(url).endsWith('/clm_refresh_failure')) return response(detail)
    if (mutated) return response({ error: { message: 'Refresh unavailable' } }, 503)
    return response({ items: [listItem], page: { next_cursor: null } })
  })
  const dom = new JSDOM(employeeHtml, {
    runScripts: 'dangerously', url: 'http://127.0.0.1:8002/',
    beforeParse(window) {
      window.fetch = fetchMock
      window.crypto.randomUUID = () => 'refresh-failure-key'
    },
  })

  await waitFor(() => expect(dom.window.document.querySelector('#completeActionSelect').value).toBe('act_refresh_failure'))
  fillProfessionalReviewCompletion(dom.window.document)
  dom.window.document.querySelector('#completeStaffActionBtn').click()

  await waitFor(() => {
    expect(dom.window.document.querySelector('#errorBanner').textContent).toContain('Refresh unavailable')
    expect(dom.window.document.querySelector('#detailContent').textContent).toContain('Select a claim')
    expect(dom.window.document.querySelector('#detailStaffActions').style.display).toBe('none')
    expect(dom.window.document.querySelector('#createStaffActionBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#completeStaffActionBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#saveAllSignalDecisionsBtn').disabled).toBe(true)
  })
  dom.window.close()
})

it('blocks incomplete evidence, saves signal findings sequentially, and isolates claimant updates', async () => {
  let revision = 10
  const signalDecisions = { sig_policy: [], sig_history: [] }
  let completed = false
  const listItem = {
    claim_id: 'clm_review_path', revision, customer_reference: 'customer-review-path',
    incident_type: 'home', workflow_state: 'professional_review', queue: 'professional_review',
    priority: 'high', next_action: 'REVIEW', evidence_summary: { received: 1 },
    open_handoff_count: 0, assignee_id: 'stf_demo',
    created_at: '2026-08-13T00:00:00Z', updated_at: '2026-08-13T00:10:00Z',
  }
  const detail = () => ({
    ...listItem,
    revision,
    channel: 'web_agent', locale: 'en-NZ',
    claim_state: { workflow_state: completed ? 'ready_for_next' : 'professional_review' },
    form: {}, route: 'professional_review', active_session_id: null,
    evidence: [{
      evidence_id: 'evd_damage', kind: 'incident_image', status: 'received', source: 'claimant',
      original_filename: 'synthetic-damage.jpg',
    }],
    sessions: [], messages: [], decisions: [], retrievals: [],
    signals: [
      {
        signal_id: 'sig_policy', code: 'POLICY_CAUSE_REVIEW',
        summary: 'Does the evidence support the reported cause?',
        source_refs: ['evd_damage'], decisions: signalDecisions.sig_policy,
      },
      {
        signal_id: 'sig_history', code: 'HISTORY_REVIEW',
        summary: 'Is the history record relevant?',
        source_refs: ['his_synthetic'], decisions: signalDecisions.sig_history,
      },
    ],
    handoffs: [],
    staff_actions: [{
      action_id: 'act_review_path', action_type: 'professional_review',
      status: completed ? 'completed' : 'open', assigned_to: 'stf_demo',
      source_refs: ['evd_damage'],
    }],
    customer_updates: [], external_claim: null, assessor_routing: null,
    customer_next_step: {
      status: 'under_review', summary: 'A professional is reviewing the claim.',
      responsible_party: 'northwind',
    },
  })
  const signalRequests = []
  let completionRequest
  const fetchMock = vi.fn((url, options = {}) => {
    const path = String(url)
    if (options.method === 'POST' && path.includes('/signals/')) {
      const signalId = path.match(/\/signals\/([^/]+)\/decisions/)?.[1]
      const body = JSON.parse(options.body)
      signalRequests.push({ signalId, revision: options.headers['If-Match'], body })
      revision += 1
      listItem.revision = revision
      signalDecisions[signalId].push({
        decision: body.decision, reason_codes: body.reason_codes,
        summary: body.summary, actor_id: 'stf_demo',
      })
      return response({ revision })
    }
    if (options.method === 'PATCH' && path.endsWith('/staff-actions/act_review_path')) {
      completionRequest = {
        revision: options.headers['If-Match'],
        body: JSON.parse(options.body),
      }
      completed = true
      revision += 1
      listItem.revision = revision
      return response({ revision })
    }
    if (path.endsWith('/clm_review_path')) return response(detail())
    return response({ items: completed ? [] : [listItem], page: { next_cursor: null } })
  })
  const dom = new JSDOM(employeeHtml, {
    runScripts: 'dangerously', url: 'http://127.0.0.1:8002/',
    beforeParse(window) {
      window.fetch = fetchMock
      window.crypto.randomUUID = () => 'review-path-key'
    },
  })
  const document = dom.window.document

  await waitFor(() => {
    expect(document.querySelector('#completeActionSelect').value).toBe('act_review_path')
    expect(document.querySelectorAll('#evidenceReviewList .evidence-review-card')).toHaveLength(1)
  })
  fillProfessionalReviewCompletion(document)
  document.querySelector('#completeStaffActionBtn').click()
  await waitFor(() => {
    expect(document.querySelector('#mutationStatus').textContent)
      .toContain('Review every evidence item')
  })
  expect(completionRequest).toBeUndefined()

  const evidenceCard = document.querySelector('#evidenceReviewList .evidence-review-card')
  evidenceCard.querySelector('.evidence-review-disposition').value = 'accepted'
  evidenceCard.querySelector('.evidence-review-disposition')
    .dispatchEvent(new dom.window.Event('change'))
  evidenceCard.querySelector('.evidence-review-summary').value =
    'The image metadata and visible damage are consistent with the reported event.'

  const signalSelect = document.querySelector('#signalDecisionSelect')
  for (const [signalId, finding] of [
    ['sig_policy', 'The damage image supports the reported cause.'],
    ['sig_history', 'The history record concerns a different property and is not relevant.'],
  ]) {
    signalSelect.value = signalId
    signalSelect.dispatchEvent(new dom.window.Event('change'))
    const card = [...document.querySelectorAll('#signalDraftList .review-task-card')].at(-1)
    card.querySelector('textarea').value = finding
    card.querySelector('textarea').dispatchEvent(new dom.window.Event('input'))
    card.querySelector('button').click()
  }
  document.querySelector('#saveAllSignalDecisionsBtn').click()

  await waitFor(() => expect(signalRequests).toHaveLength(2))
  expect(signalRequests.map(request => request.revision)).toEqual(['10', '11'])
  expect(signalRequests.map(request => request.signalId)).toEqual(['sig_policy', 'sig_history'])
  await waitFor(() => {
    expect(document.querySelector('#signalActionStatus').textContent)
      .toBe('All signal decisions saved.')
  })

  fillProfessionalReviewCompletion(document)
  document.querySelector('#evidenceReviewList .evidence-review-disposition').value = 'accepted'
  document.querySelector('#evidenceReviewList .evidence-review-summary').value =
    'The image metadata and visible damage are consistent with the reported event.'
  document.querySelector('#completeStaffActionBtn').click()

  await waitFor(() => expect(completionRequest).toBeDefined())
  expect(completionRequest.revision).toBe('12')
  expect(completionRequest.body.result.summary).toContain('Evidence findings:')
  expect(completionRequest.body.result.reason_codes).toEqual(['STAFF_REVIEW_COMPLETED'])
  expect(completionRequest.body.customer_update.summary)
    .toBe('We completed the policy review. Your report can continue and Northwind will prepare the next step.')
  expect(completionRequest.body.customer_update).not.toHaveProperty('reason_codes')
  expect(completionRequest.body.customer_update.summary).not.toContain('evd_damage')
  expect(completionRequest.body.customer_update.summary).not.toContain('sig_policy')
  expect(completionRequest.body.customer_update.summary).not.toContain('sig_history')
  dom.window.close()
})

it('keeps Agent reply suggestions internal through suggested, accepted, edited, and rejected states', async () => {
  const item = queueItem(120, { claim_id: 'clm_agent_suggestion', open_handoff_count: 1, assignee_id: 'stf_demo' })
  const detail = {
    ...queueDetail(item),
    active_session_id: 'ses_agent_suggestion',
    messages: [{
      message_id: 'msg_claimant', actor: 'claimant', visibility: 'shared',
      content: { type: 'text', text: 'Can someone help me continue?' },
      created_at: '2026-08-13T00:01:00Z',
    }],
    handoffs: [{
      handoff_id: 'hnd_agent_suggestion', status: 'accepted', assigned_to: 'stf_demo',
      priority: 'standard', trigger: 'claimant_support_request', requested_action: 'Help the claimant continue.',
      packet: {},
    }],
    customer_next_step: {
      status: 'human_support_in_progress',
      summary: 'A Northwind staff member is reviewing the saved report.',
      responsible_party: 'northwind', required_items: [],
    },
  }
  const fetchMock = vi.fn((url) => {
    if (String(url).endsWith('/clm_agent_suggestion')) return response(detail)
    return response({ items: [item], page: { next_cursor: null } })
  })
  const dom = new JSDOM(employeeHtml, {
    runScripts: 'dangerously', url: 'http://127.0.0.1:8002/',
    beforeParse(window) { window.fetch = fetchMock },
  })
  const document = dom.window.document

  await waitFor(() => expect(document.querySelector('#customerChatNav').disabled).toBe(false))
  document.querySelector('#customerChatNav').click()
  await waitFor(() => expect(document.querySelector('#customerChatText').disabled).toBe(false))
  document.querySelector('#generateAgentSuggestion').click()
  await waitFor(() => expect(document.querySelector('#agentSuggestionStatus').textContent).toContain('Suggested'))
  expect(document.querySelector('#customerChatText').value).toBe('')

  document.querySelector('#useAgentSuggestion').click()
  expect(document.querySelector('#agentSuggestionStatus').textContent).toContain('Accepted')
  expect(document.querySelector('#customerChatText').value).toContain('Northwind staff member')
  document.querySelector('#customerChatText').value += ' I checked the current claim state.'
  document.querySelector('#customerChatText').dispatchEvent(new dom.window.Event('input', { bubbles: true }))
  expect(document.querySelector('#agentSuggestionStatus').textContent).toContain('Edited')
  document.querySelector('#rejectAgentSuggestion').click()
  expect(document.querySelector('#agentSuggestionStatus').textContent).toContain('Rejected')
  expect(document.querySelector('#agentSuggestionText').value).toBe('')
  dom.window.close()
})

it('announces queue failures and exposes named keyboard controls', async () => {
  let releaseRequest
  const pendingResponse = new Promise((resolve) => {
    releaseRequest = resolve
  })
  const dom = new JSDOM(employeeHtml, {
    runScripts: 'dangerously',
    url: 'http://127.0.0.1:8002/',
    beforeParse(window) {
      window.fetch = vi.fn(() => pendingResponse)
    },
  })

  await waitFor(() => {
    expect(dom.window.document.querySelector('#refreshClaims').disabled).toBe(true)
    expect(dom.window.document.querySelector('#refreshClaims').textContent).toBe('Refreshing...')
    expect(dom.window.document.querySelector('#workbenchView').getAttribute('aria-busy')).toBe('true')
  })

  releaseRequest(new Response(JSON.stringify({ error: { message: 'Queue unavailable' } }), {
    status: 503,
    headers: { 'Content-Type': 'application/json' },
  }))

  await waitFor(() => {
    const alert = dom.window.document.querySelector('#errorBanner')
    expect(alert.getAttribute('role')).toBe('alert')
    expect(alert.textContent).toContain('Queue unavailable')
    expect(dom.window.document.querySelector('#refreshClaims').disabled).toBe(false)
    expect(dom.window.document.querySelector('#workbenchView').getAttribute('aria-busy')).toBe('false')
  })
  expect(dom.window.document.querySelector('#customerChatText').getAttribute('aria-label')).toBe('Message to claimant')
  expect(dom.window.document.querySelector('#chatInput').getAttribute('aria-label')).toBe('Assistant question')
  expect(dom.window.document.querySelector('#chatFileBtn').getAttribute('aria-label')).toBe('Attach files')
  const attachmentInput = dom.window.document.querySelector('#chatFileInput')
  Object.defineProperty(attachmentInput, 'files', {
    configurable: true,
    value: [new dom.window.File(['synthetic'], 'evidence.txt', { type: 'text/plain' })],
  })
  attachmentInput.dispatchEvent(new dom.window.Event('change'))
  expect(dom.window.document.querySelector('#chatAttachments').textContent).toContain('evidence.txt')
  expect(dom.window.document.querySelector('[aria-label="Remove evidence.txt"]')).not.toBeNull()
  dom.window.close()
})
