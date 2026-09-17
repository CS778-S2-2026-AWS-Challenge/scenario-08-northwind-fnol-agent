import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import {
  AgentTurnDisclosure,
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
