import { CheckCircle2, Clock3, Send, UserRoundCheck } from 'lucide-react'
import { useState } from 'react'
import { formatDateTime, words } from '../format.js'
import { canSubmitProjectedAction, findProjectedAction } from '../projected-action.js'
import { ProjectedActionState } from './ProjectedAction.jsx'
import ResourceBoundary from './ResourceBoundary.jsx'
import { HandoffResolution } from './ReviewActions.jsx'

export default function Conversation({
  detail,
  handoffs = [],
  profile,
  resource,
  draft,
  onDraft,
  onAccept,
  onResolve,
  onSend,
  onRetry,
}) {
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
  const handoff = latestCustomerAssistance(handoffs)
  const assistanceState = assistanceDisplayState(detail, handoff)
  const sendAction = currentProjectedAction(detail, 'conversation.send_claimant_message', displayedSessionId)
  const acceptAction = currentProjectedAction(detail, 'human.accept_handoff', handoff?.handoff_id)
  const resolveAction = currentProjectedAction(detail, 'human.resolve_handoff', handoff?.handoff_id)
  const canSend = isCurrentSession && canSubmitCurrentAction(sendAction, detail.revision)
  const timeline = conversationTimeline(resource?.items || [], handoff, profile)

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
    ? 'Historical sessions are read-only'
    : assistanceState.key === 'completed'
      ? 'Staff assistance is complete'
      : assistanceState.key === 'waiting-request'
        ? 'Take over conversation to reply'
        : assistanceState.key === 'action-needed'
          ? 'Reply to customer...'
          : assistanceState.key === 'waiting-customer'
            ? 'Waiting for the customer — send an update if needed'
            : canSend
              ? 'Write a clear claimant-safe update'
              : 'A claimant-message action is not executable'

  return (
    <ResourceBoundary resource={resource} onRetry={onRetry}>
      <section className="conversation-view">
        <header className="content-header"><div><p className="eyebrow">Shared Claim context</p><h2>Claimant conversation</h2></div><span>{resource?.items?.length || 0} messages</span></header>
        {handoff && (
          <AssistanceStatus
            action={acceptAction}
            handoff={handoff}
            profile={profile}
            state={assistanceState}
            revision={detail.revision}
            onAccept={onAccept}
          />
        )}
        <ol className="message-ledger message-list" aria-label="Shared conversation history">
          {timeline.map((item) => (
            item.kind === 'event'
              ? <SystemEvent item={item} key={item.key} />
              : <ConversationMessage message={item.message} key={item.key} />
          ))}
        </ol>
        {!timeline.length && <p className="empty-note">No messages or assistance events are recorded for this session.</p>}
        <form className="staff-composer" onSubmit={submit}>
          <label htmlFor="staff-reply">Reply to claimant</label>
          <textarea id="staff-reply" rows="3" value={draft} onChange={(event) => onDraft(event.target.value)} disabled={!canSend} placeholder={placeholder} />
          <div><p>This message will be visible to the claimant.</p><button className="button button--primary" type="submit" disabled={!canSend || !draft.trim() || sending}><Send size={16} />{sending ? 'Sending...' : 'Send message'}</button></div>
          {historicalSession ? <p className="empty-note">This saved session is read-only. Open the active claimant conversation to send a message.</p> : !canSend && <ProjectedActionState action={sendAction} absentMessage="No claimant-message action is projected for this conversation." />}
          {sendError && <p className="form-error" role="alert">{sendError}</p>}
        </form>
        {handoff && ['accepted', 'in_progress'].includes(handoff.status) && (
          <HandoffResolution
            handoff={handoff}
            allowedAction={resolveAction}
            onResolve={onResolve}
            eyebrow="Assistance session"
            title="Complete staff assistance"
            actionLabel="Complete assistance"
            submitLabel="Confirm completion"
            compact
          />
        )}
      </section>
    </ResourceBoundary>
  )
}

