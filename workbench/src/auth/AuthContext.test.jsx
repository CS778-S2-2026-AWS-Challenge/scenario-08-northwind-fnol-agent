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
  presence: vi.fn(),
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
    presence: mocks.presence,
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
    mocks.presence.mockResolvedValue({
      staff_id: 'stf_demo',
      online: true,
      available: true,
      revision: 3,
    })
    mocks.updatePresence.mockResolvedValue({ staff_id: 'stf_demo', revision: 4 })
    mocks.loadSettings.mockResolvedValue({ appearance: {} })
  })

  it('renews presence before restoring the protected Workbench and again when the window regains focus', async () => {
    mocks.updatePresence
      .mockResolvedValueOnce({ staff_id: 'stf_demo', revision: 4 })
      .mockResolvedValueOnce({ staff_id: 'stf_demo', revision: 5 })

    render(<AuthProvider><AuthState /></AuthProvider>)

    expect(await screen.findByText('Demo Staff · presence 4')).toBeVisible()
    expect(mocks.presence).toHaveBeenCalledWith('staff-token')
    expect(mocks.updatePresence).toHaveBeenCalledWith('staff-token', {
      online: true,
      available: true,
      leaseSeconds: 300,
    })
    await waitFor(() => expect(mocks.loadSettings).toHaveBeenCalled())

    window.dispatchEvent(new Event('focus'))

    await waitFor(() => expect(mocks.updatePresence).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('Demo Staff · presence 5')).toBeVisible()
  })

  it('preserves explicit unavailability during initial and focus-triggered renewal', async () => {
    mocks.presence.mockResolvedValue({
      staff_id: 'stf_demo',
      online: true,
      available: false,
      revision: 8,
    })
    mocks.updatePresence
      .mockResolvedValueOnce({ staff_id: 'stf_demo', online: true, available: false, revision: 9 })
      .mockResolvedValueOnce({ staff_id: 'stf_demo', online: true, available: false, revision: 10 })

    render(<AuthProvider><AuthState /></AuthProvider>)

    expect(await screen.findByText('Demo Staff · presence 9')).toBeVisible()
    expect(mocks.updatePresence).toHaveBeenLastCalledWith('staff-token', {
      online: true,
      available: false,
      leaseSeconds: 300,
    })
    await waitFor(() => expect(mocks.loadSettings).toHaveBeenCalled())

    window.dispatchEvent(new Event('focus'))

    await waitFor(() => expect(mocks.updatePresence).toHaveBeenCalledTimes(2))
    expect(mocks.presence).toHaveBeenCalledTimes(2)
    expect(mocks.updatePresence).toHaveBeenLastCalledWith('staff-token', {
      online: true,
      available: false,
      leaseSeconds: 300,
    })
    expect(await screen.findByText('Demo Staff · presence 10')).toBeVisible()
  })

  it('keeps an authenticated profile usable when presence renewal is temporarily unavailable', async () => {
    mocks.updatePresence.mockRejectedValue(new Error('Presence service unavailable.'))

    render(<AuthProvider><AuthState /></AuthProvider>)

    expect(await screen.findByText('Demo Staff · presence unavailable')).toBeVisible()
    expect(mocks.clearStoredSession).not.toHaveBeenCalled()
  })
})
