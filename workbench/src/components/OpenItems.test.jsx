import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import OpenItems from './OpenItems.jsx'

const question = {
  item_id: 'nwq_hire',
  kind: 'question',
  owner: 'northwind',
  state: 'open',
  subject: 'Is my hire car covered?',
  claimant_wording: 'will you pay for a hire car',
  model_view: 'No hire-car clause in the excerpts.',
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
const answerAction = {
  action_code: 'conversation.answer_claimant_question',
  target_ref: 'nwq_hire',
  availability: 'confirmation_required',
  based_on_revision: 4,
}

describe('Open items', () => {
  it('shows what is owed and answers a claimant question through the projected action', async () => {
    const user = userEvent.setup()
    const onAnswer = vi.fn().mockResolvedValue(undefined)
    render(<OpenItems items={[quote, question]} actions={[answerAction]} onAnswer={onAnswer} />)

    expect(screen.getByRole('heading', { name: 'Still owed on this Claim' })).toBeVisible()
    expect(screen.getByText('repair quote')).toBeVisible()
    expect(screen.getByText('Claimant will send')).toBeVisible()
    expect(screen.getByText(/No hire-car clause in the excerpts/)).toBeVisible()

    await user.type(screen.getByRole('textbox', { name: 'Answer for the claimant' }), 'Yes, for up to 14 days.')
    await user.click(screen.getByRole('button', { name: 'Send answer' }))

    expect(onAnswer).toHaveBeenCalledWith(answerAction, 'Yes, for up to 14 days.')
  })

  it('offers no answer form without a projected action or in read-only view', () => {
    const { rerender } = render(<OpenItems items={[question]} actions={[]} onAnswer={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Send answer' })).not.toBeInTheDocument()
    rerender(<OpenItems items={[question]} actions={[answerAction]} readOnly onAnswer={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Send answer' })).not.toBeInTheDocument()
  })
})
