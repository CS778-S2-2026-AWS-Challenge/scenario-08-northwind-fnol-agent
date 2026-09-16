import { CheckCircle2, Clock3, Info, MessageSquare, Send, UserRoundCheck } from 'lucide-react'
import { useLayoutEffect, useRef, useState } from 'react'
import { formatDate, formatTime, words } from '../format.js'
import { canSubmitProjectedAction, findProjectedAction } from '../projected-action.js'
import ResourceBoundary from './ResourceBoundary.jsx'
import { ProjectedActionState } from './ProjectedAction.jsx'
import { HandoffResolution } from './ReviewActions.jsx'

export default function Conversation({
  detail,
  handoffs = [],
  profile,
  resource,
  requestedSessionId = null,
  draft,
  onDraft,
  onAccept,
  onResolve,
  onSend,
  onRetry,
}) {
  const [pendingSendKey, setPendingSendKey] = useState(null)
  const [sendError, setSendError] = useState(null)
  const [completedSends, setCompletedSends] = useState(0)
  const completedSendKeyRef = useRef(null)
  const handledDeliveryRef = useRef(null)
  const currentConversationKeyRef = useRef(null)
  const currentDraftRef = useRef(draft)
  const messageListRef = useRef(null)
  const resourceRequestedSessionId = resource?.requested_session_id || null
  const displayedSessionId = resource?.resolved_session_id || null
  const viewSessionId = requestedSessionId || resourceRequestedSessionId || displayedSessionId
  const conversationKey = conversationIdentity(detail.claim_id, viewSessionId)
  const resourceTargetsView = Boolean(
    viewSessionId
      && (resourceRequestedSessionId
        ? resourceRequestedSessionId === viewSessionId
        : !displayedSessionId || displayedSessionId === viewSessionId),
  )
  const displayedSessionMatchesView = Boolean(
    displayedSessionId
      && resourceTargetsView
      && displayedSessionId === viewSessionId,
  )
  const isCurrentSession = Boolean(
    displayedSessionMatchesView
      && detail.active_session_id
      && displayedSessionId === detail.active_session_id,
  )
  const historicalSession = Boolean(
    viewSessionId
      && viewSessionId !== detail.active_session_id,
  )
  const handoff = isCurrentSession ? latestCustomerAssistance(handoffs) : null
  const assignment = assistanceAssignment(detail, handoff, profile)
  const assistanceState = assistanceDisplayState(detail, handoff, assignment)
  const sendAction = currentProjectedAction(detail, 'conversation.send_claimant_message', displayedSessionId)
  const acceptAction = currentProjectedAction(detail, 'human.accept_handoff', handoff?.handoff_id)
  const resolveAction = currentProjectedAction(detail, 'human.resolve_handoff', handoff?.handoff_id)
  const canSend = Boolean(
    isCurrentSession
      && !resource?.error
      && resource?.status !== 'unavailable'
      && canSubmitCurrentAction(sendAction, detail.revision),
  )
  const timeline = conversationTimeline(
    displayedSessionMatchesView ? resource?.items || [] : [],
    handoff,
    profile,
  )
  const waitingForTakeover = assistanceState.key === 'waiting-request'
  const sending = Boolean(conversationKey && pendingSendKey === conversationKey)
  const deliveryReconciliation = resource?.delivery_reconciliation || null
  const deliveryTargetsView = Boolean(
    deliveryReconciliation
    && deliveryReconciliation.claim_id === detail.claim_id
    && deliveryReconciliation.session_id === viewSessionId,
  )
  const pendingDelivery = deliveryTargetsView
    && deliveryReconciliation.status === 'pending'
    ? deliveryReconciliation
    : null
  const visibleSendError = sendError?.key === conversationKey
    ? sendError.message
    : pendingDelivery?.message || ''
  const readbackBlocksResend = Boolean(
    (sendError?.key === conversationKey && sendError.readbackFailure)
    || pendingDelivery,
  )
  const viewResource = displayedSessionMatchesView
    ? resource
    : resourceTargetsView && (resource?.error || resource?.status === 'unavailable')
      ? {
        ...resource,
        items: [],
        resolved_session_id: null,
      }
      : {
        ...resource,
        items: [],
        status: 'available',
        limitation: null,
        loading: true,
        stale: false,
        error: null,
        requested_session_id: viewSessionId,
        resolved_session_id: null,
      }

  useLayoutEffect(() => {
    currentConversationKeyRef.current = conversationKey
  }, [conversationKey])

  useLayoutEffect(() => {
    currentDraftRef.current = draft
  }, [draft])

  useLayoutEffect(() => {
    if (
      !deliveryTargetsView
      || deliveryReconciliation.status !== 'confirmed'
      || sending
      || handledDeliveryRef.current === deliveryReconciliation.message_id
    ) return

    handledDeliveryRef.current = deliveryReconciliation.message_id
    setSendError((current) => (
      current?.delivery?.message_id === deliveryReconciliation.message_id
        ? null
        : current
    ))
    if (currentDraftRef.current === deliveryReconciliation.sent_draft) onDraft('')
    completedSendKeyRef.current = conversationKey
    setCompletedSends((current) => current + 1)
  }, [
    conversationKey,
    deliveryReconciliation,
    deliveryTargetsView,
    onDraft,
    sending,
  ])

  useLayoutEffect(() => {
    const completedSendKey = completedSendKeyRef.current
    completedSendKeyRef.current = null
    if (
      !completedSends
      || completedSendKey !== conversationKey
      || !messageListRef.current
    ) return
    messageListRef.current.scrollTop = messageListRef.current.scrollHeight
  }, [completedSends, conversationKey])

  async function submit(event) {
    event.preventDefault()
    if (!draft.trim() || !canSend || !displayedSessionId) return
    const sendKey = conversationIdentity(detail.claim_id, displayedSessionId)
    const submittedDraft = draft
    const submittedMessage = draft.trim()
    setPendingSendKey(sendKey)
    setSendError(null)
    try {
      const result = await onSend({
        message: submittedMessage,
        sessionId: displayedSessionId,
        draft: submittedDraft,
      })
      if (currentConversationKeyRef.current !== sendKey) return
      if (result?.delivery?.message_id) {
        handledDeliveryRef.current = result.delivery.message_id
      }
      if (currentDraftRef.current === submittedDraft) onDraft('')
      completedSendKeyRef.current = sendKey
      setCompletedSends((current) => current + 1)
    } catch (nextError) {
      setSendError({
        key: sendKey,
        message: nextError.message,
        readbackFailure: Boolean(nextError.readbackFailure),
        sentDraft: submittedDraft,
        delivery: nextError.delivery || null,
      })
    } finally {
      setPendingSendKey((current) => current === sendKey ? null : current)
    }
  }

  const placeholder = historicalSession
    ? 'This conversation is read-only'
    : handoff && assistanceState.key === 'completed'
      ? 'Staff assistance is complete'
      : handoff && assistanceState.key === 'waiting-request'
        ? 'Take over conversation to reply'
        : handoff && assistanceState.key === 'action-needed'
          ? 'Reply to customer...'
          : handoff && assistanceState.key === 'waiting-customer'
            ? 'Waiting for the customer — send an update if needed'
            : 'Write a message…'
  const unavailableTitle = historicalSession
    ? 'Read-only conversation'
    : 'Staff messaging not available yet'
  const unavailableMessage = historicalSession
    ? 'Open the active claimant conversation to send a message.'
    : sendAction?.blocked_reason || 'Messaging is not available for this claim yet.'

  return (
    <ResourceBoundary resource={viewResource} onRetry={onRetry} contentAvailable={displayedSessionMatchesView} quietRefresh={sending}>
      <section className="conversation-view">
        {handoff && !waitingForTakeover && (
          <AssistanceStatus
            action={acceptAction}
            handoff={handoff}
            detail={detail}
            profile={profile}
            state={assistanceState}
            revision={detail.revision}
            onAccept={onAccept}
            resolveAction={resolveAction}
            onResolve={onResolve}
          />
        )}
        <ol ref={messageListRef} className="message-list" role="log" aria-label="Claimant conversation messages">
          {timeline.map((item) => (
            item.kind === 'date'
              ? <DateDivider item={item} key={item.key} />
              : item.kind === 'event'
              ? <SystemEvent item={item} key={item.key} />
              : <ConversationMessage message={item.message} key={item.key} />
          ))}
          {!timeline.length && (
            <li className="conversation-empty">
              <MessageSquare aria-hidden="true" />
              <strong>No messages yet</strong>
              <p>Messages with the claimant will appear here.</p>
            </li>
          )}
        </ol>
        <form className="staff-composer" onSubmit={submit}>
          {handoff && waitingForTakeover ? (
            <AssistanceStatus
              action={acceptAction}
              compact
              handoff={handoff}
              detail={detail}
              profile={profile}
              state={assistanceState}
              revision={detail.revision}
              onAccept={onAccept}
            />
          ) : !canSend && (
            <div className="staff-composer__notice" id="staff-message-status" role="status">
              <Info size={16} aria-hidden="true" />
              <span>
                <strong>{unavailableTitle}</strong>
                <small>{unavailableMessage}</small>
              </span>
            </div>
          )}
          <div className="staff-composer__input">
            <label className="sr-only" htmlFor="staff-reply">Message to claimant</label>
            <textarea
              id="staff-reply"
              rows="1"
              value={draft}
              onChange={(event) => {
                const nextDraft = event.target.value
                if (
                  sendError?.key === conversationKey
                  && !sendError.readbackFailure
                  && nextDraft.trim() !== sendError.sentDraft
                ) setSendError(null)
                onDraft(nextDraft)
              }}
              disabled={!canSend}
              placeholder={placeholder}
              aria-describedby={visibleSendError
                ? 'staff-message-error'
                : !canSend
                  ? 'staff-message-status'
                  : undefined}
            />
            <button
              className="staff-composer__send"
              type="submit"
              disabled={!canSend || !draft.trim() || sending || readbackBlocksResend}
              aria-label="Send message"
              aria-busy={sending}
              title={sending ? 'Sending message' : 'Send message'}
            >
              <Send size={18} aria-hidden="true" />
            </button>
          </div>
          {visibleSendError && <p className="form-error" id="staff-message-error" role="alert">{visibleSendError}</p>}
        </form>
      </section>
    </ResourceBoundary>
  )
}

