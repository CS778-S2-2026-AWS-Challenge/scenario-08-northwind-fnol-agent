import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import ConversationsPage from './ConversationsPage.jsx'

const claimConversation = {
  conversation_id: 'claim:ses_claim',
  kind: 'claim',
  session_id: 'ses_claim',
  title: 'Claim NW-1042',
  summary: 'Claimant conversation.',
  status: 'active',
}

const agentConversations = [
  agentConversation('sas_evidence', 'Evidence review', 'Police report is still pending.', 0, 2),
  agentConversation('sas_policy', 'Policy wording', 'Excess and coverage notes.', 1),
  agentConversation('sas_compare', 'New Staff Agent session', 'Compare missing evidence across both Claims.', 3),
  agentConversation('sas_older', 'Repair guidance', 'Reviewed repair assessment guidance.', 20),
]

function relativeDate(daysAgo, hour = 10) {
  const value = new Date()
  value.setHours(hour, 0, 0, 0)
  value.setDate(value.getDate() - daysAgo)
  return value.toISOString()
}

function agentConversation(sessionId, title, summary, daysAgo, unreadCount = 0) {
  return {
    conversation_id: `staff_agent:${sessionId}`,
    kind: 'staff_agent',
    session_id: sessionId,
    status: 'active',
    title,
    summary,
    unread_count: unreadCount,
    updated_at: relativeDate(daysAgo),
  }
}

function renderPage(overrides = {}) {
  const props = {
    conversations: [claimConversation, ...agentConversations],
    loading: false,
    error: null,
    onRetry: vi.fn(),
    onOpenConversation: vi.fn(),
    selectedStaffAgentSessionId: null,
    ...overrides,
  }
  return { ...render(<ConversationsPage {...props} />), props }
}

it('shows one compact Staff Agent history without page-level current or new sections', () => {
  renderPage({ selectedStaffAgentSessionId: 'sas_evidence' })

  expect(screen.getByRole('heading', { name: 'Staff Agent conversations' })).toBeInTheDocument()
  expect(screen.queryByText('Current conversation')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'New conversation' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Evidence review/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Policy wording/ })).toBeInTheDocument()
})

it('opens a history record through the existing persistent-session flow without removing history', async () => {
  const user = userEvent.setup()
  const { props } = renderPage({ selectedStaffAgentSessionId: 'sas_evidence' })
  const policyConversation = screen.getByRole('button', { name: /Policy wording/ })

  await user.click(policyConversation)

  expect(props.onOpenConversation).toHaveBeenCalledWith(agentConversations[1])
  expect(screen.getByRole('button', { name: /Policy wording/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Repair guidance/ })).toBeInTheDocument()
})

it('uses message metadata for generic titles and honest fallbacks for an empty conversation', () => {
  const emptyConversation = {
    ...agentConversation('sas_empty', 'New Staff Agent session', null, 2),
    updated_at: null,
  }
  renderPage({ conversations: [agentConversations[2], emptyConversation] })

  expect(screen.getByRole('button', { name: /Compare missing evidence across both Claims/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Empty conversation/ })).toHaveTextContent('No messages yet.')
  expect(screen.queryByText('New Staff Agent session')).not.toBeInTheDocument()
  expect(screen.queryByText('No summary is available.')).not.toBeInTheDocument()
})

it('groups conversations by updated time while retaining server order within a group', () => {
  const secondTodayConversation = agentConversation(
    'sas_follow_up',
    'Follow-up wording',
    'Drafted a concise claimant follow-up.',
    0,
  )
  renderPage({
    conversations: [agentConversations[0], secondTodayConversation, ...agentConversations.slice(1)],
  })

  expect(screen.getAllByRole('heading', { level: 4 }).map((heading) => heading.textContent)).toEqual([
    'Previous conversations',
    'Yesterday',
    'Previous 7 days',
    'Older',
  ])
  const today = screen.getByRole('list', { name: 'Previous conversations' })
  expect(within(today).getAllByRole('button').map((button) => (
    button.querySelector('strong')?.textContent
  ))).toEqual(['Evidence review', 'Follow-up wording'])
})

