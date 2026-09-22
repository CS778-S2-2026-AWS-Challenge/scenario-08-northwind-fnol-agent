import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ClaimTabs from './ClaimTabs.jsx'

const tabs = [
  { claimId: 'clm_1', label: 'Alex Morgan', reference: 'NW-100', referenceLabel: 'NW-100', draft: '' },
  { claimId: 'clm_2', label: 'Motor claim', reference: 'NW-101', referenceLabel: 'NW-101', draft: 'unsent' },
  { claimId: 'clm_3', label: 'Home claim', reference: 'NW-102', referenceLabel: 'NW-102', draft: '' },
]

describe('ClaimTabs', () => {
  it('offers an explicit open-Claim list for compact and mobile layouts', async () => {
    const user = userEvent.setup()
    const onActivate = vi.fn()
    render(<ClaimTabs tabs={tabs} activeId="clm_1" onActivate={onActivate} onClose={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Show all open claims' }))
    const homeClaim = within(document.getElementById('open-claim-list')).getByRole('button', { name: 'Home claim' })
    expect(homeClaim).toBeVisible()
    await user.click(homeClaim)
    expect(onActivate).toHaveBeenCalledWith('clm_3')
  })

  it('keeps tab semantics and exposes unsent drafts', () => {
    render(<ClaimTabs tabs={tabs} activeId="clm_2" onActivate={vi.fn()} onClose={vi.fn()} />)

    expect(screen.getByRole('tab', { name: 'Motor claim' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByText(/Claim NW-101/)).not.toBeInTheDocument()
    expect(screen.getByTitle('Unsent draft')).toBeInTheDocument()
  })
})
