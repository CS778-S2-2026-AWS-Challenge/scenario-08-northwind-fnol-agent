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

it('preserves every entered professional-review field when the staff-action PATCH fails', async () => {
  const item = {
    claim_id: 'clm_patch_failure',
    revision: 7,
    customer_reference: 'customer-patch-failure',
    incident_type: 'motor',
    workflow_state: 'professional_review',
    queue: 'professional_review',
    priority: 'high',
    next_action: 'REVIEW',
    route: 'professional_review',
    evidence_state: 'received',
    evidence_summary: { received: 1, pending: 0, needs_attention: 0 },
    next_action_summary: 'Review the saved evidence and record a professional decision.',
    responsible_party: 'claims_professional',
    claim_creation_status: null,
    assessor_routing_status: null,
    open_handoff_count: 0,
    assignee_id: 'stf_demo',
    created_at: '2026-08-13T00:00:00Z',
    updated_at: '2026-08-13T00:07:00Z',
  }
  const detail = {
    ...item,
    channel: 'web_agent',
    locale: 'en-NZ',
    claim_state: { workflow_state: 'professional_review', evidence: 'received' },
    form: {},
    active_session_id: null,
    evidence: [
      {
        evidence_id: 'evd_patch_failure',
        claim_id: item.claim_id,
        kind: 'incident_image',
        status: 'received',
        file_status: 'ready',
        original_filename: 'synthetic-damage.jpg',
        media_type: 'image/jpeg',
        size_bytes: 1000,
        source: 'claimant',
        related_fields: ['vehicle.damage_description'],
        needed_for: ['current_action'],
        provenance: {},
        claimant_note: 'Photo supplied by the claimant.',
        created_at: '2026-08-13T00:01:00Z',
        updated_at: '2026-08-13T00:01:00Z',
      },
    ],
    sessions: [],
    messages: [],
    decisions: [],
    retrievals: [],
    signals: [],
    handoffs: [],
    staff_actions: [
      {
        action_id: 'act_patch_failure',
        claim_id: item.claim_id,
        action_type: 'professional_review',
        status: 'open',
        assigned_to: 'stf_demo',
        requested_outcome: 'Review the supplied evidence and record the result.',
        source_refs: ['evd_patch_failure'],
        created_at: '2026-08-13T00:02:00Z',
      },
    ],
    customer_updates: [],
    external_claim: null,
    assessor_routing: null,
    customer_next_step: {
      status: 'under_review',
      summary: 'A claims professional is reviewing the report.',
      responsible_party: 'northwind',
      required_items: [],
    },
  }

  const fetchMock = vi.fn((url, options = {}) => {
    const path = String(url)
    if (options.method === 'PATCH' && path.endsWith('/staff-actions/act_patch_failure')) {
      return response(
        {
          error: {
            code: 'REVISION_CONFLICT',
            message: 'The claim changed after this page was loaded.',
            current_revision: 8,
          },
        },
        409,
      )
    }
    if (path.endsWith(`/${item.claim_id}`)) return response(detail)
    return response({ items: [item], page: { next_cursor: null } })
  })

  const dom = new JSDOM(employeeHtml, {
    runScripts: 'dangerously',
    url: 'http://127.0.0.1:8002/',
    beforeParse(window) {
      window.fetch = fetchMock
      window.crypto.randomUUID = () => 'patch-failure-key'
    },
  })
  const document = dom.window.document

  await waitFor(() => {
    expect(document.querySelector('#completeActionSelect').value).toBe('act_patch_failure')
    expect(document.querySelectorAll('#evidenceReviewList .evidence-review-card')).toHaveLength(1)
  })

  const resultSummary =
    'The supplied image is consistent with the reported damage, but the write-back must be retried.'
  const customerSummary =
    'We reviewed the supplied information. Your report will continue after the review is saved.'
  const evidenceSummary =
    'The image shows the reported rear damage and is suitable for this review.'

  document.querySelector('#completeResultSummary').value = resultSummary
  document.querySelector('#completeWorkflowState').value = 'ready_for_next'
  document.querySelector('#customerUpdateSummary').value = customerSummary

  const evidenceCard = document.querySelector('#evidenceReviewList .evidence-review-card')
  const disposition = evidenceCard.querySelector('.evidence-review-disposition')
  const evidenceFinding = evidenceCard.querySelector('.evidence-review-summary')
  disposition.value = 'accepted'
  disposition.dispatchEvent(new dom.window.Event('change'))
  evidenceFinding.value = evidenceSummary
  evidenceFinding.dispatchEvent(new dom.window.Event('input'))

  const getCallsBeforePatch = fetchMock.mock.calls.filter(([, options = {}]) => !options.method).length
  document.querySelector('#completeStaffActionBtn').click()

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/staff-actions/act_patch_failure'),
      expect.objectContaining({ method: 'PATCH' }),
    )
    expect(document.querySelector('#errorBanner').textContent)
      .toContain('The claim changed after this page was loaded.')
  })

  expect(document.querySelector('#completeResultSummary').value).toBe(resultSummary)
  expect(document.querySelector('#completeWorkflowState').value).toBe('ready_for_next')
  expect(document.querySelector('#customerUpdateSummary').value).toBe(customerSummary)
  expect(disposition.value).toBe('accepted')
  expect(evidenceFinding.value).toBe(evidenceSummary)
  expect(document.querySelector('#completeActionSelect').value).toBe('act_patch_failure')
  expect(document.querySelector('#completeStaffActionBtn').disabled).toBe(false)
  expect(document.querySelector('#detailStaffActions').style.display).toBe('block')

  const getCallsAfterPatch = fetchMock.mock.calls.filter(([, options = {}]) => !options.method).length
  expect(getCallsAfterPatch).toBe(getCallsBeforePatch)
  expect(document.querySelector('#claimCount').textContent).toBe('1 claim')
  expect(document.querySelector('#detailContent').textContent).toContain('customer-patch-failure')

  dom.window.close()
})