it('searches previous conversations locally and clears a distinct no-results state', async () => {
  const user = userEvent.setup()
  renderPage({ selectedStaffAgentSessionId: 'sas_evidence' })
  const search = screen.getByRole('searchbox', { name: 'Search conversations' })

  await user.type(search, 'compare missing evidence')
  expect(screen.getByRole('button', { name: /Compare missing evidence/ })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Policy wording/ })).not.toBeInTheDocument()
  expect(screen.getByText('1 matching conversation')).toBeInTheDocument()

  await user.clear(search)
  await user.type(search, 'not in loaded metadata')
  expect(screen.getByRole('status')).toHaveTextContent('No conversations match “not in loaded metadata”.')
  await user.click(screen.getByRole('button', { name: 'Clear search' }))
  expect(screen.getByRole('button', { name: /Policy wording/ })).toBeInTheDocument()
})

it('paginates long histories, supports keyboard paging, and resets filtering to page one', async () => {
  const user = userEvent.setup()
  const longHistory = Array.from({ length: 12 }, (_, index) => agentConversation(
    `sas_${index}`,
    `Conversation ${index + 1}`,
    `Unique preview ${index + 1}`,
    20 + index,
  ))
  renderPage({ conversations: longHistory })

  const firstPage = screen.getByRole('list', { name: 'Older conversations' })
  expect(within(firstPage).getAllByRole('button')).toHaveLength(5)
  expect(within(firstPage).getAllByRole('button')[0]).toHaveTextContent('Conversation 1')
  expect(screen.getByText('Page 1 of 3')).toBeInTheDocument()

  const next = screen.getByRole('button', { name: 'Next' })
  next.focus()
  await user.keyboard('{Enter}')
  expect(screen.getByText('Page 2 of 3')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Conversation 6/ })).toBeInTheDocument()

  await user.type(screen.getByRole('searchbox', { name: 'Search conversations' }), 'Unique preview 6')
  expect(screen.getByRole('button', { name: /Conversation 6/ })).toBeInTheDocument()
  expect(screen.queryByLabelText('Staff Agent conversation pages')).not.toBeInTheDocument()
})

it('distinguishes empty, loading, and failure states while preserving recovery actions', async () => {
  const user = userEvent.setup()
  const onRetry = vi.fn()
  const { rerender } = renderPage({ conversations: [], loading: false, onRetry })
  expect(screen.getByRole('status')).toHaveTextContent('No Staff Agent conversations yet.')
  expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()

  rerender(<ConversationsPage conversations={[]} loading error={null} onRetry={onRetry} onOpenConversation={vi.fn()} />)
  expect(screen.getAllByRole('status').some((status) => (
    status.textContent.includes('Loading Staff Agent conversations...')
  ))).toBe(true)

  const error = Object.assign(new Error('The conversation service timed out.'), { requestId: 'req_history_1' })
  rerender(<ConversationsPage conversations={[]} loading={false} error={error} onRetry={onRetry} onOpenConversation={vi.fn()} />)
  const alert = screen.getAllByRole('alert').find((item) => (
    item.textContent.includes('Staff Agent conversations are unavailable.')
  ))
  expect(alert).toHaveTextContent('The conversation service timed out.')
  expect(alert).toHaveTextContent('Request reference: req_history_1')
  await user.click(within(alert).getByRole('button', { name: 'Retry' }))
  expect(onRetry).toHaveBeenCalledOnce()
})

it('keeps the conversation controls usable at a compact viewport', async () => {
  const user = userEvent.setup()
  const originalWidth = window.innerWidth
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 360 })
  const { props } = renderPage({ selectedStaffAgentSessionId: 'sas_evidence' })

  const search = screen.getByRole('searchbox', { name: 'Search conversations' })
  search.focus()
  await user.keyboard('policy')
  expect(screen.getByRole('button', { name: /Policy wording/ })).toBeEnabled()
  await user.click(screen.getByRole('button', { name: /Policy wording/ }))
  expect(props.onOpenConversation).toHaveBeenCalledWith(agentConversations[1])

  Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
})
