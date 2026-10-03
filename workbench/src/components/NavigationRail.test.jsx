import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import NavigationRail from './NavigationRail.jsx'

vi.mock('./AccountMenu.jsx', () => ({
  default: () => <div data-testid="account-menu" />,
}))

function renderNavigation(pathname, { activeCount = 4, draftCount = 3 } = {}) {
  render(
    <MemoryRouter initialEntries={[pathname]}>
      <NavigationRail
        profile={{ staff_id: 'stf_demo', display_name: 'Demo Staff' }}
        activeCount={activeCount}
        draftCount={draftCount}
        onLogout={vi.fn()}
        onAgent={vi.fn()}
      />
    </MemoryRouter>,
  )
}

describe('NavigationRail', () => {
  it('renders Draft claims as a peer navigation item with a subdued count and selected state', () => {
    renderNavigation('/workbench/drafts/clm_1')

    const navigation = screen.getByRole('navigation', { name: 'Workbench navigation' })
    const links = within(navigation).getAllByRole('link')
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/workbench',
      '/workbench/active',
      '/workbench/drafts',
      '/workbench/conversations',
    ])

    const drafts = within(navigation).getByRole('link', { name: '3 Draft claims' })
    expect(drafts).toHaveClass('active')
    expect(drafts).toHaveAttribute('aria-current', 'page')
    expect(within(drafts).getByText('3')).toHaveClass('navigation-rail__count')
    expect(within(navigation).getByRole('link', { name: 'Workbench' })).not.toHaveClass('active')
  })

  it('selects Active claims and exposes its count between Workbench and Draft claims', () => {
    renderNavigation('/workbench/active/claims/clm_1')

    const navigation = screen.getByRole('navigation', { name: 'Workbench navigation' })
    const active = within(navigation).getByRole('link', { name: '4 Active claims' })
    expect(active).toHaveClass('active')
    expect(active).toHaveAttribute('aria-current', 'page')
    expect(within(active).getByText('4')).toHaveClass('navigation-rail__count')
    expect(within(navigation).getByRole('link', { name: 'Workbench' })).not.toHaveClass('active')
    expect(within(navigation).getByRole('link', { name: '3 Draft claims' })).not.toHaveClass('active')
  })

  it('renders the server-authoritative zero for Active claims', () => {
    renderNavigation('/workbench/active', { activeCount: 0 })

    const active = screen.getByRole('link', { name: '0 Active claims' })
    expect(within(active).getByText('0')).toHaveClass('navigation-rail__count')
  })

  it('names every rail control independently of its visible text, which the collapsed rail hides', () => {
    renderNavigation('/workbench')

    const navigation = screen.getByRole('navigation', { name: 'Workbench navigation' })
    expect(within(navigation).getByRole('link', { name: 'Workbench' })).toHaveAttribute('aria-label', 'Workbench')
    expect(within(navigation).getByRole('link', { name: 'Claim conversations' }))
      .toHaveAttribute('aria-label', 'Claim conversations')
    expect(within(navigation).getByRole('button', { name: 'Staff Agent' })).toHaveAttribute('aria-label', 'Staff Agent')
  })

  it('keeps Workbench selected for a submitted Claim detail route', () => {
    renderNavigation('/workbench/claims/clm_1')

    const workbench = screen.getByRole('link', { name: 'Workbench' })
    expect(workbench).toHaveClass('active')
    expect(workbench).toHaveAttribute('aria-current', 'page')
  })
})
