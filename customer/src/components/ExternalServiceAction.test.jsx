import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ExternalServiceAction, { ExternalServiceOverview } from './ExternalServiceAction'

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

function renderAction(action, props = {}) {
  return render(
    <ExternalServiceAction
      action={{ ...BASE_ACTION, ...action }}
      consentChecked={props.consentChecked ?? false}
      setConsentChecked={props.setConsentChecked ?? vi.fn()}
      onRequest={props.onRequest ?? vi.fn()}
      status={props.status ?? 'idle'}
      error={props.error ?? null}
    />,
  )
}

describe('controlled assessor claimant states', () => {
  it('requires claimant permission before enabling the first assessor request', () => {
    const action = {
      status: 'consent_required',
      consent_status: 'not_recorded',
      can_request: true,
    }
    const { rerender } = renderAction(action)

    expect(screen.getByText('What will be shared')).toBeInTheDocument()
    expect(screen.getByText('Your confirmed incident region')).toBeInTheDocument()
    expect(screen.getByRole('checkbox')).not.toBeChecked()
    expect(
      screen.getByRole('button', { name: /agree and request assessor/i }),
    ).toBeDisabled()

    rerender(
      <ExternalServiceAction
        action={{ ...BASE_ACTION, ...action }}
        consentChecked
        setConsentChecked={vi.fn()}
        onRequest={vi.fn()}
        status="idle"
        error={null}
      />,
    )

    expect(
      screen.getByRole('button', { name: /agree and request assessor/i }),
    ).toBeEnabled()
  })

  it('keeps a ready request distinct from a sent or completed request', () => {
    render(
      <ExternalServiceOverview
        action={{ ...BASE_ACTION, status: 'ready_to_request', can_request: true }}
      />,
    )

    expect(screen.getByText('Ready to request')).toBeInTheDocument()
    expect(screen.getByText(/No request has been sent yet/i)).toBeInTheDocument()
    expect(screen.queryByText(/Assessor assigned/i)).not.toBeInTheDocument()
  })

  it.each([
    [
      'queued',
      'Request accepted into the assessor queue',
      'The assessor request is waiting in the controlled queue.',
    ],
    [
      'assigned',
      'Assessor assigned',
      'A controlled assessor is assigned. The assessment is still in progress.',
    ],
  ])('does not present %s progress as completed service', (status, heading, nextStep) => {
    renderAction({
      status,
      routing: {
        next_step: nextStep,
        queue_reference: 'queue-42',
        assessor_reference: status === 'assigned' ? 'assessor-7' : null,
        expected_by: '2026-09-16T01:30:00Z',
        limitations: ['Controlled simulation only; no production provider is connected.'],
      },
    })

    expect(screen.getByText(heading)).toBeInTheDocument()
    expect(screen.getByText(nextStep)).toBeInTheDocument()
    expect(
      screen.getByText(/Controlled simulation only; no production provider is connected/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/assessment complete/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/claim decision complete/i)).not.toBeInTheDocument()
  })

  it('keeps terminal failure with Northwind and exposes no claimant retry control', () => {
    renderAction({
      status: 'terminal_failure',
      failure_code: 'access_denied',
      can_request: false,
    })

    expect(screen.getByText('Assessment request not sent')).toBeInTheDocument()
    expect(screen.getByText(/Northwind must review the request before trying again/i)).toBeInTheDocument()
    expect(screen.getByText(/Northwind needs to review this before another request/i)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('shows the persistent claimant-safe assessor status without inventing provider completion', () => {
    render(
      <ExternalServiceOverview
        action={{
          ...BASE_ACTION,
          status: 'queued',
          routing: {
            next_step: 'The request is queued with the controlled assessment fixture.',
            queue_reference: 'queue-42',
            assessor_reference: null,
            expected_by: '2026-09-16T01:30:00Z',
            limitations: ['Simulation-only; it must not be described as a production provider.'],
          },
        }}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Vehicle damage assessment' })).toBeInTheDocument()
    expect(screen.getByText('Controlled assessment fixture')).toBeInTheDocument()
    expect(screen.getByText('Permission recorded')).toBeInTheDocument()
    expect(screen.getByText('Request queued')).toBeInTheDocument()
    expect(screen.getByText('queue-42')).toBeInTheDocument()
    expect(
      screen.getByText(/Simulation-only; it must not be described as a production provider/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText('The request is queued with the controlled assessment fixture.'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/assessment complete/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/claim decision complete/i)).not.toBeInTheDocument()
  })
})

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
