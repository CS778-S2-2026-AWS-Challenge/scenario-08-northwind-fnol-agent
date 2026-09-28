import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthContext } from '../auth/auth-context.js'
import { setLanguage } from '../i18n.js'
import AccountSettingsPage from './AccountSettingsPage.jsx'

const profile = {
  staff_id: 'stf_settings',
  display_name: 'Taylor Reed',
  email: 'taylor@example.invalid',
  roles: ['claims_professional'],
}

const settings = {
  profile: {
    displayName: 'Taylor Reed',
    email: 'taylor@example.invalid',
    phone: '+64 21 555 0101',
    avatarDataUrl: '',
    position: 'Claims Professional',
    team: 'Motor Claims',
    employeeId: 'stf_settings',
  },
  security: {
    managedByOrganization: false,
    passwordLastChangedAt: '2026-09-01T00:00:00Z',
    twoFactorEnabled: true,
    devices: [{ id: 'current-browser', name: 'Test browser', location: 'Location unavailable', lastActive: 'Active now', current: true }],
  },
  notifications: {
    assignments: true,
    claimStatus: true,
    emailDigest: false,
    systemAnnouncements: true,
  },
  appearance: {
    language: 'en',
    theme: 'light',
    timezone: 'Pacific/Auckland',
    dateFormat: 'DD/MM/YYYY',
  },
  persistence: 'browser',
}

function gateway(overrides = {}) {
  return {
    load: vi.fn().mockResolvedValue(settings),
    saveProfile: vi.fn().mockImplementation(async (_profile, values) => ({
      ...settings,
      profile: { ...settings.profile, ...values },
    })),
    saveAvatar: vi.fn().mockResolvedValue(settings),
    saveNotifications: vi.fn().mockResolvedValue(settings),
    saveAppearance: vi.fn().mockResolvedValue(settings),
    performSecurityAction: vi.fn().mockResolvedValue({}),
    openHelpTarget: vi.fn().mockResolvedValue({}),
    submitFeedback: vi.fn().mockResolvedValue({}),
    ...overrides,
  }
}

