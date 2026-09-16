import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ClaimWorkspace from './ClaimWorkspace.jsx'
import { formatDateTime } from '../format.js'

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
  it('explains a Claim load failure with a request reference and in-place retry', async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    render(<ClaimWorkspace
      {...props}
      detail={null}
      error={Object.assign(new Error('Projection service timed out.'), { requestId: 'req_claim_1' })}
      onRetry={onRetry}
    />)

    expect(screen.getByRole('alert')).toHaveTextContent('This Claim could not be opened')
    expect(screen.getByRole('alert')).toHaveTextContent('Request reference: req_claim_1')
    await user.click(screen.getByRole('button', { name: 'Retry Claim' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('uses a safe inaccessible state for a Claim that is no longer visible', () => {
    render(<ClaimWorkspace
      {...props}
      detail={null}
      error={Object.assign(new Error('Not found.'), { status: 404, code: 'RESOURCE_NOT_FOUND' })}
    />)

    expect(screen.getByRole('alert')).toHaveTextContent('This Claim is not available')
    expect(screen.queryByRole('button', { name: 'Retry Claim' })).not.toBeInTheDocument()
  })

  it('exposes one selected tab and a labelled tab panel', () => {
    render(<ClaimWorkspace {...props} />)

    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Evidence' })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', 'claim-tab-summary')
  })

  it('collapses the Claim summary only while Conversation is selected', () => {
    const { rerender } = render(<ClaimWorkspace
      {...props}
      section="conversation"
      resources={{
        handoffs: { status: 'available', items: [] },
        messages: { status: 'available', items: [], resolved_session_id: null },
      }}
    />)

    expect(screen.queryByRole('heading', { name: 'Alex Morgan', level: 1 })).not.toBeInTheDocument()
    expect(screen.getByRole('tablist', { name: 'Claim sections' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: 'Claimant conversation' })).not.toBeInTheDocument()
    expect(screen.getByRole('log', { name: 'Claimant conversation messages' })).toBeVisible()

    rerender(<ClaimWorkspace
      {...props}
      section="fields"
      resources={{ fields: { status: 'available', items: [] } }}
    />)

    expect(screen.getByRole('heading', { name: 'Alex Morgan', level: 1 })).toBeVisible()
    expect(screen.getByRole('tab', { name: 'Claim information' })).toHaveAttribute('aria-selected', 'true')
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

  it('routes an exact external-task primary action to External Services without inferring from lifecycle state', async () => {
    const user = userEvent.setup()
    const onSection = vi.fn()
    const externalAction = {
      action_code: 'external.reconcile_response',
      target_type: 'external_task',
      target_ref: 'tsk_assessor_1',
      label: 'Reconcile external outcome',
      purpose: 'Check the existing provider operation before any further side effect.',
      availability: 'confirmation_required',
      confirmation: { level: 'explicit', message: 'This checks the existing operation identity; it does not submit a new request.' },
      expected_effects: ['external_task.reconcile', 'claim.revision.advance'],
      inputs: [],
      result_state: 'not_started',
      based_on_revision: 4,
    }
    render(<ClaimWorkspace
      {...props}
      onSection={onSection}
      detail={{
        ...detail,
        work_summary: {
          ...detail.work_summary,
          primary_action_code: externalAction.action_code,
          primary_action_target_ref: externalAction.target_ref,
        },
        allowed_actions: [externalAction],
      }}
    />)

    expect(screen.getByRole('heading', { name: 'Reconcile external outcome' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Open external services' }))
    expect(onSection).toHaveBeenCalledWith('external-services')
  })

  it('keeps an unconfirmed external-action warning visible after the refreshed projection removes the action', async () => {
    const user = userEvent.setup()
    const onRetryExternalActionContext = vi.fn()
    const externalAction = {
      action_code: 'external.reconcile_response',
      target_type: 'external_task',
      target_ref: 'tsk_assessor_1',
      label: 'Reconcile external outcome',
      purpose: 'Check the existing provider operation.',
      availability: 'confirmation_required',
      confirmation: { message: 'Check this operation?' },
      inputs: [],
      based_on_revision: 4,
    }
    const actionDetail = {
      ...detail,
      work_summary: {
        ...detail.work_summary,
        primary_action_code: externalAction.action_code,
        primary_action_target_ref: externalAction.target_ref,
      },
      allowed_actions: [externalAction],
    }
    const { rerender } = render(<ClaimWorkspace
      {...props}
      detail={actionDetail}
      resources={{ handoffs: { items: [] }, externalRequests: { status: 'available', items: [] } }}
    />)

    expect(screen.getByRole('heading', { name: 'Reconcile external outcome' })).toBeVisible()

    rerender(<ClaimWorkspace
      {...props}
      detail={{
        ...detail,
        revision: 5,
        work_summary: {
          ...detail.work_summary,
          primary_action_code: null,
          primary_action_target_ref: null,
        },
        allowed_actions: [],
      }}
      resources={{ handoffs: { items: [] }, externalRequests: { status: 'unavailable', items: [], error: new Error('Refresh failed.') } }}
      externalActionNotices={[{
        claimId: 'clm_1',
        taskId: 'tsk_assessor_1',
        recovering: false,
        message: 'The action for external task tsk_assessor_1 may have completed. Its outcome is not confirmed. Do not submit it again until Claim and External Services state has been refreshed.',
      }]}
      onRetryExternalActionContext={onRetryExternalActionContext}
    />)

    const alert = screen.getByRole('alert', { name: '' })
    expect(alert).toHaveTextContent('External-service action outcome not confirmed')
    expect(alert).toHaveTextContent('tsk_assessor_1')
    expect(alert).toHaveTextContent(/may have completed.*outcome is not confirmed.*do not submit it again/i)
    expect(screen.queryByRole('heading', { name: 'Reconcile external outcome' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Refresh Claim and External Services' }))
    expect(onRetryExternalActionContext).toHaveBeenCalledWith('tsk_assessor_1')
  })

  it('scopes external recovery guards to the exact task without replacing the backend primary action', async () => {
    const user = userEvent.setup()
    const taskAAction = {
      action_code: 'external.reconcile_response',
      target_type: 'external_task',
      target_ref: 'tsk_assessor_a',
      label: 'Reconcile task A',
      purpose: 'Check task A without resubmitting it.',
      availability: 'confirmation_required',
      confirmation: { message: 'Check task A?' },
      inputs: [],
      based_on_revision: 4,
    }
    const taskBAction = {
      ...taskAAction,
      target_ref: 'tsk_assessor_b',
      label: 'Reconcile task B',
      purpose: 'Check task B without resubmitting it.',
      confirmation: { message: 'Check task B?' },
    }
    const externalRecord = (taskId, service) => ({
      task: {
        task_id: taskId,
        claim_id: 'clm_1',
        service_identity: service,
        requested_action: 'assessment',
        integration_source: 'fixture',
        status: 'unknown_outcome',
        failure_code: null,
        updated_at: '2026-09-16T01:00:00Z',
      },
      request: null,
      lifecycle: {
        stakeholder: 'external_party',
        service,
        request_type: 'assessment',
        authority_state: 'recorded',
        consent_state: 'recorded',
        delivery_state: 'submitted',
        verification_state: 'reconciliation_required',
        pending_owner: 'claims_professional',
        status_label: 'Outcome not confirmed',
        status_detail: 'The provider outcome is not confirmed.',
        provider_reference: null,
        result: null,
        result_source: null,
        result_verification_state: null,
        result_received_at: null,
        result_verified_at: null,
        result_verified_against_revision: null,
        result_evidence: [],
        limitation: null,
        next_action: 'Reconcile the existing operation before any retry.',
        needs_attention: true,
      },
    })
    const actionDetail = {
      ...detail,
      work_summary: {
        ...detail.work_summary,
        primary_action_code: taskAAction.action_code,
        primary_action_target_ref: taskAAction.target_ref,
      },
      allowed_actions: [taskAAction, taskBAction],
    }
    const externalRequests = {
      status: 'available',
      items: [
        externalRecord('tsk_assessor_a', 'vehicle damage assessor'),
        externalRecord('tsk_assessor_b', 'repair assessor'),
      ],
    }
    const taskANotice = {
      claimId: 'clm_1',
      taskId: 'tsk_assessor_a',
      recovering: false,
      message: 'Task A may have completed. Its outcome is not confirmed. Do not submit it again until authoritative state has been refreshed.',
    }
    const { rerender } = render(<ClaimWorkspace
      {...props}
      detail={actionDetail}
      resources={{ handoffs: { items: [] }, externalRequests }}
      externalActionNotices={[taskANotice]}
      onRetryExternalActionContext={vi.fn()}
    />)

    expect(screen.getByRole('heading', { name: 'No staff action is currently authorised' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: 'Reconcile task B' })).not.toBeInTheDocument()

    rerender(<ClaimWorkspace
      {...props}
      detail={actionDetail}
      section="external-services"
      resources={{ handoffs: { items: [] }, externalRequests }}
      externalActionNotices={[taskANotice]}
      onRetryExternalActionContext={vi.fn()}
      onExternalTaskAction={vi.fn()}
    />)

    await user.click(screen.getByText('Vehicle Damage Assessor'))
    await user.click(screen.getByText('Repair Assessor'))
    expect(screen.queryByRole('heading', { name: 'Reconcile task A' })).not.toBeInTheDocument()
    const taskBPanel = screen.getByRole('heading', { name: 'Reconcile task B' }).closest('section')
    expect(within(taskBPanel).getByRole('button', { name: 'Review Reconcile task B' })).toBeEnabled()

    rerender(<ClaimWorkspace
      {...props}
      detail={actionDetail}
      section="external-services"
      resources={{ handoffs: { items: [] }, externalRequests }}
      externalActionNotices={[]}
      onRetryExternalActionContext={vi.fn()}
      onExternalTaskAction={vi.fn()}
    />)

    expect(screen.getByRole('heading', { name: 'Reconcile task A' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Reconcile task B' })).toBeInTheDocument()
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

  it('keeps a stale Claim readable but withdraws projected actions until refresh', () => {
    const acceptAction = {
      action_code: 'human.accept_handoff',
      target_type: 'handoff',
      target_ref: 'hnd_1',
      label: 'Accept Claim',
      purpose: 'Accept the projected handoff.',
      availability: 'confirmation_required',
      confirmation: { message: 'Accept this Claim?' },
      based_on_revision: 4,
    }
    render(<ClaimWorkspace
      {...props}
      stale
      error={new Error('Background refresh failed.')}
      detail={{
        ...detail,
        work_summary: { ...detail.work_summary, primary_action_code: acceptAction.action_code, primary_action_target_ref: acceptAction.target_ref },
        allowed_actions: [acceptAction],
      }}
      resources={{ handoffs: { items: [{ handoff_id: 'hnd_1', status: 'pending' }] } }}
    />)

    expect(screen.getByText('Showing a saved Claim snapshot')).toBeInTheDocument()
    expect(screen.getByText('Rear-end collision.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Review acceptance' })).not.toBeInTheDocument()
  })

  it('shows an actionable failure beside a controlled handoff action', async () => {
    const user = userEvent.setup()
    const onAccept = vi.fn().mockRejectedValue(Object.assign(
      new Error('Accepting the handoff was not completed. Review the latest state before trying again. Request reference: req_action_1.'),
      { code: 'REVISION_CONFLICT' },
    ))
    const acceptAction = {
      action_code: 'human.accept_handoff', target_type: 'handoff', target_ref: 'hnd_1', label: 'Accept Claim', purpose: 'Accept the projected handoff.', availability: 'confirmation_required', confirmation: { message: 'Accept this Claim?' }, based_on_revision: 4,
    }
    render(<ClaimWorkspace
      {...props}
      onAccept={onAccept}
      detail={{ ...detail, work_summary: { ...detail.work_summary, primary_action_code: acceptAction.action_code, primary_action_target_ref: acceptAction.target_ref }, allowed_actions: [acceptAction] }}
      resources={{ handoffs: { items: [{ handoff_id: 'hnd_1', status: 'pending' }] } }}
    />)

    await user.click(screen.getByRole('button', { name: 'Review acceptance' }))
    await user.click(screen.getByRole('button', { name: 'Confirm Accept Claim' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Request reference: req_action_1')
    expect(onAccept).toHaveBeenCalledWith(expect.objectContaining({ handoff_id: 'hnd_1' }))
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
    const onReopen = vi.fn().mockRejectedValueOnce(conflict).mockResolvedValueOnce(undefined)
    const reopenAction = {
      action_code: 'claim.reopen', target_type: 'claim', target_ref: 'clm_1', label: 'Reopen Claim', purpose: 'Return this Claim.', availability: 'confirmation_required', confirmation: { level: 'explicit', message: 'Confirm.' }, inputs: [{ field_code: 'reason', label: 'Reason', control: 'textarea', required: true, choices: [] }], based_on_revision: 4,
    }
    const { rerender } = render(<ClaimWorkspace
      {...props}
      onReopen={onReopen}
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

    const latestAction = { ...reopenAction, based_on_revision: 5 }
    rerender(<ClaimWorkspace
      {...props}
      onReopen={onReopen}
      detail={{ ...detail, revision: 5, work_summary: { ...detail.work_summary, primary_action_code: 'claim.reopen', primary_action_target_ref: 'clm_1' }, allowed_actions: [latestAction] }}
    />)
    expect(screen.getByLabelText('Reason')).toHaveValue('New material received.')
    await user.click(screen.getByRole('button', { name: 'Reopen Claim' }))

    await waitFor(() => expect(onReopen).toHaveBeenCalledTimes(2))
    expect(onReopen.mock.calls[1][0]).toBe(latestAction)
    expect(onReopen.mock.calls[1][2]).not.toBe(onReopen.mock.calls[0][2])
  })

  it('keeps the projected primary action ahead of authoritative recovery and integration context', () => {
    const acceptAction = {
      action_code: 'human.accept_handoff',
      target_type: 'handoff',
      target_ref: 'hnd_1',
      label: 'Accept Claim',
      purpose: 'Accept the projected handoff.',
      availability: 'confirmation_required',
      confirmation: { message: 'Accept this Claim?' },
      based_on_revision: 4,
    }
    render(<ClaimWorkspace
      {...props}
      detail={{
        ...detail,
        work_summary: {
          ...detail.work_summary,
          primary_action_code: acceptAction.action_code,
          primary_action_target_ref: acceptAction.target_ref,
          incomplete_context: {
            interrupted_at: '2026-09-14T00:00:00Z',
            last_meaningful_activity_at: '2026-09-13T23:55:00Z',
            resume_point: 'collect_vehicle_damage_evidence',
            follow_up_due_at: '2026-09-15T00:00:00Z',
            follow_up_status: 'pending',
            follow_up_attempts: 2,
          },
        },
        allowed_actions: [acceptAction],
        integration_summary: {
          claim_creation_status: 'created',
          claim_number: 'NW-CLAIM-1042',
          expected_by: '2026-09-16T01:30:00Z',
          assessor_routing_status: 'assigned',
          waiting_external_services: [{
            task_id: 'tsk_assessor_1',
            service_identity: 'vehicle_damage_assessor',
            requested_action: 'vehicle_damage_assessment',
            status: 'unknown_outcome',
          }],
        },
      }}
      resources={{ handoffs: { items: [{ handoff_id: 'hnd_1', status: 'pending' }] } }}
    />)

    const primarySection = screen.getByRole('heading', { name: 'Accept Claim' }).closest('section')
    const recoveryHeading = screen.getByRole('heading', { name: 'Incomplete Claim recovery' })
    const recoverySection = recoveryHeading.closest('section')

    expect(primarySection.nextElementSibling).toBe(recoverySection)
    expect(within(recoverySection).getByText('Interrupted')).toBeVisible()
    expect(within(recoverySection).getByText(formatDateTime('2026-09-14T00:00:00Z'))).toBeVisible()
    expect(within(recoverySection).getByText('Last meaningful activity')).toBeVisible()
    expect(within(recoverySection).getByText(formatDateTime('2026-09-13T23:55:00Z'))).toBeVisible()
    expect(within(recoverySection).getByText('Resume point')).toBeVisible()
    expect(within(recoverySection).getByText('Collect Vehicle Damage Evidence')).toBeVisible()
    expect(within(recoverySection).getByText('Follow-up status')).toBeVisible()
    const followUpStatus = within(recoverySection).getByText('Pending')
    expect(followUpStatus).toBeVisible()
    expect(followUpStatus).toHaveClass('record-status--attention')
    expect(within(recoverySection).getByText('Follow-up due')).toBeVisible()
    expect(within(recoverySection).getByText(formatDateTime('2026-09-15T00:00:00Z'))).toBeVisible()
    expect(within(recoverySection).getByText('Follow-up attempts')).toBeVisible()
    expect(within(recoverySection).getByText('2')).toBeVisible()

    const integrationHeading = screen.getByRole('heading', { name: 'Claim and external progress' })
    const integrationSection = integrationHeading.closest('section')
    expect(integrationHeading).toBeVisible()
    const createdStatus = within(integrationSection).getByText('Created')
    const assignedStatus = within(integrationSection).getByText('Assigned')
    const unknownStatus = within(integrationSection).getByText('Unknown Outcome')
    expect(createdStatus).toHaveClass('record-status--confirmed')
    expect(assignedStatus).toHaveClass('record-status--confirmed')
    expect(within(integrationSection).getByText('Claim number')).toBeVisible()
    expect(within(integrationSection).getByText('NW-CLAIM-1042')).toBeVisible()
    expect(within(integrationSection).getByText('Expected by')).toBeVisible()
    expect(within(integrationSection).getByText(formatDateTime('2026-09-16T01:30:00Z'))).toBeVisible()
    expect(screen.getByText('Vehicle Damage Assessor')).toBeVisible()
    expect(screen.getByText('Vehicle Damage Assessment')).toBeVisible()
    expect(unknownStatus).toHaveClass('record-status--attention')
    expect(within(integrationSection).queryByText('Projection limit')).not.toBeInTheDocument()
  })

  it('keeps partial recovery fields explicit when an optional due time is absent', () => {
    render(<ClaimWorkspace
      {...props}
      detail={{
        ...detail,
        work_summary: {
          ...detail.work_summary,
          incomplete_context: {
            interrupted_at: '2026-09-14T00:00:00Z',
            last_meaningful_activity_at: '2026-09-13T23:55:00Z',
            resume_point: 'collect_vehicle_damage_evidence',
            follow_up_due_at: null,
            follow_up_status: 'pending',
            follow_up_attempts: 1,
          },
        },
      }}
    />)

    const recoveryHeading = screen.getByRole('heading', { name: 'Incomplete Claim recovery' })
    const recoverySection = recoveryHeading.closest('section')
    expect(within(recoverySection).getByText(formatDateTime('2026-09-14T00:00:00Z'))).toBeVisible()
    expect(within(recoverySection).getByText(formatDateTime('2026-09-13T23:55:00Z'))).toBeVisible()
    expect(within(recoverySection).getByText('Collect Vehicle Damage Evidence')).toBeVisible()
    expect(within(recoverySection).getByText('Pending')).toBeVisible()
    expect(within(recoverySection).getByText('Follow-up due')).toBeVisible()
    expect(within(recoverySection).getByText('Not recorded')).toBeVisible()
    expect(within(recoverySection).getByText('Follow-up attempts')).toBeVisible()
    expect(within(recoverySection).getByText('1')).toBeVisible()
    expect(within(recoverySection).getByText('1 attempt')).toBeVisible()
  })

  it('keeps partial integration values explicit instead of inferring them from lifecycle state', () => {
    render(<ClaimWorkspace
      {...props}
      detail={{
        ...detail,
        lifecycle_state: 'created',
        workflow_state: 'created',
        customer_next_step: {
          ...detail.customer_next_step,
          expected_by: '2026-09-20T02:00:00Z',
        },
        integration_summary: {
          claim_creation_status: null,
          claim_number: null,
          expected_by: null,
          assessor_routing_status: null,
          waiting_external_services: [],
        },
      }}
    />)

    const integrationHeading = screen.getByRole('heading', { name: 'Claim and external progress' })
    const integrationSection = integrationHeading.closest('section')
    expect(integrationHeading).toBeVisible()
    expect(within(integrationSection).getByText('Claim number')).toBeVisible()
    expect(within(integrationSection).getByText('Expected by')).toBeVisible()
    expect(within(integrationSection).getAllByText('Not recorded')).toHaveLength(4)
    expect(within(integrationSection).getByText('No external service is currently projected as waiting.')).toBeVisible()
    expect(within(integrationSection).queryByText('Created')).not.toBeInTheDocument()
    expect(within(integrationSection).queryByText(detail.display_reference)).not.toBeInTheDocument()
    expect(within(integrationSection).queryByText(formatDateTime('2026-09-20T02:00:00Z'))).not.toBeInTheDocument()
  })

  it('does not invent recovery or integration sections when those projections are absent', () => {
    render(<ClaimWorkspace {...props} />)

    expect(screen.queryByRole('heading', { name: 'Incomplete Claim recovery' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Claim and external progress' })).not.toBeInTheDocument()
  })

})