function AssistanceStatus({ action, compact = false, handoff, detail, profile, state, revision, onAccept, resolveAction, onResolve }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const canAccept = handoff.status === 'queued' && canSubmitCurrentAction(action, revision)
  const assignment = assistanceAssignment(detail, handoff, profile)
  const assignmentCopy = state.key === 'completed'
    ? null
    : state.key === 'assigned'
      ? assignment.detail
      : assignment.label

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
    <aside
      className={`assistance-status assistance-status--${state.key}${compact ? ' assistance-status--composer' : ''}`}
      id={compact ? 'staff-message-status' : undefined}
      role={compact ? 'status' : undefined}
      aria-live="polite"
    >
      <span className="assistance-status__icon" aria-hidden="true">
        {state.key === 'completed' ? <CheckCircle2 /> : state.key === 'waiting-request' ? <Clock3 /> : <UserRoundCheck />}
      </span>
      <div className="assistance-status__copy">
        {canAccept && confirming ? (
          <strong className="assistance-status__confirmation-message">{action.confirmation?.message}</strong>
        ) : (
          <>
            {!compact && <span className="assistance-status__eyebrow">Staff assistance</span>}
            <span className="assistance-status__summary">
              <strong>{state.title}</strong>
              {!compact && assignmentCopy && <small>{assignmentCopy}</small>}
            </span>
          </>
        )}
      </div>
      {canAccept && !confirming && <button className="button button--secondary" type="button" onClick={() => setConfirming(true)}>Take over conversation</button>}
      {canAccept && confirming && (
        <div className="assistance-status__confirm">
          <button className="button button--ghost" type="button" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
          <button className="button button--secondary" type="button" disabled={busy} onClick={accept}>{busy ? 'Taking over...' : 'Confirm take over'}</button>
        </div>
      )}
      {!compact && ['accepted', 'in_progress'].includes(handoff.status) && (
        <HandoffResolution
          handoff={handoff}
          allowedAction={resolveAction}
          onResolve={onResolve}
          actionLabel="Complete assistance"
          submitLabel="Confirm completion"
          compact
          inline
        />
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
        <header><strong>{actorLabel(actor)}</strong><time dateTime={message.created_at}>{formatTime(message.created_at)}</time></header>
        <p>{message.content?.text || words(message.content?.type)}</p>
      </article>
    </li>
  )
}

function SystemEvent({ item }) {
  return (
    <li className="conversation-event">
      <span>{item.label}</span>
      <time dateTime={item.createdAt}>{formatTime(item.createdAt)}</time>
    </li>
  )
}

function DateDivider({ item }) {
  return <li className="conversation-date-divider"><span>{item.label}</span></li>
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
      label: `${staffName} joined`,
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
  const sortedItems = items.sort((left, right) => (
    new Date(left.createdAt).getTime() - new Date(right.createdAt).getTime()
      || left.key.localeCompare(right.key)
  ))
  const timeline = []
  let displayedDate = null
  sortedItems.forEach((item) => {
    const itemDate = formatDate(item.createdAt)
    if (itemDate !== displayedDate) {
      timeline.push({
        key: `date:${itemDate}`,
        kind: 'date',
        label: itemDate,
      })
      displayedDate = itemDate
    }
    timeline.push(item)
  })
  return timeline
}

function assistanceDisplayState(detail, handoff, assignment) {
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
  if (handoff?.status === 'queued') {
    return {
      key: 'waiting-request',
      label: 'Waiting request',
      tone: '',
      title: 'Customer requested staff assistance',
    }
  }
  if (
    ['accepted', 'in_progress'].includes(handoff?.status)
    && (detail.work_summary?.unread_claimant_messages || 0) > 0
  ) {
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
  return {
    key: 'assigned',
    label: assignment.title,
    tone: 'confirmed',
    title: assignment.title,
    description: 'Continue in the shared conversation and complete assistance when the request is resolved.',
    expectedActor: 'You',
  }
}

function assistanceAssignment(detail, handoff, profile) {
  if (handoff?.assigned_to && handoff.assigned_to === profile?.staff_id) {
    return {
      title: 'Assigned to you',
      detail: profile?.display_name || null,
      label: profile?.display_name
        ? `Assigned to you · ${profile.display_name}`
        : 'Assigned to you',
    }
  }

  const projectedAssignee = detail.ownership?.primary_assignee
  const projectedName = projectedAssignee
    && handoff?.assigned_to
    && projectedAssignee.staff_id === handoff.assigned_to
    ? projectedAssignee.display_name
    : null
  const title = projectedName
    ? `Assigned to ${projectedName}`
    : 'Assigned to another staff member'

  return { title, detail: null, label: title }
}

function conversationIdentity(claimId, sessionId) {
  return claimId && sessionId ? `${claimId}:${sessionId}` : null
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
