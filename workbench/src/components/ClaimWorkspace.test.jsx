import { render, screen, waitFor, within } from '@testing-library/react'
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
  onOwnershipAction: vi.fn(),
  onReopen: vi.fn(),
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

  it('uses section summaries instead of rendering full resource records on the overview', async () => {
    const user = userEvent.setup()
    render(<ClaimWorkspace
      {...props}
      detail={{ ...detail, form: { 'internal.hidden': { value: 'must not render' } }, section_summaries: { fields: { status: 'available', total: 8, needs_attention: 2 } } }}
      resources={{
        handoffs: { items: [] },
        fields: {
          status: 'available',
          items: [{ code: 'incident.description', field: { value: 'Rear-end collision', status: 'confirmed', source: 'claimant', needed_for: 'current_action' } }],
        },
        externalRequests: { status: 'available', items: [] },
      }}
    />)

    await user.click(screen.getByText('Supporting Claim context'))
    expect(screen.getByText(/8 records.*2 need attention/i)).toBeVisible()
    expect(screen.queryByText('Incident Description')).not.toBeInTheDocument()
    expect(screen.queryByText('must not render')).not.toBeInTheDocument()
  })

  it('renders only the backend-selected primary action and removes the generic action list', () => {
    render(<ClaimWorkspace
      {...props}
      detail={{
        ...detail,
        work_summary: {
          ...detail.work_summary,
          primary_action_code: 'ownership.request_cowork',
          primary_action_target_ref: 'clm_1',
        },
        allowed_actions: [
          { action_code: 'ownership.request_cowork', target_type: 'claim', target_ref: 'clm_1', label: 'Request cowork access', purpose: 'Ask the owner to collaborate.', availability: 'confirmation_required', result_state: 'awaiting_input', expected_effects: ['collaboration_request.create'], confirmation: { message: 'The owner will receive this request.' }, inputs: [{ field_code: 'reason', label: 'Reason', control: 'textarea', required: true, choices: [] }], based_on_revision: 4 },
          { action_code: 'human.accept_handoff', target_ref: 'hnd_1', label: 'Accept Claim', purpose: 'Assigned to another staff member.', availability: 'blocked', blocked_reason: 'This work is assigned to another staff member.' },
        ],
      }}
      resources={{ handoffs: { items: [] }, fields: { items: [] }, externalRequests: { items: [] } }}
    />)

    expect(screen.getByRole('heading', { name: 'Request cowork access' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Available staff actions' })).not.toBeInTheDocument()
    expect(screen.queryByText('Accept Claim')).not.toBeInTheDocument()
    expect(screen.queryByText('This work is assigned to another staff member.')).not.toBeInTheDocument()
  })

  it('does not present a blocked or inexact backend pair as the staff next action', () => {
    const blocked = {
      action_code: 'human.accept_handoff',
      target_ref: 'hnd_1',
      label: 'Accept Claim',
      purpose: 'Accept the handoff.',
      availability: 'blocked',
      blocked_reason: 'Assigned elsewhere.',
    }
    const { rerender } = render(<ClaimWorkspace
      {...props}
      detail={{
        ...detail,
        work_summary: { ...detail.work_summary, primary_action_code: blocked.action_code, primary_action_target_ref: blocked.target_ref },
        allowed_actions: [blocked],
      }}
    />)

    expect(screen.getByRole('heading', { name: 'No staff action is currently authorised' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: 'Accept Claim' })).not.toBeInTheDocument()

    rerender(<ClaimWorkspace
      {...props}
      detail={{
        ...detail,
        work_summary: { ...detail.work_summary, primary_action_code: 'human.accept_handoff', primary_action_target_ref: 'hnd_other' },
        allowed_actions: [{ ...blocked, availability: 'confirmation_required' }],
      }}
    />)
    expect(screen.getByRole('heading', { name: 'No staff action is currently authorised' })).toBeVisible()
  })

  it('shows terminal provenance and submits the exact projected reopen action through an accessible confirmation dialog', async () => {
    const user = userEvent.setup()
    const onReopen = vi.fn().mockResolvedValue(undefined)
    const reopenAction = {
      registry_version: '2026-09-11.1',
      action_code: 'claim.reopen',
      target_type: 'claim',
      target_ref: 'clm_1',
      label: 'Reopen Claim',
      purpose: 'Return a closed Claim to its retained intake position.',
      availability: 'confirmation_required',
      confirmation: { level: 'explicit', message: 'Reopening returns this Claim to active work and records your reason.' },
      expected_effects: ['terminal_disposition.clear', 'claim.revision.advance', 'audit.append'],
      source_refs: ['evt_closed_1'],
      inputs: [{ field_code: 'reason', label: 'Why are you reopening this Claim?', control: 'textarea', required: true, choices: [] }],
      based_on_revision: 4,
    }
    render(<ClaimWorkspace
      {...props}
      onReopen={onReopen}
      detail={{
        ...detail,
        terminal_disposition: {
          value: 'closed',
          reason_code: 'AUTHORISED_CLOSURE',
          source_refs: ['evt_closed_1'],
          recorded_by: { actor_type: 'staff', actor_id: 'stf_1' },
          recorded_at: '2026-09-03T00:30:00Z',
          recorded_revision: 4,
        },
        work_summary: {
          ...detail.work_summary,
          queue_key: 'closed',
          primary_action_code: 'claim.reopen',
          primary_action_target_ref: 'clm_1',
        },
        allowed_actions: [reopenAction],
      }}
    />)

    expect(screen.getByText('Terminal: Closed')).toBeInTheDocument()
    expect(screen.getByText(/Authorised Closure.*revision 4/i)).toBeInTheDocument()
    expect(screen.getByText('Sources: evt_closed_1')).toBeInTheDocument()

    const trigger = screen.getByRole('button', { name: 'Review reopen' })
    await user.click(trigger)
    const dialog = screen.getByRole('dialog', { name: 'Reopen Claim' })
    const reason = within(dialog).getByLabelText('Why are you reopening this Claim?')
    expect(reason).toHaveFocus()
    expect(within(dialog).getByRole('button', { name: 'Reopen Claim' })).toBeDisabled()

    await user.type(reason, 'The claimant supplied the missing information.')
    await user.click(within(dialog).getByRole('button', { name: 'Reopen Claim' }))

    await waitFor(() => expect(onReopen).toHaveBeenCalledWith(
      reopenAction,
      { reason: 'The claimant supplied the missing information.' },
      expect.any(String),
    ))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('traps keyboard focus, closes on Escape, and returns focus to the reopen trigger', async () => {
    const user = userEvent.setup()
    const reopenAction = {
      action_code: 'claim.reopen',
      target_type: 'claim',
      target_ref: 'clm_1',
      label: 'Reopen Claim',
      purpose: 'Return a closed Claim to active work.',
      availability: 'confirmation_required',
      confirmation: { level: 'explicit', message: 'Confirm the reopen.' },
      inputs: [{ field_code: 'reason', label: 'Reason', control: 'textarea', required: true, choices: [] }],
      based_on_revision: 4,
    }
    render(<ClaimWorkspace
      {...props}
      detail={{
        ...detail,
        work_summary: { ...detail.work_summary, primary_action_code: 'claim.reopen', primary_action_target_ref: 'clm_1' },
        allowed_actions: [reopenAction],
      }}
    />)

    const trigger = screen.getByRole('button', { name: 'Review reopen' })
    await user.click(trigger)
    const reason = screen.getByLabelText('Reason')
    expect(reason).toHaveFocus()
    await user.tab({ shift: true })
    expect(screen.getByRole('dialog')).toContainElement(document.activeElement)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    expect(reason).not.toBeInTheDocument()
  })

  it('explains a stale reopen and keeps the projected input available for retry', async () => {
    const user = userEvent.setup()
    const conflict = Object.assign(new Error('Revision mismatch.'), { code: 'REVISION_CONFLICT', projectionReloaded: true })
    const reopenAction = {
      action_code: 'claim.reopen', target_type: 'claim', target_ref: 'clm_1', label: 'Reopen Claim', purpose: 'Return this Claim.', availability: 'confirmation_required', confirmation: { level: 'explicit', message: 'Confirm.' }, inputs: [{ field_code: 'reason', label: 'Reason', control: 'textarea', required: true, choices: [] }], based_on_revision: 4,
    }
    render(<ClaimWorkspace
      {...props}
      onReopen={vi.fn().mockRejectedValue(conflict)}
      detail={{ ...detail, work_summary: { ...detail.work_summary, primary_action_code: 'claim.reopen', primary_action_target_ref: 'clm_1' }, allowed_actions: [reopenAction] }}
    />)

    await user.click(screen.getByRole('button', { name: 'Review reopen' }))
    await user.type(screen.getByLabelText('Reason'), 'New material received.')
    await user.click(screen.getByRole('button', { name: 'Reopen Claim' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/changed after you opened it.*not reopened/i)
    expect(alert).toHaveTextContent(/latest server projection/i)
    expect(alert).toHaveTextContent(/try again/i)
    expect(screen.getByLabelText('Reason')).toHaveValue('New material received.')
  })
})
