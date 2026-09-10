import { Send } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { formatDateTime, words } from '../format.js'
import { canSubmitProjectedAction, findProjectedAction } from '../projected-action.js'
import { ProjectedActionState } from './ProjectedAction.jsx'
import ResourceBoundary from './ResourceBoundary.jsx'

export default function Conversation({ detail, resource, draft, onDraft, onSend, onRefresh = reloadWorkbench }) {
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState('')
  const [searchParams] = useSearchParams()
  const resourceSessionId = resource?.items?.find((message) => message.session_id)?.session_id
  const displayedSessionId = searchParams.get('session') || resourceSessionId || detail.active_session_id
  const isCurrentSession = Boolean(
    displayedSessionId && detail.active_session_id && displayedSessionId === detail.active_session_id,
  )
  const historicalSession = Boolean(
    displayedSessionId && detail.active_session_id && displayedSessionId !== detail.active_session_id,
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
      if (nextError.code === 'REVISION_CONFLICT') {
        setSendError('This Claim changed after the conversation loaded. Reloading the current Claim before another send is allowed.')
        onRefresh()
      } else {
        setSendError(nextError.message)
      }
    } finally {
      setSending(false)
    }
  }

  const placeholder = historicalSession
    ? 'Historical sessions are read-only'
    : canSend
      ? 'Write a clear claimant-safe update'
      : 'A claimant-message action is not executable'

  return (
    <ResourceBoundary resource={resource}>
      <section className="conversation-view">
        <header className="content-header"><div><p className="eyebrow">Shared Claim context</p><h2>Claimant conversation</h2></div><span>{resource?.items?.length || 0} messages</span></header>
        <div className="message-ledger">{(resource?.items || []).map((message) => <article className={`message message--${message.actor}`} key={message.message_id}><header><strong>{words(message.actor)}</strong><time>{formatDateTime(message.created_at)}</time></header><p>{message.content?.text || words(message.content?.type)}</p></article>)}</div>
        <form className="staff-reply" onSubmit={submit}><label htmlFor="staff-reply">Reply to claimant</label><textarea id="staff-reply" rows="3" value={draft} onChange={(event) => onDraft(event.target.value)} disabled={!canSend} placeholder={placeholder} /><div><span>This message will be visible to the claimant.</span><button className="button button--primary" type="submit" disabled={!canSend || !draft.trim() || sending}><Send size={16} />{sending ? 'Sending...' : 'Send message'}</button></div>{historicalSession ? <p className="empty-note">This saved session is read-only. Open the active claimant conversation to send a message.</p> : !canSend && <ProjectedActionState action={sendAction} absentMessage="No claimant-message action is projected for this conversation." />}{sendError && <p className="form-error" role="alert">{sendError}</p>}</form>
      </section>
    </ResourceBoundary>
  )
}

function reloadWorkbench() {
  window.location.reload()
}
