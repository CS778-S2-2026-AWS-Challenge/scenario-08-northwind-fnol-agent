import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import OpenItems from './OpenItems.jsx'
import WaitingList from './WaitingList.jsx'

const question = {
  item_id: 'nwq_hire',
  kind: 'question',
  owner: 'northwind',
  state: 'open',
  subject: 'Will you pay for a hire car?',
  claimant_wording: 'will you pay for a hire car',
  proposed_answer: 'Yes, for up to 14 days.',
  basis: 'MTR-BEN-03 Hire car',
  created_at: '2026-10-02T01:00:00Z',
}
const callMe = {
  item_id: 'nwq_call',
  kind: 'contact_request',
  owner: 'northwind',
  state: 'open',
  subject: 'Please call me',
  claimant_wording: 'can someone call me',
  contact_preference: 'Phone after 5 pm',
  basis: 'General request to be contacted.',
  created_at: '2026-10-02T01:00:00Z',
}
const quote = {
  item_id: 'evd_quote',
  kind: 'document',
  owner: 'claimant',
  state: 'open',
  subject: 'repair_quote',
  created_at: '2026-10-02T01:00:00Z',
}
const action = (target) => ({
  action_code: 'conversation.answer_claimant_question',
  target_ref: target,
  availability: 'confirmation_required',
  based_on_revision: 4,
})

describe('Open items', () => {
  it('lists documents and points to the waiting list', async () => {
    const user = userEvent.setup()
    const onOpenWaitingList = vi.fn()
    render(<OpenItems items={[quote, question]} onOpenWaitingList={onOpenWaitingList} />)

    expect(screen.getByRole('heading', { name: 'Still owed on this Claim' })).toBeVisible()
    expect(screen.getByText('repair quote')).toBeVisible()
    expect(screen.queryByText('Will you pay for a hire car?')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Open waiting list' }))
    expect(onOpenWaitingList).toHaveBeenCalledOnce()
  })
})

describe('Waiting list', () => {
  it('approves the proposed answer, edits it, or marks a contact request', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn().mockResolvedValue(undefined)
    render(<WaitingList items={[quote, question, callMe]} actions={[action('nwq_hire'), action('nwq_call')]} onDecide={onDecide} />)

    expect(screen.queryByText('repair quote')).not.toBeInTheDocument()
    expect(screen.getByText(/Yes, for up to 14 days\./)).toBeVisible()
    expect(screen.getByText(/MTR-BEN-03 Hire car/)).toBeVisible()
    expect(screen.getByText(/Phone after 5 pm/)).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Approve and send' }))
    expect(onDecide).toHaveBeenLastCalledWith(action('nwq_hire'), { decision: 'approve', text: null })

    await user.click(screen.getByRole('button', { name: 'Edit then send' }))
    const answer = screen.getByRole('textbox', { name: 'Answer for the claimant' })
    expect(answer).toHaveValue('Yes, for up to 14 days.')
    await user.clear(answer)
    await user.type(answer, 'Yes, for 10 days.')
    await user.click(screen.getByRole('button', { name: 'Send answer' }))
    expect(onDecide).toHaveBeenLastCalledWith(action('nwq_hire'), { decision: 'edit', text: 'Yes, for 10 days.' })

    await user.click(screen.getByRole('button', { name: 'Mark contacted' }))
    await user.click(screen.getByRole('button', { name: 'Mark contacted' }))
    expect(onDecide).toHaveBeenLastCalledWith(action('nwq_call'), { decision: 'contacted', text: null })
  })

  it('needs a reason to decline and offers nothing without a projected action', async () => {
    const user = userEvent.setup()
    const onDecide = vi.fn().mockResolvedValue(undefined)
    const { rerender } = render(<WaitingList items={[question]} actions={[action('nwq_hire')]} onDecide={onDecide} />)

    await user.click(screen.getByRole('button', { name: 'Decline' }))
    expect(screen.getByRole('button', { name: 'Decline' })).toBeDisabled()
    await user.type(screen.getByRole('textbox', { name: 'Reason the claimant will read' }), 'We will explain on the phone.')
    await user.click(screen.getByRole('button', { name: 'Decline' }))
    expect(onDecide).toHaveBeenCalledWith(action('nwq_hire'), { decision: 'decline', text: 'We will explain on the phone.' })

    rerender(<WaitingList items={[question]} actions={[]} onDecide={onDecide} />)
    expect(screen.queryByRole('button', { name: 'Approve and send' })).not.toBeInTheDocument()
    rerender(<WaitingList items={[question]} actions={[action('nwq_hire')]} readOnly onDecide={onDecide} />)
    expect(screen.queryByRole('button', { name: 'Approve and send' })).not.toBeInTheDocument()
  })
})
