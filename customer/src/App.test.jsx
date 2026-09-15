import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const api = vi.hoisted(() => ({
  ApiRequestError: class ApiRequestError extends Error {},
  confirmClaimFields: vi.fn(),
  createExternalClaim: vi.fn(),
  createClaim: vi.fn(),
  grantAssessorConsent: vi.fn(),
  getAuthenticatedAccount: vi.fn(),
  hasClaimantAccessToken: vi.fn(),
  getClaim: vi.fn(),
  getClaimMessages: vi.fn(),
  getClaimEvidence: vi.fn(),
  getRuntimeCapabilities: vi.fn(),
  listClaims: vi.fn(),
  listEvidenceHistory: vi.fn(),
  loginClaimant: vi.fn(),
  logoutClaimant: vi.fn(),
  requestId: vi.fn((prefix) => `${prefix}-test`),
  requestHumanSupport: vi.fn(),
  promoteAnonymousClaim: vi.fn(),
  requestAssessorRouting: vi.fn(),
  registerClaimant: vi.fn(),
  requestEvidenceUpload: vi.fn(),
  uploadEvidenceContent: vi.fn(),
  completeEvidenceUpload: vi.fn(),
  resumeClaimSession: vi.fn(),
  startClaimSession: vi.fn(),
  streamClaimUpdates: vi.fn(() => new Promise(() => {})),
  submitClaimMessage: vi.fn(),
  setClaimantAccessToken: vi.fn(),
  updateAccountPreferences: vi.fn(),
  updateAccountProfile: vi.fn(),
  updateClaimField: vi.fn(),
}))

vi.mock('./api.js', () => api)

