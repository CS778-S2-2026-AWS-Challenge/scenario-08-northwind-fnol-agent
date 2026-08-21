import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

describe('claimant intake', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
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
    expect(screen.getByRole('button', { name: 'Continue claim' })).toBeEnabled()
  })

  it('keeps the claimant entry path operable by keyboard', async () => {
    fetch.mockImplementationOnce(() => jsonResponse(createdClaim(), 201))
    fetch.mockImplementationOnce(() => jsonResponse(firstTurn()))
    const user = userEvent.setup()
    render(<App />)

    await user.tab()
    expect(screen.getByRole('link', { name: 'Northwind home' })).toHaveFocus()
    await user.tab()
    const description = screen.getByLabelText('Incident description')
    expect(description).toHaveFocus()
    await user.type(description, 'Another vehicle hit my parked car.')
    await user.tab()
    expect(screen.getByRole('button', { name: 'Continue claim' })).toHaveFocus()
    await user.keyboard('{Enter}')

    expect(await screen.findByRole('button', { name: 'Confirm details' })).toBeEnabled()
  })

  it('resumes a saved report with confirmed facts and focused context', async () => {
    const resumedNextStep = {
      ...nextStep,
      status: 'provide_incident_location',
      summary: 'Where did the incident happen?',
      required_items: ['incident.location'],
    }
    const confirmedDescription = {
      ...firstTurn().form_changes[0].field,
      status: 'confirmed',
    }
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        items: [{
          claim_id: 'clm_saved',
          revision: 6,
          incident_type: 'motor',
          workflow_state: 'awaiting_evidence',
          external_claim: null,
          customer_next_step: resumedNextStep,
          created_at: '2026-08-02T02:00:00Z',
          updated_at: '2026-08-12T02:20:00Z',
          can_resume: true,
        }],
        page: { next_cursor: null },
      }),
    )
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        session_id: 'ses_resumed',
        claim_id: 'clm_saved',
        status: 'active',
        resume: {
          summary: 'Rear-end collision; the incident description is confirmed.',
          unresolved_questions: ['Where did the incident happen?'],
          pending_items: ['Police report expected later.'],
          prior_commitments: ['The police report can be added without restarting.'],
          customer_next_step: resumedNextStep,
        },
        started_at: '2026-08-12T02:20:00Z',
        last_active_at: '2026-08-12T02:20:00Z',
        closed_at: null,
      }, 201),
    )
    fetch.mockImplementationOnce(() =>
      jsonResponse({
        ...createdClaim().claim,
        claim_id: 'clm_saved',
        revision: 7,
        incident_type: 'motor',
        form: { 'incident.description': confirmedDescription },
        customer_next_step: resumedNextStep,
      }),
    )
    fetch.mockImplementationOnce(() =>
      jsonResponse({ items: [], page: { next_cursor: null } }),
    )

    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Resume a saved report' }))
    expect(await screen.findByText('Where did the incident happen?')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Resume report' }))

    expect(await screen.findByText('Continue where you left off')).toBeVisible()
    expect(screen.getByText('Rear-end collision; the incident description is confirmed.')).toBeVisible()
    expect(screen.getByText('Police report expected later.')).toBeVisible()
    expect(screen.getByText('The police report can be added without restarting.')).toBeVisible()
    expect(screen.getByText('Confirmed')).toBeVisible()
    expect(screen.getByLabelText('Incident location')).toBeEnabled()
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      '/api/v1/claims/clm_saved/sessions',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('reuses the claim idempotency key when a failed submission is retried', async () => {
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
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: 'Continue claim' }))
    await screen.findByRole('button', { name: 'Confirm details' })

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
