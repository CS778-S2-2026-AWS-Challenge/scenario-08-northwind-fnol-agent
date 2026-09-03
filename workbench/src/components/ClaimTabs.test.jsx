import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ClaimTabs from './ClaimTabs.jsx'

const tabs = [
  { claimId: 'clm_1', label: 'NW-100', draft: '' },
  { claimId: 'clm_2', label: 'NW-101', draft: 'unsent' },
  { claimId: 'clm_3', label: 'NW-102', draft: '' },
]

describe('ClaimTabs', () => {
  it('offers an explicit open-Claim list for compact and mobile layouts', async () => {
    const user = userEvent.setup()
    const onActivate = vi.fn()
    render(<ClaimTabs tabs={tabs} activeId="clm_1" onActivate={onActivate} onClose={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Show all open claims' }))
    expect(screen.getByRole('button', { name: 'NW-102' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'NW-102' }))
    expect(onActivate).toHaveBeenCalledWith('clm_3')
  })

  it('keeps tab semantics and exposes unsent drafts', () => {
    render(<ClaimTabs tabs={tabs} activeId="clm_2" onActivate={vi.fn()} onClose={vi.fn()} />)

    expect(screen.getByRole('tab', { name: 'NW-101' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTitle('Unsent draft')).toBeInTheDocument()
  })
})
