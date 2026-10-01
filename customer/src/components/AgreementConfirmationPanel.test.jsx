import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import AgreementConfirmationPanel from './AgreementConfirmationPanel.jsx'

const claim = {
  claim_id: 'clm_test',
  revision: 7,
  incident_type: 'home',
  form: {
    'incident.occurred_at': { value: '2026-10-01T07:30:00' },
    'property.address': { value: 'Fisher Building' },
    'claimant.contact_preference': { value: 'email' },
  },
  contents_items: [],
  evidence_summary: { state: 'not_started' },
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

function formattedDateTime(value) {
  const date = new Date(value)
  const dateLabel = new Intl.DateTimeFormat('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(date)
  const timeLabel = new Intl.DateTimeFormat('en-NZ', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).format(date)
  return `${dateLabel} · ${timeLabel}`
}

describe('AgreementConfirmationPanel', () => {
  it('renders backend copy and blocks submit until required confirmation', () => {
    const onSubmit = vi.fn()
    const onReviewInformation = vi.fn()

    render(
      <AgreementConfirmationPanel
        claim={claim}
        busy={false}
        status="idle"
        onSubmit={onSubmit}
        onReviewInformation={onReviewInformation}
        onReturnToConversation={vi.fn()}
      />,
    )

    const progressbar = screen.getByRole('progressbar', {
      name: 'Claim submission progress',
    })
    expect(progressbar).toHaveAttribute('aria-valuenow', '4')
    expect(progressbar).toHaveAttribute('aria-valuemax', '4')
    expect(progressbar).toHaveAttribute('aria-valuetext', 'Step 4 of 4: Review & submit')
    expect(progressbar.parentElement).toHaveTextContent('Step 4 of 4 · Review & submit')
    expect(
      screen.getByRole('heading', { name: 'Review and submit your claim' }),
    ).toBeTruthy()
    expect(screen.getByText('Home')).toBeTruthy()
    expect(screen.getByText('1 Oct 2026 · 7:30 am')).toBeTruthy()
    expect(screen.getByText('Fisher Building')).toBeTruthy()
    expect(screen.getByText('Email')).toBeTruthy()
    expect(screen.getByText('Not provided')).toBeTruthy()
    expect(screen.getByText('Saved')).toBeTruthy()
    expect(
      screen.getByText('Review the current claim information before submission.'),
    ).toBeTruthy()

    const submit = screen.getByRole('button', { name: 'Submit claim' })
    expect(submit.disabled).toBe(true)

    fireEvent.click(screen.getByRole('checkbox', { name: 'I confirm this submission.' }))
    expect(submit.disabled).toBe(false)

    fireEvent.click(submit)

    expect(onSubmit).toHaveBeenCalledWith({
      reviewed_and_confirmed: true,
    })

    fireEvent.click(screen.getByRole('button', { name: 'Edit details' }))
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(onReviewInformation).toHaveBeenCalledTimes(2)
  })

  it('keeps submission feedback inside the final confirmation card', () => {
    render(
      <AgreementConfirmationPanel
        claim={claim}
        busy={false}
        status="idle"
        submissionError={{
          title: "Couldn't send your claim",
          message: "Your claim hasn't been sent. Check your connection and try again.",
        }}
        onSubmit={vi.fn()}
        onReviewInformation={vi.fn()}
        onReturnToConversation={vi.fn()}
      />,
    )

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent("Couldn't send your claim")
    expect(alert).toHaveTextContent("Your claim hasn't been sent")
  })

  it('shows the backend creation result instead of a dead submit action', () => {
    const onReturnToConversation = vi.fn()
    const submittedAt = '2026-10-02T03:07:45.464181Z'
    const expectedBy = '2026-10-03T03:07:45Z'

    render(
      <AgreementConfirmationPanel
        claim={{
          ...claim,
          external_claim: {
            claim_number: 'NWF-2026-16ECDD',
            creation_status: 'created',
            route: 'Claims intake review',
            next_step: 'A claims specialist will review the submitted details.',
            expected_by: expectedBy,
            created_at: submittedAt,
          },
        }}
        busy={false}
        status="idle"
        onSubmit={vi.fn()}
        onReviewInformation={vi.fn()}
        onReturnToConversation={onReturnToConversation}
      />,
    )

    const heading = screen.getByRole('heading', { name: 'Your claim has been submitted' })
    const successPage = heading.closest('.claim-submitted-page')
    expect(successPage).not.toBeNull()
    expect(within(successPage).getByText('NWF-2026-16ECDD')).toBeTruthy()
    expect(within(successPage).getByText('Submitted')).toBeTruthy()
    expect(within(successPage).queryByText('created')).toBeNull()
    expect(within(successPage).getByText('Home')).toBeTruthy()
    expect(within(successPage).getByText('Email')).toBeTruthy()
    expect(
      within(successPage).getByRole('heading', { name: 'Claims intake review' }),
    ).toBeTruthy()
    expect(
      within(successPage).getByText('A claims specialist will review the submitted details.'),
    ).toBeTruthy()
    expect(within(successPage).getByText(formattedDateTime(submittedAt))).toBeTruthy()
    const expectedTime = within(successPage).getByText(formattedDateTime(expectedBy))
    expect(expectedTime.closest('p')).toHaveTextContent(
      `Expected by ${formattedDateTime(expectedBy)}`,
    )
    expect(within(successPage).queryByText(submittedAt)).toBeNull()
    expect(within(successPage).queryByText(expectedBy)).toBeNull()
    expect(screen.queryByText(claim.submission_agreement.display_copy)).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Review and submit your claim' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Submit claim' })).toBeNull()

    fireEvent.click(within(successPage).getByRole('button', { name: 'Back to conversation' }))
    expect(onReturnToConversation).toHaveBeenCalledTimes(1)
  })

  it('omits unavailable success dates without rendering an invalid value', () => {
    const { container } = render(
      <AgreementConfirmationPanel
        claim={{
          ...claim,
          external_claim: {
            claim_number: 'NWF-2026-NO-DATE',
            creation_status: 'created',
            next_step: 'Claims intake review',
            expected_by: null,
            created_at: null,
          },
        }}
        busy={false}
        status="idle"
        onSubmit={vi.fn()}
        onReviewInformation={vi.fn()}
        onReturnToConversation={vi.fn()}
      />,
    )

    expect(container.querySelectorAll('time')).toHaveLength(0)
    expect(screen.queryByText('Invalid Date')).toBeNull()
    expect(screen.getAllByText('Completed')).toHaveLength(2)
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
    expect(screen.getByRole('progressbar', { name: 'Claim submission progress' }))
      .toHaveAttribute('aria-valuetext', 'Step 4 of 4: Submit claim')

    const retry = screen.getByRole('button', {
      name: 'Retry claim submission',
    })
    expect(retry.disabled).toBe(false)

    fireEvent.click(retry)
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['missing', null],
    ['stale', { ...claim.primary_action, claim_revision: claim.revision - 1 }],
    ['unavailable', { ...claim.primary_action, available: false }],
    ['unknown', { ...claim.primary_action, action_code: 'claimant.continue_conversation' }],
  ])('does not manufacture progress from a %s primary action projection', (_, primaryAction) => {
    render(
      <AgreementConfirmationPanel
        claim={{ ...claim, primary_action: primaryAction }}
        busy={false}
        status="idle"
        onSubmit={vi.fn()}
        onReviewInformation={vi.fn()}
        onReturnToConversation={vi.fn()}
      />,
    )

    expect(screen.queryByRole('progressbar')).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('Claim progress unavailable')

    fireEvent.click(screen.getByRole('checkbox', { name: 'I confirm this submission.' }))
    expect(screen.getByRole('button', { name: 'Submit claim' })).toBeDisabled()
  })
})