import App from './App.jsx'

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
  },
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
    globalThis.history.replaceState({}, '', '/')
    api.hasClaimantAccessToken.mockReturnValue(false)
    api.getRuntimeCapabilities.mockResolvedValue({
      claim_types: ['motor', 'home', 'contents'],
      models: [
        { id: 'qwen-local', label: 'qwen3.8-27b', availability: 'available' },
        { id: 'nowcoding-gpt55', label: 'gpt-5.5', availability: 'available' },
      ],
      default_model_profile_id: 'qwen-local',
    })
    api.getClaimEvidence.mockResolvedValue({ items: [], revision: 1 })
    api.listEvidenceHistory.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.createClaim.mockResolvedValue({
      claim: initialClaim,
      session: { session_id: 'ses_ui_vp', model_profile_id: 'qwen-local' },
    })
  })

  it('shows the backend default model before creating a session', async () => {
    const user = userEvent.setup()
    render(<App />)

    const model = await screen.findByRole('button', { name: 'Model' })
    expect(model).toBeEnabled()
    expect(model).toHaveTextContent('qwen3.8-27b')
    const claimType = screen.getByRole('button', { name: 'Claim type (optional)' })
    expect(claimType).toHaveTextContent('Let Agent identify')

    await user.click(model)
    expect(screen.getByRole('listbox', { name: 'Model' })).toBeInTheDocument()
    await user.click(screen.getByRole('option', { name: /gpt-5\.5.*nowcoding-gpt55/ }))
    expect(model).toHaveTextContent('gpt-5.5')

    await waitFor(() => expect(model).toHaveFocus())
    await user.keyboard('{ArrowDown}')
    const selectedGpt = screen.getByRole('option', {
      name: /gpt-5\.5.*nowcoding-gpt55/,
    })
    await waitFor(() => expect(selectedGpt).toHaveFocus())
    await user.keyboard('{Home}{Enter}')
    expect(model).toHaveTextContent('qwen3.8-27b')
    expect(screen.queryByRole('listbox', { name: 'Model' })).not.toBeInTheDocument()
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
    await user.click(screen.getByRole('button', { name: 'Create an account' }))
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

    expect(api.createClaim).toHaveBeenCalledWith(expect.objectContaining({ incidentType: null }))

    const failure = await screen.findByText(
      'The model service is temporarily unavailable. The claim is unchanged. Try again in a moment.',
    )
    expect(failure).toBeInTheDocument()
    expect(screen.getByText('Not sent')).toBeInTheDocument()
    expect(container.querySelector('.workspace-composer [role="alert"]')).toHaveTextContent(
      'The model service is temporarily unavailable. The claim is unchanged. Try again in a moment.',
    )
    expect(screen.queryByText('We could not confirm delivery. Please try again.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry message' })).toBeInTheDocument()
  })

  it('shows third-party support in a dismissible dialog with a compact reopen control', async () => {
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

    const dialog = await screen.findByRole('dialog', { name: 'Third-party services' })
    expect(dialog).toBeVisible()
    expect(container.querySelector('.message-list .service-capability-list')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Close third-party services' }))
    expect(screen.queryByRole('dialog', { name: 'Third-party services' })).not.toBeInTheDocument()

    const trigger = screen.getByRole('button', { name: /Third-party support/ })
    await waitFor(() => expect(trigger).toHaveFocus())
    await user.click(trigger)
    expect(await screen.findByRole('dialog', { name: 'Third-party services' })).toBeVisible()
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

    expect(screen.getByText('Understand insurance. Understand you better.')).toBeVisible()
    expect(globalThis.location.pathname).toBe('/')
    expect(screen.queryByText(agentMessage.content.text)).not.toBeInTheDocument()

    act(() => {
      globalThis.history.replaceState({}, '', `/claims/${initialClaim.claim_id}`)
      globalThis.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(await screen.findByText(agentMessage.content.text)).toBeVisible()
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

  it('replaces Staff assistance with a waiting status and prevents duplicate requests', async () => {
    const user = userEvent.setup()
    let resolveSupport
    api.submitClaimMessage.mockResolvedValue(initialTurn())
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
      revision: 2,
    }))
    expect(initialClaim.external_claim).toBeNull()
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
    api.streamClaimUpdates.mockImplementation(({ onEvent }) => {
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
    await act(async () => pushLiveUpdate({ claim_revision: 4 }))

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
    await act(async () => pushLiveUpdate({ claim_revision: 5 }))

    expect(await screen.findByRole('status', { name: /Your response is needed/ })).toBeInTheDocument()
    expect(screen.getByText(staffMessage.content.text)).toBeInTheDocument()
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
    await act(async () => pushLiveUpdate({ claim_revision: 7 }))

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
    api.streamClaimUpdates.mockImplementation(({ onEvent }) => {
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
    await user.click(await screen.findByRole('button', { name: 'Resume claim' }))

    expect(await screen.findByRole('status', { name: /Staff assistance completed/ })).toBeVisible()
    expect(screen.queryByRole('button', { name: /Where you left off/ })).not.toBeInTheDocument()
    await waitFor(() => expect(pushLiveUpdate).toBeTypeOf('function'))
    await act(async () => pushLiveUpdate({ claim_revision: 8 }))
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
    await user.click(await screen.findByRole('button', { name: 'Resume claim' }))

    expect(await screen.findByRole('button', { name: 'Staff assistance' })).toBeEnabled()
    expect(screen.queryByRole('status', { name: /Staff assistance completed/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Staff assistance completed')).not.toBeInTheDocument()
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

    expect(api.createClaim).toHaveBeenCalledTimes(1)
    expect(api.startClaimSession).not.toHaveBeenCalled()
    expect(screen.getByPlaceholderText('Tell us what happened…')).toHaveValue('')
    expect(screen.queryByText('clm_ui_second')).not.toBeInTheDocument()

    await user.type(
      screen.getByPlaceholderText('Tell us what happened…'),
      'A second incident happened today.',
    )
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    expect(api.createClaim).toHaveBeenCalledTimes(2)
    expect(await screen.findByText('clm_ui_second')).toBeInTheDocument()
    expect(screen.getByText('Conversation history')).toBeInTheDocument()
    await waitFor(() => expect(api.streamClaimUpdates).toHaveBeenCalledWith(expect.objectContaining({
      claimId: 'clm_ui_second',
      sessionId: 'ses_ui_second',
      afterRevision: 2,
    })))
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
    await user.click((await screen.findAllByRole('button', { name: 'Resume claim' }))[0])
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

  it('keeps creation and assessment actions in the Agent message flow', async () => {
    const user = userEvent.setup()
    api.submitClaimMessage.mockResolvedValue({
      claimant_message: claimantMessage,
      agent_message: {
        ...agentMessage,
        content: { type: 'text', text: 'Everything required is ready.' },
      },
      form_changes: [],
      contents_item_changes: [],
      dynamic_form: readyDynamicForm(),
      claim_revision: 2,
      decision: {
        customer_next_step: {
          status: 'ready_to_create',
          summary: 'Ready to create',
          required_items: [],
        },
      },
    })
    api.createExternalClaim.mockResolvedValue({
      revision: 3,
      external_claim: {
        claim_number: 'NWF-2026-16ECDD',
        creation_status: 'created',
        route: 'Claims intake review',
        next_step: 'A claims specialist will review the submitted details.',
        expected_by: '2026-09-16T01:00:00Z',
      },
      external_service_action: {
        service_identity: 'vehicle_damage_assessment_routing',
        service_name: 'Vehicle damage assessment',
        provider: 'Controlled assessment fixture',
        purpose: 'Request an assessor for the vehicle damage recorded in this claim.',
        shared_data_summary: ['Your confirmed incident region'],
        consent_status: 'not_recorded',
        status: 'consent_required',
        routing: null,
        failure_code: null,
        can_request: true,
      },
      customer_next_step: {
        status: 'claim_created',
        summary: 'Claims intake review',
        required_items: [],
      },
    })

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'My car was damaged.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    const progress = await screen.findByRole('button', {
      name: /Claim progress: 9 of 9 required details complete\. Ready to create/i,
    })
    expect(progress).toHaveAttribute('aria-expanded', 'false')
    const createAction = screen.getByRole('button', { name: /Create your claim/i })
    expect(createAction.closest('.msg-agent')).toBeInTheDocument()

    await user.click(createAction)

    expect(await screen.findByRole('status', {
      name: 'Claim NWF-2026-16ECDD created',
    })).toBeInTheDocument()
    const claimDetails = screen.getByRole('button', { name: /Claim details/i })
    expect(claimDetails).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('A claims specialist will review the submitted details.')).not.toBeVisible()
    await user.click(claimDetails)
    expect(screen.getByText('A claims specialist will review the submitted details.')).toBeVisible()

    const assessmentAction = screen.getByRole('button', {
      name: /Request a vehicle damage assessment/i,
    })
    expect(assessmentAction).toHaveAttribute('aria-expanded', 'false')
    expect(assessmentAction.closest('.msg-agent')).toBeInTheDocument()
    expect(api.createExternalClaim).toHaveBeenCalledWith(expect.objectContaining({
      claimId: initialClaim.claim_id,
      revision: 2,
    }))
  })

  it('fails closed when backend projections expose conflicting primary actions', async () => {
    const user = userEvent.setup()
    const externalServiceAction = {
      service_identity: 'vehicle_damage_assessment_routing',
      service_name: 'Vehicle damage assessment',
      provider: 'Controlled assessment fixture',
      purpose: 'Request an assessor for the vehicle damage recorded in this claim.',
      shared_data_summary: ['Your confirmed incident region'],
      status: 'consent_required',
      can_request: true,
    }
    api.createClaim.mockResolvedValue({
      claim: { ...initialClaim, external_service_action: externalServiceAction },
      session: { session_id: 'ses_ui_vp', model_profile_id: 'qwen-local' },
    })
    api.submitClaimMessage.mockResolvedValue({
      ...initialTurn(),
      dynamic_form: readyDynamicForm(),
      decision: {
        customer_next_step: {
          status: 'ready_to_create',
          summary: 'Ready to create',
          required_items: [],
        },
      },
    })

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'My car was damaged.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText(agentMessage.content.text)

    expect(screen.queryByRole('button', { name: /Create your claim/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', {
      name: /Request a vehicle damage assessment/i,
    })).not.toBeInTheDocument()
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
    })

    render(<App />)
    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    expect(await screen.findByRole('button', { name: /Review claim details/i })).toBeInTheDocument()
    expect(screen.getByText('2 to review')).toBeInTheDocument()
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
    expect(screen.getByText('Add the affected property address')).toBeInTheDocument()
    expect(screen.getByRole('button', {
      name: /Claim progress: 1 of 2 required details complete/i,
    })).toHaveAttribute('aria-expanded', 'false')
  })

  it('shows what to provide from the Evidence projection and supports keyboard tab navigation', async () => {
    const user = userEvent.setup()
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
    expect(screen.getByText('Repair Quote')).toBeInTheDocument()
    expect(screen.getByText('1 item needs your attention')).toBeInTheDocument()

    await user.keyboard('{Home}')
    expect(summaryTab).toHaveFocus()
    expect(summaryTab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('What we have so far')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'What to provide, 1 outstanding' }))
    expect(documentsTab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('Repair Quote')).toBeInTheDocument()
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
    await waitFor(
      () => expect(api.getClaimEvidence).toHaveBeenCalledTimes(2),
      { timeout: 2500 },
    )
    expect(await screen.findByText('Received')).toBeInTheDocument()
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

  it('stages a pre-message attachment and uploads it only after the first message', async () => {
    const user = userEvent.setup()
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.submitClaimMessage.mockResolvedValue(initialTurn())
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

    await user.type(screen.getByPlaceholderText('Tell us what happened…'), 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    await waitFor(() => expect(api.requestEvidenceUpload).toHaveBeenCalledWith(expect.objectContaining({
      claimId: initialClaim.claim_id,
      revision: 2,
    })))
    expect(api.createClaim).toHaveBeenCalledTimes(1)
    expect(api.submitClaimMessage).toHaveBeenCalledTimes(1)
    expect(api.submitClaimMessage.mock.invocationCallOrder[0])
      .toBeLessThan(api.requestEvidenceUpload.mock.invocationCallOrder[0])
    expect(await screen.findByText('Ready')).toBeInTheDocument()
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
})
