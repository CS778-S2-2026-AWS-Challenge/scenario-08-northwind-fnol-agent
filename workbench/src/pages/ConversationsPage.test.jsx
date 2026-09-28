import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import ConversationsPage from './ConversationsPage.jsx'

vi.mock('../components/Conversation.jsx', () => ({
  default: ({ draft, evidenceRecords, onDraft, onScrollPosition }) => (
    <div data-testid="conversation-timeline">
      <label htmlFor="mock-reply">Reply</label>
      <textarea id="mock-reply" value={draft} onChange={(event) => onDraft?.(event.target.value)} />
      <button type="button" onClick={() => onScrollPosition?.(240)}>Save reading position</button>
      <output>{evidenceRecords.length} evidence records</output>
    </div>
  ),
}))

const claimDetail = {
  claim_id: 'clm_1042',
  revision: 3,
  display_reference: 'NW-1042',
  claimant: { customer_id: 'cus_alex', display_name: 'Alex Morgan' },
  incident: { family: 'motor', summary: 'Rear bumper damage.' },
  lifecycle_state: 'staff_support',
  updated_at: '2026-09-14T03:00:00Z',
  ownership: {
    state: 'assigned',
    current_staff_access: 'primary',
    primary_assignee: { staff_id: 'stf_demo', display_name: 'Demo Staff' },
  },
  priority_projection: { level: 'urgent', rank: 1, is_overdue: false },
  work_summary: { unread_claimant_messages: 2 },
  customer_next_step: { responsible_party: 'claims_professional' },
  active_session_id: 'ses_claim',
  allowed_actions: [],
}

const claimConversation = {
  conversation_id: 'claim:ses_claim',
  kind: 'claim',
  claim_id: 'clm_1042',
  display_reference: 'NW-1042',
  session_id: 'ses_claim',
  title: 'Claim NW-1042',
  summary: 'Can you confirm when the assessor will call?',
  status: 'active',
  updated_at: '2026-09-14T03:00:00Z',
  detail: claimDetail,
  assistance: { status: 'in_progress', waitingForCustomer: false },
}

const waitingConversation = {
  ...claimConversation,
  conversation_id: 'claim:ses_waiting',
  claim_id: 'clm_2002',
  display_reference: 'NW-2002',
  session_id: 'ses_waiting',
  summary: 'Please upload the repair quote.',
  detail: {
    ...claimDetail,
    claim_id: 'clm_2002',
    display_reference: 'NW-2002',
    claimant: { display_name: 'Jamie Lee' },
    work_summary: { unread_claimant_messages: 0 },
    customer_next_step: { responsible_party: 'claimant' },
  },
  assistance: { status: 'in_progress', waitingForCustomer: true },
}

const resolvedConversation = {
  ...waitingConversation,
  conversation_id: 'claim:ses_resolved',
  claim_id: 'clm_2003',
  display_reference: 'NW-2003',
  session_id: 'ses_resolved',
  status: 'completed',
  detail: {
    ...waitingConversation.detail,
    claim_id: 'clm_2003',
    display_reference: 'NW-2003',
    claimant: { display_name: 'Taylor Singh' },
  },
  assistance: { status: 'resolved', waitingForCustomer: false },
}

const assistanceRequest = {
  claim_id: 'clm_help',
  display_reference: 'NW-3001',
  incident: { family: 'motor', summary: 'Vehicle was hit while parked.' },
  detail: {
    ...claimDetail,
    claim_id: 'clm_help',
    display_reference: 'NW-3001',
    claimant: { display_name: 'Morgan Chen' },
    active_session_id: 'ses_help',
    ownership: { state: 'unassigned', current_staff_access: 'read_only' },
    work_summary: { unread_claimant_messages: 0 },
  },
  handoff: {
    handoff_id: 'hnd_help',
    status: 'queued',
    reason: 'Customer asked to speak with staff.',
    created_at: '2026-09-14T02:00:00Z',
    packet: { incident_summary: 'Parked vehicle damage; registration is confirmed.' },
  },
  canTakeOver: true,
}

