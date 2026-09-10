import { render, screen, waitFor } from '@testing-library/react'
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

    expect(screen.getByText('Accept the handoff before replying.')).toBeVisible()
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

    expect(screen.getByText(/no claimant-message action is projected/i)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
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

    expect(screen.getByLabelText('Reply to claimant')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
    expect(screen.getByText(/saved session is read-only/i)).toBeInTheDocument()
    expect(onSend).not.toHaveBeenCalled()
  })

  it('refreshes authoritative Claim context after a stale revision without clearing the draft', async () => {
    const user = userEvent.setup()
    const onDraft = vi.fn()
    const onRefresh = vi.fn()
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
      onRefresh,
    })

    await user.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1))
    expect(onDraft).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Reply to claimant')).toHaveValue('Preserve this draft')
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
      onRefresh: vi.fn(),
    })

    await user.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('could not be reached')
    expect(onDraft).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Reply to claimant')).toHaveValue('Retry this safely')
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
    expect(screen.getByLabelText('Reply to claimant')).toBeDisabled()
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
    expect(screen.queryByLabelText('Reply to claimant')).not.toBeInTheDocument()
  })

})
