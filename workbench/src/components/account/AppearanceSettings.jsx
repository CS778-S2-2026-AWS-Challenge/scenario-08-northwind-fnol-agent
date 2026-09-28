import { CalendarDays, Globe2, MonitorCog } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { applyAppearanceSettings } from '../../account/settings-gateway.js'
import { translate as t } from '../../i18n.js'
import { SettingsFormActions } from './ProfileSettings.jsx'

const THEMES = [
  { value: 'system', label: 'Follow system' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

const TIMEZONES = [
  'Pacific/Auckland',
  'Australia/Sydney',
  'Asia/Singapore',
  'Europe/London',
  'America/New_York',
  'UTC',
]

const DATE_FORMATS = ['DD/MM/YYYY', 'MM/DD/YYYY', 'YYYY-MM-DD']

export default function AppearanceSettings({ values, onSave }) {
  const [form, setForm] = useState(values)
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState(null)
  const savedRef = useRef(values)

  useEffect(() => () => applyAppearanceSettings(savedRef.current), [])

  function update(field, value) {
    const next = { ...form, [field]: value }
    setForm(next)
    setFeedback(null)
    applyAppearanceSettings(next)
  }

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setFeedback(null)
    try {
      const next = await onSave(form)
      setForm(next.appearance)
      savedRef.current = next.appearance
      setFeedback({ kind: 'success', message: t('Language and display preferences are saved on this browser. Account sync still requires backend support.') })
    } catch (error) {
      setFeedback({ kind: 'error', message: t(error.message) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="settings-form" onSubmit={submit}>
      <section className="settings-card" aria-labelledby="appearance-heading">
        <div className="settings-card__heading">
          <div>
            <h2 id="appearance-heading">{t('Language and display')}</h2>
            <p>{t('Preview display choices now, then save them for this browser.')}</p>
          </div>
        </div>
        <div className="settings-fields settings-fields--two-column">
          <label className="settings-field">
            <span><Globe2 size={17} aria-hidden="true" />{t('Interface language')}</span>
            <select value={form.language} onChange={(event) => update('language', event.target.value)}>
              <option value="zh-CN">简体中文</option>
              <option value="en">English</option>
            </select>
          </label>
          <label className="settings-field">
            <span><Globe2 size={17} aria-hidden="true" />{t('Time zone')}</span>
            <select value={form.timezone} onChange={(event) => update('timezone', event.target.value)}>
              {TIMEZONES.map((timezone) => <option value={timezone} key={timezone}>{timezone}</option>)}
            </select>
          </label>
          <label className="settings-field">
            <span><CalendarDays size={17} aria-hidden="true" />{t('Date format')}</span>
            <select value={form.dateFormat} onChange={(event) => update('dateFormat', event.target.value)}>
              {DATE_FORMATS.map((format) => <option value={format} key={format}>{format}</option>)}
            </select>
          </label>
        </div>
        <fieldset className="settings-theme-options">
          <legend><MonitorCog size={17} aria-hidden="true" />{t('Display theme')}</legend>
          <div>
            {THEMES.map((theme) => (
              <label key={theme.value} className={form.theme === theme.value ? 'is-selected' : ''}>
                <input
                  type="radio"
                  name="display-theme"
                  value={theme.value}
                  checked={form.theme === theme.value}
                  onChange={(event) => update('theme', event.target.value)}
                />
                <span>{t(theme.label)}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="settings-preview" aria-live="polite">
          <strong>{t('Preview')}</strong>
          <span>{form.language === 'zh-CN' ? '界面语言：简体中文' : t('Interface language: English')}</span>
          <small>{formatPreviewDate(form.dateFormat)} · {form.timezone}</small>
        </div>
      </section>
      <SettingsFormActions busy={busy} feedback={feedback} label={t('Save display settings')} busyLabel={t('Saving display settings...')} />
    </form>
  )
}

function formatPreviewDate(format) {
  if (format === 'MM/DD/YYYY') return '09/27/2026'
  if (format === 'YYYY-MM-DD') return '2026-09-27'
  return '27/09/2026'
}
