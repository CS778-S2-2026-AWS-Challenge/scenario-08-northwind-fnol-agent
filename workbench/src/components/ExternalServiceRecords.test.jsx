import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import ExternalServiceRecords, { ExternalServiceSummary } from './ExternalServiceRecords.jsx'

const request = {
  task: {
    task_id: 'tsk_1',
    claim_id: 'clm_1',
    service_identity: 'vehicle damage assessor',
    requested_action: 'vehicle damage assessment',
    integration_source: 'fixture',
    status: 'unknown_outcome',
    delivery: 'submitted',
    delivery_evidence: 'provider-receipt-1',
    failure_code: 'timeout',
    provider_reference: null,
    created_at: '2026-09-03T01:00:00Z',
    updated_at: '2026-09-03T01:10:00Z',
  },
  request: {
    task_id: 'tsk_1',
    claim_id: 'clm_1',
    purpose: 'Assess the vehicle damage.',
    disclosed_fields: ['claim_id', 'location.region'],
    authorisation: {
      northwind_authority_ref: 'AUTH-1',
      claimant_consent_ref: 'CONSENT-1',
      authorised_revision: 4,
    },
    prepared_at: '2026-09-03T00:59:00Z',
    sent_at: '2026-09-03T01:00:00Z',
    operation_id: 'op_1',
  },
  lifecycle: {
    stakeholder: 'external_party',
    service: 'vehicle damage assessor',
    request_type: 'vehicle damage assessment',
    authority_state: 'recorded',
    consent_state: 'recorded',
    delivery_state: 'submitted',
    verification_state: 'reconciliation_required',
    pending_owner: 'claims_professional',
    status_label: 'Outcome not confirmed',
    status_detail: 'Submission may have occurred; the result remains unknown.',
    result: null,
    limitation: 'Synthetic fixture record; no production provider completion is verified.',
    next_action: 'Reconcile by operation or provider reference before any retry.',
    needs_attention: true,
  },
}

describe('ExternalServiceRecords', () => {
  it('shows authority and requires reconciliation for an unknown outcome', async () => {
    const user = userEvent.setup()
    render(<ExternalServiceRecords records={[request]} />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    expect(screen.getByText('Recorded · consent Recorded')).toBeVisible()
    expect(screen.getAllByText('Reconcile by operation or provider reference before any retry.')[0]).toBeVisible()
    expect(screen.getByText('AUTH-1')).toBeVisible()
    expect(screen.getByText('CONSENT-1')).toBeVisible()
    expect(screen.getByText('Submission')).toBeVisible()
    expect(screen.getByText('Submitted')).toBeVisible()
    expect(screen.getByText(/Synthetic fixture record; no production provider completion is verified/)).toBeVisible()
  })

  it('states when no request has been prepared', async () => {
    const user = userEvent.setup()
    render(<ExternalServiceRecords records={[{ ...request, request: null, task: { ...request.task, status: 'prepared', delivery: 'not_submitted', failure_code: null }, lifecycle: { ...request.lifecycle, authority_state: 'not_recorded', consent_state: 'not_recorded', delivery_state: 'not_submitted', verification_state: 'not_started', status_label: 'Pending', status_detail: 'The request is prepared and has not been submitted.', next_action: 'Review the projected request before submission.', needs_attention: false } }]} />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    expect(screen.getByText('Request details have not been prepared.')).toBeVisible()
    expect(screen.getByText('No disclosure manifest recorded')).toBeVisible()
  })

  it('does not infer completion from an accepted fixture task', () => {
    render(<ExternalServiceSummary resource={{
      status: 'available',
      items: [{ ...request, task: { ...request.task, status: 'accepted', failure_code: null }, lifecycle: { ...request.lifecycle, status_label: 'Completion not confirmed', status_detail: 'The provider acknowledged the request; no verified completed result is recorded.', verification_state: 'pending_verification', pending_owner: 'external_party', needs_attention: false } }],
    }} />)

    expect(screen.getByText(/Completion not confirmed/)).toBeInTheDocument()
    expect(screen.getByText(/Synthetic fixture record; no production provider completion is verified/)).toBeInTheDocument()
    expect(screen.queryByText(/complete$/i)).not.toBeInTheDocument()
  })

  it.each([
    ['prepared', 'Pending'],
    ['retryable_failure', 'Failed'],
    ['terminal_failure', 'Failed'],
    ['unknown_outcome', 'Outcome not confirmed'],
  ])('renders %s with truthful summary status %s', (status, label) => {
    render(<ExternalServiceSummary resource={{
      status: 'available',
      items: [{ ...request, task: { ...request.task, status }, lifecycle: { ...request.lifecycle, status_label: label } }],
    }} />)

    expect(screen.getByText(new RegExp(label))).toBeInTheDocument()
  })

  it('preserves unavailable and empty third-party states', () => {
    const { rerender } = render(<ExternalServiceSummary resource={{
      status: 'unavailable',
      limitation: 'External-service records are temporarily unavailable.',
      items: [],
    }} />)
    expect(screen.getByText('External-service records are temporarily unavailable.')).toBeInTheDocument()

    rerender(<ExternalServiceSummary resource={{ status: 'available', items: [] }} />)
    expect(screen.getByText('No third-party task is recorded for this Claim.')).toBeInTheDocument()
  })

  it('preserves the loading state', () => {
    render(<ExternalServiceSummary resource={{ loading: true, items: [] }} />)

    expect(screen.getByText('Loading third-party tasks...')).toBeInTheDocument()
  })
})
