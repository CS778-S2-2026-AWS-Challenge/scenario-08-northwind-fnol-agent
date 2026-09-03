import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import ExternalServiceRecords from './ExternalServiceRecords.jsx'

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
}

describe('ExternalServiceRecords', () => {
  it('shows authority and requires reconciliation for an unknown outcome', async () => {
    const user = userEvent.setup()
    render(<ExternalServiceRecords records={[request]} />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    expect(screen.getByText('Northwind authority and claimant consent recorded')).toBeVisible()
    expect(screen.getAllByText('Reconcile by operation or provider reference before any retry.')[0]).toBeVisible()
    expect(screen.getByText('AUTH-1')).toBeVisible()
    expect(screen.getByText('CONSENT-1')).toBeVisible()
  })

  it('states when no request has been prepared', async () => {
    const user = userEvent.setup()
    render(<ExternalServiceRecords records={[{ ...request, request: null, task: { ...request.task, status: 'prepared', delivery: 'not_submitted', failure_code: null } }]} />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    expect(screen.getByText('Request details have not been prepared.')).toBeVisible()
    expect(screen.getByText('No disclosure manifest recorded')).toBeVisible()
  })
})
