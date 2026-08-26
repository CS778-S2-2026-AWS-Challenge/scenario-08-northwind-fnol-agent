import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import at08ResumeFixture from '../../tests/fixtures/api/AT-08-resume-public.json'
import App from './App.jsx'

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

describe('claimant intake', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    vi.stubGlobal('scrollTo', vi.fn())
    window.history.replaceState(null, '', '/')
    localStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lets claimants start without login and keeps employee access inside the login page', async () => {
    const user = userEvent.setup()
    render(<App />)

    expect(screen.getByRole('tab', { name: 'Motor' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByLabelText('Incident description')).toBeEnabled()
    expect(screen.queryByRole('link', { name: 'Employee access' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Log in' }))

    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
    expect(screen.getByRole('link', { name: 'Employee access' })).toHaveAttribute(
      'href',
      'http://127.0.0.1:8002/',
    )
    expect(screen.getByRole('button', { name: 'Log in to prototype' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Start a claim without logging in' }))
    expect(screen.getByLabelText('Incident description')).toBeEnabled()
  })

  it('opens a prototype customer account and saves profile preferences locally', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Log in' }))
    await user.type(screen.getByLabelText('Email address'), 'alex@example.com')
    await user.type(screen.getByLabelText('Password'), 'prototype-password')
    await user.click(screen.getByRole('button', { name: 'Log in to prototype' }))

    expect(screen.getByRole('heading', { name: /When the unexpected happens/ })).toBeVisible()
    const accountMenu = screen.getByRole('button', { name: 'Customer account menu' })
    expect(accountMenu).toBeVisible()
    await user.hover(accountMenu)
    await user.click(screen.getByRole('button', { name: 'Account overview' }))

    expect(screen.getByRole('heading', { name: 'Good morning, Alex' })).toBeVisible()
    const accountDisclosure = screen.getByRole('note')
    expect(accountDisclosure).toHaveTextContent('profile, claim, and message data shown here is synthetic')
    expect(accountDisclosure).toHaveTextContent('stored only in this browser')
    expect(accountDisclosure).toHaveTextContent('Authentication is not connected')
    expect(screen.getByText(/Claim detail navigation is not connected/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'View claim details' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Profile and preferences' }))
    const lastName = screen.getByLabelText('Last name')
    await user.clear(lastName)
    await user.type(lastName, 'Taylor')
    await user.selectOptions(screen.getByLabelText('Preferred contact method'), 'sms')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(screen.getByRole('status')).toHaveTextContent('Changes saved')
    expect(JSON.parse(localStorage.getItem('northwind-customer-profile-prototype'))).toMatchObject({
      lastName: 'Taylor',
      contactPreference: 'sms',
    })
  })

  it('offers a three-step guided Motor claim without replacing conversational intake', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByRole('button', { name: /Start guided Motor claim/ }))

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

  it('shows a preparation checklist for each claim type', async () => {
    const user = userEvent.setup()
    render(<App />)

    expect(screen.getByRole('heading', { name: 'Motor claim materials' })).toBeVisible()
    expect(screen.getByText('Vehicle and driver details')).toBeVisible()

    await user.click(screen.getByRole('tab', { name: 'Home' }))
    expect(screen.getByRole('heading', { name: 'Home claim materials' })).toBeVisible()
    expect(screen.getByText('Emergency work records')).toBeVisible()

    await user.click(screen.getByRole('tab', { name: 'Contents' }))
    expect(screen.getByRole('heading', { name: 'Contents claim materials' })).toBeVisible()
    expect(screen.getByText('Proof of ownership')).toBeVisible()
  })

  it('returns to the homepage when browser history goes back from the claim page', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByRole('button', { name: /Start guided Motor claim/ }))
    expect(screen.getByRole('heading', { name: 'Your details and incident' })).toBeVisible()

    window.dispatchEvent(new PopStateEvent('popstate', { state: null }))

    expect(await screen.findByRole('heading', { name: /When the unexpected happens/ })).toBeVisible()
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0 })
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
    expect(screen.getByLabelText('Add more information')).toBeDisabled()
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      '/api/v1/claims/clm_test/sessions/ses_test/messages',
      expect.objectContaining({ method: 'POST' }),
    )
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
    await user.tab() // Start a claim hero action
    expect(screen.getByRole('link', { name: 'Start a claim' })).toHaveFocus()
    expect(screen.getByRole('link', { name: 'Start a claim' })).toHaveAttribute('href', '#claims')
    await user.tab() // Claim online hero shortcut
    await user.tab() // Motor
    await user.tab() // Home
    await user.tab() // Contents
    await user.tab() // Guided Motor claim
    await user.tab()
    const otherWays = screen.getByText('Other ways to claim')
    expect(otherWays).toHaveFocus()
    await user.keyboard('{Enter}')
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
          priority: 'standard',
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
          priority: 'standard',
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
    await user.click(await screen.findByRole('button', { name: 'Refresh status' }))

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
          priority: 'standard',
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
          priority: 'standard',
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
    await user.click(await screen.findByRole('button', { name: 'Refresh status' }))

    expect(await screen.findByText('A Northwind staff member is now assisting you.')).toBeVisible()
    expect(screen.queryByText('Human support')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Refresh status' })).not.toBeInTheDocument()
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
        priority: 'urgent',
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