function renderPage(initialEntry, settingsGateway) {
  const logout = vi.fn().mockResolvedValue(undefined)
  render(
    <AuthContext.Provider value={{ profile, token: 'staff-token', logout }}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/workbench/settings/:settingsSection" element={<AccountSettingsPage gateway={settingsGateway} />} />
          <Route path="*" element={<div>Destination</div>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
  return { logout }
}

describe('AccountSettingsPage', () => {
  afterEach(() => setLanguage('en'))

  it('validates profile fields, preserves input, and prevents duplicate saves', async () => {
    const user = userEvent.setup()
    let resolveSave
    const savePromise = new Promise((resolve) => { resolveSave = resolve })
    const settingsGateway = gateway({
      saveProfile: vi.fn().mockReturnValue(savePromise),
    })
    renderPage('/workbench/settings/profile', settingsGateway)

    const email = await screen.findByLabelText('Work email')
    await user.clear(email)
    await user.type(email, 'not-an-email')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(screen.getByText('Enter a valid work email address, such as name@example.com.')).toBeInTheDocument()
    expect(settingsGateway.saveProfile).not.toHaveBeenCalled()
    expect(email).toHaveValue('not-an-email')

    await user.clear(email)
    await user.type(email, 'new@example.invalid')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    const saving = screen.getByRole('button', { name: 'Saving changes...' })
    expect(saving).toBeDisabled()
    await user.click(saving)
    expect(settingsGateway.saveProfile).toHaveBeenCalledTimes(1)

    await act(async () => {
      resolveSave({
        ...settings,
        profile: { ...settings.profile, email: 'new@example.invalid' },
      })
      await savePromise
    })

    expect(await screen.findByRole('status')).toHaveTextContent('Profile changes are saved on this browser')
  })

  it('keeps required announcements enabled and saves notification preferences', async () => {
    const user = userEvent.setup()
    const settingsGateway = gateway()
    renderPage('/workbench/settings/notifications', settingsGateway)

    const announcements = await screen.findByRole('switch', { name: /System announcements/ })
    expect(announcements).toBeChecked()
    expect(announcements).toBeDisabled()

    await user.click(screen.getByRole('switch', { name: /Email task summary/ }))
    await user.click(screen.getByRole('button', { name: 'Save notifications' }))

    expect(settingsGateway.saveNotifications).toHaveBeenCalledWith(
      profile,
      expect.objectContaining({ emailDigest: true, systemAnnouncements: true }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Notification preferences are saved on this browser')
  })

  it('requires confirmation before turning off two-factor authentication', async () => {
    const user = userEvent.setup()
    const settingsGateway = gateway()
    renderPage('/workbench/settings/security', settingsGateway)

    await screen.findByRole('heading', { name: 'Account security' })
    await user.click(screen.getByRole('button', { name: 'Turn off' }))

    expect(settingsGateway.performSecurityAction).not.toHaveBeenCalled()
    expect(screen.getByRole('alertdialog', { name: 'Turn off two-factor authentication?' })).toBeInTheDocument()

    const dialog = screen.getByRole('alertdialog', { name: 'Turn off two-factor authentication?' })
    await user.click(dialog.querySelector('.button--danger'))
    expect(settingsGateway.performSecurityAction).toHaveBeenCalledWith(profile, 'disable_mfa', {})
  })

  it('disables security controls when the identity-provider gateway is unavailable', async () => {
    const reason = 'This action is unavailable because no staff identity-provider endpoint is configured. Contact your administrator to make this change.'
    const settingsGateway = gateway({
      load: vi.fn().mockResolvedValue({
        ...settings,
        security: {
          ...settings.security,
          actions: {
            changePassword: { available: false, reason },
            changeTwoFactor: { available: false, reason },
            manageDevices: { available: false, reason },
          },
        },
      }),
    })
    renderPage('/workbench/settings/security', settingsGateway)

    expect(await screen.findByRole('button', { name: 'Change password' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Turn off' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Manage devices' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Remove' })).toBeDisabled()
    expect(screen.getAllByText(reason)).not.toHaveLength(0)
  })

  it('preserves feedback text when the delivery gateway fails', async () => {
    const user = userEvent.setup()
    const settingsGateway = gateway({
      submitFeedback: vi.fn().mockRejectedValue(new Error('Feedback could not be delivered. Retry later.')),
    })
    renderPage('/workbench/settings/help', settingsGateway)

    const textarea = await screen.findByRole('textbox', { name: /Feedback/ })
    await user.type(textarea, 'Please improve keyboard shortcuts.')
    expect(textarea).toHaveValue('Please improve keyboard shortcuts.')
    await user.click(screen.getByRole('button', { name: 'Submit feedback' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Feedback could not be delivered')
    expect(textarea).toHaveValue('Please improve keyboard shortcuts.')
  })

  it('shows unconfigured help destinations as disabled with visible reasons', async () => {
    const settingsGateway = gateway({
      load: vi.fn().mockResolvedValue({
        ...settings,
        helpTargets: {
          guide: { available: false, reason: 'The usage guide is unavailable because no approved destination is configured.' },
          administrator: { available: false, reason: 'Administrator contact is unavailable because no approved destination is configured.' },
        },
      }),
    })
    renderPage('/workbench/settings/help', settingsGateway)

    expect(await screen.findByRole('button', { name: /Usage guide/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Contact administrator/ })).toBeDisabled()
    expect(screen.getByText(/usage guide is unavailable/i)).toBeInTheDocument()
    expect(screen.getByText(/administrator contact is unavailable/i)).toBeInTheDocument()
  })

  it('submits feedback with the authenticated staff token and clears it after success', async () => {
    const user = userEvent.setup()
    const settingsGateway = gateway()
    renderPage('/workbench/settings/help', settingsGateway)

    const textarea = await screen.findByRole('textbox', { name: /Feedback/ })
    await user.type(textarea, 'Keep the account menu keyboard friendly.')
    await user.click(screen.getByRole('button', { name: 'Submit feedback' }))

    expect(settingsGateway.submitFeedback).toHaveBeenCalledWith(
      profile,
      'Keep the account menu keyboard friendly.',
      'staff-token',
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Thank you. Your feedback was submitted.')
    expect(textarea).toHaveValue('')
  })

  it('previews Simplified Chinese immediately and saves the selected language', async () => {
    const user = userEvent.setup()
    const settingsGateway = gateway({
      saveAppearance: vi.fn().mockImplementation(async (_profile, values) => ({
        ...settings,
        appearance: values,
      })),
    })
    renderPage('/workbench/settings/appearance', settingsGateway)

    const language = await screen.findByRole('combobox', { name: 'Interface language' })
    await user.selectOptions(language, 'zh-CN')

    expect(document.documentElement).toHaveAttribute('lang', 'zh-CN')
    expect(screen.getByText('账户设置')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: '语言与显示' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '保存显示设置' }))
    expect(settingsGateway.saveAppearance).toHaveBeenCalledWith(
      profile,
      expect.objectContaining({ language: 'zh-CN' }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('语言和显示偏好已保存到此浏览器')
  })
})
