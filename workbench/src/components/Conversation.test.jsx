import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api.js'
import { formatDate, formatTime } from '../format.js'
import Conversation from './Conversation.jsx'

const detail = { claim_id: 'clm_1', active_session_id: 'ses_1', revision: 1, allowed_actions: [] }

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

function DraftConversation({ onSend }) {
  const [draft, setDraft] = useState('First staff message')
  return (
    <Conversation
      detail={{
        ...detail,
        allowed_actions: [{
          action_code: 'conversation.send_claimant_message',
          target_ref: 'ses_1',
          based_on_revision: 1,
          availability: 'available',
        }],
      }}
      resource={{ items: [], resolved_session_id: 'ses_1' }}
      draft={draft}
      onDraft={setDraft}
      onSend={onSend}
    />
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

    expect(screen.queryByText('Waiting request')).not.toBeInTheDocument()
    expect(screen.getByText('Customer requested staff assistance')).toBeVisible()
    expect(screen.queryByText('Review the conversation without taking ownership, or take over to reply.')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Message to claimant').closest('form')).toContainElement(
      screen.getByText('Customer requested staff assistance'),
    )
    expect(screen.getByText('Staff assistance requested')).toBeVisible()
    expect(screen.getByText('Customer')).toBeVisible()
    expect(screen.getByText('AI Agent')).toBeVisible()
    expect(screen.getByText('Northwind staff')).toBeVisible()
    expect(screen.getByText('System')).toBeVisible()
    expect(screen.getAllByText(formatDate('2026-09-14T10:00:00Z'))).toHaveLength(1)
    expect(screen.getByText(formatTime('2026-09-14T10:01:00Z'))).toBeVisible()
    expect(screen.getByLabelText('Message to claimant')).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Take over conversation' }))
    expect(onAccept).not.toHaveBeenCalled()
    const confirmationMessage = screen.getByText('Confirm this action.')
    expect(confirmationMessage.closest('.assistance-status__copy')).not.toBeNull()
    expect(screen.queryByText('Waiting request')).not.toBeInTheDocument()
    expect(screen.queryByText('Customer requested staff assistance')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Message to claimant').closest('form')).toContainElement(confirmationMessage)
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText('Waiting request')).not.toBeInTheDocument()
    expect(screen.getByText('Customer requested staff assistance')).toBeVisible()
    expect(screen.queryByText('Confirm this action.')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Take over conversation' }))
    await user.click(screen.getByRole('button', { name: 'Confirm take over' }))
    expect(onAccept).toHaveBeenCalledWith(handoff)
  })

  it('keeps a queued handoff with unread messages in the composer take-over flow', async () => {
    const user = userEvent.setup()
    const onAccept = vi.fn().mockResolvedValue(undefined)
    const handoff = assistanceHandoff('queued')
    const { container } = renderConversation({
      detail: {
        ...detail,
        revision: 2,
        work_summary: { unread_claimant_messages: 1 },
        allowed_actions: [action('human.accept_handoff', 'hnd_1')],
      },
      handoffs: [handoff],
      profile: { staff_id: 'stf_demo', display_name: 'Demo Staff' },
      resource: { items: [], resolved_session_id: 'ses_1' },
      draft: '',
      onDraft: vi.fn(),
      onAccept,
      onResolve: vi.fn(),
      onSend: vi.fn(),
    })

    const composer = screen.getByLabelText('Message to claimant').closest('form')
    expect(composer).toContainElement(screen.getByText('Customer requested staff assistance'))
    expect(composer).toContainElement(screen.getByRole('button', { name: 'Take over conversation' }))
    expect(container.querySelector('.conversation-view > .assistance-status')).toBeNull()
    expect(screen.getByLabelText('Message to claimant')).toBeDisabled()
    expect(screen.queryByText('Staff messaging not available yet')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Take over conversation' }))
    expect(onAccept).not.toHaveBeenCalled()
    expect(composer).toContainElement(screen.getByText('Confirm this action.'))

    await user.click(screen.getByRole('button', { name: 'Confirm take over' }))
    expect(onAccept).toHaveBeenCalledOnce()
    expect(onAccept).toHaveBeenCalledWith(handoff)
  })

  it('keeps the assignee and completion workflow in the compact status bar', async () => {
    const user = userEvent.setup()
    const onResolve = vi.fn().mockResolvedValue(undefined)
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
      resource: { items: [], resolved_session_id: 'ses_1', loading: true },
      draft: '',
      onDraft: vi.fn(),
      onAccept: vi.fn(),
      onResolve,
      onSend: vi.fn(),
    })

    const completeButton = screen.getByRole('button', { name: 'Complete assistance' })
    const statusBar = completeButton.closest('.assistance-status')
    expect(statusBar).toHaveTextContent('Staff assistance')
    expect(statusBar).toHaveTextContent('Assigned to you')
    expect(statusBar).toHaveTextContent('Demo Staff')
    expect(statusBar).not.toHaveTextContent('Expected to act')
    expect(statusBar).not.toHaveTextContent('Claims professional')
    expect(screen.getByText('Demo Staff joined')).toBeVisible()
    expect(screen.getByText('Refreshing this section')).toBeVisible()
    expect(screen.queryByText('Loading current records...')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Message to claimant')).toBeEnabled()
    expect(completeButton).toBeEnabled()
    expect(screen.queryByText('Assistance session')).not.toBeInTheDocument()
    expect(screen.queryByText('Claim completed')).not.toBeInTheDocument()

    await user.click(completeButton)
    await user.type(screen.getByLabelText('Internal result summary'), 'Customer received the requested support.')
    await user.type(screen.getByLabelText('Claimant update'), 'We have completed this assistance session.')
    await user.click(screen.getByRole('button', { name: 'Confirm completion' }))

    expect(onResolve).toHaveBeenCalledWith(handoff, {
      result: {
        outcome: 'support_completed',
        reason_codes: ['SUPPORT_NEED_MET'],
        source_refs: ['hnd_1'],
        summary: 'Customer received the requested support.',
      },
      state_changes: [],
      customer_update: {
        responsible_party: 'claims_professional',
        related_refs: ['hnd_1'],
        summary: 'We have completed this assistance session.',
      },
    })
  })

  it.each([
    {
      access: 'coworker',
      primaryAssignee: { staff_id: 'stf_owner', display_name: 'Owner Staff' },
      expectedAssignment: 'Assigned to Owner Staff',
    },
    {
      access: 'read_only',
      primaryAssignee: { staff_id: 'stf_owner' },
      expectedAssignment: 'Assigned to another staff member',
    },
  ])('uses the projected handoff assignee for a $access viewer', ({ access, primaryAssignee, expectedAssignment }) => {
    renderConversation({
      detail: {
        ...detail,
        ownership: {
          state: 'assigned',
          current_staff_access: access,
          primary_assignee: primaryAssignee,
        },
        work_summary: { unread_claimant_messages: 0 },
        customer_next_step: { responsible_party: 'claims_professional' },
      },
      handoffs: [assistanceHandoff('accepted', { assigned_to: 'stf_owner' })],
      profile: { staff_id: 'stf_viewer', display_name: 'Viewing Staff' },
      resource: { items: [], resolved_session_id: 'ses_1' },
      draft: '',
      onDraft: vi.fn(),
      onAccept: vi.fn(),
      onResolve: vi.fn(),
      onSend: vi.fn(),
    })

    const statusBar = screen.getByText('Staff assistance').closest('.assistance-status')
    expect(statusBar).toHaveTextContent(expectedAssignment)
    expect(statusBar).not.toHaveTextContent('Assigned to you')
    expect(statusBar).not.toHaveTextContent('Viewing Staff')
  })

  it.each([
    {
      name: 'customer reply',
      handoff: assistanceHandoff('in_progress'),
      workSummary: { unread_claimant_messages: 1 },
      nextStep: { responsible_party: 'claims_professional' },
      title: 'Customer replied',
      placeholder: 'Reply to customer...',
    },
    {
      name: 'waiting customer',
      handoff: assistanceHandoff('in_progress'),
      workSummary: { unread_claimant_messages: 0 },
      nextStep: { responsible_party: 'claimant' },
      title: 'Waiting for customer',
      placeholder: 'Waiting for the customer — send an update if needed',
    },
    {
      name: 'completed assistance',
      handoff: assistanceHandoff('resolved'),
      workSummary: { unread_claimant_messages: 0 },
      nextStep: { responsible_party: 'claims_professional' },
      title: 'Staff assistance completed',
      placeholder: 'Staff assistance is complete',
    },
  ])('renders the $name composer and assistance state from server projections', ({ handoff, workSummary, nextStep, title, placeholder }) => {
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

    const statusBar = screen.getByText('Staff assistance').closest('.assistance-status')
    expect(statusBar).toHaveTextContent(title)
    if (handoff.status === 'resolved') {
      expect(statusBar).not.toHaveTextContent('Completed by')
      expect(statusBar).not.toHaveTextContent('Demo Staff')
    } else {
      expect(statusBar).toHaveTextContent('Assigned to you · Demo Staff')
    }
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
    let finishSend
    const onSend = vi.fn(() => new Promise((resolve) => { finishSend = resolve }))
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
      resource: { items: [], resolved_session_id: 'ses_1', loading: true },
      draft: 'A claimant-safe update',
      onDraft: vi.fn(),
      onSend,
    })

    expect(screen.queryByRole('heading', { name: 'Claimant conversation' })).not.toBeInTheDocument()
    const messageList = screen.getByRole('log', { name: 'Claimant conversation messages' })
    Object.defineProperty(messageList, 'scrollHeight', { configurable: true, value: 600 })
    messageList.scrollTop = 0
    expect(messageList).toHaveTextContent('No messages yet')
    expect(messageList).toHaveTextContent(
      'Messages with the claimant will appear here.',
    )
    expect(screen.getByLabelText('Message to claimant')).toHaveAttribute('placeholder', 'Write a message…')
    expect(screen.queryByText(/shared claim context|0 messages|visible to the claimant/i)).not.toBeInTheDocument()
    expect(screen.getByText('Refreshing this section')).toBeVisible()

    const click = user.click(screen.getByRole('button', { name: 'Send message' }))
    await waitFor(() => expect(onSend).toHaveBeenCalledOnce())
    expect(screen.queryByText('Refreshing this section')).not.toBeInTheDocument()
    finishSend()
    await click
    expect(onSend).toHaveBeenCalledWith({
      draft: 'A claimant-safe update',
      message: 'A claimant-safe update',
      sessionId: 'ses_1',
    })
    await waitFor(() => expect(messageList.scrollTop).toBe(600))
  })

  it('preserves a follow-up draft typed while the first message is sending', async () => {
    let finishSend
    const onSend = vi.fn(() => new Promise((resolve) => {
      finishSend = () => resolve({ delivery: { message_id: 'msg_first_staff' } })
    }))
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/workbench/claims/clm_1/conversation?session=ses_1']}>
        <DraftConversation onSend={onSend} />
      </MemoryRouter>,
    )

    const textarea = screen.getByLabelText('Message to claimant')
    await user.click(screen.getByRole('button', { name: 'Send message' }))
    await waitFor(() => expect(onSend).toHaveBeenCalledOnce())

    await user.clear(textarea)
    await user.type(textarea, 'Follow-up draft written while sending')
    expect(textarea).toHaveValue('Follow-up draft written while sending')

    finishSend()

    await waitFor(() => {
      expect(textarea).toHaveValue('Follow-up draft written while sending')
      expect(screen.getByRole('button', { name: 'Send message' })).toBeEnabled()
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
      statusLabel: 'Assigned to you',
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
        requested_session_id: 'ses_old',
        resolved_session_id: 'ses_old',
        items: [{
          message_id: 'msg_old',
          session_id: 'ses_old',
          actor: 'claimant',
          content: { type: 'text', text: 'Existing claimant message.' },
          created_at: '2026-09-08T10:00:00Z',
        }],
      },
      requestedSessionId: 'ses_old',
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

  it('never renders a resolved session under a different requested session', () => {
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
        requested_session_id: 'ses_active',
        resolved_session_id: 'ses_old',
        items: [{
          message_id: 'msg_old',
          session_id: 'ses_old',
          actor: 'claimant',
          content: { type: 'text', text: 'Old session message.' },
          created_at: '2026-09-10T05:00:00Z',
        }],
      },
      requestedSessionId: 'ses_active',
      draft: 'Must not send',
      onDraft: vi.fn(),
      onSend,
    }, '/workbench/claims/clm_1/conversation?session=ses_active')

    expect(screen.queryByText('Old session message.')).not.toBeInTheDocument()
    expect(screen.getByText('Loading current records...')).toBeVisible()
    expect(screen.queryByLabelText('Message to claimant')).not.toBeInTheDocument()
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
        requested_session_id: 'ses_missing',
        resolved_session_id: null,
        status: 'unavailable',
        error: 'The requested claimant session is not available. Return to the Claim and open an available conversation.',
      },
      requestedSessionId: 'ses_missing',
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
