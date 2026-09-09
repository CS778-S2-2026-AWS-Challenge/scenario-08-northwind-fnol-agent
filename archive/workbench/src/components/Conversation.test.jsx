import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Conversation from './Conversation.jsx'

const detail = { active_session_id: 'ses_1', allowed_actions: [] }

describe('Conversation', () => {
  it('shows the exact blocked claimant-message reason without a usable form', () => {
    render(<Conversation detail={{ ...detail, allowed_actions: [{ action_code: 'conversation.send_claimant_message', target_ref: 'ses_1', label: 'Reply to claimant', availability: 'blocked', blocked_reason: 'Accept the handoff before replying.' }] }} resource={{ items: [] }} draft="" onDraft={vi.fn()} onSend={vi.fn()} />)

    expect(screen.getByText('Accept the handoff before replying.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
  })

  it('ignores a projected message action for another session', () => {
    render(<Conversation detail={{ ...detail, allowed_actions: [{ action_code: 'conversation.send_claimant_message', target_ref: 'ses_other', availability: 'available' }] }} resource={{ items: [] }} draft="Ready" onDraft={vi.fn()} onSend={vi.fn()} />)

    expect(screen.getByText(/no claimant-message action is projected/i)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
  })

  it('submits an available exact-target message action', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<Conversation detail={{ ...detail, allowed_actions: [{ action_code: 'conversation.send_claimant_message', target_ref: 'ses_1', availability: 'available' }] }} resource={{ items: [] }} draft="A claimant-safe update" onDraft={vi.fn()} onSend={onSend} />)

    await user.click(screen.getByRole('button', { name: 'Send message' }))
    expect(onSend).toHaveBeenCalledWith('A claimant-safe update')
  })
})
