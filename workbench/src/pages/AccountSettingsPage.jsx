import {
  Bell,
  CircleHelp,
  Palette,
  ShieldCheck,
  UserRound,
} from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'
import { Navigate, NavLink, useNavigate, useParams } from 'react-router-dom'
import { browserStaffSettingsGateway } from '../account/settings-gateway.js'
import { useStaffSettings } from '../account/useStaffSettings.js'
import { useAuth } from '../auth/auth-context.js'
import NavigationRail from '../components/NavigationRail.jsx'
import AppearanceSettings from '../components/account/AppearanceSettings.jsx'
import HelpFeedbackSettings from '../components/account/HelpFeedbackSettings.jsx'
import NotificationSettings from '../components/account/NotificationSettings.jsx'
import ProfileSettings from '../components/account/ProfileSettings.jsx'
import SecuritySettings from '../components/account/SecuritySettings.jsx'
import { translate as t, useLanguage } from '../i18n.js'

const SETTINGS_SECTIONS = {
  profile: {
    label: 'Profile',
    description: 'Manage your staff identity and contact information.',
    icon: UserRound,
  },
  security: {
    label: 'Account & Security',
    description: 'Review sign-in protection and connected devices.',
    icon: ShieldCheck,
  },
  notifications: {
    label: 'Notifications',
    description: 'Choose how the Workbench gets your attention.',
    icon: Bell,
  },
  appearance: {
    label: 'Language & Display',
    description: 'Set language, theme, time zone, and date format.',
    icon: Palette,
  },
  help: {
    label: 'Help & Feedback',
    description: 'Find support and share feedback about the Workbench.',
    icon: CircleHelp,
  },
}

export default function AccountSettingsPage({ gateway = browserStaffSettingsGateway }) {
  useLanguage()
  const { settingsSection } = useParams()
  const navigate = useNavigate()
  const { profile, token, logout } = useAuth()
  const headingRef = useRef(null)
  const controller = useStaffSettings(profile, gateway, token)
  const metadata = SETTINGS_SECTIONS[settingsSection]

  const effectiveProfile = useMemo(() => {
    if (!controller.settings) return profile
    return {
      ...profile,
      display_name: controller.settings.profile.displayName,
      email: controller.settings.profile.email,
      phone: controller.settings.profile.phone,
      avatar_url: controller.settings.profile.avatarDataUrl,
    }
  }, [controller.settings, profile])

  useEffect(() => {
    if (metadata && !controller.loading) headingRef.current?.focus()
  }, [controller.loading, metadata, settingsSection])

  if (!metadata) return <Navigate to="/workbench/settings/profile" replace />

  async function signOut() {
    await logout()
    navigate('/workbench/login', { replace: true })
  }

  return (
    <div className="workbench-app settings-app">
      <NavigationRail profile={effectiveProfile} onLogout={signOut} onAgent={() => navigate('/workbench')} />
      <div className="workbench-stage settings-stage">
        <header className="workbench-topbar settings-topbar">
          <div><strong>{t('Account settings')}</strong><span>{t('Personal preferences and staff account information')}</span></div>
        </header>
        <main className="settings-layout">
          <aside className="settings-navigation" aria-label={t('Account settings')}>
            <p className="eyebrow">{t('Settings')}</p>
            <nav>
              {Object.entries(SETTINGS_SECTIONS).map(([key, item]) => {
                const Icon = item.icon
                return (
                  <NavLink key={key} to={`/workbench/settings/${key}`}>
                    <Icon size={18} aria-hidden="true" />
                    <span>{t(item.label)}</span>
                  </NavLink>
                )
              })}
            </nav>
          </aside>
          <section className="settings-content" aria-labelledby="settings-page-title">
            <header className="settings-content__header">
              <p className="eyebrow">{t('Your account')}</p>
              <h1 id="settings-page-title" ref={headingRef} tabIndex={-1}>{t(metadata.label)}</h1>
              <p>{t(metadata.description)}</p>
            </header>
            {controller.loading && (
              <div className="settings-state" role="status" aria-live="polite">
                <span className="loading-mark" aria-hidden="true" />
                <p>{t('Loading account settings...')}</p>
              </div>
            )}
            {!controller.loading && controller.error && (
              <div className="settings-state settings-state--error" role="alert">
                <strong>{t('Account settings are unavailable')}</strong>
                <p>{controller.error.message || t('The settings could not be loaded. Retry from this page.')}</p>
                <button className="button button--secondary" type="button" onClick={controller.retry}>{t('Retry')}</button>
              </div>
            )}
            {!controller.loading && controller.settings && (
              <SettingsSection section={settingsSection} controller={controller} />
            )}
          </section>
        </main>
      </div>
    </div>
  )
}

function SettingsSection({ section, controller }) {
  if (section === 'profile') {
    return <ProfileSettings values={controller.settings.profile} onSave={controller.saveProfile} onAvatar={controller.saveAvatar} />
  }
  if (section === 'security') {
    return <SecuritySettings values={controller.settings.security} onAction={controller.performSecurityAction} />
  }
  if (section === 'notifications') {
    return <NotificationSettings values={controller.settings.notifications} onSave={controller.saveNotifications} />
  }
  if (section === 'appearance') {
    return <AppearanceSettings values={controller.settings.appearance} onSave={controller.saveAppearance} />
  }
  return <HelpFeedbackSettings targets={controller.settings.helpTargets} onOpenTarget={controller.openHelpTarget} onSubmitFeedback={controller.submitFeedback} />
}
