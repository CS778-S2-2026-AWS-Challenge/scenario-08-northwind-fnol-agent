import { BookOpenText, MessageSquareMore, UserRoundCog } from 'lucide-react'
import { useState } from 'react'
import { translate as t } from '../../i18n.js'

const MAX_FEEDBACK_LENGTH = 2000

export default function HelpFeedbackSettings({ targets = {}, onOpenTarget, onSubmitFeedback }) {
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState(null)

  async function openTarget(kind) {
    setFeedback(null)
    try {
      const target = await onOpenTarget(kind)
      if (target?.url) window.location.assign(target.url)
    } catch (error) {
      setFeedback({ kind: 'error', message: t(error.message) })
    }
  }

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    const submittedMessage = event.currentTarget.elements.feedback.value.trim()
    if (!submittedMessage) {
      setFeedback({ kind: 'error', message: t('Feedback was not submitted because the message is empty. Enter your feedback and try again.') })
      return
    }
    if (submittedMessage.length > MAX_FEEDBACK_LENGTH) {
      setFeedback({ kind: 'error', message: t('Feedback was not submitted because the message is longer than 2,000 characters. Shorten it and try again.') })
      return
    }
    setBusy(true)
    setFeedback(null)
    try {
      await onSubmitFeedback(submittedMessage)
      setMessage('')
      setFeedback({ kind: 'success', message: t('Thank you. Your feedback was submitted.') })
    } catch (error) {
      setFeedback({ kind: 'error', message: t(error.message) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="settings-form">
      <section className="settings-card" aria-labelledby="help-heading">
        <div className="settings-card__heading">
          <div>
            <h2 id="help-heading">{t('Help resources')}</h2>
            <p>{t('Find Workbench guidance or ask your organisation for account help.')}</p>
          </div>
        </div>
        <div className="settings-help-links">
          <HelpTarget
            icon={BookOpenText}
            label={t('Usage guide')}
            description={t('Learn the main Workbench tasks and keyboard controls.')}
            capability={targets.guide}
            onOpen={() => openTarget('guide')}
          />
          <HelpTarget
            icon={UserRoundCog}
            label={t('Contact administrator')}
            description={t('Get help with access, identity, or organisation-managed details.')}
            capability={targets.administrator}
            onOpen={() => openTarget('administrator')}
          />
        </div>
      </section>

      <form className="settings-card" onSubmit={submit} noValidate>
        <div className="settings-card__heading">
          <div>
            <h2><MessageSquareMore size={18} aria-hidden="true" />{t('Share feedback')}</h2>
            <p>{t('Tell us what would make your daily Claim work clearer or faster.')}</p>
            <p>{t('Do not include claimant names, Claim numbers, contact details, or other personal information.')}</p>
          </div>
        </div>
        <label className="settings-field" htmlFor="staff-feedback">
          <span>{t('Feedback')} <small>{t('Required')}</small></span>
          <textarea
            id="staff-feedback"
            name="feedback"
            value={message}
            aria-invalid={feedback?.kind === 'error' && !message.trim() ? 'true' : undefined}
            onChange={(event) => { setMessage(event.target.value); setFeedback(null) }}
            placeholder={t('Describe your suggestion or problem...')}
            maxLength={MAX_FEEDBACK_LENGTH}
          />
          <small>{t('{count} of 2,000 characters', { count: message.length })}</small>
        </label>
        <div className="settings-card__actions">
          <button className="button button--primary" type="submit" disabled={busy}>{busy ? t('Submitting...') : t('Submit feedback')}</button>
        </div>
      </form>

      <div className="settings-form__actions" aria-live="polite">
        {feedback && <p className={`settings-feedback settings-feedback--${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.message}</p>}
      </div>
    </div>
  )
}

function HelpTarget({ icon: Icon, label, description, capability, onOpen }) {
  const unavailable = capability?.available === false
  return (
    <button type="button" disabled={unavailable} onClick={onOpen}>
      <span className="settings-row__icon"><Icon size={19} aria-hidden="true" /></span>
      <span>
        <strong>{label}</strong>
        <small>{description}</small>
        {unavailable && <small className="settings-unavailable-note">{t(capability.reason)}</small>}
      </span>
    </button>
  )
}
