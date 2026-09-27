import { Bell, BriefcaseBusiness, Mail, Megaphone } from 'lucide-react'
import { useState } from 'react'
import { translate as t } from '../../i18n.js'
import { SettingsFormActions } from './ProfileSettings.jsx'

const OPTIONS = [
  {
    key: 'assignments',
    label: 'New task or Claim assignment',
    description: 'Receive an alert when work is assigned to you.',
    icon: BriefcaseBusiness,
  },
  {
    key: 'claimStatus',
    label: 'Claim status changes',
    description: 'Receive an alert when a Claim you are working on changes state.',
    icon: Bell,
  },
  {
    key: 'emailDigest',
    label: 'Email task summary',
    description: 'Receive a summary of outstanding work by email.',
    icon: Mail,
  },
  {
    key: 'systemAnnouncements',
    label: 'System announcements',
    description: 'Required service and security notices cannot be turned off.',
    icon: Megaphone,
    required: true,
  },
]

export default function NotificationSettings({ values, onSave }) {
  const [form, setForm] = useState(values)
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState(null)

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setFeedback(null)
    try {
      const next = await onSave(form)
      setForm(next.notifications)
      setFeedback({ kind: 'success', message: t('Notification preferences are saved on this browser. Account sync still requires backend support.') })
    } catch (error) {
      setFeedback({ kind: 'error', message: t(error.message) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="settings-form" onSubmit={submit}>
      <section className="settings-card" aria-labelledby="notification-heading">
        <div className="settings-card__heading">
          <div>
            <h2 id="notification-heading">{t('Notification preferences')}</h2>
            <p>{t('Choose which Workbench events should get your attention.')}</p>
          </div>
        </div>
        <div className="settings-option-list">
          {OPTIONS.map(({ key, label, description, icon: Icon, required }) => (
            <label className={`settings-toggle-row${required ? ' is-required' : ''}`} key={key}>
              <span className="settings-row__icon"><Icon size={18} aria-hidden="true" /></span>
              <span className="settings-row__copy"><strong>{t(label)}</strong><small>{t(description)}</small></span>
              <input
                type="checkbox"
                role="switch"
                checked={Boolean(form[key])}
                disabled={required || busy}
                aria-describedby={required ? `${key}-requirement` : undefined}
                onChange={(event) => {
                  setForm((current) => ({ ...current, [key]: event.target.checked }))
                  setFeedback(null)
                }}
              />
              <span className="settings-switch" aria-hidden="true" />
              {required && <span className="sr-only" id={`${key}-requirement`}>{t('This notification is required and cannot be disabled.')}</span>}
            </label>
          ))}
        </div>
      </section>
      <SettingsFormActions busy={busy} feedback={feedback} label={t('Save notifications')} busyLabel={t('Saving notifications...')} />
    </form>
  )
}
