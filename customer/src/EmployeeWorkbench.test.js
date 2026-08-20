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
    expect(dom.window.document.querySelector('#signalDecisionSelect').value).toBe('sig_review')
  })
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
    expect(dom.window.document.querySelector('#confirmSignalBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#dismissSignalBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#resolveSignalBtn').disabled).toBe(true)
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
  dom.window.document.querySelector('#completeStaffActionBtn').click()

  await waitFor(() => {
    expect(dom.window.document.querySelector('#claimCount').textContent).toBe('1 claim')
    expect(dom.window.document.querySelector('#detailStaffActions').style.display).toBe('none')
    expect(dom.window.document.querySelector('#completeActionSelect').value).toBe('')
    expect(dom.window.document.querySelector('#signalDecisionSelect').value).toBe('')
    expect(dom.window.document.querySelector('#completeStaffActionBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#confirmSignalBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#dismissSignalBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#resolveSignalBtn').disabled).toBe(true)
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
  dom.window.document.querySelector('#completeStaffActionBtn').click()

  await waitFor(() => {
    expect(dom.window.document.querySelector('#errorBanner').textContent).toContain('Refresh unavailable')
    expect(dom.window.document.querySelector('#detailContent').textContent).toContain('Select a claim')
    expect(dom.window.document.querySelector('#detailStaffActions').style.display).toBe('none')
    expect(dom.window.document.querySelector('#createStaffActionBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#completeStaffActionBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#confirmSignalBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#dismissSignalBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#resolveSignalBtn').disabled).toBe(true)
  })
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
