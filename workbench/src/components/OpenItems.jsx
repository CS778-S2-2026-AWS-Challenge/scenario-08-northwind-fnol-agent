import { useState } from 'react'
import { translate as t } from '../i18n.js'
import { canSubmitProjectedAction, findProjectedAction } from '../projected-action.js'

// What the claimant, Northwind or a third party still owes on this Claim, from
// the server's open-item projection. A question the Agent passed to the claims
// team is answered here; the answer reaches the claimant as a claim update.

const OWNER_LABELS = {
  claimant: 'Claimant will send',
  northwind: 'Question for Northwind',
  third_party: 'Northwind is obtaining',
}

const STATE_LABELS = {
  open: 'Open',
  done: 'Done',
  not_available: 'Claimant does not have it',
}

function itemTitle(item) {
  return item.kind === 'question' ? item.subject : item.subject.replaceAll('_', ' ')
}

function AnswerForm({ item, action, onAnswer }) {
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const inputId = `answer-${item.item_id}`
  async function submit(event) {
    event.preventDefault()
    if (!answer.trim()) return
    setBusy(true)
    setError(null)
    try {
      await onAnswer(action, answer.trim())
      setAnswer('')
    } catch (failure) {
      setError(failure?.message || t('The answer was not saved. Refresh the Claim and try again.'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <form className="open-item-answer-form" onSubmit={submit}>
      <label htmlFor={inputId}>{t('Answer for the claimant')}</label>
      <textarea id={inputId} rows="3" value={answer} onChange={(event) => setAnswer(event.target.value)} />
      <p className="field-hint">{t('This answer will be visible to the claimant.')}</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="button" type="submit" disabled={busy || !answer.trim()}>{t('Send answer')}</button>
    </form>
  )
}

export default function OpenItems({ items = [], actions = [], readOnly = false, onAnswer }) {
  if (items.length === 0) return null
  const openCount = items.filter((item) => item.state === 'open').length
  return (
    <section className="detail-section" aria-labelledby="open-items-title">
      <div className="section-heading">
        <div><p className="eyebrow">{t('Open items')}</p><h2 id="open-items-title">{t('Still owed on this Claim')}</h2></div>
        <span className="count-badge">{openCount}</span>
      </div>
      <ul className="open-item-records">
        {items.map((item) => {
          const action = findProjectedAction(actions, 'conversation.answer_claimant_question', item.item_id)
          return (
            <li className="open-item-record" key={item.item_id}>
              <div className="open-item-record__heading">
                <strong>{itemTitle(item)}</strong>
                <span className="status-pill">{t(STATE_LABELS[item.state] || item.state)}</span>
              </div>
              <p className="record-meta">{t(OWNER_LABELS[item.owner] || item.owner)}{item.service_identity ? ` · ${item.service_identity}` : ''}</p>
              {item.claimant_wording && <p><span className="record-label">{t('Claimant said')}</span> “{item.claimant_wording}”</p>}
              {item.model_view && <p><span className="record-label">{t("Assistant's view")}</span> {item.model_view}</p>}
              {item.answer && <p><span className="record-label">{t('Answer sent')}</span> {item.answer}</p>}
              {!readOnly && onAnswer && item.state === 'open' && canSubmitProjectedAction(action) && (
                <AnswerForm item={item} action={action} onAnswer={onAnswer} />
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
