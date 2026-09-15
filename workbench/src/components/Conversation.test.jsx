import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api.js'
import Conversation from './Conversation.jsx'

const detail = { active_session_id: 'ses_1', revision: 1, allowed_actions: [] }

function assistanceHandoff(status, overrides = {}) {
  return {
    handoff_id: 'hnd_1',
    support_need: 'human_requested',
    status,
    reason: 'Customer requested staff assistance.',
    requested_action: 'Help the customer continue their report.',
    created_at: '2026-09-14T10:01:00Z',
    assigned_to: status === 'queued' ? null : 'stf_demo',
    accepted_at: status === 'queued' ? null : '2026-09-14T10:03:00Z',
    resolved_at: status === 'resolved' ? '2026-09-14T10:07:00Z' : null,
    ...overrides,
  }
}

function action(actionCode, targetRef, overrides = {}) {
  return {
    action_code: actionCode,
    target_ref: targetRef,
    availability: 'confirmation_required',
    based_on_revision: 2,
    confirmation: { message: 'Confirm this action.' },
    inputs: [],
    payload_defaults: {},
    ...overrides,
  }
}

function renderConversation(props, route = '/workbench/claims/clm_1/conversation?session=ses_1') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Conversation {...props} />
    </MemoryRouter>,
  )
}

