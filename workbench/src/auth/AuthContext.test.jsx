import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from './AuthContext.jsx'
import { useAuth } from './auth-context.js'

const mocks = vi.hoisted(() => ({
  clearStoredSession: vi.fn(),
  readStoredSession: vi.fn(),
  storeSession: vi.fn(),
  session: vi.fn(),
  profile: vi.fn(),
  updatePresence: vi.fn(),
  loadSettings: vi.fn(),
  applyAppearanceSettings: vi.fn(),
}))

vi.mock('../api.js', () => ({
  clearStoredSession: mocks.clearStoredSession,
  readStoredSession: mocks.readStoredSession,
  storeSession: mocks.storeSession,
  workbenchApi: {
    session: mocks.session,
    profile: mocks.profile,
    updatePresence: mocks.updatePresence,
    login: vi.fn(),
    logout: vi.fn(),
  },
}))

vi.mock('../account/settings-gateway.js', () => ({
  applyAppearanceSettings: mocks.applyAppearanceSettings,
  browserStaffSettingsGateway: { load: mocks.loadSettings },
}))

function AuthState() {
  const { checking, profile, presenceRevision } = useAuth()
  return (
    <output>
      {checking ? 'Checking' : `${profile?.display_name || 'No profile'} · presence ${presenceRevision ?? 'unavailable'}`}
    </output>
  )
}

describe('AuthProvider staff presence', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.readStoredSession.mockReturnValue({ access_token: 'staff-token', staff_id: 'stf_demo' })
    mocks.session.mockResolvedValue({ staff_id: 'stf_demo' })
    mocks.profile.mockResolvedValue({ staff_id: 'stf_demo', display_name: 'Demo Staff' })
    mocks.updatePresence.mockResolvedValue({ staff_id: 'stf_demo', revision: 4 })
    mocks.loadSettings.mockResolvedValue({ appearance: {} })
  })

  it('renews presence before restoring the protected Workbench and again when the window regains focus', async () => {
    mocks.updatePresence
      .mockResolvedValueOnce({ staff_id: 'stf_demo', revision: 4 })
      .mockResolvedValueOnce({ staff_id: 'stf_demo', revision: 5 })

    render(<AuthProvider><AuthState /></AuthProvider>)

    expect(await screen.findByText('Demo Staff · presence 4')).toBeVisible()
    expect(mocks.updatePresence).toHaveBeenCalledWith('staff-token', {
      online: true,
      available: true,
      leaseSeconds: 300,
    })

    window.dispatchEvent(new Event('focus'))

    await waitFor(() => expect(mocks.updatePresence).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('Demo Staff · presence 5')).toBeVisible()
  })

  it('keeps an authenticated profile usable when presence renewal is temporarily unavailable', async () => {
    mocks.updatePresence.mockRejectedValue(new Error('Presence service unavailable.'))

    render(<AuthProvider><AuthState /></AuthProvider>)

    expect(await screen.findByText('Demo Staff · presence unavailable')).toBeVisible()
    expect(mocks.clearStoredSession).not.toHaveBeenCalled()
  })
})