function AssistanceStatus({ action, handoff, profile, state, revision, onAccept }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const canAccept = handoff.status === 'queued' && canSubmitCurrentAction(action, revision)

  async function accept() {
    if (!canAccept || busy) return
    setBusy(true)
    setError('')
    try {
      await onAccept(handoff)
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className={`assistance-status assistance-status--${state.key}`} aria-live="polite">
      <span className="assistance-status__icon" aria-hidden="true">
        {state.key === 'completed' ? <CheckCircle2 /> : state.key === 'waiting-request' ? <Clock3 /> : <UserRoundCheck />}
      </span>
      <div className="assistance-status__copy">
        <span className={`record-status${state.tone ? ` record-status--${state.tone}` : ''}`}>{state.label}</span>
        <strong>{state.title}</strong>
        <p>{state.description}</p>
        {state.expectedActor && <small>Expected to act: {state.expectedActor}</small>}
        {handoff.assigned_to === profile?.staff_id && profile?.display_name && <small>Assigned staff: {profile.display_name} · Claims professional</small>}
      </div>
      {canAccept && !confirming && <button className="button button--secondary" type="button" onClick={() => setConfirming(true)}>Take over conversation</button>}
      {canAccept && confirming && (
        <div className="assistance-status__confirm">
          <span>{action.confirmation?.message}</span>
          <button className="button button--ghost" type="button" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
          <button className="button button--secondary" type="button" disabled={busy} onClick={accept}>{busy ? 'Taking over...' : 'Confirm take over'}</button>
        </div>
      )}
      {handoff.status === 'queued' && !canAccept && <ProjectedActionState action={action} absentMessage="No take-over action is projected for this request." />}
      {error && <p className="form-error" role="alert">{error}</p>}
    </aside>
  )
}

function ConversationMessage({ message }) {
  const actor = message.actor || 'system'
  return (
    <li className={`message message--${actor}`}>
      <article>
        <header><strong>{actorLabel(actor)}</strong><time dateTime={message.created_at}>{formatDateTime(message.created_at)}</time></header>
        <p>{message.content?.text || words(message.content?.type)}</p>
      </article>
    </li>
  )
}

function SystemEvent({ item }) {
  return (
    <li className="conversation-event">
      <span>{item.label}</span>
      <time dateTime={item.createdAt}>{formatDateTime(item.createdAt)}</time>
    </li>
  )
}

function conversationTimeline(messages, handoff, profile) {
  const items = messages.map((message) => ({
    key: `message:${message.message_id}`,
    kind: 'message',
    createdAt: message.created_at,
    message,
  }))
  if (handoff?.created_at) {
    items.push({
      key: `handoff:${handoff.handoff_id}:requested`,
      kind: 'event',
      createdAt: handoff.created_at,
      label: 'Staff assistance requested',
    })
  }
  if (handoff?.accepted_at) {
    const staffName = handoff.assigned_to === profile?.staff_id && profile?.display_name
      ? profile.display_name
      : 'A Northwind staff member'
    items.push({
      key: `handoff:${handoff.handoff_id}:accepted`,
      kind: 'event',
      createdAt: handoff.accepted_at,
      label: `${staffName} joined the conversation`,
    })
  }
  if (handoff?.resolved_at) {
    items.push({
      key: `handoff:${handoff.handoff_id}:resolved`,
      kind: 'event',
      createdAt: handoff.resolved_at,
      label: 'Staff assistance completed',
    })
  }
  return items.sort((left, right) => (
    new Date(left.createdAt).getTime() - new Date(right.createdAt).getTime()
      || left.key.localeCompare(right.key)
  ))
}

function assistanceDisplayState(detail, handoff) {
  if (handoff?.status === 'resolved') {
    return {
      key: 'completed',
      label: 'Completed',
      tone: 'confirmed',
      title: 'Staff assistance completed',
      description: 'This assistance session is complete. The Claim remains separate and may still need work.',
      expectedActor: null,
    }
  }
  if ((detail.work_summary?.unread_claimant_messages || 0) > 0) {
    return {
      key: 'action-needed',
      label: 'Action needed',
      tone: 'attention',
      title: 'Customer replied',
      description: 'Review the latest customer message and continue the conversation.',
      expectedActor: 'You',
    }
  }
  if (
    ['accepted', 'in_progress'].includes(handoff?.status)
    && detail.customer_next_step?.responsible_party === 'claimant'
  ) {
    return {
      key: 'waiting-customer',
      label: 'Waiting for customer',
      tone: '',
      title: 'Waiting for customer',
      description: 'The customer is expected to respond or provide information.',
      expectedActor: 'Customer',
    }
  }
  if (handoff?.status === 'queued') {
    return {
      key: 'waiting-request',
      label: 'Waiting request',
      tone: '',
      title: 'Customer requested staff assistance',
      description: 'Review the conversation without taking ownership, or take over to reply.',
      expectedActor: 'Northwind staff',
    }
  }
  return {
    key: 'assigned',
    label: 'Assigned to me',
    tone: 'confirmed',
    title: 'You are helping this customer',
    description: 'Continue in the shared conversation and complete assistance when the request is resolved.',
    expectedActor: 'You',
  }
}

function latestCustomerAssistance(handoffs) {
  return [...handoffs].reverse().find((item) => item.support_need === 'human_requested') || null
}

function actorLabel(actor) {
  if (actor === 'claimant') return 'Customer'
  if (actor === 'agent') return 'AI Agent'
  if (actor === 'staff') return 'Northwind staff'
  return 'System'
}

function canSubmitCurrentAction(action, revision) {
  return canSubmitProjectedAction(action) && action.based_on_revision === revision
}

function currentProjectedAction(detail, actionCode, targetRef) {
  const action = findProjectedAction(detail.allowed_actions, actionCode, targetRef)
  return action?.based_on_revision === detail.revision ? action : undefined
}