describe('Conversation', () => {
  it('keeps review read-only until take-over and renders the shared actor history with request event', async () => {
    const user = userEvent.setup()
    const onAccept = vi.fn().mockResolvedValue(undefined)
    const handoff = assistanceHandoff('queued')
    renderConversation({
      detail: {
        ...detail,
        revision: 2,
        work_summary: { unread_claimant_messages: 0 },
        allowed_actions: [action('human.accept_handoff', 'hnd_1')],
      },
      handoffs: [handoff],
      profile: { staff_id: 'stf_demo', display_name: 'Demo Staff' },
      resource: {
        resolved_session_id: 'ses_1',
        items: [
          { message_id: 'msg_customer', session_id: 'ses_1', actor: 'claimant', content: { type: 'text', text: 'I need help.' }, created_at: '2026-09-14T10:00:00Z' },
          { message_id: 'msg_agent', session_id: 'ses_1', actor: 'agent', content: { type: 'text', text: 'I have sent your request.' }, created_at: '2026-09-14T10:02:00Z' },
          { message_id: 'msg_staff', session_id: 'ses_1', actor: 'staff', content: { type: 'text', text: 'I can review this.' }, created_at: '2026-09-14T10:04:00Z' },
          { message_id: 'msg_system', session_id: 'ses_1', actor: 'system', content: { type: 'text', text: 'Conversation updated.' }, created_at: '2026-09-14T10:05:00Z' },
        ],
      },
      draft: '',
      onDraft: vi.fn(),
      onAccept,
      onResolve: vi.fn(),
      onSend: vi.fn(),
    })

    expect(screen.getByText('Waiting request')).toBeVisible()
    expect(screen.getByText('Staff assistance requested')).toBeVisible()
    expect(screen.getByText('Customer')).toBeVisible()
    expect(screen.getByText('AI Agent')).toBeVisible()
    expect(screen.getByText('Northwind staff')).toBeVisible()
    expect(screen.getByText('System')).toBeVisible()
    expect(screen.getByLabelText('Message to claimant')).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Take over conversation' }))
    expect(onAccept).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Confirm take over' }))
    expect(onAccept).toHaveBeenCalledWith(handoff)
  })

  it('shows the current assignee, joined event, reply controls, and assistance-only completion action', () => {
    const handoff = assistanceHandoff('accepted')
    renderConversation({
      detail: {
        ...detail,
        revision: 2,
        work_summary: { unread_claimant_messages: 0 },
        customer_next_step: { responsible_party: 'claims_professional' },
        allowed_actions: [
          action('conversation.send_claimant_message', 'ses_1'),
          action('human.resolve_handoff', 'hnd_1', {
            inputs: [
              { field_code: 'result.summary', label: 'Internal result summary', control: 'textarea', required: true },
              { field_code: 'customer_update.summary', label: 'Claimant update', control: 'textarea', required: true },
            ],
            payload_defaults: {
              result: { outcome: 'support_completed', reason_codes: ['SUPPORT_NEED_MET'], source_refs: ['hnd_1'] },
              state_changes: [],
              customer_update: { responsible_party: 'claims_professional', related_refs: ['hnd_1'] },
            },
          }),
        ],
      },
      handoffs: [handoff],
      profile: { staff_id: 'stf_demo', display_name: 'Demo Staff' },
      resource: { items: [], resolved_session_id: 'ses_1' },
      draft: '',
      onDraft: vi.fn(),
      onAccept: vi.fn(),
      onResolve: vi.fn(),
      onSend: vi.fn(),
    })

    expect(screen.getByText('Assigned to me')).toBeVisible()
    expect(screen.getByText('Demo Staff joined the conversation')).toBeVisible()
    expect(screen.getByText('Assigned staff: Demo Staff · Claims professional')).toBeVisible()
    expect(screen.getByLabelText('Message to claimant')).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Complete assistance' })).toBeEnabled()
    expect(screen.queryByText('Claim completed')).not.toBeInTheDocument()
  })

  it.each([
    {
      name: 'customer reply',
      handoff: assistanceHandoff('in_progress'),
      workSummary: { unread_claimant_messages: 1 },
      nextStep: { responsible_party: 'claims_professional' },
      label: 'Action needed',
      title: 'Customer replied',
      placeholder: 'Reply to customer...',
    },
    {
      name: 'waiting customer',
      handoff: assistanceHandoff('in_progress'),
      workSummary: { unread_claimant_messages: 0 },
      nextStep: { responsible_party: 'claimant' },
      label: 'Waiting for customer',
      title: 'Waiting for customer',
      placeholder: 'Waiting for the customer — send an update if needed',
    },
    {
      name: 'completed assistance',
      handoff: assistanceHandoff('resolved'),
      workSummary: { unread_claimant_messages: 0 },
      nextStep: { responsible_party: 'claims_professional' },
      label: 'Completed',
      title: 'Staff assistance completed',
      placeholder: 'Staff assistance is complete',
    },
  ])('renders the $name composer and assistance state from server projections', ({ handoff, workSummary, nextStep, label, title, placeholder }) => {
    renderConversation({
      detail: {
        ...detail,
        revision: 2,
        work_summary: workSummary,
        customer_next_step: nextStep,
        allowed_actions: handoff.status === 'resolved'
          ? []
          : [action('conversation.send_claimant_message', 'ses_1')],
      },
      handoffs: [handoff],
      profile: { staff_id: 'stf_demo', display_name: 'Demo Staff' },
      resource: { items: [], resolved_session_id: 'ses_1' },
      draft: '',
      onDraft: vi.fn(),
      onAccept: vi.fn(),
      onResolve: vi.fn(),
      onSend: vi.fn(),
    })

    expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    expect(screen.getAllByText(title).length).toBeGreaterThan(0)
    expect(screen.getByLabelText('Message to claimant')).toHaveAttribute('placeholder', placeholder)
  })

  it('shows the exact blocked claimant-message reason without a usable form', () => {
    renderConversation({
      detail: {
        ...detail,
        allowed_actions: [{
          action_code: 'conversation.send_claimant_message',
          target_ref: 'ses_1',
          based_on_revision: 1,
          label: 'Reply to claimant',
          availability: 'blocked',
          blocked_reason: 'Accept the handoff before replying.',
        }],
      },
      resource: { items: [], resolved_session_id: 'ses_1' },
      draft: '',
      onDraft: vi.fn(),
      onSend: vi.fn(),
    })

    expect(screen.getByText('Staff messaging not available yet')).toBeVisible()
    expect(screen.getByText('Accept the handoff before replying.')).toBeVisible()
    expect(screen.getByPlaceholderText('Write a message…')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
  })

  it('ignores a projected message action for another session', () => {
    renderConversation({
      detail: {
        ...detail,
        allowed_actions: [{
          action_code: 'conversation.send_claimant_message',
          target_ref: 'ses_other',
          based_on_revision: 1,
          availability: 'available',
        }],
      },
      resource: { items: [], resolved_session_id: 'ses_1' },
      draft: 'Ready',
      onDraft: vi.fn(),
      onSend: vi.fn(),
    })

    expect(screen.getByText('Staff messaging not available yet')).toBeVisible()
    expect(screen.getByText('Messaging is not available for this claim yet.')).toBeVisible()
    expect(screen.queryByText(/accepted staff handoff is required/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/action|projected/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
  })

  it.each([
    {
      name: 'queued handoff assigned to another staff member',
      allowedActions: [{
        action_code: 'human.accept_handoff',
        target_ref: 'hnd_1',
        availability: 'blocked',
        blocked_reason: 'This work is assigned to another staff member.',
      }],
    },
    {
      name: 'terminal Claim with no active handoff',
      allowedActions: [{
        action_code: 'claim.reopen',
        target_ref: 'clm_1',
        availability: 'blocked',
        blocked_reason: 'A created external Claim cannot be reopened from FNOL intake.',
      }],
    },
  ])('uses a neutral unavailable explanation for a $name', ({ allowedActions }) => {
    renderConversation({
      detail: { ...detail, allowed_actions: allowedActions },
      resource: { items: [], resolved_session_id: 'ses_1' },
      draft: '',
      onDraft: vi.fn(),
      onSend: vi.fn(),
    })

    expect(screen.getByText('Staff messaging not available yet')).toBeVisible()
    expect(screen.getByText('Messaging is not available for this claim yet.')).toBeVisible()
    expect(screen.queryByText(/accepted staff handoff is required/i)).not.toBeInTheDocument()
    expect(screen.queryByText(allowedActions[0].blocked_reason)).not.toBeInTheDocument()
  })

  it('submits an available exact-target message action with the displayed session', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    renderConversation({
      detail: {
        ...detail,
        allowed_actions: [{
          action_code: 'conversation.send_claimant_message',
          target_ref: 'ses_1',
          based_on_revision: 1,
          availability: 'available',
        }],
      },
      resource: { items: [], resolved_session_id: 'ses_1' },
      draft: 'A claimant-safe update',
      onDraft: vi.fn(),
      onSend,
    })

    expect(screen.queryByRole('heading', { name: 'Claimant conversation' })).not.toBeInTheDocument()
    expect(screen.getByRole('log', { name: 'Claimant conversation messages' })).toHaveTextContent('No messages yet')
    expect(screen.getByRole('log', { name: 'Claimant conversation messages' })).toHaveTextContent(
      'Messages with the claimant will appear here.',
    )
    expect(screen.getByLabelText('Message to claimant')).toHaveAttribute('placeholder', 'Write a message…')
    expect(screen.queryByText(/shared claim context|0 messages|visible to the claimant/i)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Send message' }))
    expect(onSend).toHaveBeenCalledWith({
      message: 'A claimant-safe update',
      sessionId: 'ses_1',
    })
  })

  it.each([
    {
      handoff: assistanceHandoff('queued'),
      actionCode: 'human.accept_handoff',
      actionLabel: 'Take over conversation',
      statusLabel: 'Waiting request',
    },
    {
      handoff: assistanceHandoff('accepted'),
      actionCode: 'human.resolve_handoff',
      actionLabel: 'Complete assistance',
      statusLabel: 'Assigned to me',
    },
  ])('keeps a displayed historical session read only when the current handoff is $handoff.status', ({ handoff, actionCode, actionLabel, statusLabel }) => {
    const onSend = vi.fn()
    renderConversation({
      detail: {
        ...detail,
        active_session_id: 'ses_active',
        allowed_actions: [
          {
            action_code: 'conversation.send_claimant_message',
            target_ref: 'ses_active',
            based_on_revision: 1,
            availability: 'available',
          },
          action(actionCode, 'hnd_1', { based_on_revision: 1 }),
        ],
      },
      handoffs: [handoff],
      profile: { staff_id: 'stf_demo', display_name: 'Demo Staff' },
      resource: {
        items: [{
          message_id: 'msg_old',
          session_id: 'ses_old',
          actor: 'claimant',
          content: { type: 'text', text: 'Existing claimant message.' },
          created_at: '2026-09-08T10:00:00Z',
        }],
      },
      draft: 'A staff reply',
      onDraft: vi.fn(),
      onAccept: vi.fn(),
      onResolve: vi.fn(),
      onSend,
    }, '/workbench/claims/clm_1/conversation?session=ses_old')

    expect(screen.getByLabelText('Message to claimant')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: actionLabel })).not.toBeInTheDocument()
    expect(screen.queryByText(statusLabel)).not.toBeInTheDocument()
    expect(screen.queryByText('Staff assistance requested')).not.toBeInTheDocument()
    expect(screen.getByText('Read-only conversation')).toBeInTheDocument()
    expect(screen.getByText('Open the active claimant conversation to send a message.')).toBeInTheDocument()
    expect(onSend).not.toHaveBeenCalled()
  })

  it('keeps the draft after a stale revision while page-level recovery owns projection refresh', async () => {
    const user = userEvent.setup()
    const onDraft = vi.fn()
    const onSend = vi.fn().mockRejectedValue(
      new ApiError('The Claim changed after this page was loaded.', {
        status: 409,
        code: 'REVISION_CONFLICT',
      }),
    )

    renderConversation({
      detail: {
        ...detail,
        allowed_actions: [{
          action_code: 'conversation.send_claimant_message',
          target_ref: 'ses_1',
          based_on_revision: 1,
          availability: 'available',
        }],
      },
      resource: { items: [], resolved_session_id: 'ses_1' },
      draft: 'Preserve this draft',
      onDraft,
      onSend,
    })

    await user.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The Claim changed after this page was loaded.',
    )
    expect(onDraft).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Message to claimant')).toHaveValue(
      'Preserve this draft',
    )
  })

  it('keeps the draft available after an ambiguous send failure', async () => {
    const user = userEvent.setup()
    const onDraft = vi.fn()
    const onSend = vi.fn().mockRejectedValue(
      new ApiError('The Workbench service could not be reached. Try again shortly.'),
    )
    renderConversation({
      detail: {
        ...detail,
        allowed_actions: [{
          action_code: 'conversation.send_claimant_message',
          target_ref: 'ses_1',
          based_on_revision: 1,
          availability: 'available',
        }],
      },
      resource: { items: [], resolved_session_id: 'ses_1' },
      draft: 'Retry this safely',
      onDraft,
      onSend,
    })

    await user.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('could not be reached')
    expect(onDraft).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Message to claimant')).toHaveValue('Retry this safely')
  })

  it('uses the actually loaded session instead of the URL as send authority', () => {
    const onSend = vi.fn()

    renderConversation({
      detail: {
        ...detail,
        active_session_id: 'ses_active',
        allowed_actions: [{
          action_code: 'conversation.send_claimant_message',
          target_ref: 'ses_active',
          based_on_revision: 1,
          availability: 'available',
        }],
      },
      resource: {
        resolved_session_id: 'ses_old',
        items: [{
          message_id: 'msg_old',
          session_id: 'ses_old',
          actor: 'claimant',
          content: { type: 'text', text: 'Old session message.' },
          created_at: '2026-09-10T05:00:00Z',
        }],
      },
      draft: 'Must not send',
      onDraft: vi.fn(),
      onSend,
    }, '/workbench/claims/clm_1/conversation?session=ses_active')

    expect(screen.getByText('Old session message.')).toBeVisible()
    expect(screen.getByLabelText('Message to claimant')).toBeDisabled()
    expect(onSend).not.toHaveBeenCalled()
  })

  it('shows an unavailable state instead of falling back for an unknown session', () => {
    renderConversation({
      detail: {
        ...detail,
        active_session_id: 'ses_active',
      },
      resource: {
        items: [],
        resolved_session_id: null,
        status: 'unavailable',
        error: 'The requested claimant session is not available. Return to the Claim and open an available conversation.',
      },
      draft: '',
      onDraft: vi.fn(),
      onSend: vi.fn(),
    }, '/workbench/claims/clm_1/conversation?session=ses_missing')

    expect(screen.getByRole('alert')).toHaveTextContent(
      'The requested claimant session is not available',
    )
    expect(screen.queryByLabelText('Message to claimant')).not.toBeInTheDocument()
  })

})
