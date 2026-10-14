import { Inbox } from 'lucide-react'
import { useState } from 'react'
import { translate as t } from '../i18n.js'
import { canSubmitProjectedAction, findProjectedAction } from '../projected-action.js'
import { waitingListItems } from '../waiting-list.js'
import ResourceEmptyState, { ResourcePageHeader } from './ResourceEmptyState.jsx'

// The claim's waiting list: what the assistant could not settle while the
// report was being collected. A question carries the claimant's words and the
// assistant's proposed answer with its basis; a contact request carries how the
// claimant wants to be reached. The handler settles each one here; an approved
// or edited answer reaches the claimant as the handler's message.

const ACTION_CODE = 'conversation.answer_claimant_question'

const STATE_LABELS = {
  open: 'Waiting',
  done: 'Settled',
  declined: 'Declined',
}

function Decision({ item, action, onDecide }) {
  const [mode, setMode] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const inputId = `waiting-${item.item_id}`
  const isQuestion = item.kind === 'question'

  async function decide(decision, body = null) {
    setBusy(true)
    setError(null)
    try {
      await onDecide(action, { decision, text: body })
      setMode(null)
      setText('')
    } catch (failure) {
      setError(failure?.message || t('The decision was not saved. Refresh the Claim and try again.'))
    } finally {
      setBusy(false)
    }
  }

  function open(nextMode) {
    setMode(nextMode)
    setText(nextMode === 'edit' ? item.proposed_answer || '' : '')
  }

  if (mode) {
    const label = mode === 'edit'
      ? t('Answer for the claimant')
      : mode === 'decline'
        ? t('Reason the claimant will read')
        : t('Note for the claimant (optional)')
    return (
      <form
        className="open-item-answer-form"
        onSubmit={(event) => {
          event.preventDefault()
          if (mode !== 'contacted' && !text.trim()) return
          decide(mode, text.trim() || null)
        }}
      >
        <label htmlFor={inputId}>{label}</label>
        <textarea id={inputId} rows="3" value={text} onChange={(event) => setText(event.target.value)} autoFocus />
        <p className="field-hint">{t('This will be visible to the claimant.')}</p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="waiting-item__actions">
          <button className="button" type="submit" disabled={busy || (mode !== 'contacted' && !text.trim())}>
            {t(mode === 'edit' ? 'Send answer' : mode === 'decline' ? 'Decline' : 'Mark contacted')}
          </button>
          <button className="button button--quiet" type="button" disabled={busy} onClick={() => setMode(null)}>{t('Cancel')}</button>
        </div>
      </form>
    )
  }

  return (
    <>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="waiting-item__actions">
        {isQuestion && item.proposed_answer && (
          <button className="button" type="button" disabled={busy} onClick={() => decide('approve')}>{t('Approve and send')}</button>
        )}
        {isQuestion && (
          <button className="button button--secondary" type="button" disabled={busy} onClick={() => open('edit')}>{t('Edit then send')}</button>
        )}
        {!isQuestion && (
          <button className="button" type="button" disabled={busy} onClick={() => open('contacted')}>{t('Mark contacted')}</button>
        )}
        <button className="button button--quiet" type="button" disabled={busy} onClick={() => open('decline')}>{t('Decline')}</button>
      </div>
    </>
  )
}

export default function WaitingList({ items = [], actions = [], readOnly = false, onDecide }) {
  const waiting = waitingListItems(items)
  const openCount = waiting.filter((item) => item.state === 'open').length
  return (
    <section className="resource-view waiting-list" aria-labelledby="waiting-list-title">
      <ResourcePageHeader
        title="Waiting list"
        subtitle="Questions and contact requests that need a claims-team response."
        countLabel={t('{count} open', { count: openCount })}
        titleId="waiting-list-title"
      />
      {waiting.length === 0 ? (
        <ResourceEmptyState
          icon={Inbox}
          title="No waiting items"
          description="New claimant questions and contact requests will appear here when staff attention is needed."
        />
      ) : (
        <ul className="open-item-records">
          {waiting.map((item) => {
            const action = findProjectedAction(actions, ACTION_CODE, item.item_id)
            return (
              <li className={`open-item-record waiting-item is-${item.state}`} key={item.item_id}>
                <div className="open-item-record__heading">
                  <strong>{item.subject}</strong>
                  <span className="status-pill">{t(STATE_LABELS[item.state] || item.state)}</span>
                </div>
                <p className="record-meta">{t(item.kind === 'question' ? 'Question from the claimant' : 'Request to be contacted')}</p>
                {item.claimant_wording && <p><span className="record-label">{t('Claimant said')}</span> “{item.claimant_wording}”</p>}
                {item.contact_preference && <p><span className="record-label">{t('How to reach them')}</span> {item.contact_preference}</p>}
                {item.proposed_answer && item.state === 'open' && (
                  <p><span className="record-label">{t('Proposed answer')}</span> {item.proposed_answer}</p>
                )}
                {item.basis && <p><span className="record-label">{t('Basis')}</span> {item.basis}</p>}
                {item.answer && <p><span className="record-label">{t(item.state === 'declined' ? 'Reason sent' : 'Sent to the claimant')}</span> {item.answer}</p>}
                {!readOnly && onDecide && item.state === 'open' && canSubmitProjectedAction(action) && (
                  <Decision item={item} action={action} onDecide={onDecide} />
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
