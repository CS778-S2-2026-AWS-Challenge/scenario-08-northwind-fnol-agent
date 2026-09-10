import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
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

function claimDetail(revision) {
  return {
    claim_id: 'clm_journey',
    display_reference: 'NW-JOURNEY',
    claimant: { customer_id: 'cus_demo', display_name: 'Synthetic Claimant' },
    incident: { family: 'motor', summary: 'Synthetic session boundary journey.' },
    lifecycle_state: 'staff_support',
    workflow_state: 'collecting',
    revision,
    updated_at: '2026-09-10T06:30:00Z',
    active_session_id: 'ses_26',
    allowed_actions: [{
      action_code: 'conversation.send_claimant_message',
      target_ref: 'ses_26',
      availability: 'available',
    }],
  }
}

function renderJourney() {
  return render(
    <MemoryRouter initialEntries={[
      '/workbench/claims/clm_journey/conversation?session=ses_26',
    ]}>
      <Routes>
        <Route
          path="/workbench/claims/:claimId/:section"
          element={<WorkbenchPage />}
        />
      </Routes>
    </MemoryRouter>,
  )
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
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads the requested active session beyond page one, sends, and rereads the persisted message from that session', async () => {
    let revision = 7
    const persistedMessages = []
    const historicalMessages = []

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
        return jsonResponse(200, claimDetail(revision))
      }
      if (path.startsWith('/api/v1/workbench/claims/clm_journey/handoffs')) {
        return jsonResponse(200, { items: [], page: { next_cursor: null } })
      }
      if (path.startsWith('/api/v1/workbench/claims/clm_journey/collaboration-requests')) {
        return jsonResponse(200, { items: [], page: { next_cursor: null } })
      }
      if (path.startsWith('/api/v1/workbench/claims/clm_journey/sessions?')) {
        if (path.includes('cursor=page-2')) {
          return jsonResponse(200, {
            items: [{ session_id: 'ses_26', status: 'active' }],
            page: { next_cursor: null },
          })
        }
        return jsonResponse(200, {
          items: Array.from({ length: 25 }, (_, index) => ({
            session_id: `ses_${index + 1}`,
            status: 'closed',
          })),
          page: { next_cursor: 'page-2' },
        })
      }
      if (path.startsWith('/api/v1/workbench/claims/clm_journey/sessions/ses_26/messages')) {
        return jsonResponse(200, {
          items: persistedMessages.map((message) => ({ ...message })),
          page: { next_cursor: null },
        })
      }
      if (path.startsWith('/api/v1/workbench/claims/clm_journey/sessions/ses_25/messages')) {
        return jsonResponse(200, {
          items: historicalMessages.map((message) => ({ ...message })),
          page: { next_cursor: null },
        })
      }
      if (path === '/api/v1/workbench/claims/clm_journey/messages' && method === 'POST') {
        expect(options.headers['If-Match']).toBe('7')
        expect(options.headers['Idempotency-Key']).toBeTruthy()
        const payload = JSON.parse(options.body)
        expect(payload).toEqual({
          content: { type: 'text', text: 'Journey staff reply' },
        })

        const message = {
          message_id: 'msg_staff_journey',
          session_id: 'ses_26',
          actor: 'staff',
          visibility: 'claimant_visible',
          content: payload.content,
          created_at: '2026-09-10T06:31:00Z',
        }
        persistedMessages.push(message)
        revision += 1
        return jsonResponse(200, {
          message,
          claim_revision: revision,
        })
      }

      throw new Error(`Unexpected Workbench request: ${method} ${path}`)
    })

    vi.stubGlobal('fetch', fetchMock)
    renderJourney()

    const sendButton = await screen.findByRole('button', { name: 'Send message' })
    await waitFor(() => expect(sendButton).toBeEnabled())

    expect(fetchMock.mock.calls.some(([url]) => (
      String(url).includes('/sessions?limit=25&cursor=page-2')
    ))).toBe(true)
    expect(fetchMock.mock.calls.some(([url]) => (
      String(url).includes('/sessions/ses_26/messages')
    ))).toBe(true)

    await userEvent.setup().click(sendButton)

    await waitFor(() => {
      expect(screen.getByText('Journey staff reply')).toBeVisible()
    })

    expect(persistedMessages).toHaveLength(1)
    expect(persistedMessages[0]).toMatchObject({
      session_id: 'ses_26',
      actor: 'staff',
      content: { type: 'text', text: 'Journey staff reply' },
    })
    expect(historicalMessages).toHaveLength(0)
    expect(fetchMock.mock.calls.filter(([url]) => (
      String(url).includes('/sessions/ses_26/messages')
    )).length).toBeGreaterThanOrEqual(2)
  })
})
