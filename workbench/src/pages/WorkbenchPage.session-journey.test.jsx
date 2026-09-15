import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import WorkbenchPage from './WorkbenchPage.jsx'

const tabs = vi.hoisted(() => ({
  tabs: [],
  activeId: 'clm_journey',
  open: vi.fn(),
  activate: vi.fn(),
  close: vi.fn(),
  update: vi.fn(),
}))

vi.mock('../auth/auth-context.js', () => ({
  useAuth: () => ({
    token: 'staff-token',
    profile: { staff_id: 'stf_demo', display_name: 'Demo Staff' },
    logout: vi.fn(),
  }),
}))
vi.mock('../hooks/usePersistentTabs.js', () => ({ usePersistentTabs: () => tabs }))
vi.mock('../components/NavigationRail.jsx', () => ({ default: () => null }))
vi.mock('../components/ClaimTabs.jsx', () => ({ default: () => null }))
vi.mock('../components/QueuePanel.jsx', () => ({ default: () => null }))
vi.mock('../components/StaffAgent.jsx', () => ({ default: () => null }))

const metadata = {
  views: [{ value: 'all', label: 'All active work', group: 'overview' }],
  workflow_states: [],
  priorities: [],
  tags: [],
  tag_registry_version: '0.3',
}

function jsonResponse(status, payload) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: vi.fn().mockResolvedValue(payload),
  }
}

function claimDetail(revision, {
  activeSessionId = 'ses_26',
  actionTarget = activeSessionId,
  actionAvailability = 'available',
} = {}) {
  return {
    claim_id: 'clm_journey',
    display_reference: 'NW-JOURNEY',
    claimant: { customer_id: 'cus_demo', display_name: 'Synthetic Claimant' },
    incident: { family: 'motor', summary: 'Synthetic session boundary journey.' },
    lifecycle_state: 'staff_support',
    workflow_state: 'collecting',
    revision,
    updated_at: '2026-09-10T06:30:00Z',
    active_session_id: activeSessionId,
    allowed_actions: actionTarget ? [{
      action_code: 'conversation.send_claimant_message',
      target_ref: actionTarget,
      availability: actionAvailability,
      based_on_revision: revision,
    }] : [],
  }
}

function staffMessage(text, messageId = 'msg_staff_journey', sessionId = 'ses_26') {
  return {
    message_id: messageId,
    session_id: sessionId,
    actor: 'staff',
    visibility: 'shared',
    content: { type: 'text', text },
    created_at: '2026-09-10T06:31:00Z',
  }
}

function JourneySessionSwitcher() {
  const navigate = useNavigate()
  return (
    <button
      type="button"
      onClick={() => navigate('/workbench/claims/clm_journey/conversation?session=ses_25')}
    >
      Open historical test session
    </button>
  )
}

function renderJourney(sessionId = 'ses_26', { withSessionSwitcher = false } = {}) {
  return render(
    <MemoryRouter initialEntries={[
      `/workbench/claims/clm_journey/conversation?session=${sessionId}`,
    ]}>
      {withSessionSwitcher && <JourneySessionSwitcher />}
      <Routes>
        <Route
          path="/workbench/claims/:claimId/:section"
          element={<WorkbenchPage />}
        />
      </Routes>
    </MemoryRouter>,
  )
}

function messageReadCount(state, sessionId) {
  return state.messageReads.filter((readSessionId) => readSessionId === sessionId).length
}

async function expectLedgerMessageAfterRead(state, sessionId, readsBefore, text) {
  await waitFor(() => {
    expect(messageReadCount(state, sessionId)).toBeGreaterThan(readsBefore)
    const ledger = document.querySelector('.message-list')
    expect(ledger).toBeInTheDocument()
    const matchingArticles = [...ledger.querySelectorAll('.message')].filter(
      (article) => article.textContent?.includes(text),
    )
    expect(matchingArticles).toHaveLength(1)
  })
}

