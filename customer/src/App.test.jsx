import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const originalCreateObjectUrl = Object.getOwnPropertyDescriptor(globalThis.URL, 'createObjectURL')
const originalRevokeObjectUrl = Object.getOwnPropertyDescriptor(globalThis.URL, 'revokeObjectURL')

const api = vi.hoisted(() => ({
  ApiRequestError: class ApiRequestError extends Error {},
  acceptClaimAgreement: vi.fn(),
  confirmClaimFields: vi.fn(),
  createAccountAsset: vi.fn(),
  createAccountPolicy: vi.fn(),
  createExternalClaim: vi.fn(),
  createPaymentDestination: vi.fn(),
  createClaim: vi.fn(),
  grantAssessorConsent: vi.fn(),
  getAuthenticatedAccount: vi.fn(),
  hasClaimantAccessToken: vi.fn(),
  getClaim: vi.fn(),
  getClaimMessages: vi.fn(),
  getClaimEvidence: vi.fn(),
  getRuntimeCapabilities: vi.fn(),
  listAccountAssets: vi.fn(),
  listAccountIdentityDocuments: vi.fn(),
  listAccountPaymentDestinations: vi.fn(),
  listAccountPolicies: vi.fn(),
  listClaims: vi.fn(),
  listEvidenceHistory: vi.fn(),
  listPaymentDestinations: vi.fn(),
  loginClaimant: vi.fn(),
  logoutClaimant: vi.fn(),
  pauseClaimSession: vi.fn(),
  requestId: vi.fn((prefix) => `${prefix}-test`),
  requestHumanSupport: vi.fn(),
  promoteAnonymousClaim: vi.fn(),
  requestAssessorRouting: vi.fn(),
  registerClaimant: vi.fn(),
  requestEvidenceUpload: vi.fn(),
  selectClaimPayoutContact: vi.fn(),
  uploadEvidenceContent: vi.fn(),
  completeEvidenceUpload: vi.fn(),
  resumeClaimSession: vi.fn(),
  startClaimSession: vi.fn(),
  streamClaimUpdates: vi.fn(() => new Promise(() => {})),
  streamRealtimeEvents: vi.fn(() => new Promise(() => {})),
  submitClaimMessage: vi.fn(),
  setClaimantAccessToken: vi.fn(),
  updateAccountPreferences: vi.fn(),
  updateAccountProfile: vi.fn(),
  updateClaimAutoFillPreferences: vi.fn(),
  updateAccountAsset: vi.fn(),
  createAccountIdentityDocument: vi.fn(),
  updateAccountIdentityDocument: vi.fn(),
  updateAccountPaymentDestination: vi.fn(),
  updateAccountPolicy: vi.fn(),
  updateClaimField: vi.fn(),
}))

vi.mock('./api.js', () => api)
vi.mock('./runtimeConfig.js', () => ({ WORKBENCH_URL: '/workbench/' }))

import App from './App.jsx'

function primaryAction({
  actionCode = 'claimant.continue_conversation',
  actionType = 'conversation',
  available = false,
  requiredInputs = [],
  revision = 1,
  targetRef = 'clm_ui_vp',
} = {}) {
  return {
    action_type: actionType,
    action_code: actionCode,
    action_id: `${actionCode}:${targetRef}`,
    target_ref: targetRef,
    available,
    required_inputs: requiredInputs,
    claim_revision: revision,
    registry_version: '1.0.0',
    visibility: 'claimant',
    execution_boundary:
      actionType === 'claim_creation'
        ? 'claimant_api'
        : actionType === 'external_service'
          ? 'external_service'
          : 'conversation',
    projection_version: 'v1',
  }
}

const initialClaim = {
  claim_id: 'clm_ui_vp',
  revision: 1,
  incident_type: 'home',
  form: {},
  contents_items: [],
  dynamic_form: null,
  customer_next_step: {
    status: 'describe_incident',
    summary: 'Describe what happened',
    required_items: [],
    can_resume: true,
  },
  primary_action: primaryAction(),
  created_at: '2026-09-14T01:00:00Z',
  updated_at: '2026-09-14T01:00:00Z',
  external_claim: null,
}

const claimantMessage = {
  message_id: 'msg_claimant',
  actor: 'claimant',
  content: { type: 'text', text: 'A pipe burst in the kitchen.' },
  created_at: '2026-09-10T01:00:00Z',
}

const agentMessage = {
  message_id: 'msg_agent',
  actor: 'agent',
  content: { type: 'text', text: 'Thanks. I need the incident time next.' },
  created_at: '2026-09-10T01:00:01Z',
}

function assistanceHandoff(status = 'queued') {
  return {
    handoff_id: 'hnd_customer_support',
    status,
    support_need: 'human_requested',
    summary: 'A Northwind support request has been queued with the details already provided.',
    created_at: '2026-09-14T01:01:00Z',
  }
}

function resolvedAssistanceHandoff() {
  return {
    handoff_id: 'hnd_customer_support',
    type: 'human_support',
    status: 'resolved',
    completed_at: '2026-09-14T01:05:00Z',
    customer_update: 'Staff assistance is complete. You can continue your claim.',
  }
}

function initialTurn() {
  return {
    claimant_message: claimantMessage,
    agent_message: agentMessage,
    form_changes: [],
    contents_item_changes: [],
    dynamic_form: null,
    claim_revision: 2,
    decision: { customer_next_step: initialClaim.customer_next_step },
    primary_action: primaryAction({ revision: 2 }),
  }
}

function deferredRequest() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function pausedClaim() {
  return {
    ...initialClaim,
    revision: 3,
    active_session_id: null,
    incomplete_context: { interrupted_at: '2026-09-16T01:05:00Z',
      resume_point: 'Describe what happened', follow_up_status: 'blocked' },
  }
}

async function startActiveClaim(user) {
  await user.type(screen.getByPlaceholderText('Tell us what happened…'), claimantMessage.content.text)
  await user.click(screen.getByRole('button', { name: 'Start claim' }))
  await screen.findByText(agentMessage.content.text)
}

function testAccount(customerId, displayName) {
  return { customer_id: customerId,
    profile: { display_name: displayName, email: `${customerId}@example.test`, phone: '' },
    preferences: { email: true, sms: false } }
}

function mockAuthenticatedAccounts(...accounts) {
  let authenticated = true
  api.hasClaimantAccessToken.mockImplementation(() => authenticated)
  api.setClaimantAccessToken.mockImplementation((token) => { authenticated = Boolean(token) })
  api.logoutClaimant.mockImplementation(() => { authenticated = false })
  accounts.forEach((account) => api.getAuthenticatedAccount.mockResolvedValueOnce(account))
  api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
}

function enableAuthenticatedImageAttachments() {
  api.hasClaimantAccessToken.mockReturnValue(true)
  api.getAuthenticatedAccount.mockResolvedValue({
    customer_id: 'cus_attachment_test',
    profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
    preferences: { email: true, sms: false },
  })
  api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
  api.getRuntimeCapabilities.mockResolvedValue({
    claim_types: ['motor', 'home', 'contents'],
    models: [{
      id: 'qwen-local',
      label: 'qwen3.8-27b',
      availability: 'available',
      image_input: true,
      document_input: true,
    }],
    default_model_profile_id: 'qwen-local',
  })
}

function realtimeChange(revision, resources = ['claim', 'messages']) {
  return realtimeChangeFor(initialClaim.claim_id, revision, resources)
}

function realtimeChangeFor(claimId, revision, resources = ['claim', 'messages']) {
  const eventId = `evt-${claimId}-${revision}-${resources.join('-')}`
  return {
    type: 'resources.changed',
    cursor: eventId,
    data: {
      event_id: eventId,
      claim_id: claimId,
      claim_revision: revision,
      resources,
    },
  }
}

function dynamicForm({ value = '8pm', valueState = 'proposed' } = {}) {
  return {
    selected_family: 'home',
    claim_revision: 2,
    requirements: {
      ready: false,
      current_action_total: 2,
      current_action_satisfied: 1,
      satisfied: ['incident.description'],
      next_required_item: 'incident.occurred_at',
      pending_later: ['property.address'],
      missing_required_now: ['incident.occurred_at'],
    },
    fields: [
      {
        field_code: 'incident.occurred_at',
        selection_state: 'required_now',
        value_state: valueState,
        reason: 'We need the time to place the incident in sequence.',
      },
    ],
    form: {
      'incident.occurred_at': {
        value,
        status: 'proposed',
        source: 'claimant',
      },
    },
  }
}

function readyDynamicForm() {
  return {
    selected_family: 'motor',
    claim_revision: 2,
    requirements: {
      ready: true,
      current_action_total: 9,
      current_action_satisfied: 9,
      satisfied: [
        'claim.product_family',
        'incident.description',
        'incident.injury_or_danger',
        'incident.occurred_at',
        'incident.location',
        'loss.description',
        'parties.other_parties',
        'vehicle.damage_description',
        'vehicle.drivable',
      ],
      next_required_item: null,
      pending_later: [],
      missing_required_now: [],
    },
    fields: [],
    form: {},
  }
}

