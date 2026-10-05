import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import {
  AgentTurnDisclosure,
  AgentTurnPlaceholder,
} from './AgentTurnActivity.jsx'
import { reduceTurnProgress } from '../agentTurnProgress.js'

function progressEvent(stage, ordinal, state = 'running') {
  return {
    event_type: 'agent.turn.progress',
    turn_id: 'message-one',
    stage,
    state,
    ordinal,
  }
}

describe('Agent turn activity', () => {
  it('keeps the pending assistant state inside the agent message bubble', () => {
    const { container } = render(<AgentTurnPlaceholder turnId="message-one" />)

    const article = screen.getByLabelText('Claims assistant is working')
    const bubble = article.querySelector('.agent-bubble')
    expect(bubble).toHaveClass('chat-bubble', 'agent-turn-bubble')
    expect(bubble).toContainElement(screen.getByRole('status'))
    expect(screen.getByRole('status')).toHaveTextContent('Sending your message')
    expect(container.querySelector('.agent-avatar + .agent-body .agent-label'))
      .toHaveTextContent('Claims assistant')
  })

  it('ignores duplicate, out-of-order, foreign, and post-terminal progress', () => {
    const accepted = reduceTurnProgress(null, progressEvent('turn.accepted', 1), 'message-one')
    const loading = reduceTurnProgress(
      accepted,
      progressEvent('context.loading', 2),
      'message-one',
    )
    const duplicate = reduceTurnProgress(
      loading,
      progressEvent('model.waiting', 2),
      'message-one',
    )
    const completed = reduceTurnProgress(
      loading,
      progressEvent('turn.completed', 3, 'completed'),
      'message-one',
    )

    expect(duplicate).toBe(loading)
    expect(reduceTurnProgress(completed, progressEvent('tool.running', 4), 'message-one'))
      .toBe(completed)
    expect(reduceTurnProgress(loading, { ...progressEvent('model.waiting', 3), turn_id: 'other' }, 'message-one'))
      .toBe(loading)
  })

  it('uses an accessible compact disclosure for observed completed work', async () => {
    const user = userEvent.setup()
    render(<AgentTurnDisclosure progress={{
      state: 'completed',
      activities: [
        { stage: 'context.loading', label: 'Reviewing your claim details' },
        { stage: 'knowledge.querying', label: 'Checking relevant policy information' },
      ],
    }} />)

    const trigger = screen.getByRole('button', { name: 'Checked relevant policy information' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    await user.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Reviewing your claim details')).toBeVisible()
  })
})
