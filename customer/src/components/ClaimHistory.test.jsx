import { expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ClaimHistory, { ClaimFeatureDirectory } from './ClaimHistory.jsx'

const olderClaim = {
  claim_id: 'clm_home_older',
  incident_type: 'home',
  external_claim: { creation_status: 'created' },
  customer_next_step: { summary: 'Add the affected property address.' },
  updated_at: '2026-09-12T01:00:00Z',
}

const newerClaim = {
  claim_id: 'clm_motor_newer',
  incident_type: 'motor',
  workflow_state: 'professional_review',
  external_claim: { claim_number: 'NWF-2026-001042', creation_status: 'created' },
  customer_next_step: {
    status: 'claims_review',
    summary: 'Review the incident details.',
    responsible_party: 'claims_professional',
    expected_by: '2026-09-15T03:30:00Z',
  },
  updated_at: '2026-09-14T03:30:00Z',
}

// The most recently updated report is still in progress: it is promoted separately from past Claims.
const reportInProgress = {
  claim_id: 'clm_motor_in_progress',
  incident_type: 'motor',
  workflow_state: 'collecting',
  external_claim: null,
  customer_next_step: {
    status: 'confirmation_required',
    summary: 'Review and confirm the proposed incident information.',
    responsible_party: 'claimant',
  },
  updated_at: '2026-09-15T00:00:00Z',
}

const olderReportInProgress = {
  ...reportInProgress,
  claim_id: 'clm_home_in_progress',
  incident_type: 'home',
  external_claim: { creation_status: 'pending' },
  updated_at: '2026-09-13T00:00:00Z',
}

it('lists only created Claims, latest update first, with their reference, status, and next step', () => {
  render(<ClaimHistory claims={[olderClaim, reportInProgress, newerClaim]} onSelect={vi.fn()} />)

  const rows = screen.getAllByRole('button', { name: /^Open / })
  expect(rows.map((row) => row.getAttribute('aria-label'))).toEqual([
    'Open Motor claim, Claim NWF-2026-001042',
    'Open Home claim, Claim reference clm_home_older',
  ])
  expect(screen.getByText('2 claims')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Your report is underway' })).toBeInTheDocument()
  expect(screen.queryByText(/clm_motor_in_progress/)).not.toBeInTheDocument()

  const newest = within(rows[0])
  expect(newest.getByText('Claims Review')).toBeInTheDocument()
  expect(newest.getByText('Review the incident details.')).toBeInTheDocument()
  expect(newest.getByText('Responsible now: Claims professional')).toBeInTheDocument()
  expect(newest.getByText('Updated 14 Sept 2026, 3:30 pm')).toBeInTheDocument()
  expect(rows[0]).toHaveAccessibleDescription(
    'Review the incident details. Responsible now: Claims professional',
  )
})

it('opens a created Claim from the keyboard', async () => {
  const user = userEvent.setup()
  const onSelect = vi.fn()
  render(<ClaimHistory claims={[olderClaim, newerClaim]} onRetry={vi.fn()} onSelect={onSelect} />)

  await user.tab()
  await user.tab()
  expect(screen.getByRole('button', { name: /NWF-2026-001042/ })).toHaveFocus()
  await user.keyboard('{Enter}')

  expect(onSelect).toHaveBeenCalledWith(newerClaim)
})

it('offers a route to start a Claim when the claimant has none', async () => {
  const user = userEvent.setup()
  const onStartClaim = vi.fn()
  render(<ClaimHistory claims={[]} onSelect={vi.fn()} onStartClaim={onStartClaim} />)

  expect(screen.getByRole('heading', { name: 'No past claims yet' })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Start a claim' }))

  expect(onStartClaim).toHaveBeenCalledOnce()
})

it('tells a claimant with reports in progress where they are instead of calling the list empty', async () => {
  const user = userEvent.setup()
  const onContinueReport = vi.fn()
  render(
    <ClaimHistory
      claims={[olderReportInProgress, reportInProgress]}
      onSelect={vi.fn()}
      onStartClaim={vi.fn()}
      onContinueReport={onContinueReport}
    />,
  )

  expect(screen.getByRole('heading', { name: 'Your report is underway' })).toBeInTheDocument()
  expect(screen.getByText('0 claims')).toBeInTheDocument()
  expect(screen.getByText(/Finish the remaining details in your conversation\./)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Start a claim' })).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Continue report' }))

  expect(onContinueReport).toHaveBeenCalledWith('clm_motor_in_progress')
})

it('keeps earlier Claim records visible when a refresh fails', () => {
  render(
    <ClaimHistory
      claims={[olderClaim]}
      error="The Claim service did not respond."
      onRetry={vi.fn()}
      onSelect={vi.fn()}
    />,
  )

  expect(screen.getByText('Showing earlier Claim records')).toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: 'Open Home claim, Claim reference clm_home_older' }),
  ).toBeInTheDocument()
})