const agentConversations = Array.from({ length: 7 }, (_, index) => ({
  conversation_id: `staff_agent:sas_${index + 1}`,
  kind: 'staff_agent',
  session_id: `sas_${index + 1}`,
  status: 'active',
  title: index === 0 ? 'Evidence review' : `Internal review ${index + 1}`,
  summary: index === 0 ? 'Police report is still pending.' : `Internal message ${index + 1}`,
  unread_count: index === 0 ? 2 : 0,
  updated_at: `2026-09-${String(14 - index).padStart(2, '0')}T02:00:00Z`,
}))

function renderPage(overrides = {}) {
  const props = {
    conversations: [claimConversation, waitingConversation, resolvedConversation, ...agentConversations],
    loading: false,
    error: null,
    onRetry: vi.fn(),
    onOpenConversation: vi.fn(),
    selectedStaffAgentSessionId: null,
    assistanceRequests: [assistanceRequest],
    assistanceLoading: false,
    assistanceError: null,
    onRetryAssistance: vi.fn(),
    onReviewRequest: vi.fn(),
    onTakeOver: vi.fn().mockResolvedValue(undefined),
    onActivateConversation: vi.fn(),
    onCloseConversation: vi.fn(),
    onBackToList: vi.fn(),
    onOpenClaim: vi.fn(),
    onRetryDetail: vi.fn(),
    onRetryConversation: vi.fn(),
    onDraft: vi.fn(),
    onScrollPosition: vi.fn(),
    profile: { staff_id: 'stf_demo', display_name: 'Demo Staff' },
    ...overrides,
  }
  return { ...render(<ConversationsPage {...props} />), props }
}

it('uses counted category tabs with Action needed selected by default and keyboard navigation', async () => {
  const user = userEvent.setup()
  renderPage()

  const attention = screen.getByRole('tab', { name: 'Action needed, 2 conversations' })
  const assigned = screen.getByRole('tab', { name: 'My conversations, 3 conversations' })
  const agent = screen.getByRole('tab', { name: 'Staff Agent, 7 conversations' })
  expect(attention).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('list', { name: 'Conversation queue' })).toHaveTextContent('Alex Morgan')
  expect(screen.getByRole('list', { name: 'Conversation queue' })).toHaveTextContent('Morgan Chen')

  attention.focus()
  await user.keyboard('{ArrowRight}')
  expect(assigned).toHaveAttribute('aria-selected', 'true')
  expect(assigned).toHaveFocus()
  expect(screen.getByRole('list', { name: 'Conversation queue' })).toHaveTextContent('Taylor Singh')

  await user.keyboard('{End}')
  expect(agent).toHaveAttribute('aria-selected', 'true')
})

it('keeps an unassigned unread customer reply in Action needed without adding it to My conversations', async () => {
  const user = userEvent.setup()
  const unassignedConversation = {
    ...claimConversation,
    conversation_id: 'claim:ses_unassigned',
    claim_id: 'clm_unassigned',
    display_reference: 'NW-4001',
    session_id: 'ses_unassigned',
    detail: {
      ...claimDetail,
      claim_id: 'clm_unassigned',
      display_reference: 'NW-4001',
      claimant: { display_name: 'Robin Patel' },
      ownership: { state: 'unassigned', current_staff_access: 'read_only' },
      work_summary: { unread_claimant_messages: 1 },
    },
  }
  renderPage({ conversations: [unassignedConversation], assistanceRequests: [] })

  expect(screen.getByRole('tab', { name: 'Action needed, 1 conversations' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('list', { name: 'Conversation queue' })).toHaveTextContent('Robin Patel')

  await user.click(screen.getByRole('tab', { name: 'My conversations, 0 conversations' }))
  expect(screen.getByRole('status')).toHaveTextContent('No assigned conversations')
})

it('opens queue summaries without expanding full messages in the list', async () => {
  const user = userEvent.setup()
  const { props } = renderPage()
  const queue = screen.getByRole('list', { name: 'Conversation queue' })
  const alex = within(queue).getByRole('button', { name: /Alex Morgan/ })

  expect(alex).toHaveTextContent('Claim NW-1042')
  expect(alex).toHaveTextContent('Can you confirm when the assessor will call?')
  expect(alex).toHaveTextContent('Needs attention')
  expect(alex).toHaveTextContent('2')
  await user.click(alex)
  expect(props.onOpenConversation).toHaveBeenCalledWith(expect.objectContaining({
    conversation_id: claimConversation.conversation_id,
    claim_id: claimConversation.claim_id,
    session_id: claimConversation.session_id,
  }))
  expect(screen.queryByRole('log')).not.toBeInTheDocument()
})

it('keeps review separate from a confirmed take-over action', async () => {
  const user = userEvent.setup()
  const { props } = renderPage()
  const requestRow = screen.getByRole('button', { name: /Morgan Chen/ })

  await user.click(requestRow)
  expect(props.onReviewRequest).toHaveBeenCalledWith(assistanceRequest)
  expect(props.onTakeOver).not.toHaveBeenCalled()

  await user.click(screen.getByRole('button', { name: 'Take over' }))
  expect(props.onTakeOver).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'Confirm take over' }))
  expect(props.onTakeOver).toHaveBeenCalledWith(assistanceRequest)
})

