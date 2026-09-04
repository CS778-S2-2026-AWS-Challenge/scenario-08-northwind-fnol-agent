import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ClaimWorkspace from './ClaimWorkspace.jsx'

const detail = {
  claim_id: 'clm_1',
  display_reference: 'NW-1042',
  revision: 4,
  claimant: { customer_id: 'cus_1', display_name: 'Alex Morgan' },
  incident: { family: 'motor', summary: 'Rear-end collision.' },
  lifecycle_state: 'professional_review',
  workflow_state: 'professional_review',
  updated_at: '2026-09-03T01:00:00Z',
  claim_state: { workflow_state: 'professional_review' },
  ownership: { state: 'unassigned', current_staff_access: 'read_only' },
  priority_projection: { level: 'standard' },
  work_summary: { queue_key: 'professional_review', missing_information: [], risk_signals: [] },
  allowed_actions: [],
  customer_next_step: { responsible_party: 'claims_professional', summary: 'Review is required.' },
  tags: [],
}

const props = {
  detail,
  resources: { handoffs: { items: [] } },
  loading: false,
  error: '',
  section: 'summary',
  draft: '',
  profile: { staff_id: 'stf_1' },
  onSection: vi.fn(),
  onDraft: vi.fn(),
  onAccept: vi.fn(),
  onResolve: vi.fn(),
  onSignalDecision: vi.fn(),
  onCreateAction: vi.fn(),
  onUpdateAction: vi.fn(),
  onLoadEvidence: vi.fn(),
  onSend: vi.fn(),
}

describe('ClaimWorkspace navigation', () => {
  it('exposes one selected tab and a labelled tab panel', () => {
    render(<ClaimWorkspace {...props} />)

    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Evidence' })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', 'claim-tab-summary')
  })

  it('supports arrow-key tab activation', async () => {
    const onSection = vi.fn()
    const user = userEvent.setup()
    render(<ClaimWorkspace {...props} onSection={onSection} />)

    screen.getByRole('tab', { name: 'Overview' }).focus()
    await user.keyboard('{ArrowRight}')

    expect(onSection).toHaveBeenCalledWith('conversation')
  })

  it('renders paged field resources instead of expecting fields on Claim detail', () => {
    render(<ClaimWorkspace
      {...props}
      section="fields"
      resources={{
        fields: {
          status: 'available',
          items: [{ code: 'incident.location', field: { value: 'Queen Street', status: 'confirmed', source: 'claimant', needed_for: 'current_action' } }],
        },
      }}
    />)

    expect(screen.getByText('Queen Street')).toBeInTheDocument()
    expect(screen.getByText(/confirmed.*claimant.*current action/i)).toBeInTheDocument()
  })

  it('shows only API-projected structured Claim Context on the overview', () => {
    render(<ClaimWorkspace
      {...props}
      detail={{ ...detail, form: { 'internal.hidden': { value: 'must not render' } } }}
      resources={{
        handoffs: { items: [] },
        fields: {
          status: 'available',
          items: [{ code: 'incident.description', field: { value: 'Rear-end collision', status: 'confirmed', source: 'claimant', needed_for: 'current_action' } }],
        },
        externalRequests: { status: 'available', items: [] },
      }}
    />)

    expect(screen.getByRole('heading', { name: 'Claim Context' })).toBeInTheDocument()
    expect(screen.getByText('Incident Description')).toBeInTheDocument()
    expect(screen.getByText('Rear-end collision')).toBeInTheDocument()
    expect(screen.queryByText('must not render')).not.toBeInTheDocument()
  })

  it('shows only runtime-projected staff actions that are actually available', () => {
    render(<ClaimWorkspace
      {...props}
      detail={{
        ...detail,
        allowed_actions: [
          { action_code: 'ownership.request_cowork', target_ref: 'clm_1', label: 'Request cowork access', purpose: 'Ask the owner to collaborate.', availability: 'confirmation_required' },
          { action_code: 'human.accept_handoff', target_ref: 'hnd_1', label: 'Accept Claim', purpose: 'Assigned to another staff member.', availability: 'blocked', blocked_reason: 'This work is assigned to another staff member.' },
        ],
      }}
      resources={{ handoffs: { items: [] }, fields: { items: [] }, externalRequests: { items: [] } }}
    />)

    const availableActions = screen.getByRole('heading', { name: 'Available staff actions' }).closest('section')
    expect(within(availableActions).getByText('Request cowork access')).toBeInTheDocument()
    expect(screen.queryByText('Accept Claim')).not.toBeInTheDocument()
    expect(screen.queryByText('This work is assigned to another staff member.')).not.toBeInTheDocument()
  })
})
