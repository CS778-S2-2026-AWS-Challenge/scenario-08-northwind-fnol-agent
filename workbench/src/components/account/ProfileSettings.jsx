import { Camera, Info } from 'lucide-react'
import { useRef, useState } from 'react'
import { initials } from '../../format.js'
import { validateProfile } from '../../account/settings-validation.js'
import { translate as t } from '../../i18n.js'

export default function ProfileSettings({ values, onSave, onAvatar }) {
  const [form, setForm] = useState(values)
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const [avatarBusy, setAvatarBusy] = useState(false)
  const [feedback, setFeedback] = useState(null)
  const nameRef = useRef(null)
  const emailRef = useRef(null)
  const phoneRef = useRef(null)

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
    setFeedback(null)
  }

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    const result = validateProfile(form)
    setErrors(result.errors)
    const firstError = Object.keys(result.errors)[0]
    if (firstError) {
      const refs = { displayName: nameRef, email: emailRef, phone: phoneRef }
      refs[firstError]?.current?.focus()
      setFeedback({ kind: 'error', message: t('Your changes were not saved. Correct the highlighted fields and try again.') })
      return
    }
    setBusy(true)
    setFeedback(null)
    try {
      const next = await onSave(result.values)
      setForm(next.profile)
      setFeedback({ kind: 'success', message: t('Profile changes are saved on this browser. Account-wide profile sync still requires backend support.') })
    } catch (error) {
      setFeedback({ kind: 'error', message: t(error.message) })
    } finally {
      setBusy(false)
    }
  }

  async function selectAvatar(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || avatarBusy) return
    setAvatarBusy(true)
    setFeedback(null)
    try {
      const next = await onAvatar(file)
      setForm(next.profile)
      setFeedback({ kind: 'success', message: t('The avatar is saved on this browser. Account-wide avatar sync still requires backend support.') })
    } catch (error) {
      setFeedback({ kind: 'error', message: t(error.message) })
    } finally {
      setAvatarBusy(false)
    }
  }

  return (
    <form className="settings-form" onSubmit={submit} noValidate>
      <section className="settings-card settings-avatar-section" aria-labelledby="profile-avatar-heading">
        <div>
          <h2 id="profile-avatar-heading">{t('Profile photo')}</h2>
          <p>{t('Use a clear JPG or PNG image up to 1 MB.')}</p>
        </div>
        <div className="settings-avatar-editor">
          <span className="settings-avatar" aria-hidden="true">
            {form.avatarDataUrl
              ? <img src={form.avatarDataUrl} alt="" />
              : initials(form.displayName)}
          </span>
          <div>
            <input
              className="sr-only"
              id="staff-avatar-upload"
              type="file"
              accept="image/jpeg,image/png"
              disabled={avatarBusy}
              onChange={selectAvatar}
            />
            <label className={`button button--secondary${avatarBusy ? ' is-disabled' : ''}`} htmlFor="staff-avatar-upload">
              <Camera size={17} aria-hidden="true" />
              {avatarBusy ? t('Uploading...') : t('Change avatar')}
            </label>
          </div>
        </div>
      </section>

      <section className="settings-card" aria-labelledby="profile-basic-heading">
        <div className="settings-card__heading">
          <div>
            <h2 id="profile-basic-heading">{t('Basic information')}</h2>
            <p>{t('Keep the contact information used in your Workbench account up to date.')}</p>
          </div>
        </div>
        <div className="settings-fields settings-fields--two-column">
          <Field label={t('Name')} error={errors.displayName} inputId="profile-display-name">
            <input
              ref={nameRef}
              id="profile-display-name"
              value={form.displayName}
              aria-invalid={Boolean(errors.displayName)}
              aria-describedby={errors.displayName ? 'profile-display-name-error' : undefined}
              onChange={(event) => update('displayName', event.target.value)}
              autoComplete="name"
            />
          </Field>
          <Field label={t('Work email')} error={errors.email} inputId="profile-email">
            <input
              ref={emailRef}
              id="profile-email"
              type="email"
              value={form.email}
              aria-invalid={Boolean(errors.email)}
              aria-describedby={errors.email ? 'profile-email-error' : undefined}
              onChange={(event) => update('email', event.target.value)}
              autoComplete="email"
            />
          </Field>
          <Field label={t('Contact phone')} error={errors.phone} inputId="profile-phone">
            <input
              ref={phoneRef}
              id="profile-phone"
              type="tel"
              value={form.phone}
              aria-invalid={Boolean(errors.phone)}
              aria-describedby={errors.phone ? 'profile-phone-error' : undefined}
              onChange={(event) => update('phone', event.target.value)}
              autoComplete="tel"
              placeholder="+64 21 555 0123"
            />
          </Field>
        </div>
      </section>

      <section className="settings-card" aria-labelledby="profile-employment-heading">
        <div className="settings-card__heading">
          <div>
            <h2 id="profile-employment-heading">{t('Employment details')}</h2>
            <p className="settings-guidance"><Info size={17} aria-hidden="true" />{t('Position, team, and employee ID are maintained by an administrator.')}</p>
          </div>
        </div>
        <div className="settings-fields settings-fields--two-column">
          <ReadOnlyField label={t('Position')} value={form.position} />
          <ReadOnlyField label={t('Team')} value={form.team} />
          <ReadOnlyField label={t('Employee ID')} value={form.employeeId} />
        </div>
      </section>

      <SettingsFormActions busy={busy} feedback={feedback} label={t('Save changes')} busyLabel={t('Saving changes...')} />
    </form>
  )
}

function Field({ label, error, inputId, children }) {
  return (
    <label className="settings-field" htmlFor={inputId}>
      <span>{label}</span>
      {children}
      {error && <small id={`${inputId}-error`} className="settings-field__error">{t(error)}</small>}
    </label>
  )
}

function ReadOnlyField({ label, value }) {
  return (
    <label className="settings-field settings-field--readonly">
      <span>{label}</span>
      <input readOnly value={value || t('Not provided')} />
    </label>
  )
}

export function SettingsFormActions({ busy, feedback, label, busyLabel }) {
  return (
    <div className="settings-form__actions">
      <div aria-live="polite">
        {feedback && (
          <p className={`settings-feedback settings-feedback--${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'}>
            {feedback.message}
          </p>
        )}
      </div>
      <button className="button button--primary" type="submit" disabled={busy}>
        {busy ? busyLabel : label}
      </button>
    </div>
  )
}
