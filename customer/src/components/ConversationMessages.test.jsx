import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  AgentMessageRow,
  ClaimantMessageRow,
  StaffMessageRow,
} from './ConversationMessages.jsx'

function message(text, id) {
  return {
    message_id: id,
    created_at: '2026-10-06T01:23:00Z',
    content: { type: 'text', text },
    evidence_refs: [],
  }
}

describe('conversation message rows', () => {
  it('renders consecutive assistant replies in their own content-sized bubbles', () => {
    render(
      <>
        <AgentMessageRow message={message('A short reply.', 'agent-one')} />
        <AgentMessageRow message={message(
          'A longer reply that can wrap naturally without changing the alignment of the avatar or assistant name.',
          'agent-two',
        )} />
      </>,
    )

    const replies = screen.getAllByText(/reply/)
    expect(replies).toHaveLength(2)
    for (const reply of replies) {
      expect(reply.closest('.agent-bubble')).toHaveClass('chat-bubble')
      expect(reply.closest('.msg-agent')?.querySelector('.agent-avatar')).toHaveTextContent('N')
      expect(reply.closest('.msg-agent')).toHaveTextContent('Claims assistant')
    }
  })

  it('places captured information directly after, and outside, the assistant bubble', () => {
    render(
      <AgentMessageRow message={message('I recorded the claim type.', 'agent-card')}>
        <section className="captured-information-card" aria-label="Captured information">
          Captured information
        </section>
      </AgentMessageRow>,
    )

    const bubble = screen.getByText('I recorded the claim type.').closest('.agent-bubble')
    const card = screen.getByRole('region', { name: 'Captured information' })
    expect(bubble).not.toContainElement(card)
    expect(bubble?.nextElementSibling).toBe(card)
  })

  it('keeps claimant messages right-oriented in their distinct existing bubble', () => {
    render(
      <ClaimantMessageRow
        message={message('My vehicle was damaged.', 'claimant-one')}
        displayName="Alex"
        evidenceItems={[]}
        previewFiles={new Map()}
        readings={new Map()}
      />,
    )

    const article = screen.getByText('My vehicle was damaged.').closest('.msg-user')
    expect(article?.querySelector('.user-bubble')).toHaveClass('chat-bubble')
    expect(article?.querySelector('.chat-message-row > .user-message-body + .claimant-message-avatar'))
      .toBeInTheDocument()
  })

  it('uses the neutral message bubble for Northwind staff messages', () => {
    render(<StaffMessageRow message={message('I can help with that.', 'staff-one')} />)

    const bubble = screen.getByText('I can help with that.').closest('.staff-bubble')
    expect(bubble).toHaveClass('chat-bubble')
    expect(bubble?.previousElementSibling).toHaveClass('staff-label')
  })
})
