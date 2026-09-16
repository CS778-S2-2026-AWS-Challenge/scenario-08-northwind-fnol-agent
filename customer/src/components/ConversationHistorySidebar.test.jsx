import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ConversationHistorySidebar from './ConversationHistorySidebar.jsx'

function conversation({
  claimId,
  incidentType,
  updatedAt,
}) {
  return {
    claim_id: claimId,
    incident_type: incidentType,
    created_at: updatedAt,
    updated_at: updatedAt,
    can_resume: true,
  }
}

function SidebarHarness({
  account = { profile: { display_name: 'Test claimant' } },
  activeClaimId = null,
  conversations = [],
  error = '',
  loading = false,
  onLogin = vi.fn(),
  onNewConversation = vi.fn(),
  onRetry = vi.fn(),
  onSelect = vi.fn(),
}) {
  const [isOpen, setIsOpen] = useState(false)
  return (
    <ConversationHistorySidebar
      account={account}
      activeClaimId={activeClaimId}
      busy={false}
      conversations={conversations}
      error={error}
      isOpen={isOpen}
      loading={loading}
      onClose={() => setIsOpen(false)}
      onLogin={onLogin}
      onNewConversation={onNewConversation}
      onOpen={() => setIsOpen(true)}
      onRetry={onRetry}
      onSelect={onSelect}
    />
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ConversationHistorySidebar', () => {
  it('opens as a desktop overlay, closes with Escape, and restores focus', async () => {
    const user = userEvent.setup()
    render(<SidebarHarness account={null} />)

    const opener = screen.getByRole('button', { name: 'Expand conversation history' })
    expect(document.getElementById(opener.getAttribute('aria-describedby'))).toHaveTextContent(
      'Expand conversation history',
    )
    expect(screen.queryByRole('complementary', { name: 'Conversation history' })).not.toBeInTheDocument()

    await user.click(opener)

    expect(screen.getByRole('complementary', { name: 'Conversation history' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Collapse conversation history' })).toHaveFocus()
    expect(screen.getByText('No conversations in this browser session')).toBeVisible()
    expect(screen.getByText('Saved in this browser session.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeVisible()

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('complementary', { name: 'Conversation history' })).not.toBeInTheDocument()
    expect(opener).toHaveFocus()

    await user.click(opener)
    await user.click(document.querySelector('.conversation-sidebar-scrim'))
    expect(screen.queryByRole('complementary', { name: 'Conversation history' })).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('groups real conversations, filters by title, and marks the active item', async () => {
    const user = userEvent.setup()
    const now = Date.now()
    const conversations = [
      conversation({
        claimId: 'clm_today',
        incidentType: 'home',
        updatedAt: new Date(now).toISOString(),
      }),
      conversation({
        claimId: 'clm_previous',
        incidentType: 'contents',
        updatedAt: new Date(now - 2 * 86_400_000).toISOString(),
      }),
      conversation({
        claimId: 'clm_older',
        incidentType: 'motor',
        updatedAt: new Date(now - 10 * 86_400_000).toISOString(),
      }),
    ]
    render(<SidebarHarness conversations={conversations} activeClaimId="clm_today" />)

    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))

    expect(screen.getByRole('heading', { name: 'TODAY' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'PREVIOUS 7 DAYS' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'OLDER' })).toBeVisible()
    expect(screen.getByRole('button', { name: /Open Home claim/ })).toHaveAttribute('aria-current', 'page')
    expect(screen.queryByText('clm_today')).not.toBeInTheDocument()

    await user.type(screen.getByRole('searchbox', { name: 'Search conversations' }), 'contents')

    expect(screen.getByRole('button', { name: /Open Contents claim/ })).toBeVisible()
    expect(screen.queryByRole('button', { name: /Open Home claim/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Open Motor claim/ })).not.toBeInTheDocument()
  })

  it('uses a focus-contained modal drawer on mobile', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })))
    render(<SidebarHarness account={null} />)

    const opener = screen.getByRole('button', { name: 'Open conversation history' })
    await user.click(opener)

    const dialog = screen.getByRole('dialog', { name: 'Conversation history' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByRole('button', { name: 'Collapse conversation history' })).toHaveFocus()

    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Sign in' })).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Collapse conversation history' })).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Conversation history' })).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('uses the supplied new-conversation and retry actions without inventing data', async () => {
    const user = userEvent.setup()
    const onNewConversation = vi.fn()
    const onRetry = vi.fn()
    const { rerender } = render(
      <SidebarHarness onNewConversation={onNewConversation} loading />,
    )

    await user.click(screen.getByRole('button', { name: 'New conversation' }))
    expect(onNewConversation).toHaveBeenCalledOnce()

    rerender(
      <SidebarHarness
        error="The Claim service did not respond."
        onNewConversation={onNewConversation}
        onRetry={onRetry}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Expand conversation history' }))
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})
