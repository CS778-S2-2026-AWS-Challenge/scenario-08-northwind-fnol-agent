import { expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ClaimHistory, { ClaimFeatureDirectory } from './ClaimHistory.jsx'

const olderClaim = {
  claim_id: 'clm_home_older',
  incident_type: 'home',
  customer_next_step: { summary: 'Add the affected property address.' },
  updated_at: '2026-09-12T01:00:00Z',
}

const newerClaim = {
  claim_id: 'clm_motor_newer',
  incident_type: 'motor',
  workflow_state: 'professional_review',
  external_claim: { claim_number: 'NWF-2026-001042' },
  customer_next_step: {
    status: 'claims_review',
    summary: 'Review the incident details.',
    responsible_party: 'claims_professional',
    expected_by: '2026-09-15T03:30:00Z',
  },
  updated_at: '2026-09-14T03:30:00Z',
}

it('lists Claims vertically by the latest server update with formal titles and timestamps', async () => {
  const user = userEvent.setup()
  const onSelect = vi.fn()
  render(<ClaimHistory claims={[olderClaim, newerClaim]} onSelect={onSelect} />)

  const claimLinks = screen.getAllByRole('button', { name: /^Open .* claim clm_/ })
  expect(claimLinks[0]).toHaveAccessibleName('Open Motor claim clm_motor_newer')
  expect(claimLinks[1]).toHaveAccessibleName('Open Home claim clm_home_older')
  expect(screen.getByText('Updated 14 Sept 2026, 3:30 pm')).toBeInTheDocument()

  await user.click(claimLinks[0])
  expect(onSelect).toHaveBeenCalledWith(newerClaim)
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
  expect(screen.getByRole('button', { name: 'Open Home claim clm_home_older' })).toBeInTheDocument()
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