it('shows one selected conversation with authoritative Claim metadata, draft, and mobile return control', async () => {
  const user = userEvent.setup()
  const openTabs = [{
    claimId: 'clm_1042',
    sessionId: 'ses_claim',
    label: 'Alex Morgan',
    unreadCount: 2,
    draft: 'Saved reply',
  }]
  const { props } = renderPage({
    selectedConversationSessionId: 'ses_claim',
    openConversationTabs: openTabs,
    detail: claimDetail,
    resources: { evidence: { items: [{ evidence_id: 'evd_1' }] } },
    profile: { staff_id: 'stf_demo', display_name: 'Demo Staff' },
    draft: 'Saved reply',
  })

  expect(screen.getByRole('heading', { name: 'Alex Morgan' })).toBeInTheDocument()
  expect(screen.getByText(/Claim NW-1042 · Motor claim/)).toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: 'Current conversation' })).getByText('Assigned to you')).toBeInTheDocument()
  expect(screen.getByText('2 new customer messages', { selector: 'div' })).toHaveAttribute('role', 'status')
  expect(screen.getByRole('textbox', { name: 'Reply' })).toHaveValue('Saved reply')
  expect(screen.getByText('1 evidence records')).toBeInTheDocument()

  fireEvent.change(screen.getByRole('textbox', { name: 'Reply' }), { target: { value: 'Saved reply updated' } })
  expect(props.onDraft).toHaveBeenLastCalledWith('Saved reply updated')
  await user.click(screen.getByRole('button', { name: 'Save reading position' }))
  expect(props.onScrollPosition).toHaveBeenCalledWith(240)
  await user.click(screen.getByRole('button', { name: 'Conversations' }))
  expect(props.onBackToList).toHaveBeenCalledOnce()
  await user.click(screen.getByRole('button', { name: 'Open claim' }))
  expect(props.onOpenClaim).toHaveBeenCalledOnce()
})

it('limits direct workspace tabs, exposes overflow as a keyboard menu, and supports Delete', async () => {
  const user = userEvent.setup()
  const tabs = Array.from({ length: 7 }, (_, index) => ({
    claimId: `clm_${index + 1}`,
    sessionId: `ses_${index + 1}`,
    label: `Customer ${index + 1}`,
    unreadCount: index === 5 ? 3 : 0,
    draft: index === 6 ? 'Unsent' : '',
  }))
  const { props } = renderPage({ openConversationTabs: tabs })

  expect(screen.getAllByRole('tab', { name: /Customer/ })).toHaveLength(5)
  const more = screen.getByRole('button', { name: 'More' })
  more.focus()
  await user.keyboard('{ArrowDown}')
  const menu = screen.getByRole('menu', { name: 'More open conversations' })
  expect(within(menu).getAllByRole('menuitem')).toHaveLength(2)
  expect(within(menu).getByRole('menuitem', { name: /Customer 6/ })).toHaveFocus()
  await user.keyboard('{Escape}')
  expect(more).toHaveFocus()

  const first = screen.getByRole('tab', { name: 'Customer 1' })
  first.focus()
  await user.keyboard('{Delete}')
  expect(props.onCloseConversation).toHaveBeenCalledWith('clm_1')
})

