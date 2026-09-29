import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PrivacyPage from './PrivacyPage.jsx'
import { privacyContent, TO_BE_CONFIRMED } from './privacyContent.js'

function useViewport({ mobile = false } = {}) {
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: mobile,
    media: '(max-width: 980px)',
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })))
}

function renderPrivacyPage(props = {}) {
  return render(
    <PrivacyPage
      claimType="motor"
      hasCurrentClaim
      onBack={vi.fn()}
      onViewClaim={vi.fn()}
      {...props}
    />,
  )
}

function sectionTitles(container) {
  return [...container.querySelectorAll('.privacy-section > h2')]
    .map((heading) => heading.textContent.replace(/[+−]$/, ''))
}

describe('PrivacyPage', () => {
  let warn

  beforeEach(() => {
    globalThis.history.replaceState({}, '', '/')
    useViewport()
    warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    warn.mockRestore()
  })

  it('renders the full approved common content and explicit prototype configuration state', () => {
    const { container } = renderPrivacyPage()

    expect(screen.getByRole('heading', { level: 1, name: 'Privacy & your data' })).toBeVisible()
    expect(screen.getByText(privacyContent.prototypeNotice)).toBeVisible()
    expect(screen.getByText(/29 September 2026/)).toBeVisible()
    expect(container.querySelectorAll('.privacy-section')).toHaveLength(17)
    expect(screen.getAllByText(TO_BE_CONFIRMED).length).toBeGreaterThan(10)
    expect(screen.getByRole('heading', { name: 'Use of AI and automated tools' })).toBeVisible()
    expect(screen.getByText(/do not make the final decision about policy cover/)).toBeVisible()
    expect(screen.getByRole('link', { name: 'Office of the Privacy Commissioner website' }))
      .toHaveAttribute('href', 'https://www.privacy.org.nz/')
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('lastUpdated.production'))
  })

  it.each([
    ['motor', 'Information collected for a Motor claim', 'Information collected for a Home & Contents claim'],
    ['home', 'Information collected for a Home & Contents claim', 'Information collected for a Motor claim'],
    ['contents', 'Information collected for a Home & Contents claim', 'Information collected for a Motor claim'],
  ])('puts the %s product section first', (claimType, firstTitle, secondTitle) => {
    const { container } = renderPrivacyPage({ claimType })
    const titles = sectionTitles(container)

    expect(titles.indexOf(firstTitle)).toBeLessThan(titles.indexOf(secondTitle))
    expect(screen.getByText('Your current claim')).toBeVisible()
    expect(screen.getByText('Other claim types')).toBeVisible()
  })

  it('shows both product sections equally when there is no current claim', () => {
    const { container } = renderPrivacyPage({
      claimType: null,
      hasCurrentClaim: false,
      onViewClaim: null,
    })

    expect(screen.queryByRole('heading', { name: 'Information recorded for your current claim' }))
      .not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'View information recorded for this claim' }))
      .not.toBeInTheDocument()
    expect(screen.getByText('Motor and Home & Contents information is shown with equal prominence.'))
      .toBeVisible()
    expect(sectionTitles(container).slice(2, 4)).toEqual([
      'Information collected for a Motor claim',
      'Information collected for a Home & Contents claim',
    ])
    expect(screen.queryByText('Your current claim')).not.toBeInTheDocument()
    expect(screen.queryByText('Other claim types')).not.toBeInTheDocument()
  })

  it('renders the claim-data action only when a real callback is supplied', async () => {
    const user = userEvent.setup()
    const onViewClaim = vi.fn()
    const { rerender } = renderPrivacyPage({ onViewClaim })

    await user.click(screen.getByRole('button', { name: 'View information recorded for this claim' }))
    expect(onViewClaim).toHaveBeenCalledOnce()

    rerender(
      <PrivacyPage
        claimType="motor"
        hasCurrentClaim
        onBack={vi.fn()}
        onViewClaim={null}
      />,
    )
    expect(screen.queryByRole('button', { name: 'View information recorded for this claim' }))
      .not.toBeInTheDocument()
  })

  it('uses native-button accordion semantics and opens the approved mobile defaults', async () => {
    const user = userEvent.setup()
    useViewport({ mobile: true })
    renderPrivacyPage({ claimType: 'motor' })

    const information = screen.getByRole('button', { name: /Information we collect/ })
    const motor = screen.getByRole('button', { name: /Information collected for a Motor claim/ })
    const rights = screen.getByRole('button', { name: /Your rights and choices/ })
    const about = screen.getByRole('button', { name: /About this notice/ })

    expect(information).toHaveAttribute('aria-expanded', 'true')
    expect(motor).toHaveAttribute('aria-expanded', 'true')
    expect(rights).toHaveAttribute('aria-expanded', 'true')
    expect(about).toHaveAttribute('aria-expanded', 'false')
    expect(document.getElementById(about.getAttribute('aria-controls'))).toHaveClass('is-collapsed')

    about.focus()
    await user.keyboard('{Enter}')
    expect(about).toHaveAttribute('aria-expanded', 'true')
    await user.keyboard(' ')
    expect(about).toHaveAttribute('aria-expanded', 'false')
  })

  it('opens a collapsed section for table-of-contents and browser-fragment navigation', async () => {
    const user = userEvent.setup()
    useViewport({ mobile: true })
    renderPrivacyPage()

    await user.click(screen.getByText('On this page'))
    const securityLink = within(screen.getByRole('navigation', { name: 'On this page' }))
      .getByRole('link', { name: 'Security' })
    await user.click(securityLink)
    expect(screen.getByRole('button', { name: /Security/ })).toHaveAttribute('aria-expanded', 'true')

    globalThis.history.pushState({}, '', '#contact-us')
    fireEvent(globalThis, new HashChangeEvent('hashchange'))
    expect(screen.getByRole('button', { name: /Contact us/ })).toHaveAttribute('aria-expanded', 'true')
  })
})
