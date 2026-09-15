import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api.js'
import Conversation from './Conversation.jsx'

const detail = { active_session_id: 'ses_1', allowed_actions: [] }

function renderConversation(props, route = '/workbench/claims/clm_1/conversation?session=ses_1') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Conversation {...props} />
    </MemoryRouter>,
  )
}

describe('Conversation', () => {
  it('shows the exact blocked claimant-message reason without a usable form', () => {
    renderConversation({
      detail: {
        ...detail,
        allowed_actions: [{
          action_code: 'conversation.send_claimant_message',
          target_ref: 'ses_1',
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

  it('keeps a displayed historical session read only', () => {
    const onSend = vi.fn()
    renderConversation({
      detail: {
        ...detail,
        active_session_id: 'ses_active',
        allowed_actions: [{
          action_code: 'conversation.send_claimant_message',
          target_ref: 'ses_active',
          availability: 'available',
        }],
      },
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
      onSend,
    }, '/workbench/claims/clm_1/conversation?session=ses_old')

    expect(screen.getByLabelText('Message to claimant')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
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