function createJourneyService({
  revision = { value: 7 },
  claimFactory = () => claimDetail(revision.value),
  pageOneSessions = Array.from({ length: 25 }, (_, index) => ({
    session_id: `ses_${index + 1}`,
    status: 'closed',
  })),
  pageTwoSessions = [{ session_id: 'ses_26', status: 'active' }],
  messagesBySession = { ses_25: [], ses_26: [] },
  onMessageRead,
  onPost,
} = {}) {
  const state = {
    revision,
    messagesBySession,
    postRequests: [],
    claimReads: 0,
    sessionReads: [],
    messageReads: [],
  }

  const fetchMock = vi.fn(async (url, options = {}) => {
    const path = String(url)
    const method = options.method || 'GET'

    if (path === '/api/v1/workbench/claims/filter-metadata') {
      return jsonResponse(200, metadata)
    }
    if (path.startsWith('/api/v1/workbench/claims?')) {
      return jsonResponse(200, {
        items: [],
        page: { next_cursor: null },
        view_counts: {
          status: 'available',
          items: [{ view: 'all', count: 0 }],
          limitation: null,
        },
      })
    }
    if (path === '/api/v1/workbench/claims/clm_journey') {
      state.claimReads += 1
      return jsonResponse(200, claimFactory())
    }
    if (path.startsWith('/api/v1/workbench/claims/clm_journey/handoffs')) {
      return jsonResponse(200, { items: [], page: { next_cursor: null } })
    }
    if (path.startsWith('/api/v1/workbench/claims/clm_journey/collaboration-requests')) {
      return jsonResponse(200, { items: [], page: { next_cursor: null } })
    }
    if (path.startsWith('/api/v1/workbench/claims/clm_journey/sessions?')) {
      state.sessionReads.push(path)
      if (path.includes('cursor=page-2')) {
        return jsonResponse(200, {
          items: pageTwoSessions.map((session) => ({ ...session })),
          page: { next_cursor: null },
        })
      }
      return jsonResponse(200, {
        items: pageOneSessions.map((session) => ({ ...session })),
        page: { next_cursor: pageTwoSessions.length ? 'page-2' : null },
      })
    }

    const messageMatch = path.match(
      /^\/api\/v1\/workbench\/claims\/clm_journey\/sessions\/([^/]+)\/messages\?/,
    )
    if (messageMatch) {
      const sessionId = decodeURIComponent(messageMatch[1])
      state.messageReads.push(sessionId)
      const controlledResponse = onMessageRead?.(sessionId, state)
      if (controlledResponse) return controlledResponse
      return jsonResponse(200, {
        items: (state.messagesBySession[sessionId] || []).map((message) => ({ ...message })),
        page: { next_cursor: null },
      })
    }

    if (path === '/api/v1/workbench/claims/clm_journey/messages' && method === 'POST') {
      const request = {
        key: options.headers['Idempotency-Key'],
        revision: options.headers['If-Match'],
        payload: JSON.parse(options.body),
      }
      state.postRequests.push(request)

      if (onPost) return onPost(request, state)

      const message = staffMessage(request.payload.content.text)
      state.messagesBySession.ses_26.push(message)
      state.revision.value += 1
      return jsonResponse(200, {
        message,
        claim_revision: state.revision.value,
      })
    }

    throw new Error(`Unexpected Workbench request: ${method} ${path}`)
  })

  return { fetchMock, state }
}

