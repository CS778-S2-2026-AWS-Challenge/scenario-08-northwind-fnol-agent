import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import at08ResumeFixture from '../../tests/fixtures/api/AT-08-resume-public.json'
import { setClaimantAccessToken } from './api.js'

const realtime = vi.hoisted(() => ({ streamClaimUpdates: vi.fn() }))

vi.mock('./api.js', async (importOriginal) => ({
  ...await importOriginal(),
  streamClaimUpdates: realtime.streamClaimUpdates,
}))

import App from './App.jsx'

function holdRealtimeConnection() {
  realtime.streamClaimUpdates.mockReset()
  realtime.streamClaimUpdates.mockImplementation(({ signal }) => new Promise((resolve) => {
    if (signal.aborted) {
      resolve()
      return
    }
    signal.addEventListener('abort', resolve, { once: true })
  }))
}

function jsonResponse(body, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

const nextStep = {
  status: 'describe_incident',
  summary: 'Tell me what happened in your own words.',
  responsible_party: 'claimant',
  can_resume: true,
  required_items: [],
}

function createdClaim() {
  return {
    claim: {
      claim_id: 'clm_test',
      revision: 1,
      incident_type: null,
      workflow_state: 'collecting',
      form: {},
      evidence_summary: { received: 0, pending: 0, needs_attention: 0 },
      external_claim: null,
      customer_next_step: nextStep,
      created_at: '2026-08-12T00:00:00Z',
      updated_at: '2026-08-12T00:00:00Z',
    },
    session: {
      session_id: 'ses_test',
      claim_id: 'clm_test',
      status: 'active',
      resume: { customer_next_step: nextStep },
      started_at: '2026-08-12T00:00:00Z',
      last_active_at: '2026-08-12T00:00:00Z',
      closed_at: null,
    },
  }
}

function firstTurn() {
  const field = {
    value: 'Another vehicle hit my parked car.',
    source: 'claimant',
    source_refs: ['msg_claimant'],
    status: 'proposed',
    needed_for: 'current_action',
    confidence: 1,
    updated_at: '2026-08-12T00:01:00Z',
    updated_by: { actor_type: 'agent', actor_id: 'controlled_agent' },
  }
  return {
    claim_id: 'clm_test',
    session_id: 'ses_test',
    claim_revision: 2,
    claimant_message: {
      message_id: 'msg_claimant',
      actor: 'claimant',
      content: { type: 'text', text: field.value },
      evidence_refs: [],
      in_reply_to: null,
      created_at: '2026-08-12T00:01:00Z',
    },
    agent_message: {
      message_id: 'msg_agent',
      actor: 'agent',
      content: { type: 'text', text: 'Please check the incident description.' },
      evidence_refs: [],
      in_reply_to: 'msg_claimant',
      created_at: '2026-08-12T00:01:01Z',
    },
    form_changes: [{ field_code: 'incident.description', field }],
    decision: {
      decision_id: 'dec_test',
      action: 'CONFIRM',
      reason_codes: ['MATERIAL_FACTS_PROPOSED'],
      customer_reason: 'Please check the incident description.',
      customer_next_step: {
        ...nextStep,
        status: 'confirmation_required',
        summary: 'Please check the incident description before I continue.',
        required_items: ['incident.description'],
      },
    },
    handoff: null,
  }
}

function completeMotorTurn() {
  return {
    ...firstTurn(),
    form_changes: [
      firstTurn().form_changes[0],
      {
        field_code: 'incident.location',
        field: { ...firstTurn().form_changes[0].field, value: 'Auckland' },
      },
      {
        field_code: 'loss.description',
        field: { ...firstTurn().form_changes[0].field, value: 'Rear bumper damage' },
      },
    ],
  }
}

function confirmedMotorFields() {
  return Object.fromEntries(
    completeMotorTurn().form_changes.map(({ field_code: fieldCode, field }) => [
      fieldCode,
      { ...field, status: 'confirmed' },
    ]),
  )
}

function assessmentAction(overrides = {}) {
  return {
    service_identity: 'vehicle_damage_assessment_routing',
    service_name: 'Vehicle damage assessment',
    provider: 'Controlled assessment fixture',
    purpose: 'Request an assessor for the vehicle damage recorded in this claim. This does not decide coverage or approve repairs.',
    shared_data_summary: [
      'Your Northwind claim and external claim references',
      'Northwind routing authority and your permission reference',
      'The vehicle damage assessment request',
      'Your confirmed incident region',
    ],
    status: 'consent_required',
    consent_status: null,
    routing: null,
    can_request: true,
    ...overrides,
  }
}

function createdMotorClaimResponse(action = assessmentAction()) {
  return {
    claim_id: 'clm_test',
    revision: 4,
    decision: {
      action: 'CREATE_CLAIM',
      reason_codes: ['CLAIM_CREATION_AUTHORISED'],
    },
    external_claim: {
      external_claim_id: 'ext_fixture_test',
      claim_number: 'NWF-2026-TEST01',
      creation_status: 'created',
      route: 'standard_motor_intake',
      next_step: 'Claims intake review',
      expected_by: '2026-08-14T00:00:00Z',
      created_at: '2026-08-13T00:00:00Z',
    },
    external_service_action: action,
    customer_next_step: {
      ...nextStep,
      status: 'claim_created',
      summary: 'Claims intake review',
      responsible_party: 'northwind',
    },
  }
}

function createdMotorClaimSnapshot(action, revision) {
  const response = createdMotorClaimResponse(action)
  return {
    ...createdClaim().claim,
    revision,
    incident_type: 'motor',
    workflow_state: 'created',
    form: confirmedMotorFields(),
    external_claim: response.external_claim,
    external_service_action: action,
    customer_next_step: {
      ...response.customer_next_step,
      status: action.status === 'ready_to_request' ? 'assessor_request_ready' : 'assessor_assigned',
      summary: action.routing?.next_step || 'Your permission is recorded.',
      responsible_party: action.routing ? 'external_party' : 'claimant',
    },
  }
}

function mockAt08Resume(sessionNextStep = at08ResumeFixture.session.resume.customer_next_step) {
  const { claim, messages, session } = at08ResumeFixture
  fetch.mockImplementationOnce(() =>
    jsonResponse({
      items: [
        {
          claim_id: claim.claim_id,
          revision: claim.revision,
          incident_type: claim.incident_type,
          workflow_state: claim.workflow_state,
          external_claim: claim.external_claim,
          customer_next_step: claim.customer_next_step,
          created_at: claim.created_at,
          updated_at: claim.updated_at,
          can_resume: true,
        },
      ],
      page: { next_cursor: null },
    }),
  )
  fetch.mockImplementationOnce(() =>
    jsonResponse(
      {
        ...session,
        resume: { ...session.resume, customer_next_step: sessionNextStep },
      },
      201,
    ),
  )
  fetch.mockImplementationOnce(() => jsonResponse(claim))
  fetch.mockImplementationOnce(() => jsonResponse(messages))
}

describe.skip('legacy claimant intake (migrate scenarios to the adaptive Agent journey)', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    holdRealtimeConnection()
    setClaimantAccessToken(null)
    localStorage.clear()
    window.history.replaceState({}, '', '/')
  })

  afterEach(() => {
    setClaimantAccessToken(null)
    vi.unstubAllGlobals()
  })

  it('lets claimants start without login and keeps employee access inside the login page', async () => {
    const user = userEvent.setup()
    render(<App />)

    expect(screen.getByRole('radio', { name: 'Motor' })).toBeChecked()
    expect(screen.getByLabelText('Incident description')).toBeEnabled()
    expect(screen.queryByRole('link', { name: 'Employee access' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Log in' }))

    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Employee access' })).toHaveAttribute(
      'href',
      'http://127.0.0.1:8002/',
    )
    expect(screen.getByRole('button', { name: 'Log in' })).toBeEnabled()
    expect(screen.getByRole('note')).toHaveTextContent(/anonymous and synthetic/i)

    await user.click(screen.getByRole('button', { name: 'Start a claim without logging in' }))
    expect(screen.getByLabelText('Incident description')).toBeEnabled()
  })

  it('uses an in-memory authenticated session for account updates and logout', async () => {
    const user = userEvent.setup()
    fetch
      .mockResolvedValueOnce(jsonResponse({
        customer_id: 'cus_demo', access_token: 'opaque-session-token',
        token_type: 'Bearer', expires_at: '2026-08-27T05:00:00Z', development_identity: true,
      }, 201))
      .mockResolvedValueOnce(jsonResponse({
        customer_id: 'cus_demo', development_identity: true,
        profile: { display_name: 'Demo Claimant One', email: 'claimant.one@example.invalid', phone: '' },
        preferences: { email: true, sms: false },
      }))
      .mockResolvedValueOnce({ ok: true, status: 204, json: async () => null })
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Log in' }))
    await user.type(screen.getByLabelText('Email address'), 'claimant.one@example.invalid')
    await user.type(screen.getByLabelText('Password'), 'northwind-demo-one')
    await user.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByRole('heading', { name: 'Your account' })).toBeVisible()
    expect(screen.getByRole('note')).toHaveTextContent(/not a production Northwind identity/i)
    expect(fetch.mock.calls[1][1].headers.Authorization).toBe('Bearer opaque-session-token')

    await user.click(screen.getByRole('button', { name: 'Log out' }))
    expect(await screen.findByRole('heading', { name: /get back on track/i })).toBeVisible()
    expect(fetch.mock.calls[2][1].headers.Authorization).toBe('Bearer opaque-session-token')
  })

  it('loads an authenticated claimant saved claim and its shared conversation', async () => {
    const user = userEvent.setup()
    fetch
      .mockResolvedValueOnce(jsonResponse({
        customer_id: 'cus_demo', access_token: 'opaque-session-token',
        token_type: 'Bearer', expires_at: '2026-08-27T05:00:00Z', development_identity: true,
      }, 201))
      .mockResolvedValueOnce(jsonResponse({
        customer_id: 'cus_demo', development_identity: true,
        profile: { display_name: 'Demo Claimant One', email: 'claimant.one@example.invalid', phone: '' },
        preferences: { email: true, sms: false },
      }))
      .mockResolvedValueOnce(jsonResponse({
        items: [{
          claim_id: 'clm_saved', revision: 6, incident_type: 'motor',
          workflow_state: 'collecting', external_claim: null,
          customer_next_step: nextStep, created_at: '2026-08-27T01:00:00Z',
          updated_at: '2026-08-27T02:00:00Z', can_resume: true,
        }],
        page: { next_cursor: null },
      }))
      .mockResolvedValueOnce(jsonResponse({
        session_id: 'ses_saved', claim_id: 'clm_saved', status: 'active',
        resume: { summary: 'Rear-end Motor report.', pending_items: [], prior_commitments: [], customer_next_step: nextStep },
        started_at: '2026-08-27T01:00:00Z', last_active_at: '2026-08-27T02:00:00Z', closed_at: null,
      }, 201))
      .mockResolvedValueOnce(jsonResponse({
        ...createdClaim().claim, claim_id: 'clm_saved', revision: 6, incident_type: 'motor',
      }))
      .mockResolvedValueOnce(jsonResponse({
        items: [{
          message_id: 'msg_saved_staff', actor: 'staff',
          content: { type: 'text', text: 'I have your earlier report and can continue from here.' },
          evidence_refs: [], in_reply_to: null, created_at: '2026-08-27T02:00:00Z',
        }],
        page: { next_cursor: null },
      }))
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Log in' }))
    await user.type(screen.getByLabelText('Email address'), 'claimant.one@example.invalid')
    await user.type(screen.getByLabelText('Password'), 'northwind-demo-one')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    await user.click(await screen.findByRole('button', { name: 'View saved claims' }))
    await user.click(await screen.findByRole('button', { name: 'Resume report' }))

    expect(await screen.findByText('I have your earlier report and can continue from here.')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Continue where you left off' })).toBeVisible()
    expect(fetch.mock.calls[5][1].headers.Authorization).toBe('Bearer opaque-session-token')
  })

  it('keeps entered login details available after an authentication failure', async () => {
    const user = userEvent.setup()
    fetch.mockResolvedValueOnce(jsonResponse({
      error: {
        code: 'AUTHENTICATION_REQUIRED',
        message: 'The email or password was not recognised.',
        request_id: 'req-login-failure',
      },
    }, 401))
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Log in' }))
    const email = screen.getByLabelText('Email address')
    const password = screen.getByLabelText('Password')
    await user.type(email, 'claimant.one@example.invalid')
    await user.type(password, 'incorrect-password')
    await user.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/not recognised/i)
    expect(email).toHaveValue('claimant.one@example.invalid')
    expect(password).toHaveValue('incorrect-password')
    expect(screen.getByRole('button', { name: 'Log in' })).toBeEnabled()
  })

  it('offers a three-step guided Motor claim without replacing conversational intake', async () => {
    const user = userEvent.setup()
    render(<App />)

    const description = screen.getByLabelText('Incident description')
    const guidedStart = screen.getByRole('button', { name: /Start guided Motor claim/ })
    expect(screen.getByRole('heading', { name: 'Tell us what happened' })).toBeVisible()
    expect(description.compareDocumentPosition(guidedStart)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    expect(screen.getByText(/These items are useful, not required/)).toBeVisible()

    await user.click(guidedStart)

    expect(screen.getByText('1 Details')).toBeVisible()
    expect(screen.getByText('2 Materials')).toBeVisible()
    expect(screen.getByText('3 Declaration')).toBeVisible()
    expect(screen.getByLabelText('Client Number')).toBeRequired()
    expect(screen.getByLabelText('What happened')).toBeRequired()
    await user.click(screen.getByRole('button', { name: 'Incident date' }))
    expect(screen.getByRole('dialog', { name: 'Choose incident date' })).toBeVisible()
    expect(screen.getByText('Mon')).toBeVisible()
    await user.click(screen.getByRole('heading', { name: 'Your details and incident' }))
    expect(screen.queryByRole('dialog', { name: 'Choose incident date' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Incident date' }))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Choose incident date' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Incident date' })).toHaveFocus()
    expect(screen.getByLabelText('Vehicle registration plate number')).toHaveAttribute('placeholder', 'For example, ABC123')
    expect(screen.getByText(/letters and numbers shown on your vehicle's licence plate/i)).toBeVisible()
  })

  it('shows optional preparation by claim type and preserves the description through guided Motor', async () => {
    const user = userEvent.setup()
    render(<App />)

    const description = screen.getByLabelText('Incident description')
    await user.type(description, 'Another vehicle hit my parked car.')
    const claimTypeGroup = screen.getByRole('group', { name: 'Claim type' })
    const motor = screen.getByRole('radio', { name: 'Motor' })
    const home = screen.getByRole('radio', { name: 'Home' })
    expect(description.compareDocumentPosition(claimTypeGroup)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    expect(motor).toBeChecked()

    await user.click(home)
    expect(screen.getByRole('heading', { name: 'Helpful to have ready for your home claim' })).toBeVisible()
    expect(screen.getByText('Emergency work records')).toBeVisible()
    expect(screen.queryByRole('button', { name: /Start guided Motor claim/ })).not.toBeInTheDocument()

    await user.keyboard('{ArrowLeft}')
    expect(motor).toBeChecked()
    expect(motor).toHaveFocus()
    await user.click(screen.getByRole('button', { name: /Start guided Motor claim/ }))
    expect(screen.getByLabelText('What happened')).toHaveValue('Another vehicle hit my parked car.')
    await user.click(screen.getByRole('button', { name: /Back to claim options/ }))
    expect(screen.getByLabelText('Incident description')).toHaveValue('Another vehicle hit my parked car.')
  })

  it('keeps a new homepage description when restoring an older guided Motor draft', async () => {
    localStorage.setItem('northwind-guided-motor-draft', JSON.stringify({
      step: 1,
      draft: {
        policyNumber: 'NW-123456',
        description: 'An older saved incident description.',
      },
      claimRef: null,
      uploaded: [],
    }))
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Incident description'), 'A cyclist hit my parked car today.')
    await user.click(screen.getByRole('button', { name: /Start guided Motor claim/ }))

    expect(screen.getByLabelText('Client Number')).toHaveValue('NW-123456')
    expect(screen.getByLabelText('What happened')).toHaveValue('A cyclist hit my parked car today.')

    await user.click(screen.getByRole('button', { name: /Back to claim options/ }))
    expect(screen.getByLabelText('Incident description')).toHaveValue('A cyclist hit my parked car today.')
  })

  it('returns to guided details and continues without overwriting confirmed fields', async () => {
    const today = new Date()
    const selectedDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-12`
    const confirmed = (value) => ({ value, source: 'claimant', source_refs: [], status: 'confirmed', needed_for: 'current_action', confidence: null, updated_at: '2026-08-12T00:00:00Z', updated_by: { actor_type: 'claimant', actor_id: 'cus_demo' } })
    const savedForm = {
      'claimant.client_number': confirmed('NW-123456'), 'claimant.role': confirmed('policyholder'),
      'claimant.contact_preference': confirmed('email'), 'incident.type': confirmed('motor'),
      'incident.occurred_at': confirmed(selectedDate), 'incident.location': confirmed('Queen Street'),
      'incident.description': confirmed('Another vehicle hit my parked car.'),
      'loss.description': confirmed('Rear bumper damage.'),
    }
    fetch
      .mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
      .mockImplementationOnce(() => jsonResponse({ ...createdClaim().claim, incident_type: 'motor' }))
      .mockImplementationOnce(() => jsonResponse(firstTurn()))
      .mockImplementationOnce(() => jsonResponse({ ...createdClaim().claim, revision: 2, incident_type: 'motor', form: { 'incident.description': firstTurn().form_changes[0].field } }))
      .mockImplementationOnce(() => jsonResponse({ claim_id: 'clm_test', revision: 3, updated_fields: savedForm, invalidated_decision_ids: [], customer_next_step: nextStep }))
      .mockImplementationOnce(() => jsonResponse({ ...createdClaim().claim, revision: 3, incident_type: 'motor', form: savedForm }))
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: /Start guided Motor claim/ }))
    await user.type(screen.getByLabelText('Client Number'), 'NW-123456')
    await user.click(screen.getByRole('button', { name: 'Incident date' }))
    await user.click(screen.getByRole('button', { name: '12' }))
    await user.type(screen.getByLabelText('Where it happened'), 'Queen Street')
    await user.type(screen.getByLabelText('What happened'), 'Another vehicle hit my parked car.')
    await user.type(screen.getByLabelText('What was damaged or lost'), 'Rear bumper damage.')
    await user.click(screen.getByRole('button', { name: 'Save and continue' }))
    expect(await screen.findByRole('heading', { name: 'Add supporting materials' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Back' }))
    await user.click(screen.getByRole('button', { name: 'Save and continue' }))
    expect(await screen.findByRole('heading', { name: 'Add supporting materials' })).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(fetch).toHaveBeenCalledTimes(6)
  })

  it('creates shared claim state, submits the first message, and requires confirmation', async () => {
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(firstTurn()))
    const user = userEvent.setup()
    render(<App />)

    await user.type(
      screen.getByLabelText('Incident description'),
      'Another vehicle hit my parked car.',
    )
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))

    expect(await screen.findByText('Please check the incident description.')).toBeVisible()
    expect(screen.getAllByText('Another vehicle hit my parked car.')).toHaveLength(2)
    expect(screen.getByText(/Sender: You · Audience: Shared claim conversation · Delivered/)).toBeVisible()
    expect(screen.getByText(/Sender: Northwind · Audience: Shared claim conversation · Delivered/)).toBeVisible()
    expect(screen.getByText('Check this')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Confirm details' })).toBeEnabled()
    expect(screen.getByLabelText('Add more information')).toBeEnabled()
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      '/api/v1/claims/clm_test/sessions/ses_test/messages',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('shows focused progress and keeps natural-language correction available during review', async () => {
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(firstTurn()))
    const user = userEvent.setup()
    render(<App />)

    await user.type(
      screen.getByLabelText('Incident description'),
      'Another vehicle hit my parked car.',
    )
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))

    expect(await screen.findByRole('region', {
      name: 'Claim progress: Step 2 of 3, Check the details',
    })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Check these details' })).toBeVisible()
    expect(screen.getByText('What happened needs your review.')).toBeVisible()
    expect(screen.getByLabelText('Add more information')).toBeEnabled()
    expect(screen.getByText(/keep describing the incident or correct a detail/i)).toBeVisible()
  })

  it('confirms the proposed field and moves to the next unanswered question', async () => {
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(firstTurn()))
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        claim_id: 'clm_test',
        revision: 3,
        confirmed_fields: {
          'incident.description': {
            ...firstTurn().form_changes[0].field,
            status: 'confirmed',
          },
        },
        decision: null,
        customer_next_step: {
          ...nextStep,
          status: 'provide_incident_location',
          summary: 'Where did the incident happen?',
          required_items: ['incident.location'],
        },
      }),
    )
    const user = userEvent.setup()
    render(<App />)

    await user.type(
      screen.getByLabelText('Incident description'),
      'Another vehicle hit my parked car.',
    )
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    await user.click(await screen.findByRole('button', { name: 'Confirm details' }))

    await waitFor(() => {
      expect(screen.getAllByText('Where did the incident happen?')).toHaveLength(2)
    })
    expect(screen.getByText('Confirmed')).toBeVisible()
    expect(screen.getByLabelText('Incident location')).toBeEnabled()
  })

  it('shows the corrected value and its source after saving a form correction', async () => {
    const correctedValue = 'Another vehicle hit my parked car outside Queen Street.'
    const correctedField = {
      ...firstTurn().form_changes[0].field,
      value: correctedValue,
      status: 'proposed',
      source: 'claimant',
    }
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(firstTurn()))
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        claim_id: 'clm_test',
        revision: 3,
        updated_fields: {
          'incident.description': correctedField,
        },
        customer_next_step: {
          ...nextStep,
          status: 'confirmation_required',
          summary: 'Please check the incident description.',
          required_items: ['incident.description'],
        },
      }),
    )
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        claim_id: 'clm_test',
        revision: 4,
        confirmed_fields: {
          'incident.description': {
            ...correctedField,
            status: 'confirmed',
          },
        },
        decision: null,
        customer_next_step: {
          ...nextStep,
          status: 'provide_incident_location',
          summary: 'Where did the incident happen?',
          required_items: ['incident.location'],
        },
      }),
    )

    const user = userEvent.setup()
    render(<App />)
    await user.type(
      screen.getByLabelText('Incident description'),
      'Another vehicle hit my parked car.',
    )
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    await user.click(await screen.findByRole('button', { name: 'Edit' }))

    const correction = screen.getByRole('textbox', { name: 'Correct What happened' })
    await user.clear(correction)
    await user.type(correction, correctedValue)
    await user.click(screen.getByRole('button', { name: 'Save correction' }))

    expect(await screen.findByText(correctedValue)).toBeVisible()
    expect(screen.getByText('Provided by you')).toBeVisible()
    expect(screen.getByText('Confirmed')).toBeVisible()
  })

  it('presents an inferred field source in claimant-safe language', async () => {
    const inferredTurn = {
      ...firstTurn(),
      form_changes: [
        {
          ...firstTurn().form_changes[0],
          field: {
            ...firstTurn().form_changes[0].field,
            source: 'inference',
          },
        },
      ],
    }
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(inferredTurn))

    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Incident description'), 'Another vehicle hit my car.')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))

    expect(await screen.findByText('Suggested from your description')).toBeVisible()
    expect(screen.queryByText('Source: inference')).not.toBeInTheDocument()
  })

  it('shows an actionable failure state', async () => {
    fetch.mockImplementationOnce(() => Promise.reject(new TypeError('Failed to fetch')))
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Incident description'), 'A synthetic incident.')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'We could not reach the claim service. Check your connection and try again.',
      )
    })
    expect(screen.getByText(/Delivery outcome unknown/)).toBeVisible()
    expect(screen.queryByText(/Failed before delivery/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry claim message' })).toBeEnabled()
  })

  it('keeps the claimant entry path operable by keyboard', async () => {
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(firstTurn()))
    const user = userEvent.setup()
    render(<App />)

    await user.tab()
    expect(screen.getByRole('link', { name: 'Northwind home' })).toHaveFocus()
    await user.tab() // Claims navigation
    await user.tab() // How it works navigation
    await user.tab() // Log in
    await user.tab()
    const description = screen.getByLabelText('Incident description')
    expect(description).toHaveFocus()
    await user.type(description, 'Another vehicle hit my parked car.')
    await user.tab()
    expect(screen.getByRole('button', { name: 'Continue claim' })).toHaveFocus()
    await user.keyboard('{Enter}')

    expect(await screen.findByRole('button', { name: 'Confirm details' })).toBeEnabled()
  })

  it('resumes canonical AT-08 context without re-asking confirmed facts', async () => {
    mockAt08Resume()
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Resume a saved report' }))
    expect(
      await screen.findByText(
        'Confirm how the police report will be added when it becomes available.',
      ),
    ).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Resume report' }))

    expect(await screen.findByText('Continue where you left off')).toBeVisible()
    expect(
      screen.getByText('Rear-end collision in Newmarket; incident and location are confirmed.'),
    ).toBeVisible()
    expect(screen.getByText('Police report expected after the original session.')).toBeVisible()
    expect(
      screen.getByText('The police report can be added later without restarting the claim.'),
    ).toBeVisible()
    expect(screen.getAllByText('Confirmed')).toHaveLength(2)
    expect(screen.queryByLabelText('Incident description')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Incident location')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Add more information')).toBeEnabled()
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      '/api/v1/claims/clm_fixture_at08/sessions',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('finds a resumable report after a page with no resumable claims', async () => {
    const { claim } = at08ResumeFixture
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        items: [
          {
            claim_id: 'clm_already_created',
            revision: 5,
            incident_type: 'motor',
            workflow_state: 'created',
            external_claim: { creation_status: 'created' },
            customer_next_step: claim.customer_next_step,
            created_at: claim.created_at,
            updated_at: claim.updated_at,
            can_resume: false,
          },
        ],
        page: { next_cursor: 'page-2' },
      }),
    )
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        items: [
          {
            claim_id: claim.claim_id,
            revision: claim.revision,
            incident_type: claim.incident_type,
            workflow_state: claim.workflow_state,
            external_claim: claim.external_claim,
            customer_next_step: claim.customer_next_step,
            created_at: claim.created_at,
            updated_at: claim.updated_at,
            can_resume: true,
          },
        ],
        page: { next_cursor: null },
      }),
    )

    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Resume a saved report' }))

    expect(await screen.findByRole('button', { name: 'Resume report' })).toBeVisible()
    expect(screen.queryByText('No saved reports are available to resume.')).not.toBeInTheDocument()
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      '/api/v1/claims?limit=25',
      expect.any(Object),
    )
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      '/api/v1/claims?limit=25&cursor=page-2',
      expect.any(Object),
    )
  })

  it('uses the latest claim next step instead of a stale session snapshot', async () => {
    const staleSessionNextStep = {
      ...nextStep,
      status: 'provide_incident_location',
      summary: 'Where did the incident happen?',
      required_items: ['incident.location'],
    }
    mockAt08Resume(staleSessionNextStep)

    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Resume a saved report' }))
    await user.click(await screen.findByRole('button', { name: 'Resume report' }))

    expect(screen.queryByText('Where did the incident happen?')).not.toBeInTheDocument()
    expect(
      screen.getAllByText(
        'Confirm how the police report will be added when it becomes available.',
      ).length,
    ).toBeGreaterThan(0)
    expect(screen.getByLabelText('Add more information')).toBeEnabled()
  })

  it('reconciles a committed message after its response is lost', async () => {
    fetch.mockImplementationOnce(() => Promise.reject(new TypeError('Response lost')))
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(firstTurn()))
    const user = userEvent.setup()
    render(<App />)

    await user.type(
      screen.getByLabelText('Incident description'),
      'Another vehicle hit my parked car.',
    )
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/try again/i)
    expect(screen.getByText(/Delivery outcome unknown/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Retry claim message' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Retry claim message' }))
    await screen.findByRole('button', { name: 'Confirm details' })
    expect(screen.getAllByText('Another vehicle hit my parked car.')[0]).toBeVisible()
    expect(screen.queryByText(/Delivery outcome unknown/)).not.toBeInTheDocument()

    const firstHeaders = fetch.mock.calls[0][1].headers
    const retryHeaders = fetch.mock.calls[1][1].headers
    expect(retryHeaders['Idempotency-Key']).toBe(firstHeaders['Idempotency-Key'])
  })

  it('requests human support and pauses ordinary intake with preserved context', async () => {
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(firstTurn()))
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        handoff: {
          handoff_id: 'hnd_test',
          status: 'queued',
          support_need: 'human_requested',
          summary: 'A Northwind support request has been queued with the details already provided.',
          created_at: '2026-08-12T00:02:00Z',
        },
        revision: 3,
        customer_next_step: {
          ...nextStep,
          status: 'human_support_queued',
          summary: 'A Northwind support request has been queued with the details already provided.',
          responsible_party: 'northwind',
        },
      }, 201),
    )
    const user = userEvent.setup()
    render(<App />)

    await user.type(
      screen.getByLabelText('Incident description'),
      'Another vehicle hit my parked car.',
    )
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    await user.click(await screen.findByRole('button', { name: 'Request human support' }))

    expect(await screen.findByText('Your support request is queued')).toBeVisible()
    expect(screen.getByText('Status: Queued')).toBeVisible()
    expect(screen.getByText('Northwind support')).toBeVisible()
    expect(screen.getByText('Saved with the details already provided')).toBeVisible()
    expect(screen.getByLabelText('Add more information')).toBeEnabled()
    expect(screen.getByText(/message will be saved for Northwind support/)).toBeVisible()
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      '/api/v1/claims/clm_test/support-requests',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('refreshes a queued handoff and displays the persisted staff update', async () => {
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(firstTurn()))
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        handoff: {
          handoff_id: 'hnd_test',
          status: 'queued',
          support_need: 'human_requested',
          summary: 'A Northwind support request has been queued with the details already provided.',
          created_at: '2026-08-12T00:02:00Z',
        },
        revision: 3,
        customer_next_step: {
          ...nextStep,
          status: 'human_support_queued',
          responsible_party: 'northwind',
        },
      }, 201),
    )
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        ...createdClaim().claim,
        revision: 5,
        customer_next_step: {
          ...nextStep,
          status: 'staff_update',
          summary: 'A staff member reviewed your report and will contact you.',
          responsible_party: 'northwind',
        },
      }),
    )
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Incident description'), 'Another vehicle hit my car.')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    await user.click(await screen.findByRole('button', { name: 'Request human support' }))
    await user.click(await screen.findByRole('button', { name: 'Refresh conversation' }))

    expect(await screen.findByText('Your support request has been reviewed')).toBeVisible()
    expect(screen.getAllByText('A staff member reviewed your report and will contact you.')).toHaveLength(2)
    expect(fetch).toHaveBeenNthCalledWith(
      4,
      '/api/v1/claims/clm_test',
      expect.objectContaining({ headers: expect.any(Object) }),
    )
  })

  it('replaces the handoff card with a system notice when staff support starts', async () => {
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(firstTurn()))
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        handoff: {
          handoff_id: 'hnd_test',
          status: 'queued',
          support_need: 'human_requested',
          summary: 'A Northwind support request has been queued.',
          created_at: '2026-08-12T00:02:00Z',
        },
        revision: 3,
        customer_next_step: { ...nextStep, status: 'human_support_queued' },
      }, 201),
    )
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        ...createdClaim().claim,
        revision: 5,
        handoff: {
          handoff_id: 'hnd_test',
          status: 'in_progress',
          support_need: 'human_requested',
          summary: 'A Northwind support request has been queued.',
          created_at: '2026-08-12T00:02:00Z',
        },
        customer_next_step: {
          ...nextStep,
          status: 'human_support_in_progress',
          summary: 'A Northwind staff member is now assisting you.',
          responsible_party: 'northwind',
        },
      }),
    )
    fetch.mockImplementationOnce(() => jsonResponse({ items: [], page: { next_cursor: null } }))
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Incident description'), 'Another vehicle hit my car.')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    await user.click(await screen.findByRole('button', { name: 'Request human support' }))
    await user.click(await screen.findByRole('button', { name: 'Refresh conversation' }))

    expect(await screen.findByText('A Northwind staff member is now assisting you.')).toBeVisible()
    expect(screen.queryByText('Human support')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh conversation' })).toBeEnabled()
  })

  it('refreshes the shared conversation when the claimant returns to the window', async () => {
    const staffMessage = {
      message_id: 'msg_staff_reply',
      actor: 'staff',
      content: { type: 'text', text: 'I have reviewed the saved details and can help from here.' },
      evidence_refs: [],
      in_reply_to: null,
      created_at: '2026-08-12T00:03:00Z',
    }
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(firstTurn()))
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        handoff: {
          handoff_id: 'hnd_test', status: 'queued',
          support_need: 'human_requested', summary: 'Support is queued.',
          created_at: '2026-08-12T00:02:00Z',
        },
        revision: 3,
        customer_next_step: { ...nextStep, status: 'human_support_queued' },
      }, 201),
    )
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        ...createdClaim().claim,
        revision: 5,
        handoff: {
          handoff_id: 'hnd_test', status: 'in_progress',
          support_need: 'human_requested', summary: 'Support is in progress.',
          created_at: '2026-08-12T00:02:00Z',
        },
        customer_next_step: {
          ...nextStep,
          status: 'human_support_in_progress',
          summary: 'A Northwind staff member is now assisting you.',
          responsible_party: 'northwind',
        },
      }),
    )
    fetch.mockImplementationOnce(() =>
      jsonResponse({ items: [staffMessage], page: { next_cursor: null } }),
    )
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Incident description'), 'Another vehicle hit my car.')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    await user.click(await screen.findByRole('button', { name: 'Request human support' }))
    act(() => window.dispatchEvent(new Event('focus')))

    expect(await screen.findByText(staffMessage.content.text)).toBeVisible()
    expect(screen.getByText('A Northwind staff member is now assisting you.')).toBeVisible()
  })

  it('labels pending evidence fields without asking the claimant to confirm them', async () => {
    const pendingTurn = {
      ...firstTurn(),
      form_changes: [{
        field_code: 'authorities.police_report_reference',
        field: {
          ...firstTurn().form_changes[0].field,
          value: null,
          status: 'pending_generation',
        },
      }],
    }
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(pendingTurn))
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Incident description'), 'Police report is due next week.')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))

    expect(await screen.findByText('Pending')).toBeVisible()
    expect(screen.getByText('Expected later')).toBeVisible()
    expect(screen.queryByText('null')).not.toBeInTheDocument()
  })

  it('creates a mock claim only after all proposed facts are confirmed', async () => {
    const completeTurn = {
      ...firstTurn(),
      form_changes: [
        firstTurn().form_changes[0],
        {
          field_code: 'incident.location',
          field: { ...firstTurn().form_changes[0].field, value: 'Queen Street' },
        },
        {
          field_code: 'loss.description',
          field: { ...firstTurn().form_changes[0].field, value: 'Rear bumper damage' },
        },
      ],
    }
    const confirmedFields = Object.fromEntries(
      completeTurn.form_changes.map(({ field_code: fieldCode, field }) => [
        fieldCode,
        { ...field, status: 'confirmed' },
      ]),
    )
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(completeTurn))
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        claim_id: 'clm_test',
        revision: 3,
        confirmed_fields: confirmedFields,
        decision: null,
        customer_next_step: {
          ...nextStep,
          status: 'ready_to_create',
          summary: 'Your confirmed report is ready for controlled claim creation.',
        },
      }),
    )
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        claim_id: 'clm_test',
        revision: 4,
        decision: {
          action: 'CREATE_CLAIM',
          reason_codes: ['CLAIM_CREATION_AUTHORISED'],
        },
        external_claim: {
          external_claim_id: 'ext_fixture_test',
          claim_number: 'NWF-2026-TEST01',
          creation_status: 'created',
          route: 'standard_motor_intake',
          next_step: 'Claims intake review',
          expected_by: '2026-08-14T00:00:00Z',
          created_at: '2026-08-13T00:00:00Z',
        },
        customer_next_step: {
          ...nextStep,
          status: 'claim_created',
          summary: 'Claims intake review',
          responsible_party: 'northwind',
        },
      }, 201),
    )
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Incident description'), 'A complete motor report.')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    await user.click(await screen.findByRole('button', { name: 'Confirm details' }))
    await user.click(await screen.findByRole('button', { name: 'Create claim' }))

    expect(await screen.findByText('NWF-2026-TEST01')).toBeVisible()
    expect(screen.getByText('standard_motor_intake')).toBeVisible()
    expect(screen.getAllByText('Claims intake review').length).toBeGreaterThan(0)
    expect(fetch).toHaveBeenNthCalledWith(
      4,
      '/api/v1/claims/clm_test/creation',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('shows the assessment action only after claim creation and completes consent and routing', async () => {
    const completeTurn = completeMotorTurn()
    const confirmedFields = confirmedMotorFields()
    const readyAction = assessmentAction({
      status: 'ready_to_request',
      consent_status: 'granted',
    })
    const assignedAction = assessmentAction({
      status: 'assigned',
      consent_status: 'granted',
      can_request: false,
      routing: {
        routing_status: 'assigned',
        assessor_reference: 'asr_fixture_01',
        queue_reference: 'QUE-AUC-001',
        next_step: 'An assessor will review the confirmed claim information.',
        expected_by: '2026-08-15T00:00:00Z',
        limitations: ['Synthetic fixture routing; no production assessor was contacted.'],
      },
    })
    let releaseConsent = () => {}
    let releaseRouting = () => {}
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(completeTurn))
    fetch.mockImplementationOnce(() => jsonResponse({
      claim_id: 'clm_test',
      revision: 3,
      confirmed_fields: confirmedFields,
      decision: null,
      customer_next_step: {
        ...nextStep,
        status: 'ready_to_create',
        summary: 'Your confirmed report is ready for controlled claim creation.',
      },
    }))
    fetch.mockImplementationOnce(() => jsonResponse(createdMotorClaimResponse(), 201))
    fetch.mockImplementationOnce(() => new Promise((resolve) => {
      releaseConsent = () => {
        jsonResponse({
          claim_id: 'clm_test',
          revision: 5,
          action: readyAction,
          customer_next_step: {
            ...nextStep,
            status: 'assessor_request_ready',
            summary: 'Your permission is recorded.',
          },
        }, 201).then(resolve)
      }
    }))
    fetch.mockImplementationOnce(() => new Promise((resolve) => {
      releaseRouting = () => {
        jsonResponse({
          claim_id: 'clm_test',
          revision: 6,
          action: assignedAction,
          customer_next_step: {
            ...nextStep,
            status: 'assessor_assigned',
            summary: assignedAction.routing.next_step,
            responsible_party: 'external_party',
          },
        }, 201).then(resolve)
      }
    }))
    const user = userEvent.setup()
    render(<App />)

    expect(screen.queryByRole('heading', { name: 'Request a vehicle damage assessment' }))
      .not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Incident description'), 'A complete motor report.')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    await user.click(await screen.findByRole('button', { name: 'Confirm details' }))
    await user.click(await screen.findByRole('button', { name: 'Create claim' }))

    expect(await screen.findByText('Controlled assessment fixture')).toBeVisible()
    expect(screen.getByText('Your confirmed incident region')).toBeVisible()
    const requestButton = screen.getByRole('button', { name: 'Agree and request assessor' })
    expect(requestButton).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /I give Northwind permission/ }))
    await user.click(requestButton)

    expect(await screen.findByText('Recording your permission...')).toBeVisible()
    releaseConsent()
    expect(await screen.findByText('Sending the assessment request...')).toBeVisible()
    releaseRouting()
    expect(await screen.findByText('Assessor assigned')).toBeVisible()
    expect(screen.getByText('asr_fixture_01')).toBeVisible()
    expect(screen.getByText('Synthetic fixture routing; no production assessor was contacted.'))
      .toBeVisible()
    expect(fetch).toHaveBeenNthCalledWith(
      5,
      '/api/v1/claims/clm_test/assessor-routing/consent',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(fetch).toHaveBeenNthCalledWith(
      6,
      '/api/v1/claims/clm_test/assessor-routing',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('keeps the created claim unchanged when optional assessment consent is declined', async () => {
    const completeTurn = completeMotorTurn()
    const confirmedFields = confirmedMotorFields()
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(completeTurn))
    fetch.mockImplementationOnce(() => jsonResponse({
      claim_id: 'clm_test',
      revision: 3,
      confirmed_fields: confirmedFields,
      decision: null,
      customer_next_step: {
        ...nextStep,
        status: 'ready_to_create',
        summary: 'Your confirmed report is ready for controlled claim creation.',
      },
    }))
    fetch.mockImplementationOnce(() => jsonResponse(createdMotorClaimResponse(), 201))
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Incident description'), 'A complete motor report.')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    await user.click(await screen.findByRole('button', { name: 'Confirm details' }))
    await user.click(await screen.findByRole('button', { name: 'Create claim' }))

    expect(await screen.findByText('NWF-2026-TEST01')).toBeVisible()
    expect(screen.getByText('Optional next step')).toBeVisible()
    const checkbox = screen.getByRole('checkbox', { name: /I give Northwind permission/ })
    const requestButton = screen.getByRole('button', { name: 'Agree and request assessor' })
    await user.click(checkbox)
    await user.click(checkbox)

    expect(checkbox).not.toBeChecked()
    expect(requestButton).toBeDisabled()
    expect(screen.getByText('NWF-2026-TEST01')).toBeVisible()
    expect(screen.getAllByText('Claims intake review').length).toBeGreaterThan(0)
    expect(fetch).toHaveBeenCalledTimes(4)
    expect(fetch.mock.calls.some(([path]) => path.includes('/assessor-routing'))).toBe(false)
  })

  it('keeps the claim saved after a retryable assessment failure and safely retries', async () => {
    const completeTurn = completeMotorTurn()
    const confirmedFields = confirmedMotorFields()
    const readyAction = assessmentAction({
      status: 'ready_to_request',
      consent_status: 'granted',
    })
    const assignedAction = assessmentAction({
      status: 'assigned',
      consent_status: 'granted',
      can_request: false,
      routing: {
        routing_status: 'assigned',
        assessor_reference: 'asr_fixture_retry',
        queue_reference: 'QUE-AUC-RETRY',
        next_step: 'An assessor will review the confirmed claim information.',
        expected_by: null,
        limitations: ['Synthetic fixture routing; no production assessor was contacted.'],
      },
    })
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(completeTurn))
    fetch.mockImplementationOnce(() => jsonResponse({
      claim_id: 'clm_test',
      revision: 3,
      confirmed_fields: confirmedFields,
      decision: null,
      customer_next_step: {
        ...nextStep,
        status: 'ready_to_create',
        summary: 'Your confirmed report is ready for controlled claim creation.',
      },
    }))
    fetch.mockImplementationOnce(() => jsonResponse(createdMotorClaimResponse(), 201))
    fetch.mockImplementationOnce(() => jsonResponse({
      claim_id: 'clm_test',
      revision: 5,
      action: readyAction,
      customer_next_step: {
        ...nextStep,
        status: 'assessor_request_ready',
        summary: 'Your permission is recorded.',
      },
    }, 201))
    fetch.mockImplementationOnce(() => jsonResponse({
      error: {
        code: 'DEPENDENCY_UNAVAILABLE',
        message: 'The assessment service is unavailable. The claim is saved and no assessor has been assigned.',
        retryable: true,
      },
    }, 503))
    fetch.mockImplementationOnce(() => jsonResponse(
      createdMotorClaimSnapshot(readyAction, 5),
    ))
    fetch.mockImplementationOnce(() => jsonResponse({
      claim_id: 'clm_test',
      revision: 6,
      action: assignedAction,
      customer_next_step: {
        ...nextStep,
        status: 'assessor_assigned',
        summary: assignedAction.routing.next_step,
        responsible_party: 'external_party',
      },
    }, 201))
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Incident description'), 'A complete motor report.')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    await user.click(await screen.findByRole('button', { name: 'Confirm details' }))
    await user.click(await screen.findByRole('button', { name: 'Create claim' }))
    await user.click(await screen.findByRole('checkbox', { name: /I give Northwind permission/ }))
    await user.click(screen.getByRole('button', { name: 'Agree and request assessor' }))

    expect(await screen.findByText('Assessment request not sent')).toBeVisible()
    expect(screen.getByText('Your claim is saved, and no assessor has been assigned.')).toBeVisible()
    const firstRouteHeaders = fetch.mock.calls[5][1].headers
    await user.click(screen.getByRole('button', { name: 'Retry assessment request' }))

    expect(await screen.findByText('Assessor assigned')).toBeVisible()
    expect(fetch.mock.calls[7][1].headers['Idempotency-Key'])
      .toBe(firstRouteHeaders['Idempotency-Key'])
    expect(fetch.mock.calls[7][1].headers['If-Match']).toBe('5')
  })

  it('restores an authoritative assessor assignment after a response failure', async () => {
    const completeTurn = completeMotorTurn()
    const readyAction = assessmentAction({
      status: 'ready_to_request',
      consent_status: 'granted',
    })
    const assignedAction = assessmentAction({
      status: 'assigned',
      consent_status: 'granted',
      can_request: false,
      routing: {
        routing_status: 'assigned',
        assessor_reference: 'asr_fixture_restored',
        queue_reference: 'QUE-AUC-RESTORED',
        next_step: 'An assessor will review the confirmed claim information.',
        expected_by: null,
        limitations: ['Synthetic fixture routing; no production assessor was contacted.'],
      },
    })
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(completeTurn))
    fetch.mockImplementationOnce(() => jsonResponse({
      claim_id: 'clm_test',
      revision: 3,
      confirmed_fields: confirmedMotorFields(),
      decision: null,
      customer_next_step: {
        ...nextStep,
        status: 'ready_to_create',
        summary: 'Your confirmed report is ready for controlled claim creation.',
      },
    }))
    fetch.mockImplementationOnce(() => jsonResponse(createdMotorClaimResponse(), 201))
    fetch.mockImplementationOnce(() => jsonResponse({
      claim_id: 'clm_test',
      revision: 5,
      action: readyAction,
      customer_next_step: createdMotorClaimSnapshot(readyAction, 5).customer_next_step,
    }, 201))
    fetch.mockImplementationOnce(() => jsonResponse({
      error: {
        code: 'INTERNAL_ERROR',
        message: 'The assessment response could not be saved.',
        retryable: true,
      },
    }, 500))
    fetch.mockImplementationOnce(() => jsonResponse(
      createdMotorClaimSnapshot(assignedAction, 6),
    ))
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Incident description'), 'A complete motor report.')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    await user.click(await screen.findByRole('button', { name: 'Confirm details' }))
    await user.click(await screen.findByRole('button', { name: 'Create claim' }))
    await user.click(await screen.findByRole('checkbox', { name: /I give Northwind permission/ }))
    await user.click(screen.getByRole('button', { name: 'Agree and request assessor' }))

    expect(await screen.findByText('Assessor assigned')).toBeVisible()
    expect(screen.getByText('asr_fixture_restored')).toBeVisible()
    expect(screen.queryByText('Assessment request not sent')).not.toBeInTheDocument()
  })

  it('clears assessment permission when another eligible report finishes resuming', async () => {
    const eligibleAction = assessmentAction()
    const claimA = {
      ...createdMotorClaimSnapshot(eligibleAction, 5),
      claim_id: 'clm_eligible_a',
      external_claim: {
        ...createdMotorClaimSnapshot(eligibleAction, 5).external_claim,
        claim_number: 'NWF-ELIGIBLE-A',
      },
    }
    const claimB = {
      ...createdMotorClaimSnapshot(eligibleAction, 3),
      claim_id: 'clm_eligible_b',
      external_claim: {
        ...createdMotorClaimSnapshot(eligibleAction, 3).external_claim,
        claim_number: 'NWF-ELIGIBLE-B',
      },
    }
    let releaseA = () => {}
    let releaseB = () => {}
    fetch.mockImplementation((url, options = {}) => {
      if (url.startsWith('/api/v1/claims?')) {
        return jsonResponse({
          items: [claimA, claimB].map((claim) => ({
            claim_id: claim.claim_id,
            revision: claim.revision,
            incident_type: claim.incident_type,
            workflow_state: claim.workflow_state,
            external_claim: claim.external_claim,
            customer_next_step: claim.customer_next_step,
            created_at: claim.created_at,
            updated_at: claim.updated_at,
            can_resume: true,
          })),
          page: { next_cursor: null },
        })
      }
      if (url === '/api/v1/claims/clm_eligible_a/sessions' && options.method === 'POST') {
        return new Promise((resolve) => {
          releaseA = () => jsonResponse({
            session_id: 'ses_eligible_a',
            claim_id: claimA.claim_id,
            status: 'active',
            resume: {
              ...at08ResumeFixture.session.resume,
              customer_next_step: claimA.customer_next_step,
            },
          }, 201).then(resolve)
        })
      }
      if (url === '/api/v1/claims/clm_eligible_b/sessions' && options.method === 'POST') {
        return new Promise((resolve) => {
          releaseB = () => jsonResponse({
            session_id: 'ses_eligible_b',
            claim_id: claimB.claim_id,
            status: 'active',
            resume: {
              ...at08ResumeFixture.session.resume,
              customer_next_step: claimB.customer_next_step,
            },
          }, 201).then(resolve)
        })
      }
      if (url === '/api/v1/claims/clm_eligible_a') return jsonResponse(claimA)
      if (url === '/api/v1/claims/clm_eligible_b') return jsonResponse(claimB)
      if (url.includes('/messages?limit=100')) {
        return jsonResponse({ items: [], page: { next_cursor: null } })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Resume a saved report' }))
    const resumeButtons = await screen.findAllByRole('button', { name: 'Resume report' })
    act(() => {
      resumeButtons[0].click()
      resumeButtons[1].click()
    })
    await act(async () => releaseA())
    expect(await screen.findByText('NWF-ELIGIBLE-A')).toBeVisible()
    const firstConsent = screen.getByRole('checkbox', { name: /I give Northwind permission/ })
    await user.click(firstConsent)
    expect(firstConsent).toBeChecked()

    await act(async () => releaseB())
    expect(await screen.findByText('NWF-ELIGIBLE-B')).toBeVisible()
    expect(screen.getByRole('checkbox', { name: /I give Northwind permission/ }))
      .not.toBeChecked()
  })

  it('renders an urgent message handoff without claiming emergency contact', async () => {
    const urgentTurn = {
      ...firstTurn(),
      form_changes: [],
      decision: {
        ...firstTurn().decision,
        action: 'URGENT_HANDOFF',
        reason_codes: ['EXPLICIT_SAFETY_SIGNAL'],
        customer_next_step: {
          ...nextStep,
          status: 'urgent_support_queued',
          responsible_party: 'northwind',
          summary: 'Contact local emergency services yourself if immediate help is needed.',
        },
      },
      agent_message: {
        ...firstTurn().agent_message,
        content: {
          type: 'text',
          text: 'Contact local emergency services yourself if immediate help is needed.',
        },
      },
      handoff: {
        handoff_id: 'hnd_urgent',
        status: 'queued',
        support_need: 'urgent',
        summary: 'Contact local emergency services yourself if immediate help is needed.',
        created_at: '2026-08-12T00:02:00Z',
      },
    }
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(urgentTurn))
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Incident description'), 'A passenger is injured.')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))

    expect(await screen.findByText('Normal intake has paused')).toBeVisible()
    expect(screen.getAllByText(/Contact local emergency services yourself/)).toHaveLength(3)
    expect(screen.queryByText(/we contacted emergency services/i)).not.toBeInTheDocument()
    expect(screen.getByLabelText('Add more information')).toBeEnabled()
  })
})

describe('adaptive claimant entry', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    holdRealtimeConnection()
    setClaimantAccessToken(null)
    localStorage.clear()
    window.history.replaceState({}, '', '/')
  })

  afterEach(() => {
    setClaimantAccessToken(null)
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  function evidenceRecord(fileStatus) {
    return {
      evidence_id: 'evd_test',
      kind: 'incident_photo',
      status: 'received',
      file_status: fileStatus,
      original_filename: 'damage.png',
      media_type: 'image/png',
      size_bytes: 3,
      wait_type: fileStatus === 'processing' ? 'internal' : null,
      responsible_party: fileStatus === 'processing' ? 'system' : 'claimant',
      context_summary: fileStatus === 'failed'
        ? 'Northwind could not process this evidence upload.'
        : 'Northwind is processing the completed evidence upload.',
    }
  }

  function installAuthenticatedEvidenceApi({ onEvidenceRead, completion = 'lost' }) {
    setClaimantAccessToken('claimant-test-token')
    const counts = { evidenceReads: 0, contentUploads: 0, completionAttempts: 0 }
    fetch.mockImplementation((url, options = {}) => {
      const method = options.method || 'GET'
      if (url === '/api/v1/claims/capabilities') {
        return jsonResponse({ claim_types: ['motor', 'home', 'contents'], models: [] })
      }
      if (url === '/api/v1/account') {
        return jsonResponse({
          customer_id: 'cus_test',
          development_identity: true,
          profile: { display_name: 'Test Claimant', email: 'test@example.invalid', phone: '' },
          preferences: { email: true, sms: false },
        })
      }
      if (url === '/api/v1/claims' && method === 'POST') return jsonResponse(createdClaim(), 201)
      if (url.endsWith('/evidence') && method === 'GET') {
        counts.evidenceReads += 1
        const result = onEvidenceRead(counts.evidenceReads)
        if (result instanceof Error) return Promise.reject(result)
        if (result && typeof result.then === 'function') return result.then(jsonResponse)
        return jsonResponse(result)
      }
      if (url.endsWith('/sessions/ses_test/messages') && method === 'POST') {
        return jsonResponse({ ...firstTurn(), claim_revision: 5 })
      }
      if (url.endsWith('/evidence/uploads') && method === 'POST') {
        return jsonResponse({
          evidence_id: 'evd_test',
          revision: 2,
          upload: {
            method: 'PUT',
            url: '/api/v1/claims/clm_test/evidence/evd_test/content',
            headers: { 'Content-Type': 'image/png' },
            expires_at: '2026-08-12T01:00:00Z',
          },
          constraints: { max_size_bytes: 10_000_000, allowed_media_types: ['image/png'] },
          customer_next_step: nextStep,
        }, 201)
      }
      if (url.endsWith('/content') && method === 'PUT') {
        counts.contentUploads += 1
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      if (url.endsWith('/complete') && method === 'POST') {
        counts.completionAttempts += 1
        if (completion === 'lost') return Promise.reject(new TypeError('connection lost'))
        return jsonResponse({
          evidence: evidenceRecord('processing'),
          revision: 3,
          status_url: '/api/v1/claims/clm_test/evidence',
          customer_next_step: nextStep,
        }, 202)
      }
      throw new Error(`Unexpected request: ${method} ${url}`)
    })
    return counts
  }

  it('reconciles a lost completion response before retrying without another content upload', async () => {
    const counts = installAuthenticatedEvidenceApi({
      onEvidenceRead: (read) => read === 1
        ? { items: [], revision: 1 }
        : { items: [evidenceRecord('processing')], revision: 3 },
    })
    const user = userEvent.setup()
    render(<App />)
    await user.upload(document.querySelector('input[type="file"]'), new File(['abc'], 'damage.png', { type: 'image/png' }))

    await user.click(await screen.findByRole('button', { name: 'Retry' }))

    expect((await screen.findAllByText('Processing')).length).toBeGreaterThan(0)
    expect(counts.contentUploads).toBe(1)
    expect(counts.completionAttempts).toBe(1)
  })

  it('keeps polling after a transient status failure and recovers to ready', async () => {
    installAuthenticatedEvidenceApi({
      completion: 'accepted',
      onEvidenceRead: (read) => {
        if (read === 1) return { items: [], revision: 1 }
        if (read === 2) return new Error('temporary status outage')
        return { items: [evidenceRecord('ready')], revision: 4 }
      },
    })
    const user = userEvent.setup()
    render(<App />)
    await user.upload(document.querySelector('input[type="file"]'), new File(['abc'], 'damage.png', { type: 'image/png' }))

    await waitFor(
      () => expect(screen.getByRole('status')).toHaveTextContent(/keep trying to reconnect/i),
      { timeout: 4000 },
    )
    await waitFor(() => expect(screen.getAllByText('Ready').length).toBeGreaterThan(0), { timeout: 5000 })
  }, 10000)

  it('does not let a delayed evidence poll roll the whole claim revision backwards', async () => {
    let releaseDelayedPoll
    let delayedPollStarted = false
    installAuthenticatedEvidenceApi({
      completion: 'accepted',
      onEvidenceRead: (read) => {
        if (read === 1) return { items: [], revision: 1 }
        if (read === 2) return { items: [evidenceRecord('processing')], revision: 4 }
        delayedPollStarted = true
        return new Promise((resolve) => {
          releaseDelayedPoll = () => resolve({ items: [evidenceRecord('processing')], revision: 4 })
        })
      },
    })
    const user = userEvent.setup()
    render(<App />)
    await user.upload(document.querySelector('input[type="file"]'), new File(['abc'], 'damage.png', { type: 'image/png' }))

    await waitFor(() => expect(delayedPollStarted).toBe(true), { timeout: 5000 })
    await user.type(screen.getByPlaceholderText('Write the details you know...'), 'The car was moved after the incident.')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(fetch.mock.calls.some(([url, options = {}]) =>
      url.endsWith('/sessions/ses_test/messages') && options.method === 'POST')).toBe(true))
    expect(screen.getByText('Revision 5')).toBeVisible()

    releaseDelayedPoll()
    await waitFor(() => expect(screen.getByText('Revision 5')).toBeVisible())
    expect(screen.getAllByText('Processing').length).toBeGreaterThan(0)
  }, 10000)

  it('presents processing failure with a status-check recovery action', async () => {
    installAuthenticatedEvidenceApi({
      completion: 'accepted',
      onEvidenceRead: (read) => read === 1
        ? { items: [], revision: 1 }
        : { items: [evidenceRecord('failed')], revision: 4 },
    })
    const user = userEvent.setup()
    render(<App />)
    await user.upload(document.querySelector('input[type="file"]'), new File(['abc'], 'damage.png', { type: 'image/png' }))

    await waitFor(() => expect(screen.getAllByText('Processing failed').length).toBeGreaterThan(0), { timeout: 4000 })
    expect(screen.getByRole('button', { name: 'Check status' })).toBeVisible()
  }, 10000)

  it('promotes an anonymous claim before allowing the claimant to resume with an upload', async () => {
    fetch.mockImplementation((url, options = {}) => {
      const method = options.method || 'GET'
      if (url === '/api/v1/claims/capabilities') {
        return jsonResponse({ claim_types: ['motor', 'home', 'contents'], models: [] })
      }
      if (url === '/api/v1/claims' && method === 'POST') return jsonResponse(createdClaim(), 201)
      if (url.endsWith('/sessions/ses_test/messages') && method === 'POST') return jsonResponse(firstTurn())
      if (url === '/api/v1/auth/sessions' && method === 'POST') {
        return jsonResponse({ customer_id: 'cus_test', access_token: 'promoted-token', token_type: 'Bearer' }, 201)
      }
      if (url === '/api/v1/claims/clm_test/promote' && method === 'POST') {
        return jsonResponse({ ...createdClaim().claim, revision: 2, form: { 'incident.description': firstTurn().form_changes[0].field } })
      }
      if (url === '/api/v1/account') {
        return jsonResponse({
          customer_id: 'cus_test',
          development_identity: true,
          profile: { display_name: 'Test Claimant', email: 'test@example.invalid', phone: '' },
          preferences: { email: true, sms: false },
        })
      }
      if (url.endsWith('/evidence') && method === 'GET') return jsonResponse({ items: [], revision: 2 })
      if (url.endsWith('/evidence/uploads') && method === 'POST') {
        return jsonResponse({
          evidence_id: 'evd_test',
          revision: 3,
          upload: {
            method: 'PUT',
            url: '/api/v1/claims/clm_test/evidence/evd_test/content',
            headers: { 'Content-Type': 'image/png' },
            expires_at: '2026-08-12T01:00:00Z',
          },
          constraints: { max_size_bytes: 10_000_000, allowed_media_types: ['image/png'] },
          customer_next_step: nextStep,
        }, 201)
      }
      if (url.endsWith('/content') && method === 'PUT') return Promise.resolve(new Response(null, { status: 204 }))
      if (url.endsWith('/complete') && method === 'POST') {
        return jsonResponse({
          evidence: evidenceRecord('processing'),
          revision: 4,
          status_url: '/api/v1/claims/clm_test/evidence',
          customer_next_step: nextStep,
        }, 202)
      }
      throw new Error(`Unexpected request: ${method} ${url}`)
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Incident description'), 'A car hit mine.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    expect(await screen.findByText('Please check the incident description.')).toBeVisible()
    await user.upload(document.querySelector('input[type="file"]'), new File(['abc'], 'damage.png', { type: 'image/png' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/sign in before uploading/i)
    expect(fetch.mock.calls.some(([url]) => url.endsWith('/evidence/uploads'))).toBe(false)

    await user.click(screen.getByRole('button', { name: /Log in to save your chat/ }))
    await user.type(screen.getByLabelText('Email address'), 'test@example.invalid')
    await user.type(screen.getByLabelText('Password'), 'test-password')
    await user.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByText('Please check the incident description.')).toBeVisible()

    await user.upload(document.querySelector('input[type="file"]'), new File(['abc'], 'damage.png', { type: 'image/png' }))

    expect((await screen.findAllByText('Processing')).length).toBeGreaterThan(0)
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/claims/clm_test/promote',
      expect.objectContaining({ method: 'POST' }),
    )
    const uploadRequest = fetch.mock.calls.find(([url]) => url.endsWith('/evidence/uploads'))
    expect(uploadRequest[1].headers.Authorization).toBe('Bearer promoted-token')
  })

  it('presents the Agent as the single primary entry without legacy guided controls', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Tell us what happened' })).toBeVisible()
    expect(screen.getByLabelText('Incident description')).toBeEnabled()
    expect(screen.queryByRole('radio', { name: 'Motor' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /guided motor/i })).not.toBeInTheDocument()
  })

  it('keeps How it works in the entry journey', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: 'How it works' }))
    expect(screen.getByRole('heading', { name: 'How this works' })).toBeVisible()
  })

  it('supports registration as a separate authentication view', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Create an account' }))
    expect(screen.getByRole('heading', { name: 'Create your account' })).toBeVisible()
    expect(screen.getByLabelText('Confirm password')).toBeVisible()
  })

  it('shows the collapsible What we have so far panel after a claim starts', async () => {
    fetch
      .mockResolvedValueOnce(jsonResponse({ claim_types: ['motor', 'home', 'contents'], models: [] }))
      .mockResolvedValueOnce(jsonResponse(createdClaim(), 201))
      .mockResolvedValueOnce(jsonResponse(firstTurn()))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Incident description'), 'A car hit mine.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    expect(await screen.findByRole('heading', { name: 'What we have so far' })).toBeVisible()
    const toggle = screen.getByRole('button', { name: 'Collapse' })
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('renders the server dynamic form projection with selection and value statuses', async () => {
    const turn = {
      ...firstTurn(),
      dynamic_form: {
        claim_id: 'clm_test',
        claim_revision: 2,
        field_registry_version: '4',
        branch_rules_version: 'vp-dynamic-form-branch-rules-v1',
        selected_family: 'motor',
        active_branches: ['family.motor', 'incident.collision'],
        fields: [
          { field_code: 'incident.description', selection_state: 'candidate_now', value_state: 'proposed', source: 'claimant', reason: 'This detail helps describe the incident.' },
          { field_code: 'incident.occurred_at', selection_state: 'required_now', value_state: 'missing', source: null, reason: 'The incident date is needed for the current safe action.' },
          { field_code: 'authorities.police_report_reference', selection_state: 'pending_later', value_state: 'pending_generation', source: null, reason: 'This report can be added when it becomes available.' },
          { field_code: 'claimant.client_number', selection_state: 'system_owned', value_state: 'confirmed', source: 'claimant', reason: 'Internal identity field.' },
        ],
      },
    }
    fetch
      .mockResolvedValueOnce(jsonResponse({ claim_types: ['motor', 'home', 'contents'], models: [] }))
      .mockResolvedValueOnce(jsonResponse(createdClaim(), 201))
      .mockResolvedValueOnce(jsonResponse(turn))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Incident description'), 'A car hit mine.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    expect(await screen.findByRole('heading', { name: 'Motor claim details' })).toBeVisible()
    expect(screen.getByText('Needed now')).toBeVisible()
    expect(screen.getByText('Helpful now')).toBeVisible()
    expect(screen.getByText('Needed later')).toBeVisible()
    expect(screen.getByText('The incident date is needed for the current safe action.')).toBeVisible()
    expect(screen.getAllByText('Not provided yet').length).toBeGreaterThan(0)
    expect(screen.queryByText('Internal identity field.')).not.toBeInTheDocument()
  })

  it('replaces a corrected contents item from the authoritative turn projection', async () => {
    const contentsItem = {
      item_id: 'itm_laptop',
      description: 'Laptop computer',
      category: 'electronics',
      quantity: 1,
      loss_type: 'damaged',
      ownership: 'owned',
      estimated_value: null,
      source: 'claimant',
      source_refs: ['msg_contents_initial'],
      status: 'proposed',
      needed_for: 'current_action',
      resolution_state: 'needs_confirmation',
      updated_at: '2026-09-08T00:00:00Z',
    }
    const dynamicForm = {
      claim_id: 'clm_test',
      claim_revision: 2,
      field_registry_version: '5',
      branch_rules_version: 'vp-dynamic-form-branch-rules-v1',
      selected_family: 'contents',
      active_branches: ['family.contents'],
      fields: [],
      requirements: {
        satisfied: [],
        missing_required_now: ['contents.items'],
        pending_later: [],
        next_required_item: 'contents.items',
        ready: false,
        current_action_satisfied: 0,
        current_action_total: 6,
      },
    }
    const initialTurn = {
      ...firstTurn(),
      claim_revision: 2,
      form_changes: [],
      contents_item_changes: [contentsItem],
      dynamic_form: dynamicForm,
      decision: {
        ...firstTurn().decision,
        customer_next_step: {
          ...firstTurn().decision.customer_next_step,
          required_items: ['contents.items'],
        },
      },
    }
    const correctedTurn = {
      ...initialTurn,
      claim_revision: 3,
      claimant_message: {
        ...initialTurn.claimant_message,
        message_id: 'msg_contents_correction',
        content: { type: 'text', text: 'Actually, the laptop was stolen.' },
      },
      agent_message: {
        ...initialTurn.agent_message,
        message_id: 'msg_contents_agent_correction',
        in_reply_to: 'msg_contents_correction',
      },
      contents_item_changes: [{
        ...contentsItem,
        loss_type: 'stolen',
        source_refs: ['msg_contents_correction'],
        updated_at: '2026-09-08T00:01:00Z',
      }],
      dynamic_form: { ...dynamicForm, claim_revision: 3 },
    }
    fetch
      .mockResolvedValueOnce(jsonResponse({ claim_types: ['motor', 'home', 'contents'], models: [] }))
      .mockResolvedValueOnce(jsonResponse(createdClaim(), 201))
      .mockResolvedValueOnce(jsonResponse(initialTurn))
      .mockResolvedValueOnce(jsonResponse({ items: [], revision: 2, page: { next_cursor: null } }))
      .mockResolvedValueOnce(jsonResponse(correctedTurn))
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Incident description'), 'My laptop was damaged.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    expect(await screen.findByText('1 × electronics · damaged')).toBeVisible()

    await user.type(screen.getByLabelText('Add more information'), 'Actually, it was stolen.')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('1 × electronics · stolen')).toBeVisible()
    expect(screen.queryByText('1 × electronics · damaged')).not.toBeInTheDocument()
    expect(screen.getAllByText('Laptop computer needs your review.')).toHaveLength(1)
    expect(screen.getByText('Updated with revision 3')).toBeVisible()
  })

  it('starts an anonymous claim with a browser session header instead of an empty bearer token', async () => {
    fetch
      .mockResolvedValueOnce(jsonResponse({ claim_types: ['motor', 'home', 'contents'], models: [] }))
      .mockResolvedValueOnce(jsonResponse(createdClaim(), 201))
      .mockResolvedValueOnce(jsonResponse(firstTurn()))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Incident description'), 'A car hit mine.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/api/v1/claims',
      expect.objectContaining({ method: 'POST' }),
    ))
    const [, request] = fetch.mock.calls.find(([url, options]) => (
      url === '/api/v1/claims' && options?.method === 'POST'
    ))
    const headers = request.headers
    expect(headers.Authorization).toBeUndefined()
    expect(headers['X-Northwind-Anonymous-Session']).toMatch(/^[0-9a-f-]{36}$/i)
  })

  it('renders non-urgent human support from the claimant support need', async () => {
    const turn = {
      ...firstTurn(),
      form_changes: [],
      decision: {
        ...firstTurn().decision,
        action: 'HANDOFF',
        customer_next_step: {
          ...nextStep,
          status: 'human_support_queued',
          summary: 'A Northwind support request has been queued.',
          responsible_party: 'northwind',
        },
      },
      handoff: {
        handoff_id: 'hnd_standard',
        status: 'queued',
        support_need: 'human_requested',
        summary: 'A Northwind support request has been queued.',
        created_at: '2026-08-12T00:02:00Z',
      },
    }
    fetch
      .mockResolvedValueOnce(jsonResponse({ claim_types: ['motor', 'home', 'contents'], models: [] }))
      .mockResolvedValueOnce(jsonResponse(createdClaim(), 201))
      .mockResolvedValueOnce(jsonResponse(turn))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Incident description'), 'I want help from a person.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    expect(await screen.findByText('Your support request is queued')).toBeVisible()
    expect(screen.getByText('Human support')).toBeVisible()
    expect(screen.queryByText('Urgent support')).not.toBeInTheDocument()
    expect(screen.queryByText('Normal intake has paused')).not.toBeInTheDocument()
  })

  it('renders urgent support from the claimant support need without claiming emergency contact', async () => {
    const safetySummary = 'Contact local emergency services yourself if immediate help is needed.'
    const turn = {
      ...firstTurn(),
      form_changes: [],
      decision: {
        ...firstTurn().decision,
        action: 'URGENT_HANDOFF',
        customer_next_step: {
          ...nextStep,
          status: 'urgent_support_queued',
          summary: safetySummary,
          responsible_party: 'northwind',
        },
      },
      agent_message: {
        ...firstTurn().agent_message,
        content: { type: 'text', text: safetySummary },
      },
      handoff: {
        handoff_id: 'hnd_urgent',
        status: 'queued',
        support_need: 'urgent',
        summary: safetySummary,
        created_at: '2026-08-12T00:02:00Z',
      },
    }
    fetch
      .mockResolvedValueOnce(jsonResponse({ claim_types: ['motor', 'home', 'contents'], models: [] }))
      .mockResolvedValueOnce(jsonResponse(createdClaim(), 201))
      .mockResolvedValueOnce(jsonResponse(turn))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Incident description'), 'A passenger is injured.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))

    expect(await screen.findByText('Normal intake has paused')).toBeVisible()
    expect(screen.getByText('Urgent support')).toBeVisible()
    expect(screen.getAllByText(safetySummary).length).toBeGreaterThan(0)
    expect(screen.queryByText(/we contacted emergency services/i)).not.toBeInTheDocument()
  })

  it('reloads the safe claim projection and staff message after a live update', async () => {
    let publishUpdate
    realtime.streamClaimUpdates.mockImplementation(({ signal, onEvent }) => {
      publishUpdate = onEvent
      return new Promise((resolve) => signal.addEventListener('abort', resolve, { once: true }))
    })
    const initialTurn = {
      ...firstTurn(),
      dynamic_form: {
        claim_id: 'clm_test',
        claim_revision: 2,
        field_registry_version: '4',
        branch_rules_version: 'vp-dynamic-form-branch-rules-v1',
        selected_family: 'motor',
        active_branches: ['family.motor'],
        fields: [
          {
            field_code: 'incident.description',
            selection_state: 'candidate_now',
            value_state: 'proposed',
            source: 'claimant',
            reason: 'This detail describes the incident.',
          },
        ],
      },
    }
    const updatedClaim = {
      ...createdClaim().claim,
      revision: 4,
      dynamic_form: {
        ...initialTurn.dynamic_form,
        claim_revision: 4,
      },
      handoff: {
        handoff_id: 'hnd_live',
        status: 'in_progress',
        support_need: 'human_requested',
        summary: 'A claims professional is helping with this report.',
        created_at: '2026-08-12T00:02:00Z',
      },
      customer_next_step: {
        ...nextStep,
        status: 'human_support_in_progress',
        summary: 'A Northwind staff member is now assisting you.',
        responsible_party: 'claims_professional',
      },
    }
    const staffMessage = {
      message_id: 'msg_staff_live',
      actor: 'staff',
      content: { type: 'text', text: 'I can help you continue from the details already saved.' },
      evidence_refs: [],
      in_reply_to: null,
      created_at: '2026-08-12T00:03:00Z',
    }
    fetch
      .mockResolvedValueOnce(jsonResponse({ claim_types: ['motor', 'home', 'contents'], models: [] }))
      .mockResolvedValueOnce(jsonResponse(createdClaim(), 201))
      .mockResolvedValueOnce(jsonResponse(initialTurn))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Incident description'), 'Another car hit mine.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    await waitFor(() => expect(publishUpdate).toBeTypeOf('function'))
    fetch
      .mockResolvedValueOnce(jsonResponse(updatedClaim))
      .mockResolvedValueOnce(jsonResponse({ items: [staffMessage], page: { next_cursor: null } }))

    await act(async () => publishUpdate({
      claim_id: 'clm_test',
      session_id: 'ses_test',
      claim_revision: 4,
      resources: ['claim', 'messages'],
    }))

    expect(await screen.findByText(staffMessage.content.text)).toBeVisible()
    expect(screen.getAllByText('A Northwind staff member is now assisting you.').length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { name: 'Motor claim details' })).toBeVisible()
    expect(screen.getByText('Updated with revision 4')).toBeVisible()
    expect(realtime.streamClaimUpdates).toHaveBeenCalledWith(expect.objectContaining({
      claimId: 'clm_test',
      sessionId: 'ses_test',
      afterRevision: 2,
    }))
  })

  it('clears a stale dynamic form when an authoritative live claim has no projection', async () => {
    let publishUpdate
    realtime.streamClaimUpdates.mockImplementation(({ signal, onEvent }) => {
      publishUpdate = onEvent
      return new Promise((resolve) => signal.addEventListener('abort', resolve, { once: true }))
    })
    const initialTurn = {
      ...firstTurn(),
      dynamic_form: {
        claim_id: 'clm_test',
        claim_revision: 2,
        field_registry_version: '4',
        branch_rules_version: 'vp-dynamic-form-branch-rules-v1',
        selected_family: 'motor',
        active_branches: ['family.motor'],
        fields: [
          {
            field_code: 'incident.description',
            selection_state: 'candidate_now',
            value_state: 'proposed',
            source: 'claimant',
            reason: 'This detail describes the incident.',
          },
        ],
      },
    }
    const updatedClaim = {
      ...createdClaim().claim,
      revision: 4,
      dynamic_form: null,
    }
    fetch
      .mockResolvedValueOnce(jsonResponse({ claim_types: ['motor', 'home', 'contents'], models: [] }))
      .mockResolvedValueOnce(jsonResponse(createdClaim(), 201))
      .mockResolvedValueOnce(jsonResponse(initialTurn))
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Incident description'), 'Another car hit mine.')
    await user.click(screen.getByRole('button', { name: 'Start claim' }))
    expect(await screen.findByRole('heading', { name: 'Motor claim details' })).toBeVisible()
    await waitFor(() => expect(publishUpdate).toBeTypeOf('function'))
    fetch
      .mockResolvedValueOnce(jsonResponse(updatedClaim))
      .mockResolvedValueOnce(jsonResponse({ items: [], page: { next_cursor: null } }))

    await act(async () => publishUpdate({
      claim_id: 'clm_test',
      session_id: 'ses_test',
      claim_revision: 4,
      resources: ['claim'],
    }))

    await waitFor(() => expect(
      screen.queryByRole('heading', { name: 'Motor claim details' }),
    ).not.toBeInTheDocument())
  })

  it('resumes a saved session with its persisted model after a fresh client load', async () => {
    const persistedClaim = {
      ...createdClaim().claim,
      claim_id: 'clm_saved_gpt',
      revision: 4,
      incident_type: 'motor',
    }
    const persistedSession = {
      session_id: 'ses_saved_gpt',
      claim_id: persistedClaim.claim_id,
      status: 'active',
      model_profile_id: 'nowcoding-gpt54mini',
      resume: { summary: 'Saved GPT report.', pending_items: [], prior_commitments: [], customer_next_step: nextStep },
      started_at: '2026-08-27T01:00:00Z',
      last_active_at: '2026-08-27T02:00:00Z',
      closed_at: null,
    }
    setClaimantAccessToken('claimant-test-token')
    fetch.mockImplementation((url, options = {}) => {
      const method = options.method || 'GET'
      if (url === '/api/v1/claims/capabilities') {
        return jsonResponse({
          claim_types: ['motor', 'home', 'contents'],
          default_model_profile_id: 'qwen-local',
          models: [
            { id: 'qwen-local', label: 'qwen3.8-27b', protocol: 'openai_compatible', structured_output: true, tools: true },
            { id: 'nowcoding-gpt54mini', label: 'gpt-5.4-mini', protocol: 'openai_compatible', structured_output: true, tools: true },
          ],
        })
      }
      if (url === '/api/v1/account') {
        return jsonResponse({
          customer_id: 'cus_test',
          development_identity: true,
          profile: { display_name: 'Test Claimant', email: 'test@example.invalid', phone: '' },
          preferences: { email: true, sms: false },
        })
      }
      if (url === '/api/v1/claims?limit=25') {
        return jsonResponse({
          items: [{
            ...persistedClaim,
            can_resume: true,
          }],
          page: { next_cursor: null },
        })
      }
      if (url === `/api/v1/claims/${persistedClaim.claim_id}/sessions` && method === 'POST') {
        const body = JSON.parse(options.body)
        expect(body).toEqual({ intent: 'resume' })
        return jsonResponse(persistedSession, 201)
      }
      if (url === `/api/v1/claims/${persistedClaim.claim_id}`) return jsonResponse(persistedClaim)
      if (url === `/api/v1/claims/${persistedClaim.claim_id}/sessions/${persistedSession.session_id}/messages?limit=100`) {
        return jsonResponse({ items: [], page: { next_cursor: null } })
      }
      throw new Error(`Unexpected request: ${method} ${url}`)
    })

    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Resume claim' }))

    expect(await screen.findByRole('heading', { name: 'Continue where you left off' })).toBeVisible()
    expect(screen.getByRole('combobox', { name: 'Model' })).toHaveValue('nowcoding-gpt54mini')
  })
})
