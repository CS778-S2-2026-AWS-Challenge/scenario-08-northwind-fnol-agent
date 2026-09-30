import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ExternalServicesPage from './ExternalServicesPage.jsx'

const CLAIM = {
  claim_id: 'clm_motor_1042',
  incident_type: 'motor',
}

const ASSIGNED_SERVICE = {
  service_identity: 'vehicle_damage_assessment_routing',
  service_name: 'Vehicle damage assessment',
  provider: 'Controlled assessment fixture',
  purpose: 'Inspect the reported vehicle damage and prepare an assessment.',
  shared_data_summary: ['Claim reference', 'Confirmed incident region'],
  consent_status: 'granted',
  status: 'assigned',
  routing: {
    assessor_reference: 'assessor-7',
    queue_reference: 'queue-42',
    expected_by: '2026-10-02T01:30:00Z',
    next_step: 'The assessor will contact you to arrange the inspection.',
    limitations: ['Controlled simulation only; no production provider is connected.'],
  },
}

const MESSAGE_OFFER = {
  offer_id: 'offer-repairer-1',
  agent_message_id: 'msg-agent-1',
  service_identity: 'repairer_information_or_link',
  service_name: 'Repairer information',
  provider: 'Northwind repair guidance',
  purpose: 'Help you find the right repair information for this claim.',
  shared_data_summary: ['Northwind sends no claim information for this manual service'],
  consent_status: 'not_recorded',
  status: 'manual_available',
  routing: null,
  official_url: 'https://www.example.test/repairs',
  can_request: false,
}

describe('ExternalServicesPage', () => {
  it('makes the no-service state and required claimant action explicit', async () => {
    const user = userEvent.setup()
    const onBackToOverview = vi.fn()
    const onWhatToProvide = vi.fn()

    render(
      <ExternalServicesPage
        action={null}
        claim={CLAIM}
        onBackToOverview={onBackToOverview}
        onWhatToProvide={onWhatToProvide}
      />,
    )

    expect(screen.getByRole('heading', { level: 1, name: 'External services' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'No external service is needed right now' })).toBeVisible()
    expect(screen.getByText(/You don’t need to do anything/i)).toBeVisible()
    expect(screen.getByText('clm_motor_1042')).toBeVisible()
    expect(screen.getByText('We’ll keep you informed')).toBeVisible()
    expect(screen.getByText('Your information stays protected')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'What to provide' }))
    expect(onWhatToProvide).toHaveBeenCalledOnce()
    expect(onBackToOverview).not.toHaveBeenCalled()
  })

  it('uses the same card structure while a service is being arranged', () => {
    render(
      <ExternalServicesPage
        action={{ ...ASSIGNED_SERVICE, status: 'ready_to_request', routing: null }}
        claim={CLAIM}
        onBackToOverview={vi.fn()}
        onWhatToProvide={vi.fn()}
      />,
    )

    expect(screen.getByText('Ready to request')).toBeVisible()
    expect(screen.getByText(/No request has been sent yet/i)).toBeVisible()
    expect(screen.getByText('Controlled assessment fixture')).toBeVisible()
    expect(screen.getByText('Permission recorded')).toBeVisible()
  })

  it('shows a message-bound recommendation instead of the no-service state', () => {
    render(
      <ExternalServicesPage
        action={null}
        messageActions={[MESSAGE_OFFER]}
        claim={CLAIM}
        onBackToOverview={vi.fn()}
        onWhatToProvide={vi.fn()}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Repairer information' })).toBeVisible()
    expect(screen.getByText('Northwind repair guidance')).toBeVisible()
    expect(screen.getAllByText(/find the right repair information/i)).toHaveLength(2)
    expect(screen.queryByRole('heading', { name: 'No external service is needed right now' }))
      .not.toBeInTheDocument()
  })

  it('shows every claimant-safe provider detail for an assigned service', () => {
    render(
      <ExternalServicesPage
        action={ASSIGNED_SERVICE}
        claim={CLAIM}
        onBackToOverview={vi.fn()}
        onWhatToProvide={vi.fn()}
      />,
    )

    expect(screen.getByText('Assessor assigned')).toBeVisible()
    expect(screen.getByText('Controlled assessment fixture')).toBeVisible()
    expect(screen.getAllByText('Vehicle damage assessment')).toHaveLength(2)
    expect(screen.getAllByText(/Inspect the reported vehicle damage/i)).toHaveLength(2)
    expect(screen.getByText('Claim reference')).toBeVisible()
    expect(screen.getByText('Confirmed incident region')).toBeVisible()
    expect(screen.getByText(/contact you to arrange the inspection/i)).toBeVisible()
    expect(screen.getByText('assessor-7')).toBeVisible()
    expect(screen.getByText('queue-42')).toBeVisible()
  })

  it('renders a completed state only from server-projected lifecycle wording', () => {
    render(
      <ExternalServicesPage
        action={{
          ...ASSIGNED_SERVICE,
          status: 'result_verified',
          effective_label: 'External service completed',
          status_detail: 'The assessment is complete and Northwind is reviewing the result.',
          attention_required: false,
          provider_next_step: 'No further provider action is needed.',
          routing: null,
        }}
        claim={CLAIM}
        onBackToOverview={vi.fn()}
        onWhatToProvide={vi.fn()}
      />,
    )

    expect(screen.getByText('External service completed')).toBeVisible()
    expect(screen.getByText('No further provider action is needed.')).toBeVisible()
    expect(screen.queryByText('Assessor assigned')).not.toBeInTheDocument()
  })
})