describe('WorkbenchPage staff session browser/API journey', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    tabs.tabs = [{
      claimId: 'clm_journey',
      displayReference: 'NW-JOURNEY',
      section: 'conversation',
      sessionId: 'ses_26',
      draft: 'Journey staff reply',
    }]
    tabs.update.mockImplementation((claimId, patch) => {
      const tab = tabs.tabs.find((item) => item.claimId === claimId)
      if (tab) Object.assign(tab, patch)
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('loads the requested active session beyond page one, sends, and rereads the persisted shared message from that session', async () => {
    const { fetchMock, state } = createJourneyService()
    vi.stubGlobal('fetch', fetchMock)
    renderJourney()

    const sendButton = await screen.findByRole('button', { name: 'Send message' })
    await waitFor(() => expect(sendButton).toBeEnabled())

    expect(state.sessionReads.some((path) => path.includes('cursor=page-2'))).toBe(true)
    expect(state.messageReads).toContain('ses_26')
    const readsBeforeSend = messageReadCount(state, 'ses_26')

    await userEvent.setup().click(sendButton)

    await expectLedgerMessageAfterRead(
      state,
      'ses_26',
      readsBeforeSend,
      'Journey staff reply',
    )

    expect(state.messagesBySession.ses_26).toHaveLength(1)
    expect(state.messagesBySession.ses_26[0]).toMatchObject({
      session_id: 'ses_26',
      actor: 'staff',
      visibility: 'shared',
      content: { type: 'text', text: 'Journey staff reply' },
    })
    expect(state.messagesBySession.ses_25).toHaveLength(0)
  })

  it('keeps a displayed historical session read only and never posts from it', async () => {
    tabs.tabs[0] = {
      ...tabs.tabs[0],
      sessionId: 'ses_25',
      draft: 'Must stay local',
    }
    const messagesBySession = {
      ses_25: [{
        message_id: 'msg_historical',
        session_id: 'ses_25',
        actor: 'claimant',
        visibility: 'shared',
        content: { type: 'text', text: 'Historical claimant message' },
        created_at: '2026-09-09T03:00:00Z',
      }],
      ses_26: [],
    }
    const { fetchMock, state } = createJourneyService({ messagesBySession })
    vi.stubGlobal('fetch', fetchMock)
    renderJourney('ses_25')

    expect(await screen.findByText('Historical claimant message')).toBeVisible()
    const reply = screen.getByLabelText('Message to claimant')
    const sendButton = screen.getByRole('button', { name: 'Send message' })

    expect(reply).toBeDisabled()
    expect(reply).toHaveValue('Must stay local')
    expect(sendButton).toBeDisabled()
    expect(screen.getByText('Read-only conversation')).toBeVisible()

    await userEvent.setup().click(sendButton)
    expect(state.postRequests).toHaveLength(0)
    expect(state.messageReads).toContain('ses_25')
  })

  it('removes the active-session projection while a historical session is loading', async () => {
    let finishHistoricalRead
    const messagesBySession = {
      ses_25: [{
        message_id: 'msg_historical_slow',
        session_id: 'ses_25',
        actor: 'claimant',
        visibility: 'shared',
        content: { type: 'text', text: 'Historical session loaded.' },
        created_at: '2026-09-09T03:00:00Z',
      }],
      ses_26: [{
        message_id: 'msg_active_before_switch',
        session_id: 'ses_26',
        actor: 'claimant',
        visibility: 'shared',
        content: { type: 'text', text: 'Active session must disappear.' },
        created_at: '2026-09-10T03:00:00Z',
      }],
    }
    const { fetchMock, state } = createJourneyService({
      messagesBySession,
      onMessageRead(sessionId) {
        if (sessionId !== 'ses_25') return null
        return new Promise((resolve) => {
          finishHistoricalRead = () => resolve(jsonResponse(200, {
            items: messagesBySession.ses_25.map((message) => ({ ...message })),
            page: { next_cursor: null },
          }))
        })
      },
    })
    vi.stubGlobal('fetch', fetchMock)
    renderJourney('ses_26', { withSessionSwitcher: true })

    expect(await screen.findByText('Active session must disappear.')).toBeVisible()
    await userEvent.setup().click(
      screen.getByRole('button', { name: 'Open historical test session' }),
    )
    await waitFor(() => expect(state.messageReads).toContain('ses_25'))

    expect(screen.queryByText('Active session must disappear.')).not.toBeInTheDocument()
    expect(screen.queryByText('Historical session loaded.')).not.toBeInTheDocument()
    expect(screen.getByText('Loading current records...')).toBeVisible()

    finishHistoricalRead()
    expect(await screen.findByText('Historical session loaded.')).toBeVisible()
    expect(screen.queryByText('Active session must disappear.')).not.toBeInTheDocument()
  })

  it('does not restore active-session messages when a historical session load fails', async () => {
    const messagesBySession = {
      ses_25: [],
      ses_26: [{
        message_id: 'msg_active_before_failure',
        session_id: 'ses_26',
        actor: 'claimant',
        visibility: 'shared',
        content: { type: 'text', text: 'Active session must stay hidden.' },
        created_at: '2026-09-10T03:00:00Z',
      }],
    }
    const { fetchMock } = createJourneyService({
      messagesBySession,
      onMessageRead(sessionId) {
        if (sessionId !== 'ses_25') return null
        return jsonResponse(500, {
          error: {
            code: 'INTERNAL_ERROR',
            message: 'The historical conversation could not be loaded.',
            details: [],
            retryable: true,
          },
        })
      },
    })
    vi.stubGlobal('fetch', fetchMock)
    renderJourney('ses_26', { withSessionSwitcher: true })

    expect(await screen.findByText('Active session must stay hidden.')).toBeVisible()
    await userEvent.setup().click(
      screen.getByRole('button', { name: 'Open historical test session' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The historical conversation could not be loaded.',
    )
    expect(screen.queryByText('Active session must stay hidden.')).not.toBeInTheDocument()
    expect(screen.queryByRole('log', { name: 'Claimant conversation messages' })).not.toBeInTheDocument()
  })

  it('ignores a late active-session response after the historical session is applied', async () => {
    let finishActiveRead
    let holdActiveRead = true
    const messagesBySession = {
      ses_25: [{
        message_id: 'msg_historical_winner',
        session_id: 'ses_25',
        actor: 'claimant',
        visibility: 'shared',
        content: { type: 'text', text: 'Historical response wins.' },
        created_at: '2026-09-09T03:00:00Z',
      }],
      ses_26: [{
        message_id: 'msg_late_active',
        session_id: 'ses_26',
        actor: 'claimant',
        visibility: 'shared',
        content: { type: 'text', text: 'Late active response must be ignored.' },
        created_at: '2026-09-10T03:00:00Z',
      }],
    }
    const { fetchMock, state } = createJourneyService({
      messagesBySession,
      onMessageRead(sessionId) {
        if (sessionId !== 'ses_26' || !holdActiveRead) return null
        holdActiveRead = false
        return new Promise((resolve) => {
          finishActiveRead = () => resolve(jsonResponse(200, {
            items: messagesBySession.ses_26.map((message) => ({ ...message })),
            page: { next_cursor: null },
          }))
        })
      },
    })
    vi.stubGlobal('fetch', fetchMock)
    renderJourney('ses_26', { withSessionSwitcher: true })

    await waitFor(() => expect(state.messageReads).toContain('ses_26'))
    await userEvent.setup().click(
      screen.getByRole('button', { name: 'Open historical test session' }),
    )
    expect(await screen.findByText('Historical response wins.')).toBeVisible()

    finishActiveRead()
    await waitFor(() => {
      expect(screen.getByText('Historical response wins.')).toBeVisible()
      expect(screen.queryByText('Late active response must be ignored.')).not.toBeInTheDocument()
    })
  })

  it('keeps the draft and reports a recoverable readback error after a successful post', async () => {
    const { fetchMock, state } = createJourneyService({
      onMessageRead(sessionId, serviceState) {
        if (sessionId !== 'ses_26' || messageReadCount(serviceState, sessionId) === 1) {
          return null
        }
        return jsonResponse(500, {
          error: {
            code: 'INTERNAL_ERROR',
            message: 'The latest conversation messages could not be read.',
            details: [],
            retryable: true,
          },
        })
      },
    })
    vi.stubGlobal('fetch', fetchMock)
    renderJourney()

    const sendButton = await screen.findByRole('button', { name: 'Send message' })
    await waitFor(() => expect(sendButton).toBeEnabled())
    await userEvent.setup().click(sendButton)

    expect(await screen.findByText(/message refresh failed/i)).toBeVisible()
    expect(screen.getByLabelText('Message to claimant')).toHaveValue('Journey staff reply')
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Retry section' })).toBeEnabled()
    expect(state.postRequests).toHaveLength(1)
    expect(state.messagesBySession.ses_26).toHaveLength(1)
    expect(tabs.update).not.toHaveBeenCalledWith('clm_journey', { draft: '' })
  })

  it('does not confirm a send when a competing refresh supersedes its readback', async () => {
    let finishSendReadback
    const { fetchMock, state } = createJourneyService({
      onMessageRead(sessionId, serviceState) {
        if (sessionId !== 'ses_26') return null
        const readCount = messageReadCount(serviceState, sessionId)
        if (readCount !== 2) return null
        return new Promise((resolve) => {
          finishSendReadback = () => resolve(jsonResponse(200, {
            items: serviceState.messagesBySession.ses_26.map((message) => ({ ...message })),
            page: { next_cursor: null },
          }))
        })
      },
    })
    vi.stubGlobal('fetch', fetchMock)
    renderJourney()

    const sendButton = await screen.findByRole('button', { name: 'Send message' })
    await waitFor(() => expect(sendButton).toBeEnabled())
    const ledger = screen.getByRole('log', { name: 'Claimant conversation messages' })
    Object.defineProperty(ledger, 'scrollHeight', { configurable: true, value: 800 })
    ledger.scrollTop = 91

    await userEvent.setup().click(sendButton)
    await waitFor(() => {
      expect(messageReadCount(state, 'ses_26')).toBeGreaterThanOrEqual(3)
      expect(ledger).toHaveTextContent('Journey staff reply')
    })

    finishSendReadback()

    expect(await screen.findByText(/another conversation refresh replaced its confirmation/i)).toBeVisible()
    expect(screen.getByLabelText('Message to claimant')).toHaveValue('Journey staff reply')
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
    expect(ledger.scrollTop).toBe(91)
    expect(state.postRequests).toHaveLength(1)
    expect(tabs.update).not.toHaveBeenCalledWith('clm_journey', { draft: '' })
  })

  it('does not clear or force-scroll a historical session when an active-session send finishes', async () => {
    let finishSend
    let finishHistoricalRead
    let holdFirstHistoricalRead = true
    const messagesBySession = {
      ses_25: [{
        message_id: 'msg_historical_delayed',
        session_id: 'ses_25',
        actor: 'claimant',
        visibility: 'shared',
        content: { type: 'text', text: 'Historical session remains selected' },
        created_at: '2026-09-09T03:00:00Z',
      }],
      ses_26: [],
    }
    const { fetchMock, state } = createJourneyService({
      messagesBySession,
      onMessageRead(sessionId) {
        if (sessionId !== 'ses_25' || !holdFirstHistoricalRead) return null
        holdFirstHistoricalRead = false
        return new Promise((resolve) => {
          finishHistoricalRead = () => resolve(jsonResponse(200, {
            items: messagesBySession.ses_25.map((message) => ({ ...message })),
            page: { next_cursor: null },
          }))
        })
      },
      onPost(request, serviceState) {
        return new Promise((resolve) => {
          finishSend = () => {
            const message = staffMessage(request.payload.content.text, 'msg_delayed_send')
            serviceState.messagesBySession.ses_26.push(message)
            serviceState.revision.value += 1
            resolve(jsonResponse(200, {
              message,
              claim_revision: serviceState.revision.value,
            }))
          }
        })
      },
    })
    vi.stubGlobal('fetch', fetchMock)
    renderJourney('ses_26', { withSessionSwitcher: true })

    const user = userEvent.setup()
    const sendButton = await screen.findByRole('button', { name: 'Send message' })
    await waitFor(() => expect(sendButton).toBeEnabled())
    await user.click(sendButton)
    await waitFor(() => expect(state.postRequests).toHaveLength(1))

    await user.click(screen.getByRole('button', { name: 'Open historical test session' }))
    await waitFor(() => expect(state.messageReads).toContain('ses_25'))
    expect(screen.getByText('Loading current records...')).toBeVisible()
    expect(screen.queryByLabelText('Message to claimant')).not.toBeInTheDocument()
    expect(screen.queryByText('Historical session remains selected')).not.toBeInTheDocument()

    finishHistoricalRead()
    expect(await screen.findByText('Historical session remains selected')).toBeVisible()
    expect(screen.getByLabelText('Message to claimant')).toBeDisabled()
    expect(screen.getByText('Read-only conversation')).toBeVisible()
    const historicalLedger = screen.getByRole('log', { name: 'Claimant conversation messages' })
    Object.defineProperty(historicalLedger, 'scrollHeight', { configurable: true, value: 900 })
    historicalLedger.scrollTop = 137
    const historicalReadsBeforeSendFinished = messageReadCount(state, 'ses_25')

    finishSend()
    await waitFor(() => {
      expect(messageReadCount(state, 'ses_25')).toBeGreaterThan(
        historicalReadsBeforeSendFinished,
      )
    })

    expect(screen.getByText('Historical session remains selected')).toBeVisible()
    expect(historicalLedger).not.toHaveTextContent('Journey staff reply')
    expect(screen.getByLabelText('Message to claimant')).toBeDisabled()
    expect(historicalLedger.scrollTop).toBe(137)
    expect(tabs.tabs[0].draft).toBe('Journey staff reply')
    expect(tabs.update).not.toHaveBeenCalledWith('clm_journey', { draft: '' })
  })

  it('retries an ambiguous committed send with the same idempotency key and persists exactly one rendered message', async () => {
    const committedByKey = new Map()
    const { fetchMock, state } = createJourneyService({
      onPost(request, serviceState) {
        expect(request.payload).toEqual({
          content: { type: 'text', text: 'Journey staff reply' },
        })

        if (!committedByKey.has(request.key)) {
          const message = staffMessage('Journey staff reply', 'msg_ambiguous')
          committedByKey.set(request.key, message)
          serviceState.messagesBySession.ses_26.push(message)
          serviceState.revision.value += 1
          throw new TypeError('Synthetic connection dropped after commit')
        }

        return jsonResponse(200, {
          message: committedByKey.get(request.key),
          claim_revision: serviceState.revision.value,
        })
      },
    })
    vi.stubGlobal('fetch', fetchMock)
    renderJourney()

    const user = userEvent.setup()
    const sendButton = await screen.findByRole('button', { name: 'Send message' })
    await waitFor(() => expect(sendButton).toBeEnabled())

    await user.click(sendButton)

    expect(await screen.findByRole('alert')).toHaveTextContent('could not be reached')
    expect(screen.getByLabelText('Message to claimant')).toHaveValue('Journey staff reply')
    expect(state.messagesBySession.ses_26).toHaveLength(1)
    expect(state.postRequests).toHaveLength(1)
    const readsBeforeRetry = messageReadCount(state, 'ses_26')

    await user.click(screen.getByRole('button', { name: 'Send message' }))

    await expectLedgerMessageAfterRead(
      state,
      'ses_26',
      readsBeforeRetry,
      'Journey staff reply',
    )

    expect(state.postRequests).toHaveLength(2)
    expect(state.postRequests[0].key).toBeTruthy()
    expect(state.postRequests[1].key).toBe(state.postRequests[0].key)
    expect(state.messagesBySession.ses_26).toHaveLength(1)
    expect(state.messagesBySession.ses_26[0]).toMatchObject({
      message_id: 'msg_ambiguous',
      visibility: 'shared',
    })
  })

  it('reloads stale authority, refuses silent retargeting, and only sends after the new active session is explicitly opened', async () => {
    let activeSessionId = 'ses_26'
    let postAttempt = 0
    const pageTwoSessions = [
      { session_id: 'ses_26', status: 'active' },
      { session_id: 'ses_27', status: 'closed' },
    ]
    const messagesBySession = { ses_25: [], ses_26: [], ses_27: [] }
    let serviceState
    const service = createJourneyService({
      pageTwoSessions,
      messagesBySession,
      claimFactory: () => claimDetail(serviceState.revision.value, {
        activeSessionId,
        actionTarget: activeSessionId,
      }),
      onPost(request, state) {
        postAttempt += 1
        if (postAttempt === 1) {
          activeSessionId = 'ses_27'
          pageTwoSessions[0].status = 'closed'
          pageTwoSessions[1].status = 'active'
          state.revision.value = 8
          return jsonResponse(409, {
            error: {
              code: 'REVISION_CONFLICT',
              message: 'The Claim changed after this page was loaded.',
              details: [],
            },
          })
        }

        expect(request.revision).toBe('8')
        const message = staffMessage(
          'Journey staff reply',
          'msg_after_revalidation',
          'ses_27',
        )
        state.messagesBySession.ses_27.push(message)
        state.revision.value = 9
        return jsonResponse(200, {
          message,
          claim_revision: 9,
        })
      },
    })
    serviceState = service.state
    vi.stubGlobal('fetch', service.fetchMock)

    const firstPage = renderJourney('ses_26')
    const user = userEvent.setup()
    const sendButton = await screen.findByRole('button', { name: 'Send message' })
    await waitFor(() => expect(sendButton).toBeEnabled())

    const readsBeforeConflict = {
      claim: service.state.claimReads,
      sessions: service.state.sessionReads.length,
      messages: service.state.messageReads.length,
    }

    await user.click(sendButton)

    const staleAlert = await screen.findByRole('alert')
    expect(staleAlert).toHaveTextContent(
      'latest server projection at revision 8 is now shown',
    )

    expect(screen.getByLabelText('Message to claimant')).toHaveValue(
      'Journey staff reply',
    )
    expect(service.state.postRequests).toHaveLength(1)
    expect(service.state.postRequests[0].revision).toBe('7')
    expect(service.state.messagesBySession.ses_26).toHaveLength(0)
    expect(service.state.messagesBySession.ses_27).toHaveLength(0)

    await waitFor(() => {
      expect(screen.getByText('Read-only conversation')).toBeVisible()
      expect(screen.getByLabelText('Message to claimant')).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
    })

    expect(service.state.claimReads).toBeGreaterThan(
      readsBeforeConflict.claim,
    )
    expect(service.state.sessionReads.length).toBeGreaterThan(
      readsBeforeConflict.sessions,
    )
    expect(service.state.messageReads.length).toBeGreaterThan(
      readsBeforeConflict.messages,
    )
    expect(service.state.postRequests).toHaveLength(1)

    firstPage.unmount()

    tabs.tabs[0] = {
      ...tabs.tabs[0],
      sessionId: 'ses_27',
    }

    renderJourney('ses_27')

    const revalidatedButton = await screen.findByRole('button', { name: 'Send message' })
    await waitFor(() => expect(revalidatedButton).toBeEnabled())
    expect(screen.getByLabelText('Message to claimant')).toHaveValue('Journey staff reply')
    expect(service.state.postRequests).toHaveLength(1)
    const readsBeforeRevalidatedSend = messageReadCount(service.state, 'ses_27')

    await userEvent.setup().click(revalidatedButton)

    await expectLedgerMessageAfterRead(
      service.state,
      'ses_27',
      readsBeforeRevalidatedSend,
      'Journey staff reply',
    )

    expect(service.state.postRequests).toHaveLength(2)
    expect(service.state.postRequests[1].revision).toBe('8')
    expect(service.state.postRequests[1].key).not.toBe(service.state.postRequests[0].key)
    expect(service.state.messagesBySession.ses_26).toHaveLength(0)
    expect(service.state.messagesBySession.ses_27).toHaveLength(1)
    expect(service.state.messagesBySession.ses_27[0]).toMatchObject({
      message_id: 'msg_after_revalidation',
      session_id: 'ses_27',
      visibility: 'shared',
    })
  })
})