describe('claimant intake projection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.requestId.mockImplementation((prefix) => `${prefix}-test`)
    globalThis.localStorage.clear()
    globalThis.sessionStorage.clear()
    globalThis.sessionStorage.setItem('northwind.anonymousSession', 'anonymous-session-test')
    globalThis.history.replaceState({}, '', '/')
    Object.defineProperty(globalThis.URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn((file) => `blob:app/${encodeURIComponent(file.name)}`),
    })
    Object.defineProperty(globalThis.URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    api.hasClaimantAccessToken.mockReturnValue(false)
    api.getRuntimeCapabilities.mockResolvedValue({
      claim_types: ['motor', 'home', 'contents'],
      models: [
        {
          id: 'qwen-local',
          label: 'qwen3.8-27b',
          availability: 'available',
          image_input: false,
          document_input: false,
        },
        {
          id: 'nowcoding-gpt55',
          label: 'gpt-5.5',
          availability: 'available',
          image_input: false,
          document_input: false,
        },
        {
          id: 'bedrock-nova2-lite',
          label: 'global.amazon.nova-2-lite-v1:0',
          availability: 'unavailable',
          image_input: true,
          document_input: false,
        },
        {
          id: 'google-gemini35-flash-lite',
          label: 'gemini-3.5-flash-lite',
          availability: 'available',
          image_input: true,
          document_input: true,
        },
      ],
      default_model_profile_id: 'qwen-local',
    })
    api.getClaimEvidence.mockResolvedValue({ items: [], revision: 1 })
    api.listAccountAssets.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.listAccountIdentityDocuments.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.listAccountPaymentDestinations.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.listAccountPolicies.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.listEvidenceHistory.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.listPaymentDestinations.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.streamRealtimeEvents.mockImplementation(() => new Promise(() => {}))
    api.createClaim.mockResolvedValue({
      claim: initialClaim,
      session: { session_id: 'ses_ui_vp', model_profile_id: 'qwen-local' },
    })
    api.pauseClaimSession.mockResolvedValue({
      claim: pausedClaim(),
      session: { session_id: 'ses_ui_vp', status: 'paused' },
    })
  })

  afterEach(() => {
    if (originalCreateObjectUrl) {
      Object.defineProperty(globalThis.URL, 'createObjectURL', originalCreateObjectUrl)
    } else {
      delete globalThis.URL.createObjectURL
    }
    if (originalRevokeObjectUrl) {
      Object.defineProperty(globalThis.URL, 'revokeObjectURL', originalRevokeObjectUrl)
    } else {
      delete globalThis.URL.revokeObjectURL
    }
  })

  it('shows the backend default model before creating a session', async () => {
    const user = userEvent.setup()
    render(<App />)

    const model = await screen.findByRole('button', { name: 'Model' })
    expect(model).toBeEnabled()
    expect(model).toHaveTextContent('qwen3.8-27b')
    expect(screen.queryByRole('button', { name: 'Claim type (optional)' })).not.toBeInTheDocument()

    await user.click(model)
    expect(screen.getByRole('listbox', { name: 'Model' })).toBeInTheDocument()
    expect(screen.getByRole('option', {
      name: /global\.amazon\.nova-2-lite-v1:0.*Unavailable/,
    })).toBeDisabled()
    await user.click(screen.getByRole('option', {
      name: 'gemini-3.5-flash-lite',
    }))
    expect(model).toHaveTextContent('gemini-3.5-flash-lite')

    await user.click(model)
    await user.click(screen.getByRole('option', { name: /^gpt-5\.5/ }))
    expect(model).toHaveTextContent('gpt-5.5')

    await waitFor(() => expect(model).toHaveFocus())
    await user.keyboard('{ArrowDown}')
    const selectedGpt = screen.getByRole('option', {
      name: 'gpt-5.5',
    })
    await waitFor(() => expect(selectedGpt).toHaveFocus())
    await user.keyboard('{Home}{Enter}')
    expect(model).toHaveTextContent('qwen3.8-27b')
    expect(screen.queryByRole('listbox', { name: 'Model' })).not.toBeInTheDocument()
  })

  it('renders directional chat bubbles without duplicate claimant time metadata', async () => {
    const user = userEvent.setup()
    api.submitClaimMessage.mockResolvedValue(initialTurn())

    const { container } = render(<App />)
    const app = container.querySelector('.customer-app')
    expect(app).toHaveClass('entry-shell')
    expect(app).not.toHaveClass('workspace-shell')
    await user.type(
      screen.getByPlaceholderText('Tell us what happened…'),
      claimantMessage.content.text,
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)

    expect(app).toHaveClass('workspace-shell')
    expect(app).not.toHaveClass('entry-shell')

    const claimantArticle = screen.getByText(claimantMessage.content.text).closest('.msg-user')
    const agentArticle = screen.getByText(agentMessage.content.text).closest('.msg-agent')

    expect(claimantArticle.querySelector('.chat-message-row > .user-message-body + .claimant-message-avatar'))
      .toHaveTextContent('YU')
    expect(claimantArticle.querySelector('.user-bubble')).toHaveClass('chat-bubble')
    expect(claimantArticle.querySelector('time.message-timestamp')).not.toBeInTheDocument()
    const agentRow = agentArticle.querySelector('.chat-message-row')
    expect(agentRow.querySelector('.agent-avatar')).toHaveTextContent('N')
    expect(agentRow.querySelector('.agent-body')).toBeInTheDocument()
    expect(agentArticle.querySelector('.agent-bubble')).toHaveClass('chat-bubble')
    expect(agentArticle.querySelector('time.message-timestamp'))
      .toHaveAttribute('datetime', agentMessage.created_at)
    expect(container.querySelectorAll('.message-list time.message-timestamp')).toHaveLength(1)
  })

  it('shows one truthful Agent placeholder for the first claimant turn', async () => {
    const user = userEvent.setup()
    let pushLiveUpdate
    let resolveTurn
    api.streamRealtimeEvents.mockImplementation(({ onEvent }) => {
      pushLiveUpdate = onEvent
      return new Promise(() => {})
    })
    api.submitClaimMessage.mockReturnValue(new Promise((resolve) => {
      resolveTurn = resolve
    }))

    render(<App />)
    await user.type(
      screen.getByPlaceholderText('Tell us what happened…'),
      'My car was rear-ended this morning.',
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    expect(await screen.findByLabelText('Message sending')).toHaveTextContent(
      'My car was rear-ended this morning.',
    )
    expect(screen.getAllByLabelText('Claims assistant is working')).toHaveLength(1)
    await waitFor(() => expect(pushLiveUpdate).toBeTypeOf('function'))
    await act(async () => pushLiveUpdate({
      type: 'agent.turn.progress',
      cursor: 'cursor-progress-3',
      data: {
        event_id: 'evt-progress-3',
        claim_id: initialClaim.claim_id,
        turn_id: 'message-test',
        session_id: 'ses_ui_vp',
        stage: 'knowledge.querying',
        state: 'running',
        ordinal: 3,
      },
    }))
    expect(screen.getByText('Checking relevant policy information', {
      selector: '[role="status"]',
    })).toBeInTheDocument()

    await act(async () => resolveTurn(initialTurn()))
    expect(await screen.findByText(agentMessage.content.text)).toBeVisible()
    const activity = screen.getByRole('button', {
      name: 'Checked relevant policy information',
    })
    expect(activity).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByLabelText('Claims assistant is working')).not.toBeInTheDocument()
  })

  it('does not duplicate messages when realtime readback finishes before the POST response', async () => {
    const user = userEvent.setup()
    api.requestId.mockImplementation((prefix) => `${prefix}-test`)
    let pushLiveUpdate
    let resolveTurn
    api.streamRealtimeEvents.mockImplementation(({ onEvent }) => {
      pushLiveUpdate = onEvent
      return new Promise(() => {})
    })
    api.submitClaimMessage.mockReturnValue(new Promise((resolve) => {
      resolveTurn = resolve
    }))
    api.getClaim.mockResolvedValue({
      ...initialClaim,
      revision: 2,
      primary_action: primaryAction({ revision: 2 }),
    })
    api.getClaimMessages.mockResolvedValue({ items: [
      { ...claimantMessage, client_message_id: 'message-test' }, agentMessage,
    ] })

    render(<App />)
    await user.type(
      screen.getByPlaceholderText('Tell us what happened…'),
      claimantMessage.content.text,
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await waitFor(() => expect(pushLiveUpdate).toBeTypeOf('function'))

    await act(async () => pushLiveUpdate(realtimeChange(2, ['claim', 'messages'])))
    await waitFor(() => expect(screen.queryByLabelText('Message sending')).not.toBeInTheDocument())
    await act(async () => resolveTurn(initialTurn()))

    expect(screen.getAllByText(claimantMessage.content.text)).toHaveLength(1)
    expect(screen.getAllByText(agentMessage.content.text)).toHaveLength(1)
    expect(screen.queryByLabelText('Claims assistant is working')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Message sending')).not.toBeInTheDocument()
  })

  it('returns from login to an empty local workspace without creating a Claim', async () => {
    const user = userEvent.setup()
    api.loginClaimant.mockResolvedValue({ access_token: 'claimant-token' })
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    await user.type(screen.getByLabelText('Email address'), 'test@example.test')
    await user.type(screen.getByLabelText('Password'), 'correct-horse')
    await user.click(screen.getAllByRole('button', { name: 'Log in' }).at(-1))

    expect(await screen.findByPlaceholderText('Tell us what happened…')).toBeVisible()
    expect(api.createClaim).not.toHaveBeenCalled()
    expect(api.promoteAnonymousClaim).not.toHaveBeenCalled()
    expect(screen.queryByText(initialClaim.claim_id)).not.toBeInTheDocument()
  })

  it('returns from registration to an empty local workspace without creating a Claim', async () => {
    const user = userEvent.setup()
    api.registerClaimant.mockResolvedValue({ access_token: 'claimant-token' })
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Sign up' }))
    await user.type(screen.getByLabelText('Your name'), 'Test claimant')
    await user.type(screen.getByLabelText('Email address'), 'test@example.test')
    await user.type(screen.getByLabelText('Password'), 'correct-horse')
    await user.type(screen.getByLabelText('Confirm password'), 'correct-horse')
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByPlaceholderText('Tell us what happened…')).toBeVisible()
    expect(api.createClaim).not.toHaveBeenCalled()
    expect(api.promoteAnonymousClaim).not.toHaveBeenCalled()
    expect(screen.queryByText(initialClaim.claim_id)).not.toBeInTheDocument()
  })

  it('keeps registration content on the document scroll surface', async () => {
    const user = userEvent.setup()

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Sign up' }))

    const authPage = screen.getByRole('main')
    const card = authPage.querySelector('.login-card')
    expect(card).not.toBeNull()
    expect(getComputedStyle(authPage).overflowY).not.toBe('hidden')
    expect(getComputedStyle(card).maxHeight).toBe('none')
    expect(getComputedStyle(card).overflowY).toBe('visible')

    await user.click(screen.getByRole('button', { name: 'Start a claim without logging in' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Start your insurance claim' })).toBeVisible()
  })

  it('reloads the published model catalogue after login when the initial request was unauthorized', async () => {
    const user = userEvent.setup()
    api.getRuntimeCapabilities.mockRejectedValueOnce(new api.ApiRequestError('Sign in again.'))
      .mockResolvedValueOnce({
        default_model_profile_id: 'openrouter-gpt4o-mini',
        models: [{ id: 'openrouter-gpt4o-mini', label: 'openai/gpt-4o-mini', availability: 'available' }],
      })
    api.loginClaimant.mockResolvedValue({ access_token: 'claimant-token' })
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'QA claimant', email: 'qa@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    render(<App />)
    await waitFor(() => expect(api.getRuntimeCapabilities).toHaveBeenCalledTimes(1))
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    await user.type(screen.getByLabelText('Email address'), 'qa@example.test')
    await user.type(screen.getByLabelText('Password'), 'Synthetic-QA-Password!')
    await user.click(screen.getAllByRole('button', { name: 'Log in' }).at(-1))
    expect(await screen.findByText('openai/gpt-4o-mini')).toBeVisible()
    expect(api.getRuntimeCapabilities).toHaveBeenCalledTimes(2)
  })

  it('keeps account actions and the composer without exposing the legacy form route', async () => {
    globalThis.history.replaceState({}, '', '/claim-form')
    const { container } = render(<App />)

    const header = container.querySelector('.product-header')
    expect(header).toContainElement(screen.getByRole('button', { name: 'Log in' }))
    expect(header).toContainElement(screen.getByRole('button', { name: 'Sign up' }))

    const composer = container.querySelector('.claim-starter')
    const composerInput = screen.getByPlaceholderText('Tell us what happened…')
    expect(composer).toHaveAttribute('aria-label', 'Start a claim')
    expect(composer.querySelector('h2')).not.toBeInTheDocument()
    expect(composer).toContainElement(composerInput)
    const processLink = screen.getByRole('button', { name: 'How does the claim process work?' })
    expect(composer.compareDocumentPosition(processLink) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Use the traditional web form' })).not.toBeInTheDocument()
    await waitFor(() => expect(globalThis.location.pathname).toBe('/'))
  })

  it('opens the authenticated Profile deep link and replaces edits with the API projection', async () => {
    const user = userEvent.setup()
    const initialAccount = {
      profile: {
        display_name: 'Iris Zhang',
        legal_name: 'Iris Zhang',
        preferred_name: null,
        email: 'iris@gmail.com',
        phone: '+64 21 555 123',
      },
      preferences: { email: true, sms: false },
    }
    const updatedAccount = {
      ...initialAccount,
      profile: { ...initialAccount.profile, display_name: 'Iris', preferred_name: 'Iris' },
    }
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue(initialAccount)
    api.updateAccountProfile.mockResolvedValue(updatedAccount)
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    globalThis.history.replaceState({}, '', '/profile/personal-details')

    render(<App />)

    expect(await screen.findByRole('region', { name: 'Personal details' })).toBeInTheDocument()
    expect(globalThis.location.pathname).toBe('/profile/personal-details')
    expect(screen.queryByRole('button', { name: 'Back to claims' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument()
    expect(screen.getByText('i•••@gmail.com')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Edit profile' }))
    await user.clear(screen.getByLabelText('Preferred name'))
    await user.type(screen.getByLabelText('Preferred name'), 'Iris')
    await user.click(screen.getByRole('button', { name: 'Save profile' }))

    expect(api.updateAccountProfile).toHaveBeenCalledWith({ preferred_name: 'Iris' })
    expect(await screen.findByText('Iris', { selector: '.profile-header-copy > strong' })).toBeInTheDocument()
    expect(screen.getByText('Iris Zhang', { selector: '.profile-summary-row > dd' })).toBeInTheDocument()
    expect(api.createClaim).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Back' }))
    expect(await screen.findByPlaceholderText('Tell us what happened…')).toBeVisible()
    expect(globalThis.location.pathname).toBe('/')
  })

  it('reloads a stale Profile revision, keeps the draft, and retries only after review', async () => {
    const user = userEvent.setup()
    const initialAccount = {
      customer_id: 'cus_profile_conflict',
      revision: 3,
      profile: {
        display_name: 'Iris',
        legal_name: 'Iris Zhang',
        preferred_name: 'Iris',
        email: 'iris@gmail.com',
        phone: '+64 21 555 123',
      },
      preferences: { email: true, sms: false },
    }
    const latestAccount = {
      ...initialAccount,
      revision: 4,
      profile: { ...initialAccount.profile, display_name: 'Shared saved name', preferred_name: 'Shared saved name' },
    }
    const retriedAccount = {
      ...latestAccount,
      revision: 5,
      profile: { ...latestAccount.profile, display_name: 'Iris draft', preferred_name: 'Iris draft' },
    }
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount
      .mockResolvedValueOnce(initialAccount)
      .mockResolvedValueOnce(latestAccount)
    api.updateAccountProfile
      .mockRejectedValueOnce({ code: 'REVISION_CONFLICT', status: 409 })
      .mockResolvedValueOnce(retriedAccount)
    globalThis.history.replaceState({}, '', '/profile/personal-details')

    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Edit profile' }))
    const preferredName = screen.getByLabelText('Preferred name')
    await user.clear(preferredName)
    await user.type(preferredName, 'Iris draft')
    await user.click(screen.getByRole('button', { name: 'Save profile' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('kept your draft')
    expect(preferredName).toHaveValue('Iris draft')
    expect(screen.getByText('Shared saved name', { selector: '.profile-header-copy > strong' })).toBeInTheDocument()
    expect(api.updateAccountProfile).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'Save profile' }))

    expect(api.updateAccountProfile).toHaveBeenNthCalledWith(2, { preferred_name: 'Iris draft' }, 4)
    expect(await screen.findByText('Iris draft', { selector: '.profile-header-copy > strong' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Preferred name')).not.toBeInTheDocument()
  })

  it('opens the Policies route and restores Profile categories on popstate', async () => {
    const user = userEvent.setup()
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Iris Zhang', email: 'iris@gmail.com', phone: '+64 21 555 123' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.listAccountAssets.mockResolvedValue({
      items: [{
        asset_id: 'ase_11111111111111111111',
        asset_type: 'vehicle',
        display_name: 'Family SUV',
        details: { registration: 'ABC123', make: 'Toyota', model: 'RAV4', year: 2022 },
        revision: 1,
        active: true,
        created_at: '2026-09-12T01:00:00Z',
        updated_at: '2026-09-17T01:00:00Z',
      }],
      page: { next_cursor: null },
    })
    api.listAccountPolicies.mockResolvedValue({
      items: [
        { policy_id: 'pol_11111111111111111111', policy_number: 'MOTOR-1234', revision: 1 },
        { policy_id: 'pol_22222222222222222222', policy_number: 'HOME-5678', revision: 1 },
      ],
      page: { next_cursor: null },
    })
    globalThis.history.replaceState({}, '', '/profile/policies')

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Policies' })).toBeInTheDocument()
    expect(globalThis.location.pathname).toBe('/profile/policies')
    expect(screen.getAllByRole('button', { name: 'Policies' })).toHaveLength(2)
    expect(await screen.findByText('••••1234')).toBeInTheDocument()
    expect(screen.getByText('••••5678')).toBeInTheDocument()
    expect(api.listAccountPolicies).toHaveBeenCalled()

    await user.click(screen.getAllByRole('button', { name: 'Insured assets' })[0])
    expect(await screen.findByRole('heading', { name: 'Insured assets' })).toBeInTheDocument()
    expect(globalThis.location.pathname).toBe('/profile/insured-assets')
    await user.click(screen.getByRole('button', { name: /^Vehicles/ }))
    expect(await screen.findByRole('button', { name: 'Open Family SUV' })).toBeInTheDocument()
    expect(api.listAccountAssets).toHaveBeenCalled()

    await user.click(screen.getAllByRole('button', { name: 'Payment details' })[0])
    expect(await screen.findByRole('heading', { name: 'Payment details' })).toBeInTheDocument()
    expect(globalThis.location.pathname).toBe('/profile/payment-details')

    await user.click(screen.getAllByRole('button', { name: 'Identity & verification' })[0])
    expect(await screen.findByText('No identity documents saved.')).toBeInTheDocument()
    expect(globalThis.location.pathname).toBe('/profile/identity-verification')
    expect(api.listAccountIdentityDocuments).toHaveBeenCalled()

    globalThis.history.replaceState({}, '', '/profile/insured-assets')
    globalThis.dispatchEvent(new PopStateEvent('popstate'))

    expect(await screen.findByRole('heading', { name: 'Insured assets' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Payment details' })).not.toBeInTheDocument()
  })

  it('guards an unauthenticated Profile deep link with the existing login route', async () => {
    globalThis.history.replaceState({}, '', '/profile/identity-verification')

    render(<App />)

    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    await waitFor(() => expect(globalThis.location.pathname).toBe('/auth/login'))
    expect(api.getAuthenticatedAccount).not.toHaveBeenCalled()
  })

  it.each([
    '/account/claims',
    '/account/claims/clm_guarded',
    '/account/claims/clm_guarded/evidence',
    '/files',
  ])('guards the unauthenticated protected route %s without leaving an account-loading shell', async (path) => {
    globalThis.history.replaceState({}, '', path)

    render(<App />)

    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(screen.queryByText('Checking your account…')).not.toBeInTheDocument()
    await waitFor(() => expect(globalThis.location.pathname).toBe('/auth/login'))
    expect(api.getAuthenticatedAccount).not.toHaveBeenCalled()
  })

  it('uses the configured Workbench route instead of a loopback-only employee link', () => {
    globalThis.history.replaceState({}, '', '/auth/login')

    render(<App />)

    expect(screen.getByRole('link', { name: 'Employee access' })).toHaveAttribute('href', '/workbench/')
  })

  it('loads and saves all five Claim auto-fill choices from the Account projection', async () => {
    const user = userEvent.setup()
    const initialAccount = {
      customer_id: 'cus_auto_fill',
      revision: 4,
      profile: { display_name: 'Iris Zhang', email: 'iris@example.test', phone: '' },
      preferences: { email: true, sms: false },
      claim_auto_fill_preferences: {
        personal_details: false,
        policy_number: true,
        saved_assets: false,
        payment_details: false,
        identity_information: false,
      },
    }
    const updatedAccount = {
      ...initialAccount,
      revision: 5,
      claim_auto_fill_preferences: {
        ...initialAccount.claim_auto_fill_preferences,
        saved_assets: true,
      },
    }
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue(initialAccount)
    api.updateClaimAutoFillPreferences.mockResolvedValue(updatedAccount)
    globalThis.history.replaceState({}, '', '/profile/claim-auto-fill')

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Claim auto-fill' })).toBeInTheDocument()
    expect(screen.queryByText(/could not load these choices from your account/i)).not.toBeInTheDocument()
    expect(screen.getAllByRole('combobox')).toHaveLength(5)
    expect(screen.getByRole('combobox', { name: 'Policy number' })).toHaveValue('show')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Saved assets' }), 'show')
    await user.click(screen.getByRole('button', { name: 'Save Claim auto-fill choices' }))

    expect(api.updateClaimAutoFillPreferences).toHaveBeenCalledWith({
      personal_details: false,
      policy_number: true,
      saved_assets: true,
      payment_details: false,
      identity_information: false,
    }, 4)
    expect(await screen.findByText(/choices were updated/i)).toBeInTheDocument()
  })

  it('shows one server-confirmed delivery failure with retry guidance', async () => {
    const user = userEvent.setup()
    api.submitClaimMessage.mockRejectedValue(Object.assign(
      new api.ApiRequestError('The model service is temporarily unavailable. The claim is unchanged.'),
      { code: 'DEPENDENCY_UNAVAILABLE', status: 503, retryable: true },
    ))

    const { container } = render(<App />)
    const input = screen.getByPlaceholderText('Tell us what happened…')
    await user.type(input, 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    expect(api.createClaim).toHaveBeenCalledWith(expect.not.objectContaining({ incidentType: expect.anything() }))

    const failure = await screen.findByText(
      'The model service is temporarily unavailable. The claim is unchanged. Try the message again in a moment.',
    )
    expect(failure).toBeInTheDocument()
    expect(screen.getByText('Not sent')).toBeInTheDocument()
    expect(failure.closest('[role="alert"]')).toHaveClass('is-failed')
    expect(container.querySelector('.workspace-composer [role="alert"]')).not.toBeInTheDocument()
    expect(screen.queryByText('We could not confirm delivery. Please try again.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry message' })).toBeInTheDocument()
  })

  it('keeps third-party support out of chat and reopens it from What to provide', async () => {
    const user = userEvent.setup()
    api.createClaim.mockResolvedValue({
      claim: {
        ...initialClaim,
        external_capabilities: [
          {
            service_identity: 'vehicle-assessment',
            service_name: 'Vehicle damage assessment',
            purpose: 'Assess visible vehicle damage.',
            result_semantics: 'An assessment supports review; it does not approve repairs.',
            official_phone: '0800 555 010',
          },
          {
            service_identity: 'vehicle-recovery',
            service_name: 'Vehicle recovery',
            purpose: 'Arrange recovery when a vehicle cannot be driven safely.',
            result_semantics: 'Availability depends on location and provider confirmation.',
          },
        ],
      },
      session: { session_id: 'ses_ui_vp', model_profile_id: 'qwen-local' },
    })
    api.submitClaimMessage.mockResolvedValue(initialTurn())

    const { container } = render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'My car was damaged.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    await screen.findByText(agentMessage.content.text)
    expect(screen.queryByRole('dialog', { name: 'Third-party services' })).not.toBeInTheDocument()
    expect(container.querySelector('.message-list .service-capability-list')).not.toBeInTheDocument()
    expect(container.querySelector('.message-list .external-capabilities-trigger')).not.toBeInTheDocument()

    const documentsTab = screen.getByRole('tab', { name: 'What to provide' })
    await user.click(documentsTab)
    const trigger = screen.getByRole('button', { name: /Use a third-party service/ })
    expect(trigger.closest('[role="tabpanel"]')).toHaveAccessibleName('What to provide')
    expect(trigger).toHaveTextContent('View 2 options')
    await user.click(trigger)
    expect(await screen.findByRole('dialog', { name: 'Third-party services' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Close third-party services' }))
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('keeps third-party support closed when reopening a claim from conversation history', async () => {
    const user = userEvent.setup()
    const resumedClaim = {
      ...initialClaim,
      external_capabilities: [
        {
          service_identity: 'vehicle-recovery',
          service_name: 'Vehicle recovery',
          purpose: 'Arrange recovery when a vehicle cannot be driven safely.',
          result_semantics: 'Availability depends on location and provider confirmation.',
        },
      ],
    }
    globalThis.sessionStorage.setItem(
      'northwind.anonymousConversationHistory.v1.anonymous-session-test',
      JSON.stringify([{ ...resumedClaim, can_resume: true }]),
    )
    api.getClaim.mockResolvedValue(resumedClaim)
    api.getClaimMessages.mockResolvedValue({ items: [claimantMessage, agentMessage] })
    api.resumeClaimSession.mockResolvedValue({
      session_id: 'ses_resumed_with_services',
      model_profile_id: 'qwen-local',
      started_at: '2026-09-16T01:06:00Z',
      resume: {
        summary: 'A pipe burst in the kitchen.',
        unresolved_questions: [],
        pending_items: [],
        prior_commitments: [],
        customer_next_step: resumedClaim.customer_next_step,
      },
    })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(await screen.findByRole('button', { name: /Open Home claim/ }))

    expect(await screen.findByText(agentMessage.content.text)).toBeVisible()
    expect(screen.queryByRole('dialog', { name: 'Third-party services' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'What to provide' }))
    await user.click(screen.getByRole('button', { name: /Use a third-party service/ }))
    expect(await screen.findByRole('dialog', { name: 'Third-party services' })).toBeVisible()
  })

  it.each([false, true])('retries a saved unanswered message with its original identity and a new request key (safety notice: %s)', async (hasSafetyNotice) => {
    const user = userEvent.setup()
    let requestSequence = 0
    api.requestId.mockImplementation((prefix) => `${prefix}-${++requestSequence}`)
    const recovery = {
      rule_id: 'claimant_turn.model_dependency_failure',
      claimant_projection: 'Your message is saved, but I could not respond just now. You can try again.',
      resume_triggers: ['claimant_reply', 'explicit_retry_request'],
      resume_entrypoint: 'submit_message',
      continuation: 'runtime.fail_safe',
    }
    api.submitClaimMessage.mockImplementationOnce(async (request) => ({
      ...initialTurn(),
      claimant_message: { ...claimantMessage, client_message_id: request.clientMessageId, recovery },
      agent_message: hasSafetyNotice ? {
        ...agentMessage,
        message_id: 'msg-safety-recovery',
        content: { text: 'If anyone is in immediate danger, call 111. Northwind support has been notified and your report has been saved.' },
        in_reply_to: claimantMessage.message_id,
        recovery,
      } : null,
      decision: null,
      recovery,
    })).mockImplementationOnce(async (request) => ({
      ...initialTurn(),
      claim_revision: 3,
      claimant_message: { ...claimantMessage, client_message_id: request.clientMessageId },
      agent_message: { ...agentMessage, in_reply_to: claimantMessage.message_id },
    }))

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), claimantMessage.content.text)
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    expect(await screen.findByText(recovery.claimant_projection)).toBeVisible()
    expect(screen.queryByText('Not sent')).not.toBeInTheDocument()
    if (hasSafetyNotice) {
      expect(screen.getByText(/Northwind support has been notified/)).toBeVisible()
    }
    await user.click(screen.getByRole('button', { name: 'Retry response' }))
    expect(await screen.findByText(agentMessage.content.text)).toBeVisible()
    const [first, retried] = api.submitClaimMessage.mock.calls.map(([request]) => request)
    expect(retried.clientMessageId).toBe(first.clientMessageId)
    expect(retried.idempotencyKey).not.toBe(first.idempotencyKey)
    expect(screen.getAllByText(claimantMessage.content.text)).toHaveLength(1)
    expect(screen.queryByRole('button', { name: 'Retry response' })).not.toBeInTheDocument()
  })

  it('returns to Claim history from Claim tools without dropping the active conversation', async () => {
    const user = userEvent.setup()
    api.submitClaimMessage.mockResolvedValue(initialTurn())

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)

    expect(screen.queryByRole('button', { name: 'Back to Claim history' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Claim history' }))

    expect(screen.getByRole('heading', { name: 'Claim history' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Back to conversation' }))
    expect(screen.getByText(agentMessage.content.text)).toBeInTheDocument()
    expect(screen.getByText(initialClaim.claim_id)).toBeInTheDocument()
  })

  it('opens Profile as a standalone page and returns to the loaded conversation', async () => {
    const user = userEvent.setup()
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: {
        display_name: 'Alexandria Montgomery-Sinclair',
        email: 'alexandria.montgomery-sinclair@example.invalid',
        phone: '',
      },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.submitClaimMessage.mockResolvedValue(initialTurn())

    const { container } = render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)

    const profileButton = container.querySelector('.intake-profile')
    expect(profileButton).toHaveAccessibleName(
      'Open Profile for Alexandria Montgomery-Sinclair (alexandria.montgomery-sinclair@example.invalid)',
    )
    const profileName = container.querySelector('.intake-profile-name')
    expect(profileName).toHaveAttribute('title', 'Alexandria Montgomery-Sinclair')
    expect(profileName).toHaveTextContent('Alexandria Montgomery-Sinclair')
    expect(profileName.querySelector('.intake-profile-name-start')).toHaveTextContent('Alexandria Montgomery-Si')
    expect(profileName.querySelector('.intake-profile-name-end')).toHaveTextContent('nclair')
    expect(container.querySelector('.intake-profile-email')).toHaveAttribute(
      'title',
      'alexandria.montgomery-sinclair@example.invalid',
    )
    expect(container.querySelector('.intake-profile-email')).toHaveTextContent('alexandr…invalid')
    await user.click(profileButton)

    expect(await screen.findByRole('region', { name: 'Personal details' })).toBeInTheDocument()
    expect(globalThis.location.pathname).toBe('/profile')
    expect(container.querySelector('.profile-page .user-profile')).toBeInTheDocument()
    expect(container.querySelector('.workspace-utility-page')).not.toBeInTheDocument()
    expect(screen.queryByText(initialClaim.claim_id)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Back' }))

    expect(await screen.findByText(agentMessage.content.text)).toBeVisible()
    expect(screen.getByText(initialClaim.claim_id)).toBeInTheDocument()
    expect(globalThis.location.pathname).toBe(`/claims/${initialClaim.claim_id}`)
    expect(api.createClaim).toHaveBeenCalledTimes(1)
    expect(api.resumeClaimSession).not.toHaveBeenCalled()
  })

  it('returns to the start page from the Claim header without dropping the conversation', async () => {
    const user = userEvent.setup()
    api.submitClaimMessage.mockResolvedValue(initialTurn())

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)

    const brand = screen.getByLabelText('Northwind home')
    const backButton = screen.getByRole('button', { name: 'Back to start' })
    expect(backButton.previousElementSibling).toBe(brand)

    await user.click(backButton)

    expect(screen.getByRole('heading', { level: 1, name: 'Start your insurance claim' })).toBeVisible()
    expect(screen.getByText(/Understand insurance/)).not.toHaveRole('heading')
    expect(globalThis.location.pathname).toBe('/')
    expect(screen.queryByText(agentMessage.content.text)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    const activeConversation = screen.getByRole('button', { name: /Open Home claim/ })
    expect(activeConversation).toHaveAttribute('aria-current', 'page')
    await user.click(activeConversation)

    expect(await screen.findByText(agentMessage.content.text)).toBeVisible()
    expect(globalThis.location.pathname).toBe(`/claims/${initialClaim.claim_id}`)
    expect(api.createClaim).toHaveBeenCalledTimes(1)
    expect(api.resumeClaimSession).not.toHaveBeenCalled()
  })

  it('scrolls to the latest messages after the claimant sends from earlier in the conversation', async () => {
    const user = userEvent.setup()
    api.submitClaimMessage
      .mockResolvedValueOnce(initialTurn())
      .mockResolvedValueOnce({
        ...initialTurn(),
        claimant_message: {
          ...claimantMessage,
          message_id: 'msg_claimant_follow_up',
          content: { type: 'text', text: 'It happened at 8pm.' },
        },
        agent_message: {
          ...agentMessage,
          message_id: 'msg_agent_follow_up',
          content: { type: 'text', text: 'Thank you. I have recorded the incident time.' },
        },
        claim_revision: 3,
      })

    const { container } = render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)

    const messageList = container.querySelector('.message-list')
    Object.defineProperties(messageList, {
      clientHeight: { configurable: true, value: 240 },
      scrollHeight: { configurable: true, value: 960 },
    })
    messageList.scrollTop = 0
    fireEvent.scroll(messageList)

    await user.type(screen.getByPlaceholderText('Write the details you know...'), 'It happened at 8pm.')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Thank you. I have recorded the incident time.')).toBeVisible()
    await waitFor(() => expect(messageList.scrollTop).toBe(960))
  })

  it('keeps the latest message visible when an attachment warning grows the composer', async () => {
    const user = userEvent.setup()
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.requestEvidenceUpload.mockReturnValue(new Promise(() => {}))

    const { container } = render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)

    const messageList = container.querySelector('.message-list')
    Object.defineProperties(messageList, {
      clientHeight: { configurable: true, value: 240 },
      scrollHeight: { configurable: true, value: 960 },
    })
    messageList.scrollTop = 720
    fireEvent.scroll(messageList)
    messageList.scrollTop = 0

    await user.upload(
      container.querySelector('.workspace-composer input[type="file"]'),
      new File(['image'], 'blocked-image.png', { type: 'image/png' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent('This model cannot process images.')
    await waitFor(() => expect(messageList.scrollTop).toBe(960))
  })

  it('replaces Staff assistance with a waiting status and prevents duplicate requests', async () => {
    const user = userEvent.setup()
    let resolveSupport
    api.submitClaimMessage.mockResolvedValue({
      ...initialTurn(),
      claim_revision: 2,
      current_claim_revision: 3,
      primary_action: primaryAction({ revision: 3 }),
    })
    api.requestHumanSupport.mockImplementation(() => new Promise((resolve) => {
      resolveSupport = resolve
    }))

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)

    await user.click(screen.getByRole('button', { name: 'Staff assistance' }))

    expect(await screen.findByRole('status', { name: /Waiting for staff/ })).toBeInTheDocument()
    expect(screen.getByText(
      /Your request has been sent\. You can continue adding information while you wait\./,
    )).toBeInTheDocument()
    const progress = screen.getByRole('button', { name: /Claim progress:/i })
    expect(progress).not.toHaveTextContent('Staff assisting')
    expect(progress).not.toHaveTextContent('A Northwind staff member is now assisting you.')
    expect(progress).not.toHaveTextContent('A Northwind support request has been queued')
    expect(screen.queryByRole('button', { name: 'Staff assistance' })).not.toBeInTheDocument()
    expect(api.requestHumanSupport).toHaveBeenCalledTimes(1)
    expect(api.requestHumanSupport).toHaveBeenCalledWith(expect.objectContaining({ revision: 3 }))

    await act(async () => resolveSupport({
      revision: 3,
      handoff: assistanceHandoff(),
      customer_next_step: {
        status: 'human_support_queued',
        summary: 'A Northwind support request has been queued.',
        responsible_party: 'claims_professional',
      },
    }))

    expect(await screen.findByRole('status', { name: /Waiting for staff/ })).toBeInTheDocument()
    expect(screen.queryByText('Staff assistance requested')).not.toBeInTheDocument()
    expect(api.requestHumanSupport).toHaveBeenCalledWith(expect.objectContaining({
      claimId: initialClaim.claim_id,
      revision: 3,
    }))
    expect(initialClaim.external_claim).toBeNull()
  })

  it('keeps a queued handoff stale until reconnect installs the authoritative accepted projection', async () => {
    const user = userEvent.setup()
    let firstOnEvent
    let finishFirstStream
    let streamAttempt = 0
    let replacementOpened = false

    api.streamRealtimeEvents.mockImplementation(({ onEvent, onOpen, signal }) => {
      streamAttempt += 1
      if (streamAttempt === 1) {
        firstOnEvent = onEvent
        return new Promise((resolve) => {
          finishFirstStream = resolve
          signal.addEventListener('abort', resolve, { once: true })
        })
      }

      replacementOpened = true
      return (async () => {
        await onOpen?.()
        await new Promise((resolve) => {
          signal.addEventListener('abort', resolve, { once: true })
        })
      })()
    })
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.requestHumanSupport.mockResolvedValue({
      revision: 3,
      handoff: assistanceHandoff(),
      customer_next_step: {
        status: 'human_support_queued',
        summary: 'A Northwind support request has been queued.',
        responsible_party: 'claims_professional',
      },
    })

    const { unmount } = render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    await user.click(screen.getByRole('button', { name: 'Staff assistance' }))
    expect(await screen.findByRole('status', { name: /Waiting for staff/ })).toBeInTheDocument()
    await waitFor(() => expect(firstOnEvent).toBeTypeOf('function'))

    api.getClaim.mockResolvedValueOnce({
      ...initialClaim,
      revision: 4,
      handoff: assistanceHandoff('accepted'),
      customer_next_step: {
        status: 'human_support_in_progress',
        summary: 'A Northwind staff member is now assisting you.',
        responsible_party: 'claims_professional',
      },
    })
    api.getClaimMessages.mockResolvedValueOnce({
      items: [claimantMessage, agentMessage],
    })

    await act(async () => {
      await firstOnEvent({
        type: 'resync_required',
        cursor: null,
        data: { reason: 'replay_gap' },
      })
    })
    expect(screen.getByRole('status', {
      name: /Live updates need to be resynchronised\. Some claim information may be out of date/i,
    })).toBeInTheDocument()
    expect(screen.getByRole('status', { name: /Waiting for staff/ })).toBeInTheDocument()

    await act(async () => { finishFirstStream() })
    await waitFor(() => expect(replacementOpened).toBe(true))

    expect(await screen.findByRole('status', { name: /Staff assistance accepted/ })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('status', {
      name: /Live updates need to be resynchronised/i,
    })).not.toBeInTheDocument())
    expect(screen.getByText(/Northwind has accepted your assistance request\./)).toBeInTheDocument()
    expect(api.requestHumanSupport).toHaveBeenCalledTimes(1)
    expect(api.createClaim).toHaveBeenCalledTimes(1)

    unmount()
  })

  it('renders staff, response-needed, reply-sent, and completed assistance states', async () => {
    const user = userEvent.setup()
    let pushLiveUpdate
    let resolveReply
    const staffMessage = {
      message_id: 'msg_staff',
      actor: 'staff',
      visibility: 'shared',
      content: { type: 'text', text: 'Could you confirm whether the kitchen is still usable?' },
      created_at: '2026-09-14T01:03:00Z',
    }
    const claimantReply = {
      message_id: 'msg_claimant_reply',
      actor: 'claimant',
      visibility: 'shared',
      content: { type: 'text', text: 'Yes, the kitchen is still usable.' },
      created_at: '2026-09-14T01:04:00Z',
    }
    const queuedClaimantMessage = {
      message_id: 'msg_while_waiting',
      actor: 'claimant',
      visibility: 'shared',
      content: { type: 'text', text: 'I can provide more details while I wait.' },
      created_at: '2026-09-14T01:02:00Z',
    }
    api.streamRealtimeEvents.mockImplementation(({ onEvent }) => {
      pushLiveUpdate = onEvent
      return new Promise(() => {})
    })
    api.submitClaimMessage
      .mockResolvedValueOnce(initialTurn())
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveReply = resolve
      }))
    api.requestHumanSupport.mockResolvedValue({
      revision: 3,
      handoff: assistanceHandoff(),
      customer_next_step: {
        status: 'human_support_queued',
        summary: 'A Northwind support request has been queued.',
        responsible_party: 'claims_professional',
      },
    })

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    await user.click(screen.getByRole('button', { name: 'Staff assistance' }))
    await screen.findByRole('status', { name: /Waiting for staff/ })
    await waitFor(() => expect(pushLiveUpdate).toBeTypeOf('function'))

    api.getClaim.mockResolvedValueOnce({
      ...initialClaim,
      revision: 4,
      handoff: assistanceHandoff('accepted'),
      customer_next_step: {
        status: 'human_support_in_progress',
        summary: 'A Northwind staff member is now assisting you.',
        responsible_party: 'claims_professional',
      },
    })
    api.getClaimMessages.mockResolvedValueOnce({
      items: [claimantMessage, agentMessage, queuedClaimantMessage],
    })
    await act(async () => pushLiveUpdate(realtimeChange(4)))

    expect(await screen.findByRole('status', { name: /Staff assistance accepted/ })).toBeInTheDocument()
    expect(screen.getByText(/Northwind has accepted your assistance request\./)).toBeInTheDocument()
    expect(screen.queryByText('Northwind staff joined the conversation')).not.toBeInTheDocument()
    expect(screen.queryByText('Staff assistance requested')).not.toBeInTheDocument()
    expect(screen.getByText(queuedClaimantMessage.content.text)).toBeInTheDocument()

    api.getClaim.mockResolvedValueOnce({
      ...initialClaim,
      revision: 5,
      handoff: assistanceHandoff('in_progress'),
      customer_next_step: {
        status: 'more_information_needed',
        summary: 'Please reply to the staff question.',
        responsible_party: 'claimant',
      },
    })
    api.getClaimMessages.mockResolvedValueOnce({
      items: [claimantMessage, agentMessage, queuedClaimantMessage, staffMessage],
    })
    await act(async () => pushLiveUpdate(realtimeChange(5)))

    expect(await screen.findByRole('status', { name: /Your response is needed/ })).toBeInTheDocument()
    const staffArticle = screen.getByText(staffMessage.content.text).closest('.msg-staff')
    expect(staffArticle.querySelector('.staff-mark')).toHaveTextContent('N')
    expect(staffArticle.querySelector('.staff-bubble')).toHaveClass('chat-bubble')
    expect(staffArticle.querySelector('time.message-timestamp'))
      .toHaveAttribute('datetime', staffMessage.created_at)
    expect(screen.getByText('Northwind staff')).toBeInTheDocument()
    const replyBox = screen.getByPlaceholderText('Reply to Northwind staff...')
    await user.type(replyBox, claimantReply.content.text)
    await user.click(screen.getByRole('button', { name: 'Send reply' }))

    expect(await screen.findByRole('status', { name: /Your reply was sent/ })).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: /Your response is needed/ })).not.toBeInTheDocument()
    expect(screen.getByText(/Waiting for the next claim update\./)).toBeInTheDocument()

    await act(async () => resolveReply({
      claimant_message: claimantReply,
      agent_message: null,
      form_changes: [],
      contents_item_changes: [],
      dynamic_form: null,
      claim_revision: 6,
      decision: null,
      handoff: null,
    }))

    api.getClaim.mockResolvedValueOnce({
      ...initialClaim,
      revision: 7,
      handoff: null,
      resolved_support_handoff: resolvedAssistanceHandoff(),
      customer_next_step: {
        status: 'describe_incident',
        summary: 'Describe what happened',
        responsible_party: 'claimant',
      },
    })
    api.getClaimMessages.mockResolvedValueOnce({
      items: [claimantMessage, agentMessage, staffMessage, claimantReply],
    })
    await act(async () => pushLiveUpdate(realtimeChange(7)))

    expect(await screen.findByRole('status', { name: /Staff assistance completed/ })).toBeInTheDocument()
    expect(screen.getByText(/You can continue your claim below\./)).toBeInTheDocument()
    expect(screen.getAllByText('Staff assistance completed')).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Staff assistance' })).toBeEnabled()
    expect(screen.queryByText('Claim created')).not.toBeInTheDocument()
  })

  it('restores completed staff assistance from a fresh post-resolution Claim projection', async () => {
    const user = userEvent.setup()
    let pushLiveUpdate
    const resolvedClaim = {
      ...initialClaim,
      revision: 7,
      handoff: null,
      resolved_support_handoff: resolvedAssistanceHandoff(),
      customer_next_step: {
        status: 'describe_incident',
        summary: 'Describe what happened',
        responsible_party: 'claimant',
      },
    }
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({
      items: [{ ...resolvedClaim, can_resume: true }],
      page: { next_cursor: null },
    })
    api.streamRealtimeEvents.mockImplementation(({ onEvent }) => {
      pushLiveUpdate = onEvent
      return new Promise(() => {})
    })
    api.resumeClaimSession.mockResolvedValue({
      session_id: 'ses_ui_vp',
      model_profile_id: 'qwen-local',
      started_at: '2026-09-10T01:00:02Z',
      resume: {
        customer_next_step: resolvedClaim.customer_next_step,
        summary: 'A pipe burst in the kitchen.',
        pending_items: [],
        prior_commitments: [],
      },
    })
    api.getClaim.mockResolvedValue(resolvedClaim)
    const postResumeMessage = {
      message_id: 'msg_after_resume',
      actor: 'claimant',
      content: { type: 'text', text: 'Here is another detail after resuming.' },
      created_at: '2026-09-10T01:00:03Z',
    }
    api.getClaimMessages
      .mockResolvedValueOnce({ items: [claimantMessage, agentMessage] })
      .mockResolvedValueOnce({ items: [claimantMessage, agentMessage, postResumeMessage] })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(await screen.findByRole('button', { name: /Open Home claim/ }))

    expect(await screen.findByRole('status', { name: /Staff assistance completed/ })).toBeVisible()
    expect(screen.queryByRole('button', { name: /Where you left off/ })).not.toBeInTheDocument()
    await waitFor(() => expect(pushLiveUpdate).toBeTypeOf('function'))
    await act(async () => pushLiveUpdate(realtimeChange(8)))
    const resumedEvent = screen.getByRole('status', { name: /Claim resumed/ })
    const messageAfterResume = await screen.findByText(postResumeMessage.content.text)
    expect(
      resumedEvent.compareDocumentPosition(messageAfterResume)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(screen.getByText(/You can continue your claim below\./)).toBeVisible()
    expect(screen.getAllByText('Staff assistance completed')).toHaveLength(1)
    expect(screen.queryByText('Claim created')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'New chat' }))
    expect(screen.queryByRole('status', { name: /Claim resumed/ })).not.toBeInTheDocument()
  })

  it('does not treat an ordinary staff update as completed assistance', async () => {
    const user = userEvent.setup()
    const staffUpdateClaim = {
      ...initialClaim,
      revision: 7,
      handoff: null,
      resolved_support_handoff: null,
      customer_next_step: {
        status: 'staff_update',
        summary: 'A staff member updated your claim.',
        responsible_party: 'claimant',
      },
    }
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({
      items: [{ ...staffUpdateClaim, can_resume: true }],
      page: { next_cursor: null },
    })
    api.resumeClaimSession.mockResolvedValue({
      session_id: 'ses_ui_vp',
      model_profile_id: 'qwen-local',
      started_at: '2026-09-10T01:00:02Z',
      resume: {
        customer_next_step: staffUpdateClaim.customer_next_step,
        summary: 'A pipe burst in the kitchen.',
        pending_items: [],
        prior_commitments: [],
      },
    })
    api.getClaim.mockResolvedValue(staffUpdateClaim)
    api.getClaimMessages.mockResolvedValue({ items: [claimantMessage, agentMessage] })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(await screen.findByRole('button', { name: /Open Home claim/ }))

    expect(await screen.findByRole('button', { name: 'Staff assistance' })).toBeEnabled()
    expect(screen.queryByRole('status', { name: /Staff assistance completed/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Staff assistance completed')).not.toBeInTheDocument()
  })

  it('restores persisted message attachments without adding them back to the composer', async () => {
    const user = userEvent.setup()
    const savedClaim = { ...initialClaim, revision: 4, can_resume: true }
    const savedEvidence = {
      evidence_id: 'evd_saved_photo',
      claim_id: initialClaim.claim_id,
      kind: 'incident_photo',
      status: 'received',
      file_status: 'ready',
      original_filename: 'saved-damage.jpg',
      media_type: 'image/jpeg',
      size_bytes: 5,
      source: 'claimant',
      created_at: '2026-09-14T01:05:00Z',
      updated_at: '2026-09-14T01:06:00Z',
    }
    const savedFileMessage = {
      ...claimantMessage,
      content: { type: 'evidence_reference' },
      evidence_refs: [savedEvidence.evidence_id],
    }
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [savedClaim], page: { next_cursor: null } })
    api.resumeClaimSession.mockResolvedValue({
      session_id: 'ses_ui_vp',
      model_profile_id: 'qwen-local',
      started_at: '2026-09-10T01:00:02Z',
      resume: {
        customer_next_step: savedClaim.customer_next_step,
        summary: 'A file was provided.',
        pending_items: [],
        prior_commitments: [],
      },
    })
    api.getClaim.mockResolvedValue(savedClaim)
    api.getClaimMessages.mockResolvedValue({ items: [savedFileMessage, agentMessage] })
    api.getClaimEvidence.mockResolvedValue({
      claim_id: savedClaim.claim_id,
      revision: savedClaim.revision,
      items: [savedEvidence],
    })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(await screen.findByRole('button', { name: /Open Home claim/ }))

    const attachmentBubble = (await screen.findByText('saved-damage.jpg')).closest('.user-bubble')
    expect(attachmentBubble).toHaveTextContent('Ready')
    expect(document.querySelector('.composer-attachments')).not.toBeInTheDocument()
  })

  it('starts a new local draft without creating a Claim before the first message', async () => {
    const user = userEvent.setup()
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.submitClaimMessage.mockResolvedValue({
      claimant_message: claimantMessage,
      agent_message: agentMessage,
      form_changes: [],
      contents_item_changes: [],
      dynamic_form: null,
      claim_revision: 2,
      decision: { customer_next_step: initialClaim.customer_next_step },
    })
    api.createClaim
      .mockResolvedValueOnce({
        claim: initialClaim,
        session: { session_id: 'ses_ui_vp', model_profile_id: 'qwen-local' },
      })
      .mockResolvedValueOnce({
        claim: { ...initialClaim, claim_id: 'clm_ui_second' },
        session: { session_id: 'ses_ui_second', model_profile_id: 'qwen-local' },
      })
    api.listClaims.mockResolvedValue({
      items: [
        {
          claim_id: 'clm_ui_vp',
          incident_type: 'home',
          customer_next_step: initialClaim.customer_next_step,
          can_resume: true,
        },
      ],
    })

    render(<App />)
    const input = screen.getByPlaceholderText('Tell us what happened…')
    await user.type(input, 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText('Thanks. I need the incident time next.')

    await user.click(screen.getByRole('button', { name: 'New chat' }))

    expect(api.pauseClaimSession).toHaveBeenCalledWith({
      claimId: initialClaim.claim_id,
      sessionId: 'ses_ui_vp',
      revision: 2,
      idempotencyKey: expect.stringMatching(/^pause-session-/),
    })
    expect(api.createClaim).toHaveBeenCalledTimes(1)
    expect(api.startClaimSession).not.toHaveBeenCalled()
    expect(screen.getByRole('heading', { name: 'New conversation' })).toBeVisible()
    expect(screen.getByText('Ready to start')).toBeVisible()
    expect(screen.getByPlaceholderText('Write the details you know...')).toHaveValue('')
    expect(screen.queryByRole('button', { name: 'Start claim' })).not.toBeInTheDocument()
    expect(screen.queryByText('clm_ui_second')).not.toBeInTheDocument()
    expect(globalThis.location.pathname).toBe('/claims/new')

    await user.type(
      screen.getByPlaceholderText('Write the details you know...'),
      'A second incident happened today.',
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(api.createClaim).toHaveBeenCalledTimes(2)
    expect(await screen.findByText('clm_ui_second')).toBeInTheDocument()
    expect(screen.getByText('Conversation history')).toBeInTheDocument()
    await waitFor(() => expect(api.streamRealtimeEvents).toHaveBeenCalled())
    expect(api.streamClaimUpdates).not.toHaveBeenCalled()
    expect(api.streamRealtimeEvents.mock.calls.at(-1)[0]).toEqual(expect.objectContaining({
      cursor: null,
      signal: expect.any(AbortSignal),
      onEvent: expect.any(Function),
    }))
  })

  it('keeps the active conversation visible when saving the interruption fails and retries with the same key', async () => {
    const user = userEvent.setup()
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.pauseClaimSession
      .mockRejectedValueOnce(Object.assign(
        new api.ApiRequestError('The interruption checkpoint could not be saved.'),
        { code: 'DEPENDENCY_UNAVAILABLE', status: 503, retryable: true },
      ))
      .mockResolvedValueOnce({
        claim: pausedClaim(),
        session: { session_id: 'ses_ui_vp', status: 'paused' },
      })

    render(<App />)
    await startActiveClaim(user)

    await user.click(screen.getByRole('button', { name: 'New chat' }))

    expect(screen.getByRole('heading', { name: initialClaim.claim_id })).toBeVisible()
    expect(screen.getByText(agentMessage.content.text)).toBeVisible()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Your current conversation is still open. Review the report and select New chat again.',
    )

    await user.click(screen.getByRole('button', { name: 'New chat' }))

    expect(api.pauseClaimSession).toHaveBeenCalledTimes(2)
    expect(api.pauseClaimSession.mock.calls[1][0].idempotencyKey).toBe(
      api.pauseClaimSession.mock.calls[0][0].idempotencyKey,
    )
    expect(await screen.findByRole('heading', { name: 'New conversation' })).toBeVisible()
  })

  it('prevents duplicate interruption saves while New chat is pending', async () => {
    const user = userEvent.setup()
    const pause = deferredRequest()
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.pauseClaimSession.mockReturnValue(pause.promise)

    render(<App />)
    await startActiveClaim(user)

    const newChat = screen.getByRole('button', { name: 'New chat' })
    fireEvent.click(newChat)
    fireEvent.click(newChat)

    expect(api.pauseClaimSession).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled()

    await act(async () => pause.resolve({
      claim: pausedClaim(),
      session: { session_id: 'ses_ui_vp', status: 'paused' },
    }))

    expect(await screen.findByRole('heading', { name: 'New conversation' })).toBeVisible()
  })

  it('uses authoritative Claim readback when the pause response is lost', async () => {
    const user = userEvent.setup()
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.pauseClaimSession.mockRejectedValueOnce(
      new api.ApiRequestError('We could not reach the claim service.'),
    )
    api.getClaim.mockResolvedValue(pausedClaim())

    render(<App />)
    await startActiveClaim(user)

    await user.click(screen.getByRole('button', { name: 'New chat' }))

    expect(api.getClaim).toHaveBeenCalledWith(initialClaim.claim_id)
    expect(await screen.findByRole('heading', { name: 'New conversation' })).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it.each([
    ['a successful pause response', false],
    ['an unknown pause outcome', true],
  ])('resumes a valid session before sending after leaving for a utility page with %s', async (
    _scenario,
    responseIsLost,
  ) => {
    const user = userEvent.setup()
    const pause = deferredRequest()
    const resumedClaim = {
      ...initialClaim,
      revision: 5,
      active_session_id: 'ses_after_utility',
    }
    const followUpClaimantMessage = {
      ...claimantMessage,
      message_id: 'msg_after_utility',
      client_message_id: 'message-after-utility',
      content: { type: 'text', text: 'One more detail after returning.' },
    }
    api.submitClaimMessage
      .mockResolvedValueOnce(initialTurn())
      .mockResolvedValueOnce({
        claimant_message: followUpClaimantMessage,
        agent_message: {
          ...agentMessage,
          message_id: 'msg_agent_after_utility',
          content: { type: 'text', text: 'Thanks, the resumed conversation is active.' },
        },
        form_changes: [],
        contents_item_changes: [],
        dynamic_form: null,
        claim_revision: 6,
        decision: { customer_next_step: initialClaim.customer_next_step },
        primary_action: primaryAction({ revision: 6 }),
      })
    api.pauseClaimSession.mockReturnValue(pause.promise)
    if (responseIsLost) {
      api.getClaim
        .mockResolvedValueOnce(pausedClaim())
        .mockResolvedValueOnce(pausedClaim())
        .mockResolvedValueOnce(resumedClaim)
    } else {
      api.getClaim
        .mockResolvedValueOnce(pausedClaim())
        .mockResolvedValueOnce(resumedClaim)
    }
    api.resumeClaimSession.mockResolvedValue({
      session_id: 'ses_after_utility',
      model_profile_id: 'qwen-local',
      started_at: '2026-09-16T01:06:00Z',
      resume: {
        summary: 'A pipe burst in the kitchen.',
        unresolved_questions: [],
        pending_items: [],
        prior_commitments: [],
      },
    })
    api.getClaimMessages.mockResolvedValue({ items: [claimantMessage, agentMessage] })

    render(<App />)
    await startActiveClaim(user)
    await user.click(screen.getByRole('button', { name: 'New chat' }))
    await user.click(screen.getByRole('button', { name: 'Privacy policy' }))
    await act(async () => {
      if (responseIsLost) pause.reject(new api.ApiRequestError('Response lost.'))
      else pause.resolve({
        claim: pausedClaim(),
        session: { session_id: 'ses_ui_vp', status: 'paused' },
      })
    })

    await user.click(screen.getByRole('button', { name: 'Back to conversation' }))
    await user.type(
      screen.getByPlaceholderText('Write the details you know...'),
      'One more detail after returning.',
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(api.submitClaimMessage).toHaveBeenCalledTimes(2))
    expect(api.resumeClaimSession).toHaveBeenCalledWith({ claimId: initialClaim.claim_id })
    expect(api.resumeClaimSession.mock.invocationCallOrder[0])
      .toBeLessThan(api.submitClaimMessage.mock.invocationCallOrder[1])
    expect(api.submitClaimMessage.mock.calls[1][0]).toEqual(expect.objectContaining({
      claimId: initialClaim.claim_id,
      sessionId: 'ses_after_utility',
      revision: 5,
      text: 'One more detail after returning.',
    }))
  })

  it.each([
    ['sign-out', false],
    ['account switch', true],
  ])('ignores an old pause readback after %s', async (_scenario, switchAccount) => {
    const user = userEvent.setup()
    const readback = deferredRequest()
    mockAuthenticatedAccounts(
      testAccount('cus_pause_a', 'Account A'),
      ...(switchAccount ? [testAccount('cus_pause_b', 'Account B')] : []),
    )
    api.loginClaimant.mockResolvedValue({ access_token: 'account-b-token' })
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.pauseClaimSession.mockRejectedValueOnce(new api.ApiRequestError('Response lost.'))
    api.getClaim.mockReturnValueOnce(readback.promise)

    render(<App />)
    await startActiveClaim(user)
    await user.click(screen.getByRole('button', { name: 'New chat' }))
    await waitFor(() => expect(api.getClaim).toHaveBeenCalledWith(initialClaim.claim_id))
    await user.click(screen.getByRole('button', { name: /Open Profile for Account A/ }))
    await user.click(await screen.findByRole('button', { name: 'Log out' }))
    if (switchAccount) {
      await user.click(screen.getByRole('button', { name: 'Log in' }))
      await user.type(screen.getByLabelText('Email address'), 'b@example.test')
      await user.type(screen.getByLabelText('Password'), 'account-b-password')
      await user.click(screen.getAllByRole('button', { name: 'Log in' }).at(-1))
      await screen.findByRole('button', { name: 'Profile' })
    }
    await act(async () => readback.resolve(pausedClaim()))

    if (switchAccount) {
      await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
      expect(await screen.findByText('No saved conversations yet')).toBeVisible()
    } else {
      expect(globalThis.sessionStorage.getItem(
        'northwind.anonymousConversationHistory.v1.anonymous-session-test',
      )).toBeNull()
    }
    expect(screen.queryByText(initialClaim.claim_id)).not.toBeInTheDocument()
    expect(globalThis.location.pathname).toBe('/')
  })

  it('ignores an old pause failure after a newer workspace pause starts', async () => {
    const user = userEvent.setup()
    const oldPause = deferredRequest()
    const newerPause = deferredRequest()
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.pauseClaimSession
      .mockReturnValueOnce(oldPause.promise)
      .mockReturnValueOnce(newerPause.promise)

    render(<App />)
    await startActiveClaim(user)
    await user.click(screen.getByRole('button', { name: 'New chat' }))
    await user.click(screen.getByRole('button', { name: 'Privacy policy' }))
    await user.click(screen.getByRole('button', { name: 'Back to conversation' }))
    await user.click(screen.getByRole('button', { name: 'New chat' }))
    await act(async () => oldPause.reject(new api.ApiRequestError('Old pause failed.')))

    expect(api.pauseClaimSession).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    await act(async () => newerPause.resolve({
      claim: pausedClaim(),
      session: { session_id: 'ses_ui_vp', status: 'paused' },
    }))
    expect(await screen.findByRole('heading', { name: 'New conversation' })).toBeVisible()
  })

  it('uses the homepage rail to return to the existing empty conversation workspace', async () => {
    const user = userEvent.setup()
    render(<App />)

    const input = screen.getByPlaceholderText('Tell us what happened…')
    await user.type(input, 'A draft that has not been sent.')
    await user.click(screen.getByRole('button', { name: 'New conversation' }))

    expect(input).toHaveValue('')
    expect(api.createClaim).not.toHaveBeenCalled()
    expect(api.pauseClaimSession).not.toHaveBeenCalled()
    expect(globalThis.location.pathname).toBe('/')
  })

  it('restores the empty conversation workspace from its draft route', () => {
    globalThis.history.replaceState({}, '', '/claims/new')

    render(<App />)

    expect(screen.getByRole('heading', { name: 'New conversation' })).toBeVisible()
    expect(screen.getByPlaceholderText('Write the details you know...')).toBeVisible()
    expect(screen.queryByRole('heading', { name: 'Start your insurance claim' })).not.toBeInTheDocument()
  })

  it('restores anonymous session-local history through the existing Claim APIs after reload', async () => {
    const user = userEvent.setup()
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.resumeClaimSession.mockResolvedValue({
      session_id: 'ses_ui_vp',
      model_profile_id: 'qwen-local',
      started_at: '2026-09-16T01:06:00Z',
      resume: {
        summary: 'A pipe burst in the kitchen.',
        unresolved_questions: [],
        pending_items: [],
        prior_commitments: [],
        customer_next_step: initialClaim.customer_next_step,
      },
    })
    api.getClaim.mockResolvedValue(initialClaim)
    api.getClaimMessages.mockResolvedValue({ items: [claimantMessage, agentMessage] })
    const { unmount } = render(<App />)

    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    await user.click(screen.getByRole('button', { name: 'New chat' }))
    unmount()

    render(<App />)
    expect(screen.getByRole('heading', { name: 'New conversation' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: /home.*Continue this conversation/i }))

    expect(api.listClaims).not.toHaveBeenCalled()
    expect(api.resumeClaimSession).toHaveBeenCalledWith({ claimId: initialClaim.claim_id })
    expect(await screen.findByText(agentMessage.content.text)).toBeVisible()
  })

  it('uses the authoritative post-resume revision for the next claimant message', async () => {
    const user = userEvent.setup()
    let backendClaim = {
      ...initialClaim,
      revision: 4,
      primary_action: primaryAction({ revision: 4 }),
    }
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({
      items: [{ ...backendClaim, can_resume: true }],
      page: { next_cursor: null },
    })
    api.getClaim.mockImplementation(() => Promise.resolve(backendClaim))
    api.resumeClaimSession.mockImplementation(() => {
      backendClaim = {
        ...backendClaim,
        revision: 5,
        primary_action: primaryAction({ revision: 5 }),
      }
      return Promise.resolve({
        session_id: 'ses_resumed',
        model_profile_id: 'qwen-local',
        started_at: '2026-09-16T01:06:00Z',
        resume: {
          summary: 'A pipe burst in the kitchen.',
          unresolved_questions: [],
          pending_items: [],
          prior_commitments: [],
          customer_next_step: backendClaim.customer_next_step,
        },
      })
    })
    api.getClaimMessages.mockResolvedValue({ items: [claimantMessage, agentMessage] })
    api.submitClaimMessage.mockImplementation(({ revision }) => {
      expect(revision).toBe(5)
      return Promise.resolve({
        ...initialTurn(),
        claimant_message: {
          ...claimantMessage,
          message_id: 'msg_after_authoritative_resume',
          content: { type: 'text', text: 'The water is now turned off.' },
        },
        agent_message: {
          ...agentMessage,
          message_id: 'msg_agent_after_authoritative_resume',
          content: { type: 'text', text: 'Thanks, I recorded that update.' },
        },
        claim_revision: 6,
        primary_action: primaryAction({ revision: 6 }),
      })
    })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(await screen.findByRole('button', { name: /Open Home claim/ }))
    await screen.findByText(initialClaim.claim_id)

    await user.type(screen.getByPlaceholderText('Write the details you know...'), 'The water is now turned off.')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Thanks, I recorded that update.')).toBeVisible()
    expect(api.submitClaimMessage).toHaveBeenCalledWith(expect.objectContaining({ revision: 5 }))
    expect(api.getClaim).toHaveBeenCalledTimes(2)
  })

  it('keeps a failed resumed-message retry on the saved message above Claim resumed', async () => {
    const user = userEvent.setup()
    const recovery = {
      rule_id: 'claimant_turn.model_dependency_failure',
      claimant_projection: 'Your message is saved, but I could not respond just now. You can try again.',
      resume_triggers: ['claimant_reply', 'explicit_retry_request'],
      resume_entrypoint: 'submit_message',
      continuation: 'runtime.fail_safe',
    }
    const savedHi = {
      message_id: 'msg_saved_hi',
      actor: 'claimant',
      client_message_id: 'message-saved-hi',
      content: { type: 'text', text: 'hi' },
      created_at: '2026-09-16T01:05:00Z',
      recovery,
    }
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [{ ...initialClaim, can_resume: true }], page: { next_cursor: null } })
    api.getClaim.mockResolvedValue(initialClaim)
    api.resumeClaimSession.mockResolvedValue({
      session_id: 'ses_resumed',
      model_profile_id: 'qwen-local',
      started_at: '2026-09-16T01:06:00Z',
      resume: { summary: 'You said hi.', unresolved_questions: [], pending_items: [], prior_commitments: [] },
    })
    api.getClaimMessages.mockResolvedValue({ items: [savedHi] })
    api.submitClaimMessage.mockRejectedValueOnce(Object.assign(
      new api.ApiRequestError('The claims assistant is temporarily unavailable.'),
      { status: 503, code: 'DEPENDENCY_UNAVAILABLE', retryable: true },
    ))

    const { container } = render(<App />)
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(await screen.findByRole('button', { name: /Open Home claim/ }))
    const resumed = await screen.findByText('Claim resumed')

    await user.click(screen.getByRole('button', { name: 'Retry response' }))
    expect(await screen.findByText(/The claims assistant is temporarily unavailable/)).toBeVisible()

    const hiBubbles = [...container.querySelectorAll('.message-list .user-bubble')]
      .filter((bubble) => bubble.textContent === 'hi')
    expect(hiBubbles).toHaveLength(1)
    expect(container.querySelector('.message-list .is-failed')).not.toBeInTheDocument()
    expect(hiBubbles[0].compareDocumentPosition(resumed) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Retry response' })).toBeEnabled()
    expect(api.submitClaimMessage).toHaveBeenCalledWith(expect.objectContaining({ clientMessageId: 'message-saved-hi' }))
  })

  it('renders earlier messages above Claim resumed and a genuine post-resume message below it', async () => {
    const user = userEvent.setup()
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [{ ...initialClaim, can_resume: true }], page: { next_cursor: null } })
    api.getClaim.mockResolvedValue(initialClaim)
    api.resumeClaimSession.mockResolvedValue({
      session_id: 'ses_resumed',
      model_profile_id: 'qwen-local',
      started_at: '2026-09-10T00:59:00Z',
      resume: { summary: 'A pipe burst in the kitchen.', unresolved_questions: [], pending_items: [], prior_commitments: [] },
    })
    // The readback arrives with the reply first; the client must still show the causal order.
    api.getClaimMessages.mockResolvedValue({ items: [{ ...agentMessage, in_reply_to: claimantMessage.message_id }, claimantMessage] })
    api.submitClaimMessage.mockResolvedValueOnce({
      ...initialTurn(),
      claimant_message: {
        ...claimantMessage,
        message_id: 'msg_after_resume',
        content: { type: 'text', text: 'The water is now turned off.' },
        created_at: '2026-09-16T01:10:00Z',
      },
      agent_message: {
        ...agentMessage,
        message_id: 'msg_agent_after_resume',
        in_reply_to: 'msg_after_resume',
        content: { type: 'text', text: 'Thanks, I recorded that update.' },
        created_at: '2026-09-16T01:10:01Z',
      },
    })

    const { container } = render(<App />)
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(await screen.findByRole('button', { name: /Open Home claim/ }))
    await screen.findByText('Claim resumed')
    await user.type(screen.getByPlaceholderText('Write the details you know...'), 'The water is now turned off.')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await screen.findByText('Thanks, I recorded that update.')

    const order = [...container.querySelectorAll('.message-list > *')]
      .map((item) => item.textContent)
      .map((text) => [
        claimantMessage.content.text,
        agentMessage.content.text,
        'Claim resumed',
        'The water is now turned off.',
        'Thanks, I recorded that update.',
      ].find((needle) => text.includes(needle)))
      .filter(Boolean)
    expect(order).toEqual([
      claimantMessage.content.text,
      agentMessage.content.text,
      'Claim resumed',
      'The water is now turned off.',
      'Thanks, I recorded that update.',
    ])
  })

  it('removes an anonymous history reference after a permanent resume failure', async () => {
    const user = userEvent.setup()
    const historyKey = 'northwind.anonymousConversationHistory.v1.anonymous-session-test'
    globalThis.sessionStorage.setItem(historyKey, JSON.stringify([{ ...initialClaim, can_resume: true }]))
    api.getClaim.mockRejectedValue(Object.assign(
      new api.ApiRequestError('The claim was not found.'),
      { code: 'RESOURCE_NOT_FOUND', status: 404, retryable: false },
    ))

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(screen.getByRole('button', { name: /Open Home claim/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This conversation is no longer available in this browser session, so it was removed from history.',
    )
    expect(JSON.parse(globalThis.sessionStorage.getItem(historyKey))).toEqual([])
    expect(api.resumeClaimSession).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    expect(screen.queryByRole('button', { name: /Open Home claim/ })).not.toBeInTheDocument()
  })

  it('retains an anonymous history reference after a transient resume failure', async () => {
    const user = userEvent.setup()
    const historyKey = 'northwind.anonymousConversationHistory.v1.anonymous-session-test'
    globalThis.sessionStorage.setItem(historyKey, JSON.stringify([{ ...initialClaim, can_resume: true }]))
    api.getClaim.mockRejectedValue(Object.assign(
      new api.ApiRequestError('We could not reach the claim service.'),
      { code: 'NETWORK_ERROR', retryable: true },
    ))

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(screen.getByRole('button', { name: /Open Home claim/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The conversation is still saved in history. Try opening it again.',
    )
    expect(JSON.parse(globalThis.sessionStorage.getItem(historyKey))).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    expect(screen.getByRole('button', { name: /Open Home claim/ })).toBeVisible()
  })

  it('keeps conversation history rows stable when switching the active Claim', async () => {
    const user = userEvent.setup()
    const reportA = {
      ...initialClaim,
      claim_id: 'clm_history_a',
      can_resume: true,
      customer_next_step: { ...initialClaim.customer_next_step, summary: 'Continue claim A' },
    }
    const reportB = {
      ...initialClaim,
      claim_id: 'clm_history_b',
      incident_type: 'contents',
      can_resume: true,
      customer_next_step: { ...initialClaim.customer_next_step, summary: 'Continue claim B' },
    }
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [reportA, reportB], page: { next_cursor: null } })
    api.resumeClaimSession.mockImplementation(({ claimId }) => Promise.resolve({
      session_id: `ses_${claimId}`,
      model_profile_id: 'qwen-local',
      started_at: '2026-09-14T02:00:00Z',
      resume: {
        customer_next_step: initialClaim.customer_next_step,
        summary: null,
        pending_items: [],
        prior_commitments: [],
      },
    }))
    api.getClaim.mockImplementation((claimId) => Promise.resolve(
      claimId === reportA.claim_id ? reportA : reportB,
    ))
    api.getClaimMessages.mockResolvedValue({ items: [] })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(await screen.findByRole('button', { name: /Open Home claim/ }))
    expect(await screen.findByText(reportA.claim_id)).toBeInTheDocument()

    const historyCards = () => [...document.querySelectorAll('.intake-history-item')]
    expect(historyCards()[0]).toHaveTextContent(reportA.claim_id)
    expect(historyCards()[1]).toHaveTextContent('Continue claim B')

    await user.click(historyCards()[1])
    expect(await screen.findByText(reportB.claim_id)).toBeInTheDocument()
    expect(historyCards()[0]).toHaveTextContent('Continue claim A')
    expect(historyCards()[1]).toHaveTextContent(reportB.claim_id)

    await user.click(historyCards()[1])
    expect(api.resumeClaimSession).toHaveBeenCalledTimes(2)
  })

  it('holds a target Claim realtime event until an in-flight resume installs that Claim', async () => {
    const user = userEvent.setup()
    let pushRealtime
    let resolveCurrentClaim

    const report = {
      ...initialClaim,
      claim_id: 'clm_transition_target',
      can_resume: true,
      primary_action: primaryAction({ targetRef: 'clm_transition_target' }),
    }

    const currentReadback = new Promise((resolve) => {
      resolveCurrentClaim = resolve
    })

    let claimReadCount = 0

    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: {
        display_name: 'Test claimant',
        email: 'test@example.test',
        phone: '',
      },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({
      items: [report],
      page: { next_cursor: null },
    })
    api.streamRealtimeEvents.mockImplementation(({ onEvent }) => {
      pushRealtime = onEvent
      return new Promise(() => {})
    })
    api.resumeClaimSession.mockResolvedValue({
      session_id: 'ses_transition_target',
      model_profile_id: 'qwen-local',
      started_at: '2026-09-18T02:35:00Z',
      resume: {
        customer_next_step: report.customer_next_step,
        summary: null,
        pending_items: [],
        prior_commitments: [],
      },
    })

    const revisionTwo = {
      ...report,
      revision: 2,
      customer_next_step: {
        status: 'confirmation_required',
        summary: 'Review the transition update.',
        required_items: ['incident.description'],
      },
      primary_action: primaryAction({
        actionCode: 'claimant.review_details',
        available: true,
        requiredInputs: ['incident.description'],
        revision: 2,
        targetRef: report.claim_id,
      }),
    }

    api.getClaim.mockImplementation(() => {
      claimReadCount += 1
      if (claimReadCount === 1) return Promise.resolve(report)
      if (claimReadCount === 2) return currentReadback
      return Promise.resolve(revisionTwo)
    })
    api.getClaimMessages.mockResolvedValue({ items: [] })

    render(<App />)

    await waitFor(() => expect(pushRealtime).toBeTypeOf('function'))

    await user.click(
      screen.getByRole('button', { name: 'Expand conversation history' }),
    )
    await user.click(
      await screen.findByRole('button', { name: /Open Home claim/ }),
    )

    await waitFor(() => expect(api.getClaim).toHaveBeenCalledTimes(2))

    let realtimeRefresh
    await act(async () => {
      realtimeRefresh = pushRealtime(
        realtimeChangeFor(report.claim_id, 2, ['claim']),
      )
      await Promise.resolve()
    })

    // The realtime handler is waiting for the target Claim transition
    // instead of acknowledging and dropping the event.
    expect(api.getClaim).toHaveBeenCalledTimes(2)

    await act(async () => {
      resolveCurrentClaim(report)
      await realtimeRefresh
    })

    expect(api.getClaim).toHaveBeenCalledTimes(3)
    expect(
      await screen.findByRole('button', { name: /Review claim details/i }),
    ).toBeInTheDocument()
  })

  it('does not let an old Claim event resurrect the workspace while starting a new chat', async () => {
    const user = userEvent.setup()
    let pushRealtime
    let eventDuringReset

    api.streamRealtimeEvents.mockImplementation(({ onEvent }) => {
      pushRealtime = onEvent
      return new Promise(() => {})
    })
    api.submitClaimMessage.mockResolvedValue(initialTurn())

    render(<App />)

    await user.type(
      screen.getByRole('textbox', { name: 'Incident description' }),
      'A pipe burst in the kitchen.',
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    await waitFor(() => expect(pushRealtime).toBeTypeOf('function'))

    api.getClaim.mockResolvedValue({
      ...initialClaim,
      revision: 3,
      primary_action: primaryAction({ revision: 3 }),
    })
    api.getClaim.mockClear()

    globalThis.history.replaceState(
      {},
      '',
      `/claims/${initialClaim.claim_id}`,
    )

    const originalPushState = globalThis.history.pushState.bind(
      globalThis.history,
    )

    const pushState = vi
      .spyOn(globalThis.history, 'pushState')
      .mockImplementation((...args) => {
        eventDuringReset = pushRealtime(realtimeChange(3, ['claim']))
        return originalPushState(...args)
      })

    try {

    await user.click(screen.getByRole('button', { name: 'New chat' }))

    await act(async () => {
      await eventDuringReset
    })

    expect(
      screen.getByRole('textbox', { name: 'Add more information' }),
    ).toBeVisible()
    expect(screen.getByRole('heading', { name: 'New conversation' })).toBeVisible()
    expect(screen.queryByText(initialClaim.claim_id)).not.toBeInTheDocument()
    expect(api.getClaim).not.toHaveBeenCalled()

    } finally {
      pushState.mockRestore()
    }
  })

  it('does not let a stale conflict refresh roll back a newer installed Claim projection', async () => {
    const user = userEvent.setup()

    const newerClaimantMessage = {
      ...claimantMessage,
      message_id: 'msg_conflict_newer',
      content: {
        type: 'text',
        text: 'The water has stopped now.',
      },
    }

    const newerAgentMessage = {
      ...agentMessage,
      message_id: 'msg_conflict_agent_newer',
      content: {
        type: 'text',
        text: 'I recorded the newer state.',
      },
    }

    api.submitClaimMessage
      .mockResolvedValueOnce(initialTurn())
      .mockResolvedValueOnce({
        ...initialTurn(),
        claimant_message: newerClaimantMessage,
        agent_message: newerAgentMessage,
        claim_revision: 3,
        primary_action: primaryAction({
          actionCode: 'claimant.review_details',
          available: true,
          requiredInputs: ['incident.description'],
          revision: 3,
        }),
      })

    render(<App />)

    await user.type(
      screen.getByRole('textbox', { name: 'Incident description' }),
      'A pipe burst in the kitchen.',
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)

    await user.type(
      screen.getByPlaceholderText('Write the details you know...'),
      newerClaimantMessage.content.text,
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(
      await screen.findByRole('button', { name: /Review claim details/i }),
    ).toBeInTheDocument()

    const conflict = Object.assign(
      new api.ApiRequestError('The Claim revision changed.'),
      {
        code: 'REVISION_CONFLICT',
        status: 409,
        retryable: false,
      },
    )

    api.submitClaimMessage.mockRejectedValueOnce(conflict)
    api.getClaim.mockResolvedValueOnce({
      ...initialClaim,
      revision: 2,
      primary_action: primaryAction({ revision: 2 }),
    })

    await user.type(
      screen.getByPlaceholderText('Write the details you know...'),
      'One more conflicting update.',
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(api.getClaim).toHaveBeenCalledTimes(1))

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(
      screen.getByRole('button', { name: /Review claim details/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(newerAgentMessage.content.text),
    ).toBeInTheDocument()
  })


  it('completes payout and contact Step 3 then requires Step 4 before creation', async () => {
    const user = userEvent.setup()
    const paymentDestination = {
      payment_destination_id: 'pyd_1234567890abcdef1234',
      account_type: 'cheque',
      masked_account_number: '***************6700',
      revision: 1,
      active: true,
    }
    const readyForPayout = primaryAction({
      actionCode: 'claimant.review_payout_contact',
      available: true,
      requiredInputs: ['payment_destination_id', 'claimant.contact_preference'],
      revision: 2,
    })
    const reviewAgreementAction = primaryAction({
      actionCode: 'claimant.review_agreement',
      available: true,
      revision: 3,
    })
    const createClaimAction = primaryAction({
      actionCode: 'claimant.create_claim',
      actionType: 'claim_creation',
      available: true,
      revision: 4,
    })
    const agreement = {
      agreement_id: 'northwind-fnol-claim-submission',
      version: '1',
      display_copy: 'I have reviewed the information shown for this claim.',
      confirmations: [{
        key: 'reviewed_and_confirmed',
        label: 'I confirm this submission.',
        required: true,
      }],
    }

    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      customer_id: 'cus_demo',
      profile: {
        display_name: 'Test claimant',
        email: 'test@example.test',
        phone: '',
      },
      preferences: { email: true, sms: false },
      revision: 2,
    })
    api.listPaymentDestinations.mockResolvedValue({
      items: [paymentDestination],
      page: { next_cursor: null },
    })
    api.submitClaimMessage.mockResolvedValue({
      ...initialTurn(),
      dynamic_form: readyDynamicForm(),
      claim_revision: 2,
      decision: {
        customer_next_step: {
          status: 'ready_to_create',
          summary: 'Review payout and contact details.',
          required_items: [],
        },
      },
      primary_action: readyForPayout,
    })
    api.selectClaimPayoutContact.mockResolvedValue({
      claim_id: initialClaim.claim_id,
      revision: 3,
      payment_destination_id: paymentDestination.payment_destination_id,
      contact_preference: {
        value: 'email',
        status: 'confirmed',
        source: 'claimant',
      },
      customer_next_step: {
        status: 'agreement_required',
        summary: 'Continue to agreement and confirmation.',
        required_items: [],
      },
      primary_action: reviewAgreementAction,
    })
    api.getClaim.mockResolvedValue({
      ...initialClaim,
      revision: 3,
      payment_destination_id: paymentDestination.payment_destination_id,
      submission_agreement: agreement,
      form: {
        ...initialClaim.form,
        'claimant.contact_preference': {
          value: 'email',
          status: 'confirmed',
          source: 'claimant',
        },
      },
      dynamic_form: readyDynamicForm(),
      customer_next_step: {
        status: 'agreement_required',
        summary: 'Continue to agreement and confirmation.',
        required_items: [],
      },
      primary_action: reviewAgreementAction,
    })
    api.acceptClaimAgreement.mockResolvedValue({
      claim_id: initialClaim.claim_id,
      revision: 4,
      agreement,
      acceptance: {
        acceptance_id: 'aga_test',
        agreement_id: agreement.agreement_id,
        version: agreement.version,
        confirmations: { reviewed_and_confirmed: true },
        accepted_at: '2026-09-23T10:00:00Z',
      },
      customer_next_step: {
        status: 'agreement_required',
        summary: 'Continue to agreement and confirmation.',
        required_items: [],
      },
      primary_action: createClaimAction,
    })
    api.createExternalClaim.mockResolvedValue({
      revision: 5,
      external_claim: {
        claim_number: 'NWF-2026-16ECDD',
        creation_status: 'created',
        route: 'Claims intake review',
        next_step: 'A claims specialist will review the submitted details.',
        expected_by: '2026-09-16T01:00:00Z',
      },
      external_service_action: null,
      customer_next_step: {
        status: 'claim_created',
        summary: 'Claims intake review',
        required_items: [],
      },
      primary_action: primaryAction({
        actionCode: 'claimant.continue_conversation',
        available: false,
        revision: 5,
      }),
    })

    render(<App />)
    await user.type(
      screen.getByPlaceholderText('Tell us what happened…'),
      'My claim details are complete.',
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    expect(
      await screen.findByRole('heading', { name: 'Payout & contact' }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /cheque .*6700/i }))
    await user.click(screen.getByRole('radio', { name: /Email test@example.test/i }))
    await user.click(screen.getByRole('button', { name: 'Continue to agreement' }))

    expect(
      await screen.findByText(agreement.display_copy),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', {
      name: 'I confirm this submission.',
    }))
    await user.click(screen.getByRole('button', { name: 'Submit claim' }))

    await waitFor(() => expect(api.acceptClaimAgreement).toHaveBeenCalledWith(
      expect.objectContaining({
        claimId: initialClaim.claim_id,
        revision: 3,
        agreementId: agreement.agreement_id,
        version: agreement.version,
        confirmations: { reviewed_and_confirmed: true },
      }),
    ))

    await waitFor(() => expect(api.createExternalClaim).toHaveBeenCalledWith(
      expect.objectContaining({
        claimId: initialClaim.claim_id,
        revision: 4,
      }),
    ))

    const successHeading = await screen.findByRole('heading', { name: 'Claim submitted' })
    const successPanel = successHeading.closest('section')
    expect(successPanel).not.toBeNull()
    expect(within(successPanel).getByText('NWF-2026-16ECDD')).toBeInTheDocument()
    expect(
      within(successPanel).getByText('A claims specialist will review the submitted details.'),
    ).toBeInTheDocument()
    expect(within(successPanel).getByText('2026-09-16T01:00:00Z')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Submit claim' })).not.toBeInTheDocument()

    await user.click(
      within(successPanel).getByRole('button', { name: 'Back to conversation' }),
    )
    expect(screen.queryByRole('heading', { name: 'Claim submitted' })).not.toBeInTheDocument()
  })

  it('keeps agreement review in the Agent message flow before final submission', async () => {
    const user = userEvent.setup()

    api.submitClaimMessage.mockResolvedValue({
      ...initialTurn(),
      dynamic_form: readyDynamicForm(),
      claim_revision: 2,
      decision: {
        customer_next_step: {
          status: 'agreement_required',
          summary: 'Continue to agreement and confirmation.',
          required_items: [],
        },
      },
      primary_action: primaryAction({
        actionCode: 'claimant.review_agreement',
        available: true,
        revision: 2,
      }),
    })

    render(<App />)
    await user.type(
      screen.getByPlaceholderText('Tell us what happened…'),
      'My car was damaged.',
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    await screen.findByText(agentMessage.content.text)

    const agreementAction = screen.getByRole('button', {
      name: /Agreement & confirmation/i,
    })
    expect(agreementAction.closest('.msg-agent')).toBeInTheDocument()
    expect(screen.queryByRole('button', {
      name: /Request a vehicle damage assessment/i,
    })).not.toBeInTheDocument()
  })

  it('renders boolean field values as Yes/No and shows a human label for every registered field', async () => {
    const user = userEvent.setup()
    const claimWithBooleanFields = {
      ...initialClaim,
      revision: 2,
      form: {
        'incident.injury_or_danger': { value: false, status: 'confirmed', source: 'claimant' },
        'vehicle.drivable': { value: true, status: 'confirmed', source: 'claimant' },
        'incident.cause': { value: 'Hit the guardrail while reversing.', status: 'confirmed', source: 'claimant' },
      },
      dynamic_form: {
        selected_family: 'motor',
        claim_revision: 2,
        requirements: {
          ready: false,
          current_action_total: 3,
          current_action_satisfied: 3,
          satisfied: ['incident.injury_or_danger', 'vehicle.drivable', 'incident.cause'],
          next_required_item: null,
          pending_later: [],
          missing_required_now: [],
        },
        fields: [],
        form: {},
      },
    }
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({
      items: [{ ...claimWithBooleanFields, can_resume: true }],
      page: { next_cursor: null },
    })
    api.resumeClaimSession.mockResolvedValue({
      session_id: 'ses_ui_vp',
      model_profile_id: 'qwen-local',
      started_at: '2026-09-10T01:00:02Z',
      resume: {
        customer_next_step: claimWithBooleanFields.customer_next_step,
        summary: 'My car was rear-ended.',
        pending_items: [],
        prior_commitments: [],
      },
    })
    api.getClaim.mockResolvedValue(claimWithBooleanFields)
    api.getClaimMessages.mockResolvedValue({ items: [claimantMessage, agentMessage] })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(await screen.findByRole('button', { name: /Open Home claim/ }))

    await screen.findByRole('heading', { name: 'Claim details' })

    // A boolean value must read as Yes/No, never the raw JavaScript "true"/"false" string.
    expect(screen.getByText('Yes')).toBeVisible()
    expect(screen.getByText('No')).toBeVisible()
    expect(screen.queryByText('true')).not.toBeInTheDocument()
    expect(screen.queryByText('false')).not.toBeInTheDocument()

    // A registered field without an explicit label must still show something readable,
    // not the bare last segment of its field code.
    expect(screen.getAllByText('Cause').length).toBeGreaterThan(0)
  })


  it('uses the backend agreement primary action when supporting projections disagree', async () => {
    const user = userEvent.setup()
    const externalServiceAction = {
      service_identity: 'vehicle_damage_assessment_routing',
      service_name: 'Vehicle damage assessment',
      provider: 'Controlled assessment fixture',
      purpose: 'Request a vehicle damage assessment.',
      shared_data_summary: ['Your confirmed incident region'],
      status: 'consent_required',
      can_request: true,
    }

    api.createClaim.mockResolvedValue({
      claim: {
        ...initialClaim,
        external_service_action: externalServiceAction,
        primary_action: primaryAction({
          actionCode: 'claimant.request_assessment',
          actionType: 'external_service',
          available: true,
          requiredInputs: ['claimant_consent'],
          targetRef: 'vehicle_damage_assessment_routing',
        }),
      },
      session: { session_id: 'ses_ui_vp', model_profile_id: 'qwen-local' },
    })

    api.submitClaimMessage.mockResolvedValue({
      ...initialTurn(),
      decision: {
        customer_next_step: {
          status: 'agreement_required',
          summary: 'Continue to agreement and confirmation.',
          required_items: [],
        },
      },
      primary_action: primaryAction({
        actionCode: 'claimant.review_agreement',
        available: true,
        revision: 2,
      }),
    })

    render(<App />)
    await user.type(
      screen.getByPlaceholderText('Tell us what happened…'),
      'My car was damaged.',
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)

    expect(screen.getByRole('button', {
      name: /Agreement & confirmation/i,
    })).toBeInTheDocument()

    expect(screen.queryByRole('button', {
      name: /Request a vehicle damage assessment/i,
    })).not.toBeInTheDocument()
  })

  it('keeps a message-bound service offer when no legacy Claim action exists', async () => {
    const user = userEvent.setup()
    const messageAction = {
      offer_id: 'offer-assessor-1',
      agent_message_id: agentMessage.message_id,
      service_identity: 'vehicle_damage_assessment_routing',
      service_name: 'Vehicle damage assessment',
      provider: 'Northwind assessment service',
      purpose: 'Arrange a vehicle damage assessment.',
      shared_data_summary: ['Your confirmed incident region'],
      consent_status: 'not_recorded',
      status: 'consent_required',
      routing: null,
      failure_code: null,
      can_request: true,
    }
    api.createClaim.mockResolvedValue({
      claim: { ...initialClaim, external_service_action: null },
      session: { session_id: 'ses_ui_vp', model_profile_id: 'qwen-local' },
    })
    api.submitClaimMessage.mockResolvedValue({
      ...initialTurn(),
      agent_message: { ...agentMessage, message_actions: [messageAction] },
      primary_action: primaryAction({
        actionCode: 'claimant.request_assessment',
        actionType: 'external_service',
        available: true,
        requiredInputs: ['claimant_consent'],
        revision: 2,
        targetRef: 'vehicle_damage_assessment_routing',
      }),
    })

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'Please arrange an assessor.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    expect(await screen.findByRole('button', {
      name: /Vehicle damage assessment/i,
    })).toBeInTheDocument()
    expect(screen.getByText(agentMessage.content.text)).toBeInTheDocument()
  })

  it('uses backend-required items for the review action instead of local field counts', async () => {
    const user = userEvent.setup()
    api.submitClaimMessage.mockResolvedValue({
      ...initialTurn(),
      form_changes: [{
        field_code: 'incident.occurred_at',
        field: {
          value: '8pm',
          status: 'proposed',
          source: 'claimant',
        },
      }],
      decision: {
        customer_next_step: {
          status: 'confirmation_required',
          summary: 'Review the proposed incident facts.',
          required_items: ['incident.occurred_at', 'incident.location'],
        },
      },
      primary_action: primaryAction({
        actionCode: 'claimant.review_details',
        available: true,
        requiredInputs: ['incident.occurred_at', 'incident.location'],
        revision: 2,
      }),
    })

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    expect(await screen.findByRole('button', { name: /Review claim details/i })).toBeInTheDocument()
    expect(screen.getByText('2 to review')).toBeInTheDocument()
  })

  it('uses the claimant-safe Incident type label in the details review', async () => {
    const user = userEvent.setup()
    api.submitClaimMessage.mockResolvedValue({
      ...initialTurn(),
      form_changes: [{
        field_code: 'incident.type',
        field: {
          value: 'water',
          status: 'proposed',
          source: 'claimant',
        },
      }],
    })

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    expect(await screen.findByText('Incident type needs your review.')).toBeVisible()
    expect(screen.queryByText('type needs your review.')).not.toBeInTheDocument()
  })

  it('renders backend dynamic requirements and re-renders a corrected field', async () => {
    const user = userEvent.setup()
    api.submitClaimMessage.mockResolvedValue({
      claimant_message: claimantMessage,
      agent_message: agentMessage,
      form_changes: [{
        field_code: 'incident.occurred_at',
        field: dynamicForm().form['incident.occurred_at'],
      }],
      contents_item_changes: [],
      dynamic_form: dynamicForm(),
      claim_revision: 2,
      decision: {
        customer_next_step: {
          status: 'more_information_needed',
          summary: 'Add the affected property address',
          required_items: ['property.address'],
        },
      },
    })
    api.updateClaimField.mockResolvedValue({
      revision: 3,
      updated_fields: {
        'incident.occurred_at': {
          value: '9pm',
          status: 'confirmed',
          source: 'claimant',
        },
      },
      dynamic_form: dynamicForm({ value: '9pm', valueState: 'confirmed' }),
      customer_next_step: {
        status: 'more_information_needed',
        summary: 'Add the affected property address',
        required_items: ['property.address'],
      },
    })

    render(<App />)
    const input = screen.getByPlaceholderText('Tell us what happened…')
    await user.type(input, 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    await waitFor(() => expect(screen.getAllByText('When it happened').length).toBeGreaterThan(0))
    expect(screen.queryByRole('button', { name: /Review claim details/i })).not.toBeInTheDocument()
    const progress = screen.getByRole('button', {
      name: /Claim progress: 1 of 2 required details complete/i,
    })
    expect(progress).toHaveAttribute('aria-expanded', 'false')
    const requirements = screen.getByRole('list', { name: 'Claim requirements', hidden: true })
    expect(requirements).not.toBeVisible()
    await user.click(progress)
    expect(progress).toHaveAttribute('aria-expanded', 'true')
    expect(requirements).toBeVisible()
    expect(requirements).toHaveTextContent('Complete: What happened')
    expect(requirements).toHaveTextContent('Required: When it happened')
    expect(requirements).toHaveTextContent('Needed later')
    await user.click(progress)
    expect(progress).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Needed later: Affected property')).not.toBeInTheDocument()
    expect(screen.getAllByText('8pm').length).toBeGreaterThan(0)

    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const correction = screen.getByRole('textbox', { name: 'Correct When it happened' })
    await user.clear(correction)
    await user.type(correction, '9pm')
    await user.click(screen.getByRole('button', { name: 'Save correction' }))

    await waitFor(() => expect(api.updateClaimField).toHaveBeenCalledWith(expect.objectContaining({
      claimId: 'clm_ui_vp',
      fieldCode: 'incident.occurred_at',
      value: '9pm',
      revision: 2,
    })))
    expect(await screen.findByText('9pm')).toBeInTheDocument()
    expect(screen.queryByText('Add the affected property address')).not.toBeInTheDocument()
    expect(screen.getByRole('button', {
      name: /Claim progress: 1 of 2 required details complete/i,
    })).toHaveAttribute('aria-expanded', 'false')
  })

  it.each([true, false])('installs the current snapshot and suppresses stale replay actions (readback succeeds: %s)', async (readbackSucceeds) => {
    const user = userEvent.setup()
    const currentDynamicForm = dynamicForm({ value: '9pm', valueState: 'confirmed' })
    const historicalAction = {
      offer_id: 'offer-assessor-replay',
      agent_message_id: agentMessage.message_id,
      service_identity: 'vehicle_damage_assessment_routing',
      service_name: 'Vehicle damage assessment',
      provider: 'Northwind assessment service',
      purpose: 'Arrange a vehicle damage assessment.',
      shared_data_summary: ['Your confirmed incident region'],
      consent_status: 'not_recorded',
      status: 'consent_required',
      routing: null,
      failure_code: null,
      can_request: true,
    }
    let resolveHistory
    let rejectHistory
    api.getClaimMessages.mockReturnValue(new Promise((resolve, reject) => {
      resolveHistory = resolve
      rejectHistory = reject
    }))
    api.submitClaimMessage.mockResolvedValue({
      ...initialTurn(),
      agent_message: { ...agentMessage, message_actions: [historicalAction] },
      claim_revision: 2,
      current_claim_revision: 3,
      form_changes: [{
        field_code: 'incident.occurred_at',
        field: {
          value: '8pm',
          status: 'proposed',
          source: 'claimant',
        },
      }],
      contents_item_changes: [{
        item_id: 'item-historical',
        description: 'Historical laptop description',
        category: 'Electronics',
        status: 'proposed',
        source: 'claimant',
      }],
      current_claim: {
        ...initialClaim,
        revision: 3,
        form: {
          'incident.occurred_at': {
            value: '9pm',
            status: 'confirmed',
            source: 'claimant',
          },
        },
        contents_items: [{
          item_id: 'item-current',
          description: 'Corrected laptop description',
          category: 'Electronics',
          status: 'confirmed',
          source: 'claimant',
        }],
        dynamic_form: currentDynamicForm,
        customer_next_step: {
          status: 'continue_current_report',
          summary: 'Continue from the corrected report.',
          responsible_party: 'claimant',
          required_items: [],
        },
        primary_action: primaryAction({ revision: 3 }),
        updated_at: '2026-09-14T02:00:00Z',
      },
    })

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    await waitFor(() => expect(api.getClaimMessages).toHaveBeenCalledWith(initialClaim.claim_id, 'ses_ui_vp'))
    expect(screen.queryByText('Permission needed')).not.toBeInTheDocument()
    await act(async () => {
      if (readbackSucceeds) {
        resolveHistory({ items: [claimantMessage, {
          ...agentMessage,
          message_actions: [{
            ...historicalAction,
            consent_status: 'withdrawn',
            status: 'consent_withdrawn',
            can_request: false,
          }],
        }] })
      } else {
        rejectHistory(new Error('History unavailable'))
      }
    })
    if (readbackSucceeds) {
      expect(await screen.findByText('Permission withdrawn')).toBeInTheDocument()
    } else {
      expect(await screen.findByText(/Your message is saved, but current service actions could not be refreshed/)).toBeInTheDocument()
      expect(screen.queryByText(/We could not confirm delivery/)).not.toBeInTheDocument()
    }
    expect(screen.queryByText('Permission needed')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Details' }))

    expect(screen.getAllByText('9pm').length).toBeGreaterThan(0)
    expect(screen.getByText('Corrected laptop description')).toBeInTheDocument()
    expect(screen.queryByText('8pm')).not.toBeInTheDocument()
    expect(screen.queryByText('Historical laptop description')).not.toBeInTheDocument()
  })

  it('rejects delayed realtime Claim and message readbacks after a newer claimant mutation', async () => {
    const user = userEvent.setup()
    let pushRealtime
    let resolveClaimReadback
    let resolveMessagesReadback
    const delayedClaimReadback = new Promise((resolve) => {
      resolveClaimReadback = resolve
    })
    const delayedMessagesReadback = new Promise((resolve) => {
      resolveMessagesReadback = resolve
    })
    api.streamRealtimeEvents.mockImplementation(({ onEvent }) => {
      pushRealtime = onEvent
      return new Promise(() => {})
    })

    const newerClaimantMessage = {
      ...claimantMessage,
      message_id: 'msg_claimant_newer',
      content: { type: 'text', text: 'The water is still running.' },
      created_at: '2026-09-10T01:01:00Z',
    }
    const newerAgentMessage = {
      ...agentMessage,
      message_id: 'msg_agent_newer',
      content: { type: 'text', text: 'I have kept that newer update.' },
      created_at: '2026-09-10T01:01:01Z',
    }
    api.submitClaimMessage
      .mockResolvedValueOnce(initialTurn())
      .mockResolvedValueOnce({
        ...initialTurn(),
        claimant_message: newerClaimantMessage,
        agent_message: newerAgentMessage,
        claim_revision: 3,
        decision: {
          customer_next_step: {
            status: 'confirmation_required',
            summary: 'Review the newest details.',
            required_items: ['incident.description'],
          },
        },
        primary_action: primaryAction({
          actionCode: 'claimant.review_details',
          available: true,
          requiredInputs: ['incident.description'],
          revision: 3,
        }),
      })

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    await waitFor(() => expect(pushRealtime).toBeTypeOf('function'))

    api.getClaim.mockReturnValueOnce(delayedClaimReadback)
    api.getClaimMessages.mockReturnValueOnce(delayedMessagesReadback)

    let realtimeRefresh
    await act(async () => {
      realtimeRefresh = pushRealtime(realtimeChange(2))
      await Promise.resolve()
    })
    await waitFor(() => expect(api.getClaim).toHaveBeenCalledWith(initialClaim.claim_id))
    await waitFor(() => expect(api.getClaimMessages).toHaveBeenCalledWith(
      initialClaim.claim_id,
      'ses_ui_vp',
    ))

    await user.type(
      screen.getByPlaceholderText('Write the details you know...'),
      newerClaimantMessage.content.text,
    )
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText(newerAgentMessage.content.text)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Review claim details/i })).toBeInTheDocument()

    await act(async () => {
      resolveClaimReadback({
        ...initialClaim,
        revision: 2,
        primary_action: primaryAction({ revision: 2 }),
      })
      resolveMessagesReadback({ items: [claimantMessage, agentMessage] })
      await realtimeRefresh
    })

    expect(screen.getByText(newerClaimantMessage.content.text)).toBeInTheDocument()
    expect(screen.getByText(newerAgentMessage.content.text)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Review claim details/i })).toBeInTheDocument()
  })

  it('opens a no-cursor claimant stream before taking the startup snapshot', async () => {
    const user = userEvent.setup()
    let streamOpened = false
    let snapshotObservedOpen = false

    api.streamRealtimeEvents.mockImplementation(({ cursor, onOpen, signal }) => {
      expect(cursor).toBeNull()
      streamOpened = true
      return (async () => {
        await onOpen?.()
        await new Promise((resolve) => {
          signal.addEventListener('abort', resolve, { once: true })
        })
      })()
    })
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.getClaim.mockImplementation(async () => {
      snapshotObservedOpen = streamOpened
      return {
        ...initialClaim,
        revision: 2,
        primary_action: primaryAction({ revision: 2 }),
      }
    })
    api.getClaimMessages.mockResolvedValue({
      items: [claimantMessage, agentMessage],
    })

    render(<App />)

    const incidentInput = screen.getByLabelText('Incident description')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Model' })).toBeEnabled()
    })

    await user.type(
      incidentInput,
      'A pipe burst in the kitchen.',
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    await waitFor(() => expect(api.streamRealtimeEvents).toHaveBeenCalled())
    await waitFor(() => expect(api.getClaim).toHaveBeenCalledWith(initialClaim.claim_id))

    expect(snapshotObservedOpen).toBe(true)
    expect(api.streamRealtimeEvents.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        cursor: null,
        onOpen: expect.any(Function),
      }),
    )
  })

  it('shows a generic reconnecting warning after claimant realtime transport failure', async () => {
    const user = userEvent.setup()
    let rejectCurrentStream

    api.streamRealtimeEvents.mockImplementation(({ onOpen, signal }) => (async () => {
      await onOpen?.()
      await new Promise((resolve, reject) => {
        rejectCurrentStream = reject
        signal.addEventListener('abort', resolve, { once: true })
      })
    })())
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.getClaim.mockResolvedValue({
      ...initialClaim,
      revision: 2,
      primary_action: primaryAction({ revision: 2 }),
    })
    api.getClaimMessages.mockResolvedValue({ items: [claimantMessage, agentMessage] })

    const { unmount } = render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    await waitFor(() => expect(rejectCurrentStream).toBeTypeOf('function'))

    await act(async () => {
      rejectCurrentStream(new Error('realtime transport disconnected'))
      await Promise.resolve()
    })

    expect(await screen.findByRole('status', {
      name: /Live updates are reconnecting\. Some claim information may be out of date/i,
    })).toBeInTheDocument()
    expect(screen.queryByText(/Live file status updates are temporarily disconnected/i)).not.toBeInTheDocument()

    unmount()
  })

  it('marks a cleanly ended claimant realtime stream as reconnecting', async () => {
    const user = userEvent.setup()
    let finishCurrentStream

    api.streamRealtimeEvents.mockImplementation(({ onOpen, signal }) => (async () => {
      await onOpen?.()
      await new Promise((resolve) => {
        finishCurrentStream = resolve
        signal.addEventListener('abort', resolve, { once: true })
      })
    })())
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.getClaim.mockResolvedValue({
      ...initialClaim,
      revision: 2,
      primary_action: primaryAction({ revision: 2 }),
    })
    api.getClaimMessages.mockResolvedValue({ items: [claimantMessage, agentMessage] })

    const { unmount } = render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    await waitFor(() => expect(finishCurrentStream).toBeTypeOf('function'))

    await act(async () => {
      finishCurrentStream()
      await Promise.resolve()
    })

    expect(await screen.findByRole('status', {
      name: /Live updates are reconnecting\. Some claim information may be out of date/i,
    })).toBeInTheDocument()

    unmount()
  })

  it('opens a replacement claimant stream before the resync snapshot and applies a buffered mutation', async () => {
    const user = userEvent.setup()
    let firstOnEvent
    let finishFirstStream
    let streamAttempt = 0
    let replacementOpened = false
    let resolveRecoveryMessages

    api.streamRealtimeEvents.mockImplementation(({ onEvent, onOpen, signal }) => {
      streamAttempt += 1
      if (streamAttempt === 1) {
        firstOnEvent = onEvent
        return new Promise((resolve) => {
          finishFirstStream = resolve
          signal.addEventListener('abort', resolve, { once: true })
        })
      }

      replacementOpened = true
      return (async () => {
        await onOpen?.()
        await onEvent(realtimeChange(3, ['claim']))
        await new Promise((resolve) => {
          signal.addEventListener('abort', resolve, { once: true })
        })
      })()
    })
    api.submitClaimMessage.mockResolvedValue(initialTurn())

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    await waitFor(() => expect(firstOnEvent).toBeTypeOf('function'))

    const snapshotBeforeBufferedMutation = {
      ...initialClaim,
      revision: 2,
      primary_action: primaryAction({ revision: 2 }),
    }
    const afterBufferedMutation = {
      ...initialClaim,
      revision: 3,
      customer_next_step: {
        status: 'confirmation_required',
        summary: 'Review the buffered update.',
        required_items: ['incident.description'],
      },
      primary_action: primaryAction({
        actionCode: 'claimant.review_details',
        available: true,
        requiredInputs: ['incident.description'],
        revision: 3,
      }),
    }
    api.getClaim
      .mockResolvedValueOnce(snapshotBeforeBufferedMutation)
      .mockResolvedValueOnce(afterBufferedMutation)
    api.getClaimMessages.mockReturnValueOnce(new Promise((resolve) => {
      resolveRecoveryMessages = resolve
    }))

    await act(async () => {
      await firstOnEvent({
        type: 'resync_required',
        cursor: null,
        data: { reason: 'replay_gap' },
      })
    })
    expect(await screen.findByRole('status', {
      name: /Live updates need to be resynchronised\. Some claim information may be out of date/i,
    })).toBeInTheDocument()

    await act(async () => { finishFirstStream() })
    await waitFor(() => expect(replacementOpened).toBe(true))
    await waitFor(() => expect(resolveRecoveryMessages).toBeTypeOf('function'))
    expect(screen.getByRole('status', {
      name: /Live updates need to be resynchronised\. Some claim information may be out of date/i,
    })).toBeInTheDocument()
    await act(async () => {
      resolveRecoveryMessages({ items: [claimantMessage, agentMessage] })
    })
    await waitFor(() => expect(api.streamRealtimeEvents).toHaveBeenCalledTimes(2))
    expect(api.streamRealtimeEvents.mock.calls[1][0]).toEqual(expect.objectContaining({
      cursor: null,
      onOpen: expect.any(Function),
    }))
    expect(await screen.findByRole('button', { name: /Review claim details/i })).toBeInTheDocument()
    expect(api.getClaim).toHaveBeenCalledTimes(2)
    await waitFor(() => expect(screen.queryByRole('status', {
      name: /Live updates need to be resynchronised/i,
    })).not.toBeInTheDocument())
  })

  it('keeps INVALID_EVENT_CURSOR stale until Claim and message recovery succeeds', async () => {
    const user = userEvent.setup()
    let streamAttempt = 0
    let replacementOpened = false
    let resolveRecoveryMessages

    api.streamRealtimeEvents.mockImplementation(({ onOpen, onCursor, signal }) => {
      streamAttempt += 1
      if (streamAttempt === 1) {
        return (async () => {
          await onOpen?.()
          onCursor?.('cursor-before-invalid')
          throw Object.assign(
            new api.ApiRequestError('The realtime cursor is no longer available.'),
            { code: 'INVALID_EVENT_CURSOR', status: 409, retryable: true },
          )
        })()
      }

      replacementOpened = true
      return (async () => {
        await onOpen?.()
        await new Promise((resolve) => {
          signal.addEventListener('abort', resolve, { once: true })
        })
      })()
    })
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.getClaim
      .mockResolvedValueOnce({
        ...initialClaim,
        revision: 2,
        primary_action: primaryAction({ revision: 2 }),
      })
      .mockResolvedValueOnce({
        ...initialClaim,
        revision: 2,
        primary_action: primaryAction({ revision: 2 }),
      })
    api.getClaimMessages
      .mockResolvedValueOnce({ items: [claimantMessage, agentMessage] })
      .mockReturnValueOnce(new Promise((resolve) => {
        resolveRecoveryMessages = resolve
      }))

    const { unmount } = render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)

    await waitFor(() => expect(replacementOpened).toBe(true))
    await waitFor(() => expect(resolveRecoveryMessages).toBeTypeOf('function'))
    expect(api.streamRealtimeEvents.mock.calls[1][0]).toEqual(expect.objectContaining({
      cursor: null,
      onOpen: expect.any(Function),
    }))
    expect(screen.getByRole('status', {
      name: /Live updates need to be resynchronised\. Some claim information may be out of date/i,
    })).toBeInTheDocument()

    await act(async () => {
      resolveRecoveryMessages({ items: [claimantMessage, agentMessage] })
    })
    await waitFor(() => expect(screen.queryByRole('status', {
      name: /Live updates need to be resynchronised/i,
    })).not.toBeInTheDocument())

    unmount()
  })

  it('shows what to provide from the Evidence projection and supports keyboard tab navigation', async () => {
    const user = userEvent.setup()
    let pushEvidenceUpdate
    api.streamRealtimeEvents.mockImplementation(({ onEvent }) => {
      pushEvidenceUpdate = onEvent
      return new Promise(() => {})
    })
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.submitClaimMessage.mockResolvedValue({
      claimant_message: claimantMessage,
      agent_message: agentMessage,
      form_changes: [],
      contents_item_changes: [],
      dynamic_form: null,
      claim_revision: 2,
      decision: { customer_next_step: initialClaim.customer_next_step },
    })
    const requiredEvidence = {
      evidence_id: 'evd_required_document',
      kind: 'repair_quote',
      status: 'missing',
      file_status: 'awaiting_upload',
      needed_for: ['current_action'],
      claimant_note: 'A repair quote is needed for this step.',
    }
    const receivedEvidence = {
      ...requiredEvidence,
      status: 'received',
      file_status: 'ready',
      original_filename: 'repair-quote.pdf',
      media_type: 'application/pdf',
    }
    const processingEvidence = {
      ...receivedEvidence,
      file_status: 'processing',
    }
    api.getClaimEvidence.mockResolvedValueOnce({
      claim_id: initialClaim.claim_id,
      revision: 2,
      items: [requiredEvidence],
    }).mockResolvedValue({
      claim_id: initialClaim.claim_id,
      revision: 4,
      items: [receivedEvidence],
    })
    api.requestEvidenceUpload.mockResolvedValue({
      evidence_id: requiredEvidence.evidence_id,
      revision: 3,
      upload: { method: 'PUT', url: '/upload-target', headers: {} },
    })
    api.uploadEvidenceContent.mockResolvedValue(undefined)
    api.completeEvidenceUpload.mockResolvedValue({
      revision: 4,
      evidence: processingEvidence,
    })

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    const summaryTab = await screen.findByRole('tab', { name: 'Summary' })
    const documentsTab = screen.getByRole('tab', { name: 'What to provide' })
    expect(summaryTab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('What we have so far')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'What to provide, 1 outstanding' })).toBeInTheDocument()

    summaryTab.focus()
    await user.keyboard('{ArrowRight}')
    expect(documentsTab).toHaveFocus()
    expect(documentsTab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('heading', { name: 'Documents and evidence' })).toBeInTheDocument()
    expect(screen.getByText('Repair quote')).toBeInTheDocument()
    expect(screen.getByText('0 of 1 provided')).toBeInTheDocument()
    expect(screen.queryByText(/needs your attention/)).not.toBeInTheDocument()

    await user.keyboard('{Home}')
    expect(summaryTab).toHaveFocus()
    expect(summaryTab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('What we have so far')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'What to provide, 1 outstanding' }))
    expect(documentsTab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('Repair quote')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Evidence history' })).not.toBeInTheDocument()

    const documentsPanel = screen.getByRole('tabpanel', { name: 'What to provide' })
    const uploadInput = documentsPanel.querySelector('input[type="file"]')
    await user.upload(
      uploadInput,
      new File(['quote'], 'repair-quote.pdf', { type: 'application/pdf' }),
    )

    await waitFor(() => expect(api.requestEvidenceUpload).toHaveBeenCalledWith(
      expect.objectContaining({
        claimId: initialClaim.claim_id,
        evidenceId: requiredEvidence.evidence_id,
        kind: requiredEvidence.kind,
      }),
    ))
    await waitFor(() => expect(pushEvidenceUpdate).toBeTypeOf('function'))
    await act(async () => pushEvidenceUpdate(realtimeChange(5, ['evidence'])))
    await waitFor(() => expect(api.getClaimEvidence).toHaveBeenCalledTimes(2))
    expect(await within(documentsPanel).findByText('repair-quote.pdf')).toBeInTheDocument()
    expect(within(documentsPanel).getByText('PDF · Upload complete')).toBeInTheDocument()
    expect(within(documentsPanel).getByText('1 of 1 provided')).toBeInTheDocument()
    expect(within(documentsPanel).queryByRole('button', { name: /Replace|Remove/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'What to provide' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /What to provide, .* outstanding/ })).not.toBeInTheDocument()
  })

  it('aborts an in-flight draft upload when its remove control is used', async () => {
    const user = userEvent.setup()
    let uploadSignal
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.requestEvidenceUpload.mockImplementation(({ signal }) => {
      uploadSignal = signal
      return new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      })
    })

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    const fileInput = document.querySelector('input[type="file"]')
    await user.upload(fileInput, new File(['image'], 'draft-damage.jpg', { type: 'image/jpeg' }))
    expect(await screen.findByText('draft-damage.jpg')).toBeInTheDocument()
    await waitFor(() => expect(uploadSignal).toBeInstanceOf(AbortSignal))

    await user.click(screen.getByRole('button', { name: 'Remove draft-damage.jpg' }))

    expect(uploadSignal.aborted).toBe(true)
    expect(screen.queryByText('draft-damage.jpg')).not.toBeInTheDocument()
    expect(api.uploadEvidenceContent).not.toHaveBeenCalled()
    expect(api.completeEvidenceUpload).not.toHaveBeenCalled()
  })

  it('removes a completed upload from the current composer selection', async () => {
    const user = userEvent.setup()
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.submitClaimMessage.mockResolvedValue(initialTurn())
    api.requestEvidenceUpload.mockResolvedValue({
      evidence_id: 'evd_detached_photo',
      revision: 3,
      upload: { method: 'PUT', url: '/upload-target', headers: {} },
    })
    api.uploadEvidenceContent.mockResolvedValue(undefined)
    api.completeEvidenceUpload.mockResolvedValue({
      revision: 4,
      evidence: {
        evidence_id: 'evd_detached_photo',
        claim_id: initialClaim.claim_id,
        kind: 'incident_photo',
        status: 'received',
        file_status: 'ready',
        original_filename: 'detached-damage.jpg',
        media_type: 'image/jpeg',
        size_bytes: 5,
        source: 'claimant',
        created_at: '2026-09-14T01:05:00Z',
        updated_at: '2026-09-14T01:06:00Z',
      },
    })

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    await user.upload(
      document.querySelector('input[type="file"]'),
      new File(['image'], 'detached-damage.jpg', { type: 'image/jpeg' }),
    )

    expect(await screen.findByText('Ready')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Remove detached-damage.jpg' }))

    expect(screen.queryByText('detached-damage.jpg')).not.toBeInTheDocument()
    expect(api.submitClaimMessage).toHaveBeenCalledTimes(1)
  })

  it('opens account Evidence history directly without creating an empty Claim', async () => {
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listEvidenceHistory.mockResolvedValue({
      items: [{
        evidence_id: 'evd_account_history',
        source_claim_id: 'clm_previous',
        kind: 'receipt',
        status: 'received',
        file_status: 'ready',
        original_filename: 'receipt.pdf',
        media_type: 'application/pdf',
        size_bytes: 2048,
        source: 'claimant',
        provenance_summary: ['claimant_upload'],
        can_reuse: true,
        can_remove: false,
        created_at: '2026-09-12T01:00:00Z',
        updated_at: '2026-09-12T01:01:00Z',
      }],
      page: { next_cursor: null },
    })
    globalThis.history.replaceState({}, '', '/files')

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Evidence history' })).toBeInTheDocument()
    expect(await screen.findByText('receipt.pdf')).toBeInTheDocument()
    expect(api.createClaim).not.toHaveBeenCalled()
  })

  it('uploads a staged file before the first message and shows it in the claimant bubble', async () => {
    const user = userEvent.setup()
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.submitClaimMessage.mockResolvedValue({
      ...initialTurn(),
      claimant_message: {
        ...claimantMessage,
        evidence_refs: ['evd_staged_photo'],
      },
      claim_revision: 5,
      primary_action: primaryAction({ revision: 5 }),
    })
    api.requestEvidenceUpload.mockResolvedValue({
      evidence_id: 'evd_staged_photo',
      revision: 3,
      upload: { method: 'PUT', url: '/upload-target', headers: {} },
    })
    api.uploadEvidenceContent.mockResolvedValue(undefined)
    api.completeEvidenceUpload.mockResolvedValue({
      revision: 4,
      evidence: {
        evidence_id: 'evd_staged_photo',
        claim_id: initialClaim.claim_id,
        kind: 'incident_photo',
        status: 'received',
        file_status: 'ready',
        original_filename: 'new-damage.jpg',
        media_type: 'image/jpeg',
        size_bytes: 5,
        source: 'claimant',
        created_at: '2026-09-14T01:05:00Z',
        updated_at: '2026-09-14T01:06:00Z',
      },
    })

    render(<App />)
    await user.upload(
      document.querySelector('input[type="file"]'),
      new File(['image'], 'new-damage.jpg', { type: 'image/jpeg' }),
    )
    expect(await screen.findByText('new-damage.jpg')).toBeInTheDocument()
    expect(screen.getByText('Ready to upload after your first message is sent')).toBeInTheDocument()
    expect(api.createClaim).not.toHaveBeenCalled()
    expect(api.requestEvidenceUpload).not.toHaveBeenCalled()
    expect(screen.queryByText('Conversation history')).not.toBeInTheDocument()

    expect(screen.getByRole('alert')).toHaveTextContent('This model cannot process images.')
    await user.click(screen.getByRole('button', { name: 'Model' }))
    await user.click(screen.getByRole('option', { name: /gemini-3\.5-flash-lite.*Supports images/ }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    await waitFor(() => expect(api.requestEvidenceUpload).toHaveBeenCalledWith(expect.objectContaining({
      claimId: initialClaim.claim_id,
      revision: 1,
    })))
    expect(api.createClaim).toHaveBeenCalledTimes(1)
    expect(api.submitClaimMessage).toHaveBeenCalledTimes(1)
    expect(api.requestEvidenceUpload.mock.invocationCallOrder[0])
      .toBeLessThan(api.submitClaimMessage.mock.invocationCallOrder[0])
    expect(api.submitClaimMessage).toHaveBeenCalledWith(expect.objectContaining({
      revision: 4,
      text: 'A pipe burst in the kitchen.',
      evidenceRefs: ['evd_staged_photo'],
    }))
    await waitFor(() => expect(document.querySelector('.composer-attachments')).not.toBeInTheDocument())
    const attachmentBubble = (await screen.findByText('new-damage.jpg')).closest('.user-bubble')
    expect(attachmentBubble).toHaveTextContent('A pipe burst in the kitchen.')
    expect(attachmentBubble).toHaveTextContent('Ready')
  })

  it('starts a Claim and sends an attachment without requiring message text', async () => {
    const user = userEvent.setup()
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.submitClaimMessage.mockResolvedValue({
      ...initialTurn(),
      claimant_message: {
        ...claimantMessage,
        content: { type: 'evidence_reference' },
        evidence_refs: ['evd_file_only'],
      },
      claim_revision: 5,
      primary_action: primaryAction({ revision: 5 }),
    })
    api.requestEvidenceUpload.mockResolvedValue({
      evidence_id: 'evd_file_only',
      revision: 3,
      upload: { method: 'PUT', url: '/upload-target', headers: {} },
    })
    api.uploadEvidenceContent.mockResolvedValue(undefined)
    api.completeEvidenceUpload.mockResolvedValue({
      revision: 4,
      evidence: {
        evidence_id: 'evd_file_only',
        claim_id: initialClaim.claim_id,
        kind: 'incident_photo',
        status: 'received',
        file_status: 'ready',
        original_filename: 'file-only-damage.jpg',
        media_type: 'image/jpeg',
        size_bytes: 5,
        source: 'claimant',
        created_at: '2026-09-14T01:05:00Z',
        updated_at: '2026-09-14T01:06:00Z',
      },
    })

    render(<App />)
    await user.upload(
      document.querySelector('input[type="file"]'),
      new File(['image'], 'file-only-damage.jpg', { type: 'image/jpeg' }),
    )
    const send = screen.getByRole('button', { name: 'Start claim' })
    const capabilityWarning = screen.getByRole('alert')
    expect(capabilityWarning).toHaveTextContent('This model cannot process images.')
    expect(capabilityWarning).toHaveTextContent('Your file is still attached.')
    expect(send).toBeDisabled()
    expect(api.createClaim).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Model' }))
    expect(screen.getByRole('option', { name: /qwen3\.8-27b.*Does not support images/ })).toBeDisabled()
    await user.click(screen.getByRole('option', { name: /gemini-3\.5-flash-lite.*Supports images/ }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(send).toBeEnabled()
    await user.click(send)

    await waitFor(() => expect(api.submitClaimMessage).toHaveBeenCalledWith(expect.objectContaining({
      revision: 4,
      text: '',
      evidenceRefs: ['evd_file_only'],
      modelProfileId: 'google-gemini35-flash-lite',
    })))
    await waitFor(() => expect(document.querySelector('.composer-attachments')).not.toBeInTheDocument())
    const attachmentBubble = (await screen.findByText('file-only-damage.jpg')).closest('.user-bubble')
    expect(attachmentBubble).toHaveTextContent('Ready')
    const preview = within(attachmentBubble).getByRole('link', {
      name: 'Open file-only-damage.jpg in a new tab',
    })
    expect(preview).toHaveAttribute('href', 'blob:app/file-only-damage.jpg')
    expect(preview.querySelector('img')).toHaveAttribute('src', 'blob:app/file-only-damage.jpg')
  })

  it('does not upload an attachment removed while Claim creation is pending', async () => {
    const user = userEvent.setup()
    const claimCreation = deferredRequest()
    enableAuthenticatedImageAttachments()
    api.createClaim.mockReturnValue(claimCreation.promise)

    render(<App />)
    await user.upload(
      document.querySelector('input[type="file"]'),
      new File(['image'], 'remove-before-claim.jpg', { type: 'image/jpeg' }),
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await waitFor(() => expect(api.createClaim).toHaveBeenCalledTimes(1))

    await user.click(screen.getByRole('button', { name: 'Remove remove-before-claim.jpg' }))
    await act(async () => claimCreation.resolve({
      claim: initialClaim,
      session: { session_id: 'ses_ui_vp', model_profile_id: 'qwen-local' },
    }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled())
    expect(api.requestEvidenceUpload).not.toHaveBeenCalled()
    expect(api.submitClaimMessage).not.toHaveBeenCalled()
    expect(document.querySelector('.composer-attachments')).not.toBeInTheDocument()
  })

  it('skips a later staged attachment removed while an earlier upload is pending', async () => {
    const user = userEvent.setup()
    const firstUploadRequest = deferredRequest()
    let requestSequence = 0
    enableAuthenticatedImageAttachments()
    api.requestId.mockImplementation((prefix) => `${prefix}-${++requestSequence}`)
    api.requestEvidenceUpload.mockReturnValueOnce(firstUploadRequest.promise)
    api.uploadEvidenceContent.mockResolvedValue(undefined)
    api.completeEvidenceUpload.mockResolvedValue({
      revision: 4,
      evidence: {
        evidence_id: 'evd_first_staged',
        claim_id: initialClaim.claim_id,
        kind: 'incident_photo',
        status: 'received',
        file_status: 'ready',
        original_filename: 'first-staged.jpg',
        media_type: 'image/jpeg',
        size_bytes: 5,
        source: 'claimant',
      },
    })
    api.submitClaimMessage.mockResolvedValue({
      ...initialTurn(),
      claimant_message: {
        ...claimantMessage,
        content: { type: 'evidence_reference' },
        evidence_refs: ['evd_first_staged'],
      },
      claim_revision: 5,
      primary_action: primaryAction({ revision: 5 }),
    })

    render(<App />)
    const fileInput = document.querySelector('input[type="file"]')
    await user.upload(fileInput, new File(['one'], 'first-staged.jpg', { type: 'image/jpeg' }))
    await user.upload(fileInput, new File(['two'], 'remove-from-queue.jpg', { type: 'image/jpeg' }))
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await waitFor(() => expect(api.requestEvidenceUpload).toHaveBeenCalledTimes(1))

    await user.click(screen.getByRole('button', { name: 'Remove remove-from-queue.jpg' }))
    await act(async () => firstUploadRequest.resolve({
      evidence_id: 'evd_first_staged',
      revision: 3,
      upload: { method: 'PUT', url: '/upload-target', headers: {} },
    }))

    await waitFor(() => expect(api.submitClaimMessage).toHaveBeenCalledTimes(1))
    expect(api.requestEvidenceUpload).toHaveBeenCalledTimes(1)
    expect(api.submitClaimMessage).toHaveBeenCalledWith(expect.objectContaining({
      evidenceRefs: ['evd_first_staged'],
    }))
  })

  it('aborts an active staged upload and does not send an empty attachment-only turn', async () => {
    const user = userEvent.setup()
    enableAuthenticatedImageAttachments()
    api.requestEvidenceUpload.mockResolvedValue({
      evidence_id: 'evd_cancelled_upload',
      revision: 3,
      upload: { method: 'PUT', url: '/upload-target', headers: {} },
    })
    api.uploadEvidenceContent.mockImplementation(({ signal }) => new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(
        Object.assign(new Error('Upload aborted'), { name: 'AbortError' }),
      ))
    }))

    render(<App />)
    await user.upload(
      document.querySelector('input[type="file"]'),
      new File(['image'], 'cancel-active-upload.jpg', { type: 'image/jpeg' }),
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await waitFor(() => expect(api.uploadEvidenceContent).toHaveBeenCalledTimes(1))

    await user.click(screen.getByRole('button', { name: 'Remove cancel-active-upload.jpg' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled())
    expect(api.submitClaimMessage).not.toHaveBeenCalled()
    expect(document.querySelector('.composer-attachments')).not.toBeInTheDocument()
  })

  it('keeps an uploaded image preview available when the model turn fails', async () => {
    const user = userEvent.setup()
    api.getRuntimeCapabilities.mockResolvedValue({
      claim_types: ['motor', 'home', 'contents'],
      models: [
        {
          id: 'qwen-local',
          label: 'qwen3.8-27b',
          availability: 'available',
          image_input: true,
          document_input: false,
        },
        {
          id: 'nowcoding-gpt55',
          label: 'gpt-5.5',
          availability: 'available',
          image_input: true,
          document_input: false,
        },
      ],
      default_model_profile_id: 'qwen-local',
    })
    let requestSequence = 0
    api.requestId.mockImplementation((prefix) => `${prefix}-${++requestSequence}`)
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.requestEvidenceUpload.mockResolvedValue({
      evidence_id: 'evd_failed_turn_photo',
      revision: 3,
      upload: { method: 'PUT', url: '/upload-target', headers: {} },
    })
    api.uploadEvidenceContent.mockResolvedValue(undefined)
    api.completeEvidenceUpload.mockResolvedValue({
      revision: 4,
      evidence: {
        evidence_id: 'evd_failed_turn_photo',
        claim_id: initialClaim.claim_id,
        kind: 'incident_photo',
        status: 'received',
        file_status: 'processing',
        original_filename: 'failed-turn-photo.png',
        media_type: 'image/png',
        size_bytes: 5,
        source: 'claimant',
        created_at: '2026-09-14T01:05:00Z',
        updated_at: '2026-09-14T01:06:00Z',
      },
    })
    api.submitClaimMessage.mockRejectedValue(Object.assign(
      new api.ApiRequestError('The model service could not complete the request. The claim is unchanged.'),
      { code: 'DEPENDENCY_FAILED', status: 502, retryable: false },
    ))

    render(<App />)
    await user.upload(
      document.querySelector('input[type="file"]'),
      new File(['image'], 'failed-turn-photo.png', { type: 'image/png' }),
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    const failureDetail = await screen.findByText(
      'The model service could not complete the request. The claim is unchanged. Your file upload is preserved and remains attached. Retry the message, or select another available model and retry.',
    )
    const failureCard = failureDetail.closest('[role="alert"]')
    expect(failureCard).toHaveTextContent('Not sent')
    expect(failureCard).toHaveTextContent('Processing')
    const failedPreview = within(failureCard).getByRole('link', {
      name: 'Open failed-turn-photo.png in a new tab',
    })
    expect(failedPreview).toHaveAttribute('href', 'blob:app/failed-turn-photo.png')
    expect(failedPreview).toHaveAttribute('target', '_blank')
    expect(failedPreview.querySelector('img')).toHaveAttribute('src', 'blob:app/failed-turn-photo.png')

    const firstAttempt = api.submitClaimMessage.mock.calls[0][0]
    await user.click(screen.getByRole('button', { name: 'Retry message' }))
    await waitFor(() => expect(api.submitClaimMessage).toHaveBeenCalledTimes(2))
    const safeRetry = api.submitClaimMessage.mock.calls[1][0]
    expect(safeRetry.idempotencyKey).toBe(firstAttempt.idempotencyKey)
    expect(safeRetry.clientMessageId).toBe(firstAttempt.clientMessageId)

    await user.click(screen.getByRole('button', { name: 'Model' }))
    await user.click(screen.getByRole('option', { name: /^gpt-5\.5/ }))
    await user.click(screen.getByRole('button', { name: 'Retry message' }))
    await waitFor(() => expect(api.submitClaimMessage).toHaveBeenCalledTimes(3))
    const changedModelAttempt = api.submitClaimMessage.mock.calls[2][0]
    expect(changedModelAttempt.modelProfileId).toBe('nowcoding-gpt55')
    expect(changedModelAttempt.idempotencyKey).not.toBe(firstAttempt.idempotencyKey)
    expect(changedModelAttempt.clientMessageId).not.toBe(firstAttempt.clientMessageId)
  })

  it('does not resurface Evidence already sent with an earlier message in the composer tray', async () => {
    const user = userEvent.setup()
    const historicalClaimantMessage = {
      ...claimantMessage,
      evidence_refs: ['evd_already_sent'],
    }
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({
      items: [{ ...initialClaim, can_resume: true }],
      page: { next_cursor: null },
    })
    api.resumeClaimSession.mockResolvedValue({
      session_id: 'ses_ui_vp',
      model_profile_id: 'qwen-local',
      started_at: '2026-09-10T01:00:02Z',
      resume: {
        customer_next_step: initialClaim.customer_next_step,
        summary: 'A pipe burst in the kitchen.',
        pending_items: [],
        prior_commitments: [],
      },
    })
    api.getClaim.mockResolvedValue(initialClaim)
    api.getClaimMessages.mockResolvedValue({ items: [historicalClaimantMessage, agentMessage] })
    api.getClaimEvidence.mockResolvedValue({
      revision: 1,
      items: [{
        evidence_id: 'evd_already_sent',
        claim_id: initialClaim.claim_id,
        kind: 'incident_photo',
        status: 'received',
        file_status: 'ready',
        original_filename: 'already-sent.jpg',
        media_type: 'image/jpeg',
        size_bytes: 5,
        source: 'claimant',
        created_at: '2026-09-10T00:59:00Z',
        updated_at: '2026-09-10T00:59:00Z',
      }],
    })
    api.submitClaimMessage.mockResolvedValue({
      claimant_message: {
        ...claimantMessage,
        message_id: 'msg_follow_up',
        content: { type: 'text', text: 'One more detail.' },
      },
      agent_message: agentMessage,
      form_changes: [],
      contents_item_changes: [],
      dynamic_form: null,
      claim_revision: 2,
      decision: { customer_next_step: initialClaim.customer_next_step },
    })

    const { container } = render(<App />)
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(await screen.findByRole('button', { name: /Open Home claim/ }))

    await screen.findByPlaceholderText('Write the details you know...')
    // Evidence sent on an earlier message is historical: it must never sit
    // in the composer tray as if it were staged to ride the next message.
    expect((await screen.findByText('already-sent.jpg')).closest('.user-bubble')).not.toBeNull()
    expect(container.querySelector('.composer-attachments')).not.toBeInTheDocument()

    await user.type(screen.getByPlaceholderText('Write the details you know...'), 'One more detail.')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(api.submitClaimMessage).toHaveBeenCalledTimes(1))
    expect(api.submitClaimMessage).toHaveBeenCalledWith(expect.objectContaining({
      evidenceRefs: [],
    }))
  })

  it('restores a protected Claim Evidence deep link without creating or resuming a Claim', async () => {
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({
      items: [{ ...initialClaim, can_resume: true }],
      page: { next_cursor: null },
    })
    api.getClaimEvidence.mockResolvedValue({
      claim_id: initialClaim.claim_id,
      revision: 1,
      items: [{
        evidence_id: 'evd_deep_link',
        claim_id: initialClaim.claim_id,
        kind: 'repair_quote',
        status: 'received',
        file_status: 'ready',
        original_filename: 'repair-quote.pdf',
        media_type: 'application/pdf',
        size_bytes: 4096,
        source: 'claimant',
        created_at: '2026-09-14T01:05:00Z',
        updated_at: '2026-09-14T01:06:00Z',
      }],
      customer_next_step: initialClaim.customer_next_step,
    })
    globalThis.history.replaceState({}, '', `/account/claims/${initialClaim.claim_id}/evidence`)

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Evidence history' })).toBeInTheDocument()
    expect(await screen.findByText('repair-quote.pdf')).toBeInTheDocument()
    expect(api.createClaim).not.toHaveBeenCalled()
    expect(api.resumeClaimSession).not.toHaveBeenCalled()
  })

  it('continues the current report from the in-workspace Claim history', async () => {
    const user = userEvent.setup()
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.submitClaimMessage.mockResolvedValue(initialTurn())

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    await user.click(screen.getByRole('button', { name: 'Claim history' }))
    expect(await screen.findByRole('heading', { name: 'Your report is underway' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Continue report' }))

    expect(screen.queryByRole('heading', { name: 'Claim history' })).not.toBeInTheDocument()
    expect(screen.getByText(agentMessage.content.text)).toBeInTheDocument()
  })

  it('keeps account Claim history navigable after leaving an active conversation', async () => {
    const user = userEvent.setup()
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    const createdClaim = {
      ...initialClaim,
      claim_id: 'clm_created_after_leaving',
      external_claim: { claim_number: 'NWF-2026-000973', creation_status: 'created' },
      customer_next_step: {
        status: 'claim_created',
        summary: 'Claims intake review',
        responsible_party: 'system',
      },
      updated_at: '2026-09-14T01:00:00Z',
      can_resume: true,
    }
    const reportInProgress = {
      ...initialClaim,
      claim_id: 'clm_in_progress_history',
      external_claim: null,
      updated_at: '2026-09-15T01:00:00Z',
      can_resume: true,
    }
    api.listClaims.mockResolvedValue({ items: [reportInProgress, createdClaim], page: { next_cursor: null } })
    api.submitClaimMessage.mockResolvedValue(initialTurn())

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)
    // The conversation stays loaded while the claimant leaves it for the account pages.
    await user.click(screen.getByRole('button', { name: 'Back to start' }))
    await user.click(screen.getByRole('button', { name: 'Profile' }))
    // The desktop navigation and the mobile index both render the same Claim history entry.
    const [claimHistoryEntry] = await screen.findAllByRole('button', { name: 'Claim history' })
    await user.click(claimHistoryEntry)
    expect(await screen.findByRole('heading', { name: 'Claim history' })).toBeInTheDocument()
    expect(screen.getByText('Track open claims and review your previous submissions.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Account' })).toHaveAttribute('href', '/profile')
    expect(screen.getByRole('button', { name: 'Start a new claim' })).toBeInTheDocument()
    const row = await screen.findByRole('button', { name: 'Open Home claim, Claim NWF-2026-000973' })
    // Only the created Claim is listed; the report in progress is promoted separately.
    expect(screen.getByText('1 claim')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Your report is underway' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /clm_in_progress_history|clm_ui_vp/ })).not.toBeInTheDocument()
    await user.click(row)

    expect(await screen.findByRole('heading', { name: 'Claim features' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'NWF-2026-000973' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Evidence history/ }))
    expect(await screen.findByRole('heading', { name: 'Evidence history' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Back to Claim features' }))
    await user.click(await screen.findByRole('button', { name: 'Back to Claim history' }))
    expect(await screen.findByRole('heading', { name: 'Claim history' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open Home claim, Claim NWF-2026-000973' })).toBeInTheDocument()
  })
})
