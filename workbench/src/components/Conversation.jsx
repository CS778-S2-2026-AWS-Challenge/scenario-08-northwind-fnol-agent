import { Info, MessageSquare, Send } from 'lucide-react'
import { useState } from 'react'
import { formatDateTime, words } from '../format.js'
import { canSubmitProjectedAction, findProjectedAction } from '../projected-action.js'
import ResourceBoundary from './ResourceBoundary.jsx'

export default function Conversation({ detail, resource, draft, onDraft, onSend, onRetry }) {
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState('')
  const messageSessionId = resource?.items?.find(
    (message) => message.session_id,
  )?.session_id
  const displayedSessionId = resource?.resolved_session_id || messageSessionId || null
  const isCurrentSession = Boolean(
    displayedSessionId
      && detail.active_session_id
      && displayedSessionId === detail.active_session_id,
  )
  const historicalSession = Boolean(
    displayedSessionId
      && displayedSessionId !== detail.active_session_id,
  )
  const sendAction = findProjectedAction(
    detail.allowed_actions,
    'conversation.send_claimant_message',
    displayedSessionId,
  )
  const canSend = isCurrentSession && canSubmitProjectedAction(sendAction)

  async function submit(event) {
    event.preventDefault()
    if (!draft.trim() || !canSend || !displayedSessionId) return
    setSending(true)
    setSendError('')
    try {
      await onSend({ message: draft.trim(), sessionId: displayedSessionId })
      onDraft('')
    } catch (nextError) {
      setSendError(nextError.message)
    } finally {
      setSending(false)
    }
  }

  const placeholder = historicalSession
    ? 'This conversation is read-only'
    : 'Write a message…'
  const unavailableTitle = historicalSession
    ? 'Read-only conversation'
    : 'Staff messaging not available yet'
  const unavailableMessage = historicalSession
    ? 'Open the active claimant conversation to send a message.'
    : sendAction?.blocked_reason || 'Messaging is not available for this claim yet.'

  return (
    <ResourceBoundary resource={resource} onRetry={onRetry}>
      <section className="conversation-view">
        <div className="message-list" role="log" aria-label="Claimant conversation messages">
          {(resource?.items || []).length
            ? resource.items.map((message) => (
              <article className={`message message--${message.actor}`} key={message.message_id}>
                <header>
                  <strong>{words(message.actor)}</strong>
                  <time>{formatDateTime(message.created_at)}</time>
                </header>
                <p>{message.content?.text || words(message.content?.type)}</p>
              </article>
            ))
            : (
              <div className="conversation-empty">
                <MessageSquare aria-hidden="true" />
                <strong>No messages yet</strong>
                <p>Messages with the claimant will appear here.</p>
              </div>
            )}
        </div>
        <form className="staff-composer" onSubmit={submit}>
          {!canSend && (
            <div className="staff-composer__notice" id="staff-message-status" role="status">
              <Info size={16} aria-hidden="true" />
              <span>
                <strong>{unavailableTitle}</strong>
                <small>{unavailableMessage}</small>
              </span>
            </div>
          )}
          <label className="sr-only" htmlFor="staff-reply">Message to claimant</label>
          <textarea
            id="staff-reply"
            value={draft}
            onChange={(event) => onDraft(event.target.value)}
            disabled={!canSend}
            placeholder={placeholder}
            aria-describedby={!canSend ? 'staff-message-status' : undefined}
          />
          <div className="staff-composer__actions">
            <button className="button button--primary" type="submit" disabled={!canSend || !draft.trim() || sending}>
              <Send size={16} aria-hidden="true" />
              {sending ? 'Sending...' : 'Send message'}
            </button>
          </div>
          {sendError && <p className="form-error" role="alert">{sendError}</p>}
        </form>
      </section>
    </ResourceBoundary>
  )
}
