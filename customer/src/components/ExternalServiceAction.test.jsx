import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ExternalServiceAction from './ExternalServiceAction'

// `docs/frontend-and-runtime-quality-standard.md` 8.1 requires a component test for
// component display and interaction behaviour. The backend regressions prove the
// projection value; these prove what the claimant is shown for it.

const BASE_ACTION = {
  service_identity: 'vehicle_damage_assessment_routing',
  service_name: 'Vehicle damage assessment',
  provider: 'Controlled assessment fixture',
  purpose: 'Request an assessor for the vehicle damage recorded in this claim.',
  shared_data_summary: ['Your confirmed incident region'],
  consent_status: 'granted',
  routing: null,
  failure_code: null,
  can_request: false,
}

function renderAction(action) {
  return render(
    <ExternalServiceAction
      action={{ ...BASE_ACTION, ...action }}
      consentChecked={false}
      setConsentChecked={vi.fn()}
      onRequest={vi.fn()}
      status="idle"
      error={null}
    />,
  )
}

describe('an assessment request whose outcome is not confirmed', () => {
  it('says the request may already have arrived and not to resend it', () => {
    renderAction({ status: 'awaiting_reconciliation', failure_code: 'timeout' })

    expect(screen.getByText('Assessment request outcome not confirmed')).toBeInTheDocument()
    expect(
      screen.getByText(/may already have reached the assessor/i),
    ).toHaveTextContent(/please do not resend it/i)
  })

  it('offers no retry control, so the claimant cannot send a second request', () => {
    renderAction({ status: 'awaiting_reconciliation', failure_code: 'timeout' })

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('does not present it as a failure the claimant may retry', () => {
    renderAction({ status: 'awaiting_reconciliation', failure_code: 'timeout' })

    // The retryable wording for the same `timeout` code is the one thing this state
    // must not show: it tells the claimant the request can safely be sent again.
    expect(screen.queryByText(/can safely retry the same request/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Assessment request not sent/i)).not.toBeInTheDocument()
  })

  it('still offers the retry control for a failure that never reached the assessor', () => {
    renderAction({ status: 'retryable_failure', failure_code: 'timeout', can_request: true })

    expect(screen.getByRole('button', { name: /retry assessment request/i })).toBeInTheDocument()
    expect(screen.getByText(/can safely retry the same request/i)).toBeInTheDocument()
    expect(
      screen.queryByText('Assessment request outcome not confirmed'),
    ).not.toBeInTheDocument()
  })
})
