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
      reason: 'The claimant requested a person.',
      requested_action: 'Continue with the saved report.',
      assigned_to: handoffStatus === 'accepted' ? 'stf_demo' : null,
      packet: {
        promised_next_step: 'A staff member will review the report.',
        pending_items: ['evd_police'],
        missing_items: [],
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
    expect(dom.window.document.body.textContent).toContain('Human Requested · Accepted')
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
    expect(dom.window.document.querySelector('#decideSignalBtn').disabled).toBe(true)
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
    expect(dom.window.document.querySelector('#detailStaffActions').style.display).toBe('block')
    expect(dom.window.document.querySelector('#completeActionSelect').value).toBe('')
    expect(dom.window.document.querySelector('#signalDecisionSelect').value).toBe('')
    expect(dom.window.document.querySelector('#completeStaffActionBtn').disabled).toBe(true)
    expect(dom.window.document.querySelector('#decideSignalBtn').disabled).toBe(true)
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
    expect(dom.window.document.querySelector('#decideSignalBtn').disabled).toBe(true)
  })
  dom.window.close()
})
