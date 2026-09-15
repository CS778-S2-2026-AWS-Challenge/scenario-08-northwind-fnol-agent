import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const api = vi.hoisted(() => ({
  ApiRequestError: class ApiRequestError extends Error {},
  confirmClaimFields: vi.fn(),
  createExternalClaim: vi.fn(),
  createClaim: vi.fn(),
  bootstrapClaim: vi.fn(),
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
    api.getClaim.mockResolvedValue(initialClaim)
    api.bootstrapClaim.mockResolvedValue({
      claim: initialClaim,
      session: { session_id: 'ses_ui_vp', model_profile_id: 'qwen-local' },
      claim_id: initialClaim.claim_id,
      session_id: 'ses_ui_vp',
      claimant_message: claimantMessage,
      agent_message: agentMessage,
      form_changes: [],
      contents_item_changes: [],
      dynamic_form: null,
      claim_revision: 2,
      decision: { customer_next_step: initialClaim.customer_next_step },
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

  it('shows one server-confirmed delivery failure with retry guidance', async () => {
    const user = userEvent.setup()
    api.bootstrapClaim.mockRejectedValue(Object.assign(
      new api.ApiRequestError('The model service is temporarily unavailable. The claim is unchanged.'),
      { code: 'DEPENDENCY_UNAVAILABLE', status: 503, retryable: true },
    ))

    render(<App />)
    const input = screen.getByPlaceholderText('Tell us what happened…')
    await user.type(input, 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    expect(api.bootstrapClaim).toHaveBeenCalledWith(expect.objectContaining({ incidentType: null }))

    const failure = await screen.findByRole('alert')
    expect(failure).toHaveTextContent(
      'The model service is temporarily unavailable. The claim is unchanged.',
    )
    expect(failure).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry message' })).not.toBeInTheDocument()
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

    expect(await screen.findByRole('heading', { name: 'Waiting for staff' })).toBeInTheDocument()
    expect(screen.getByText(
      'Your request has been sent. You can continue adding information while you wait.',
    )).toBeInTheDocument()
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

    expect(await screen.findByText('Staff assistance requested')).toBeInTheDocument()
    expect(api.requestHumanSupport).toHaveBeenCalledWith(expect.objectContaining({
      claimId: initialClaim.claim_id,
      revision: 2,
    }))
    expect(initialClaim.external_claim).toBeNull()
  })

  it('renders staff, response-needed, reviewing-reply, and completed assistance states', async () => {
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
    api.streamClaimUpdates.mockImplementation(({ onEvent }) => {
      pushLiveUpdate = onEvent
      return new Promise(() => {})
    })
    api.submitClaimMessage.mockImplementationOnce(() => new Promise((resolve) => {
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
    await screen.findByText('Staff assistance requested')
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
    api.getClaimMessages.mockResolvedValueOnce({ items: [claimantMessage, agentMessage] })
    await act(async () => pushLiveUpdate({ claim_revision: 4 }))

    expect(await screen.findByRole('heading', { name: 'Staff is helping you' })).toBeInTheDocument()
    expect(screen.getByText('A Northwind staff member is reviewing your information.')).toBeInTheDocument()
    expect(screen.getByText('Northwind staff joined the conversation')).toBeInTheDocument()

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
      items: [claimantMessage, agentMessage, staffMessage],
    })
    await act(async () => pushLiveUpdate({ claim_revision: 5 }))

    expect(await screen.findByRole('heading', { name: 'Your response is needed' })).toBeInTheDocument()
    expect(screen.getByText(staffMessage.content.text)).toBeInTheDocument()
    expect(screen.getByText('Northwind staff')).toBeInTheDocument()
    const replyBox = screen.getByPlaceholderText('Reply to Northwind staff...')
    await user.type(replyBox, claimantReply.content.text)
    await user.click(screen.getByRole('button', { name: 'Send reply' }))

    expect(await screen.findByRole('heading', { name: 'Staff is reviewing your reply' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Your response is needed' })).not.toBeInTheDocument()
    expect(screen.getByText('No action needed from you right now.')).toBeInTheDocument()

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

    expect(await screen.findByRole('heading', { name: 'Staff assistance completed' })).toBeInTheDocument()
    expect(screen.getByText('You can continue your claim below.')).toBeInTheDocument()
    expect(screen.getAllByText('Staff assistance completed')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Staff assistance' })).toBeEnabled()
    expect(screen.queryByText('Claim created')).not.toBeInTheDocument()
  })

  it('restores completed staff assistance from a fresh post-resolution Claim projection', async () => {
    const user = userEvent.setup()
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
    api.resumeClaimSession.mockResolvedValue({
      session_id: 'ses_ui_vp',
      model_profile_id: 'qwen-local',
      resume: {
        customer_next_step: resolvedClaim.customer_next_step,
        summary: 'A pipe burst in the kitchen.',
        pending_items: [],
        prior_commitments: [],
      },
    })
    api.getClaim.mockResolvedValue(resolvedClaim)
    api.getClaimMessages.mockResolvedValue({ items: [claimantMessage, agentMessage] })

    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Resume claim' }))

    expect(await screen.findByRole('heading', { name: 'Staff assistance completed' })).toBeVisible()
    expect(screen.getByText('You can continue your claim below.')).toBeVisible()
    expect(screen.getAllByText('Staff assistance completed')).toHaveLength(2)
    expect(screen.queryByText('Claim created')).not.toBeInTheDocument()
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
    expect(screen.queryByRole('heading', { name: 'Staff assistance completed' })).not.toBeInTheDocument()
    expect(screen.queryByText('Staff assistance completed')).not.toBeInTheDocument()
  })

  it('opens a new claim conversation without clearing the previous claim', async () => {
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
    api.bootstrapClaim.mockResolvedValueOnce({
      claim: initialClaim,
      session: { session_id: 'ses_ui_vp', model_profile_id: 'qwen-local' },
      claim_id: initialClaim.claim_id,
      session_id: 'ses_ui_vp',
      claimant_message: claimantMessage,
      agent_message: agentMessage,
      form_changes: [],
      contents_item_changes: [],
      dynamic_form: null,
      claim_revision: 2,
      decision: { customer_next_step: initialClaim.customer_next_step },
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
    api.getClaim.mockImplementation(async (claimId) => ({
      ...initialClaim,
      claim_id: claimId,
    }))
    api.createClaim.mockResolvedValue({
      claim: { ...initialClaim, claim_id: 'clm_ui_second' },
      session: { session_id: 'ses_ui_second', model_profile_id: 'qwen-local' },
    })

    render(<App />)
    const input = screen.getByPlaceholderText('Tell us what happened…')
    await user.type(input, 'A pipe burst in the kitchen.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await screen.findByText('Thanks. I need the incident time next.')

    await user.click(screen.getByRole('button', { name: 'New chat' }))

    expect(api.bootstrapClaim).toHaveBeenCalledTimes(1)
    expect(api.createClaim).toHaveBeenCalledTimes(1)
    expect(api.startClaimSession).not.toHaveBeenCalled()
    expect(screen.getByText('clm_ui_second')).toBeInTheDocument()
    expect(screen.getByText('Conversation history')).toBeInTheDocument()
    await waitFor(() => expect(api.streamClaimUpdates).toHaveBeenCalledWith(expect.objectContaining({
      claimId: 'clm_ui_second',
      sessionId: 'ses_ui_second',
      afterRevision: 1,
    })))
  })

  it('renders backend dynamic requirements and re-renders a corrected field', async () => {
    const user = userEvent.setup()
    api.getClaim.mockResolvedValue({
      ...initialClaim,
      form: dynamicForm().form,
      dynamic_form: dynamicForm(),
    })
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
    api.bootstrapClaim.mockResolvedValue({
      claim: {
        ...initialClaim,
        form: dynamicForm().form,
        dynamic_form: dynamicForm(),
      },
      session: { session_id: 'ses_ui_vp', model_profile_id: 'qwen-local' },
      claim_id: initialClaim.claim_id,
      session_id: 'ses_ui_vp',
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

    expect(api.bootstrapClaim).toHaveBeenCalledWith(expect.objectContaining({
      incidentType: null,
      text: 'A pipe burst in the kitchen.',
    }))
    await waitFor(() => expect(screen.getAllByText('When it happened').length).toBeGreaterThan(0))
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
    api.requestEvidenceUpload.mockImplementation(({ signal }) => {
      uploadSignal = signal
      return new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      })
    })

    render(<App />)
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

  it('adds a server-confirmed Claim to Claim history and drills into its Evidence', async () => {
    const user = userEvent.setup()
    api.hasClaimantAccessToken.mockReturnValue(true)
    api.getAuthenticatedAccount.mockResolvedValue({
      profile: { display_name: 'Test claimant', email: 'test@example.test', phone: '' },
      preferences: { email: true, sms: false },
    })
    api.listClaims.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.getClaimEvidence.mockResolvedValue({
      claim_id: initialClaim.claim_id,
      revision: 1,
      items: [{
        evidence_id: 'evd_current_claim',
        claim_id: initialClaim.claim_id,
        kind: 'incident_photo',
        status: 'received',
        file_status: 'ready',
        original_filename: 'kitchen-damage.jpg',
        media_type: 'image/jpeg',
        size_bytes: 2048,
        source: 'claimant',
        created_at: '2026-09-14T01:05:00Z',
        updated_at: '2026-09-14T01:06:00Z',
      }],
      customer_next_step: initialClaim.customer_next_step,
    })
    api.requestEvidenceUpload.mockReturnValue(new Promise(() => {}))

    render(<App />)
    await user.upload(
      document.querySelector('input[type="file"]'),
      new File(['image'], 'new-damage.jpg', { type: 'image/jpeg' }),
    )
    expect(await screen.findByText(initialClaim.claim_id)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Claim history' }))
    expect(await screen.findByRole('heading', { name: 'Claim history' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: `Open Home claim ${initialClaim.claim_id}` }))

    expect(screen.getByRole('heading', { name: 'Claim features' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Evidence history/ }))

    expect(await screen.findByText('kitchen-damage.jpg')).toBeInTheDocument()
    expect(api.getClaimEvidence).toHaveBeenCalledWith(
      initialClaim.claim_id,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
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
