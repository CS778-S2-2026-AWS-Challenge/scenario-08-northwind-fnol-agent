import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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
      models: [{ id: 'gpt54-mini', label: 'GPT-5.4 mini' }],
      default_model_profile_id: 'gpt54-mini',
    })
    api.getClaimEvidence.mockResolvedValue({ items: [], revision: 1 })
    api.createClaim.mockResolvedValue({
      claim: initialClaim,
      session: { session_id: 'ses_ui_vp', model_profile_id: 'gpt54-mini' },
    })
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
    expect(screen.getByText('1 of 2 needed now')).toBeInTheDocument()
    expect(screen.getByText('Needed later: Affected property')).toBeInTheDocument()
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
  })
})
