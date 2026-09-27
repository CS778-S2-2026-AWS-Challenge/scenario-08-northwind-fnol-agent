import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import AgreementConfirmationPanel from './AgreementConfirmationPanel.jsx'

const claim = {
  claim_id: 'clm_test',
  revision: 7,
  incident_type: 'motor',
  form: {
    'incident.occurred_at': { value: '2026-09-20' },
    'vehicle.registration': { value: 'ABC123' },
    'claimant.contact_preference': { value: 'email' },
  },
  contents_items: [],
  evidence_summary: { state: 'received' },
  payment_destination_id: 'pyd_0123456789abcdef0123',
  primary_action: {
    action_code: 'claimant.review_agreement',
    available: true,
    claim_revision: 7,
  },
  submission_agreement: {
    agreement_id: 'northwind-fnol-claim-submission',
    version: '1',
    display_copy: 'Review the current claim information before submission.',
    confirmations: [
      {
        key: 'reviewed_and_confirmed',
        label: 'I confirm this submission.',
        required: true,
      },
    ],
  },
}

describe('AgreementConfirmationPanel', () => {
  it('renders backend copy and blocks submit until required confirmation', () => {
    const onSubmit = vi.fn()

    render(
      <AgreementConfirmationPanel
        claim={claim}
        busy={false}
        status="idle"
        onSubmit={onSubmit}
        onReviewInformation={vi.fn()}
        onReturnToConversation={vi.fn()}
      />,
    )

    expect(
      screen.getByText('Review the current claim information before submission.'),
    ).toBeTruthy()

    const submit = screen.getByRole('button', { name: 'Submit claim' })
    expect(submit.disabled).toBe(true)

    fireEvent.click(screen.getByRole('checkbox'))
    expect(submit.disabled).toBe(false)

    fireEvent.click(submit)

    expect(onSubmit).toHaveBeenCalledWith({
      reviewed_and_confirmed: true,
    })
  })

  it('shows the backend creation result instead of a dead submit action', () => {
    const onReturnToConversation = vi.fn()

    render(
      <AgreementConfirmationPanel
        claim={{
          ...claim,
          external_claim: {
            claim_number: 'NWF-2026-16ECDD',
            creation_status: 'created',
            next_step: 'A claims specialist will review the submitted details.',
            expected_by: '2026-09-16T01:00:00Z',
          },
        }}
        busy={false}
        status="idle"
        onSubmit={vi.fn()}
        onReviewInformation={vi.fn()}
        onReturnToConversation={onReturnToConversation}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Claim submitted' })).toBeTruthy()
    expect(screen.getByText('NWF-2026-16ECDD')).toBeTruthy()
    expect(screen.getByText('created')).toBeTruthy()
    expect(
      screen.getByText('A claims specialist will review the submitted details.'),
    ).toBeTruthy()
    expect(screen.getByText('2026-09-16T01:00:00Z')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Submit claim' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Back to conversation' }))
    expect(onReturnToConversation).toHaveBeenCalledTimes(1)
  })

  it('supports creation retry without recording another acceptance', () => {
    const onSubmit = vi.fn()

    render(
      <AgreementConfirmationPanel
        claim={{
          ...claim,
          revision: 8,
          primary_action: {
            ...claim.primary_action,
            action_code: 'claimant.create_claim',
            claim_revision: 8,
          },
        }}
        busy={false}
        status="idle"
        onSubmit={onSubmit}
        onReviewInformation={vi.fn()}
        onReturnToConversation={vi.fn()}
      />,
    )

    expect(screen.getByText(/Agreement confirmed/)).toBeTruthy()

    const retry = screen.getByRole('button', {
      name: 'Retry claim submission',
    })
    expect(retry.disabled).toBe(false)

    fireEvent.click(retry)
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })
})
