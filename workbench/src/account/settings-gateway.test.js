import { beforeEach, describe, expect, it } from 'vitest'
import {
  MAX_AVATAR_BYTES,
  browserStaffSettingsGateway,
  storedProfileOverrides,
  validateAvatarFile,
} from './settings-gateway.js'
import { getLanguage, setLanguage } from '../i18n.js'

const profile = {
  staff_id: 'stf_gateway',
  display_name: 'Original Name',
  email: 'original@example.invalid',
}

describe('browserStaffSettingsGateway', () => {
  beforeEach(() => {
    localStorage.clear()
    setLanguage('en')
  })

  it('rejects unsupported and oversized avatars before reading them', () => {
    expect(() => validateAvatarFile(new File(['avatar'], 'avatar.gif', { type: 'image/gif' })))
      .toThrow(/unsupported/)
    expect(() => validateAvatarFile(new File([new Uint8Array(MAX_AVATAR_BYTES + 1)], 'avatar.png', { type: 'image/png' })))
      .toThrow(/larger than 1 MB/)
  })

  it('isolates browser preferences by authenticated staff identity', async () => {
    await browserStaffSettingsGateway.saveProfile(profile, {
      displayName: 'Saved Name',
      email: 'saved@example.invalid',
      phone: '+64 21 555 0134',
    })

    expect(storedProfileOverrides(profile)).toEqual(expect.objectContaining({
      display_name: 'Saved Name',
      email: 'saved@example.invalid',
    }))
    expect(storedProfileOverrides({ ...profile, staff_id: 'stf_other' }).display_name).toBe('Original Name')
  })

  it('applies and persists the selected language for the authenticated staff member', async () => {
    await browserStaffSettingsGateway.saveAppearance(profile, {
      language: 'zh-CN',
      theme: 'light',
      timezone: 'Pacific/Auckland',
      dateFormat: 'DD/MM/YYYY',
    })

    expect(getLanguage()).toBe('zh-CN')
    expect(document.documentElement).toHaveAttribute('lang', 'zh-CN')
    await expect(browserStaffSettingsGateway.load(profile)).resolves.toMatchObject({
      appearance: { language: 'zh-CN' },
    })
    await expect(browserStaffSettingsGateway.load({ ...profile, staff_id: 'stf_other' })).resolves.toMatchObject({
      appearance: { language: 'en' },
    })
  })

  it('keeps unavailable help destinations explicit at the data boundary', async () => {
    await expect(browserStaffSettingsGateway.load(profile)).resolves.toMatchObject({
      security: {
        actions: {
          changePassword: { available: false },
          changeTwoFactor: { available: false },
          manageDevices: { available: false },
        },
      },
      helpTargets: {
        guide: { available: false },
        administrator: { available: false },
      },
    })
    await expect(browserStaffSettingsGateway.openHelpTarget(profile, 'guide'))
      .rejects.toThrow(/usage guide/)
    await expect(browserStaffSettingsGateway.openHelpTarget(profile, 'administrator'))
      .rejects.toThrow(/administrator contact/)
  })
})
