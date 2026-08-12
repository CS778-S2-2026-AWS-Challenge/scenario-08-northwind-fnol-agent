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
})