it('reports a failed load with a retry when no created Claim can be shown', async () => {
  const user = userEvent.setup()
  const onRetry = vi.fn()
  render(<ClaimHistory claims={[]} error="The Claim service did not respond." onRetry={onRetry} onSelect={vi.fn()} />)

  expect(screen.getByRole('alert')).toHaveTextContent('Claim history could not be loaded')
  await user.click(screen.getByRole('button', { name: 'Try again' }))

  expect(onRetry).toHaveBeenCalledOnce()
})

it('does not substitute internal workflow state in a history row', () => {
  render(
    <ClaimHistory
      claims={[{ ...newerClaim, customer_next_step: { summary: 'Review the incident details.' } }]}
      onSelect={vi.fn()}
    />,
  )

  const row = within(screen.getByRole('button', { name: /NWF-2026-001042/ }))
  expect(row.getByText('Status unavailable')).toBeInTheDocument()
  expect(row.getByText('Responsible now: Not available')).toBeInTheDocument()
  expect(screen.queryByText('Professional Review')).not.toBeInTheDocument()
})

it('shows the selected Claim status summary and opens Evidence history', async () => {
  const user = userEvent.setup()
  const onOpenEvidence = vi.fn()
  render(<ClaimFeatureDirectory claim={newerClaim} onOpenEvidence={onOpenEvidence} />)

  expect(screen.getByRole('heading', { name: 'NWF-2026-001042' })).toBeInTheDocument()
  expect(screen.getByText('Claims Review')).toBeInTheDocument()
  expect(screen.getByText('Claims professional')).toBeInTheDocument()
  expect(screen.getByText('Review the incident details.')).toBeInTheDocument()
  expect(screen.getByText('Expected by 15 Sept 2026, 3:30 pm')).toBeInTheDocument()
  expect(screen.getByText('Last updated 14 Sept 2026, 3:30 pm')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /Evidence history/ }))

  expect(onOpenEvidence).toHaveBeenCalledOnce()
})

it('does not invent an estimated wait when the server omits it', () => {
  render(<ClaimFeatureDirectory claim={olderClaim} onOpenEvidence={vi.fn()} />)

  expect(screen.getByRole('heading', { name: olderClaim.claim_id })).toBeInTheDocument()
  expect(screen.getByText('No estimate available')).toBeInTheDocument()
})

it.each([
  ['claimant', 'You'],
  ['claims_professional', 'Claims professional'],
  ['external_party', 'External service provider'],
  ['system', 'System'],
  ['future_party', 'Not available'],
  [undefined, 'Not available'],
])('renders claimant-safe responsibility %s as %s', (responsibleParty, expectedLabel) => {
  render(
    <ClaimFeatureDirectory
      claim={{
        ...olderClaim,
        customer_next_step: {
          ...olderClaim.customer_next_step,
          status: 'in_progress',
          responsible_party: responsibleParty,
        },
      }}
      onOpenEvidence={vi.fn()}
    />,
  )

  expect(screen.getByText(expectedLabel)).toBeInTheDocument()
})

it('does not substitute internal workflow state when claimant-safe status is missing', () => {
  render(
    <ClaimFeatureDirectory
      claim={{
        ...olderClaim,
        workflow_state: 'professional_review',
        customer_next_step: {
          ...olderClaim.customer_next_step,
          responsible_party: 'system',
        },
      }}
      onOpenEvidence={vi.fn()}
    />,
  )

  expect(screen.getByText('Status unavailable')).toBeInTheDocument()
  expect(screen.queryByText('Professional Review')).not.toBeInTheDocument()
})
