import { setLanguage } from '../i18n.js'
import { workbenchApi } from '../api.js'

const SETTINGS_VERSION = 1
const SETTINGS_KEY_PREFIX = 'northwind.workbench.staff-settings.v1'

export const MAX_AVATAR_BYTES = 1024 * 1024
export const ALLOWED_AVATAR_TYPES = new Set(['image/jpeg', 'image/png'])

const DEFAULT_NOTIFICATIONS = Object.freeze({
  assignments: true,
  claimStatus: true,
  emailDigest: false,
  systemAnnouncements: true,
})

const DEFAULT_APPEARANCE = Object.freeze({
  language: 'en',
  theme: 'system',
  timezone: 'Pacific/Auckland',
  dateFormat: 'DD/MM/YYYY',
})

const IDENTITY_ACTION_UNAVAILABLE = 'This action is unavailable because no staff identity-provider endpoint is configured. Contact your administrator to make this change.'
const GUIDE_UNAVAILABLE = 'The usage guide is unavailable because no approved destination is configured.'
const ADMIN_CONTACT_UNAVAILABLE = 'Administrator contact is unavailable because no approved destination is configured.'

let systemThemeQuery = null
let systemThemeListener = null

export class SettingsGatewayError extends Error {
  constructor(message, code = 'SETTINGS_UNAVAILABLE') {
    super(message)
    this.name = 'SettingsGatewayError'
    this.code = code
  }
}

function storageKey(staffId) {
  return `${SETTINGS_KEY_PREFIX}:${staffId}`
}

function readRecord(staffId) {
  if (!staffId) return {}
  try {
    const record = JSON.parse(localStorage.getItem(storageKey(staffId)) || 'null')
    return record?.version === SETTINGS_VERSION ? record : {}
  } catch {
    return {}
  }
}

function writeRecord(staffId, changes) {
  if (!staffId) {
    throw new SettingsGatewayError(
      'The settings could not be saved because the authenticated staff identity is missing. Sign in again and retry.',
      'STAFF_IDENTITY_MISSING',
    )
  }
  const record = {
    ...readRecord(staffId),
    ...changes,
    version: SETTINGS_VERSION,
    updatedAt: new Date().toISOString(),
  }
  try {
    localStorage.setItem(storageKey(staffId), JSON.stringify(record))
  } catch {
    throw new SettingsGatewayError(
      'The settings could not be saved because browser storage is unavailable or full. Keep this page open, free storage space, and retry.',
      'BROWSER_STORAGE_UNAVAILABLE',
    )
  }
  return record
}

function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || DEFAULT_APPEARANCE.timezone
  } catch {
    return DEFAULT_APPEARANCE.timezone
  }
}

function currentDevice() {
  const platform = navigator.userAgentData?.platform || navigator.platform || 'Current browser'
  return {
    id: 'current-browser',
    name: `${platform} browser`,
    location: 'Location unavailable',
    lastActive: 'Active now',
    current: true,
  }
}

function normalizedSettings(profile, record = readRecord(profile?.staff_id)) {
  const storedProfile = record.profile || {}
  const appearance = {
    ...DEFAULT_APPEARANCE,
    timezone: browserTimezone(),
    ...(record.appearance || {}),
  }
  const ssoManaged = profile?.identity_provider === 'sso'
    || profile?.account_managed_by_organization === true

  return {
    profile: {
      displayName: storedProfile.displayName ?? profile?.display_name ?? '',
      email: storedProfile.email ?? profile?.email ?? '',
      phone: storedProfile.phone ?? profile?.phone ?? '',
      avatarDataUrl: storedProfile.avatarDataUrl ?? profile?.avatar_url ?? '',
      position: profile?.position ?? profile?.job_title ?? '',
      team: profile?.team ?? profile?.team_name ?? '',
      employeeId: profile?.employee_number ?? profile?.staff_id ?? '',
    },
    security: {
      managedByOrganization: ssoManaged,
      passwordLastChangedAt: profile?.password_last_changed_at ?? null,
      twoFactorEnabled: typeof profile?.two_factor_enabled === 'boolean'
        ? profile.two_factor_enabled
        : null,
      devices: [currentDevice()],
      actions: {
        changePassword: { available: false, reason: IDENTITY_ACTION_UNAVAILABLE },
        changeTwoFactor: { available: false, reason: IDENTITY_ACTION_UNAVAILABLE },
        manageDevices: { available: false, reason: IDENTITY_ACTION_UNAVAILABLE },
      },
    },
    notifications: {
      ...DEFAULT_NOTIFICATIONS,
      ...(record.notifications || {}),
      systemAnnouncements: true,
    },
    appearance,
    helpTargets: {
      guide: { available: false, reason: GUIDE_UNAVAILABLE },
      administrator: { available: false, reason: ADMIN_CONTACT_UNAVAILABLE },
    },
    persistence: 'browser',
  }
}

function dataUrlForFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.addEventListener('load', () => resolve(reader.result))
    reader.addEventListener('error', () => reject(new SettingsGatewayError(
      'The avatar could not be read from this file. Choose another JPG or PNG image and retry.',
      'AVATAR_READ_FAILED',
    )))
    reader.readAsDataURL(file)
  })
}

export function validateAvatarFile(file) {
  if (!file || !ALLOWED_AVATAR_TYPES.has(file.type)) {
    throw new SettingsGatewayError(
      'The avatar was not selected because its file type is unsupported. Choose a JPG or PNG image and retry.',
      'UNSUPPORTED_AVATAR_TYPE',
    )
  }
  if (file.size > MAX_AVATAR_BYTES) {
    throw new SettingsGatewayError(
      'The avatar was not selected because it is larger than 1 MB. Choose a smaller JPG or PNG image and retry.',
      'AVATAR_TOO_LARGE',
    )
  }
}

export function storedProfileOverrides(profile) {
  if (!profile?.staff_id) return profile
  const stored = readRecord(profile.staff_id).profile || {}
  return {
    ...profile,
    display_name: stored.displayName ?? profile.display_name,
    email: stored.email ?? profile.email,
    phone: stored.phone ?? profile.phone,
    avatar_url: stored.avatarDataUrl ?? profile.avatar_url,
  }
}

function removeSystemThemeListener() {
  if (systemThemeQuery && systemThemeListener) {
    systemThemeQuery.removeEventListener?.('change', systemThemeListener)
  }
  systemThemeQuery = null
  systemThemeListener = null
}

function setResolvedTheme(theme) {
  document.documentElement.dataset.workbenchTheme = theme
}

export function applyAppearanceSettings(appearance = DEFAULT_APPEARANCE) {
  removeSystemThemeListener()
  setLanguage(appearance.language)
  if (appearance.theme !== 'system') {
    setResolvedTheme(appearance.theme)
    return
  }
  if (typeof window.matchMedia !== 'function') {
    setResolvedTheme('light')
    return
  }
  systemThemeQuery = window.matchMedia('(prefers-color-scheme: dark)')
  systemThemeListener = (event) => setResolvedTheme(event.matches ? 'dark' : 'light')
  setResolvedTheme(systemThemeQuery.matches ? 'dark' : 'light')
  systemThemeQuery.addEventListener?.('change', systemThemeListener)
}

export const browserStaffSettingsGateway = {
  async load(profile) {
    return normalizedSettings(profile)
  },

  async saveProfile(profile, values) {
    const record = writeRecord(profile?.staff_id, {
      profile: {
        ...(readRecord(profile?.staff_id).profile || {}),
        ...values,
      },
    })
    return normalizedSettings(profile, record)
  },

  async saveAvatar(profile, file) {
    validateAvatarFile(file)
    const avatarDataUrl = await dataUrlForFile(file)
    return this.saveProfile(profile, { avatarDataUrl })
  },

  async saveNotifications(profile, values) {
    const record = writeRecord(profile?.staff_id, {
      notifications: {
        ...values,
        systemAnnouncements: true,
      },
    })
    return normalizedSettings(profile, record)
  },

  async saveAppearance(profile, values) {
    const record = writeRecord(profile?.staff_id, { appearance: values })
    const settings = normalizedSettings(profile, record)
    applyAppearanceSettings(settings.appearance)
    return settings
  },

  async performSecurityAction() {
    throw new SettingsGatewayError(
      'The security change was not made because no staff identity-provider endpoint is configured. Contact your administrator to complete this action.',
      'IDENTITY_PROVIDER_UNAVAILABLE',
    )
  },

  async openHelpTarget(_profile, kind) {
    const target = kind === 'guide' ? 'usage guide' : 'administrator contact'
    throw new SettingsGatewayError(
      `The ${target} did not open because no destination is configured. Contact your Workbench administrator for the approved link.`,
      'HELP_TARGET_UNAVAILABLE',
    )
  },

  async submitFeedback(_profile, message, token) {
    if (!token) {
      throw new SettingsGatewayError(
        'The feedback was not submitted because the staff session is unavailable. Sign in again and retry.',
        'STAFF_SESSION_MISSING',
      )
    }
    return workbenchApi.submitFeedback(token, message)
  },
}