it('searches and pages the Staff Agent queue without changing its existing open flow', async () => {
  const user = userEvent.setup()
  const { props } = renderPage()
  await user.click(screen.getByRole('tab', { name: 'Staff Agent, 7 conversations' }))

  expect(screen.getByRole('list', { name: 'Conversation queue' })).toHaveTextContent('Evidence review')
  expect(screen.getByText('Page 1 of 2')).toBeInTheDocument()
  await user.type(screen.getByRole('searchbox', { name: 'Search conversations' }), 'police report')
  const record = screen.getByRole('button', { name: /Evidence review/ })
  await user.click(record)
  expect(props.onOpenConversation).toHaveBeenCalledWith(agentConversations[0])

  await user.clear(screen.getByRole('searchbox', { name: 'Search conversations' }))
  await user.type(screen.getByRole('searchbox', { name: 'Search conversations' }), 'missing title')
  expect(screen.getByRole('status')).toHaveTextContent('No conversations match “missing title”.')
})

it('shows the selected Staff Agent history in the detail pane', () => {
  renderPage({
    selectedStaffAgentSessionId: 'sas_1',
    staffAgentDetail: <div data-testid="staff-agent-history">Persisted Staff Agent messages</div>,
  })

  expect(screen.getByRole('tab', { name: 'Staff Agent, 7 conversations' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('button', { name: /Evidence review/ })).toHaveAttribute('aria-current', 'true')
  expect(screen.getByTestId('staff-agent-history')).toHaveTextContent('Persisted Staff Agent messages')
  expect(screen.queryByRole('heading', { name: 'Select a conversation' })).not.toBeInTheDocument()
})

it('distinguishes loading, failure, empty queue, empty conversation, ownership, and resolved states', async () => {
  const user = userEvent.setup()
  const { rerender } = renderPage({ conversations: [], assistanceRequests: [], loading: true, assistanceLoading: true })
  expect(screen.getByRole('status')).toHaveTextContent('Loading conversations...')

  const error = Object.assign(new Error('Conversation service timed out.'), { requestId: 'req_1' })
  rerender(<ConversationsPage conversations={[]} assistanceRequests={[]} loading={false} assistanceLoading={false} error={error} onRetry={vi.fn()} onOpenConversation={vi.fn()} />)
  expect(screen.getByRole('alert')).toHaveTextContent('Conversation service timed out.')
  expect(screen.getByRole('alert')).toHaveTextContent('Request reference: req_1')

  rerender(<ConversationsPage conversations={[]} assistanceRequests={[]} loading={false} assistanceLoading={false} error={null} onRetry={vi.fn()} onOpenConversation={vi.fn()} />)
  expect(screen.getByRole('status')).toHaveTextContent('Nothing needs attention')
  expect(screen.getByRole('heading', { name: 'Select a conversation' })).toBeInTheDocument()

  const otherOwner = {
    ...claimDetail,
    ownership: {
      state: 'assigned',
      current_staff_access: 'read_only',
      primary_assignee: { staff_id: 'stf_other', display_name: 'Sam Rivera' },
    },
  }
  rerender(<ConversationsPage conversations={[resolvedConversation]} loading={false} error={null} onRetry={vi.fn()} onOpenConversation={vi.fn()} selectedConversationSessionId="ses_resolved" openConversationTabs={[{ claimId: 'clm_2003', sessionId: 'ses_resolved', label: 'Taylor Singh' }]} detail={{ ...otherOwner, claim_id: 'clm_2003' }} resources={{}} onBackToList={vi.fn()} onCloseConversation={vi.fn()} onOpenClaim={vi.fn()} onDraft={vi.fn()} />)
  expect(screen.getByText('Assigned to Sam Rivera')).toBeInTheDocument()
  expect(screen.getByText('Owned by another staff member')).toBeInTheDocument()
  expect(screen.getByText(/This conversation is resolved/)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Close current conversation tab' }))
})
