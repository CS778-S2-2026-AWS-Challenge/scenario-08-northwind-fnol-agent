import {
  AlertCircle,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  Clipboard,
  GripHorizontal,
  LoaderCircle,
  MessageSquarePlus,
  Send,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { workbenchApi } from '../api.js'
import { containTabFocus } from '../focus.js'
import { COMPACT_WORKBENCH_QUERY, useMediaQuery } from '../hooks/useMediaQuery.js'
import { staffAgentUnavailableReason } from '../staff-agent-availability.js'
import { translate as t } from '../i18n.js'
import { formatDateTime, words } from '../format.js'
import AttachmentDraftControl from './AttachmentDraftControl.jsx'
import CompactComposerTextarea from './CompactComposerTextarea.jsx'
import VoiceInputControl from './VoiceInputControl.jsx'

const MAX_CLAIM_SCOPE = 5
const NEW_SESSION_TITLE = 'New Staff Agent session'
const DRAG_THRESHOLD = 4

export default function StaffAgent({
  open,
  embedded = false,
  onOpenChange,
  requestedSessionId,
  token,
  onSessionChange,
  onConversationChanged,
  onBusinessActionMutation,
  onBusinessActionExecuted,
}) {
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [claims, setClaims] = useState([])
  const [models, setModels] = useState([])
  const [selectedClaimIds, setSelectedClaimIds] = useState([])
  const [newSessionModel, setNewSessionModel] = useState('qwen-local')
  const [scopeOpen, setScopeOpen] = useState(false)
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [sessionNotice, setSessionNotice] = useState('')
  const [error, setError] = useState(null)
  const [position, setPosition] = useState(null)
  // 'loading' | 'loaded' | 'failed'. Sending stays closed until model availability is known.
  const [capabilityStatus, setCapabilityStatus] = useState('loading')
  // The compact layout shows the open panel in place of the content and has no bubble to drag.
  const compactLayout = useMediaQuery(COMPACT_WORKBENCH_QUERY)
  const widgetRef = useRef(null)
  const panelRef = useRef(null)
  const scopeToggleRef = useRef(null)
  const bubbleRef = useRef(null)
  const openerRef = useRef(null)
  const panelWasOpenRef = useRef(false)
  const messageRef = useRef(null)
  const attachmentDraftRef = useRef(null)
  const voiceInputRef = useRef(null)
  const dragRef = useRef(null)
  const suppressClickRef = useRef(false)
  const activeSessionIdRef = useRef(null)
  const currentMessageDraftRef = useRef('')
  const draftsBySessionRef = useRef(new Map())
  const wasOpenRef = useRef(false)
  const onSessionChangeRef = useRef(onSessionChange)

  useEffect(() => {
    onSessionChangeRef.current = onSessionChange
  }, [onSessionChange])

  const loadMessages = useCallback(async (sessionId) => {
    if (!sessionId) {
      setMessages([])
      return
    }
    const response = await workbenchApi.staffAgentMessages(token, sessionId)
    setMessages(response.items || [])
  }, [token])

  const selectSession = useCallback(async (sessionId) => {
    draftsBySessionRef.current.set(staffAgentDraftKey(activeSessionIdRef.current), currentMessageDraftRef.current)
    attachmentDraftRef.current?.clear()
    voiceInputRef.current?.cancel({ announce: false, restoreFocus: false })
    setSessionNotice('')
    setError(null)
    setScopeOpen(false)
    activeSessionIdRef.current = sessionId
    setActiveSessionId(sessionId)
    const restoredDraft = draftsBySessionRef.current.get(staffAgentDraftKey(sessionId)) || ''
    currentMessageDraftRef.current = restoredDraft
    setMessage(restoredDraft)
    onSessionChangeRef.current(sessionId)
    setSelectedClaimIds([])
    await loadMessages(sessionId)
  }, [loadMessages])

  const loadAgent = useCallback(async () => {
    setLoading(true)
    setSessionNotice('')
    setError(null)
    setCapabilityStatus('loading')
    // Model availability is applied on its own so a failed session or Claim list cannot reopen sending.
    const capabilities = workbenchApi.staffAgentCapabilities(token).then(
      (capabilityResponse) => {
        const nextModels = capabilityResponse.models || []
        setModels(nextModels)
        if (capabilityResponse.default_model_profile_id) setNewSessionModel(capabilityResponse.default_model_profile_id)
        setCapabilityStatus('loaded')
      },
      () => setCapabilityStatus('failed'),
    )
    try {
      const [sessionResponse, claimResponse] = await Promise.all([
        workbenchApi.staffAgentSessions(token),
        workbenchApi.claims(token, { limit: 100 }),
        capabilities,
      ])
      const nextSessions = sessionResponse.items || []
      setSessions(nextSessions)
      setClaims(claimResponse.items || [])
      const nextSessionId = requestedSessionId || nextSessions[0]?.session_id || null
      if (nextSessionId) await selectSession(nextSessionId)
    } catch (nextError) {
      setError(agentError(nextError, 'load'))
    } finally {
      setLoading(false)
    }
  }, [requestedSessionId, selectSession, token])

  useEffect(() => {
    const wasOpen = wasOpenRef.current
    wasOpenRef.current = open
    if (!open) return undefined
    if (wasOpen && requestedSessionId && requestedSessionId === activeSessionIdRef.current) return undefined
    const task = window.setTimeout(loadAgent, 0)
    return () => window.clearTimeout(task)
  }, [open, loadAgent, requestedSessionId])

  // The floating panel is a non-modal dialog: focus moves in on open and returns to the
  // control that opened it on close. The embedded route panel is ordinary page content.
  useEffect(() => {
    if (embedded) return
    const wasOpen = panelWasOpenRef.current
    panelWasOpenRef.current = open
    if (open && !wasOpen) {
      const active = document.activeElement
      openerRef.current = active && active !== document.body && !widgetRef.current?.contains(active)
        ? active
        : null
      ;(messageRef.current || panelRef.current)?.focus()
    } else if (!open && wasOpen) {
      const opener = openerRef.current
      openerRef.current = null
      ;(opener?.isConnected ? opener : bubbleRef.current)?.focus()
    }
  }, [embedded, open])

  const activeSession = sessions.find((session) => session.session_id === activeSessionId)
  const unavailableReason = capabilityStatus === 'failed'
    ? 'Staff Agent model availability could not be checked. Close and reopen the panel to try again.'
    : capabilityStatus === 'loaded'
      ? staffAgentUnavailableReason(models, activeSessionId ? activeSession?.model_profile_id : newSessionModel)
      : null
  const sendClosed = capabilityStatus !== 'loaded' || Boolean(unavailableReason)

  const positioned = position !== null
  useEffect(() => {
    if (!positioned) return undefined
    const keepInViewport = () => {
      const widget = widgetRef.current
      if (!widget) return
      setPosition((current) => current && clampWidgetPosition(current.left, current.top, widget))
    }
    keepInViewport()
    window.addEventListener('resize', keepInViewport)
    return () => {
      window.removeEventListener('resize', keepInViewport)
    }
  }, [open, positioned])

  function beginNewSession() {
    setSessionNotice('')
    setError(null)

    if (activeSessionId && !messages.length) {
      setSessionNotice('This conversation is already empty. Start typing to continue.')
      messageRef.current?.focus()
      return
    }

    draftsBySessionRef.current.set(staffAgentDraftKey(activeSessionIdRef.current), currentMessageDraftRef.current)
    attachmentDraftRef.current?.clear()
    voiceInputRef.current?.cancel({ announce: false, restoreFocus: false })
    activeSessionIdRef.current = null
    setActiveSessionId(null)
    setMessages([])
    setSelectedClaimIds([])
    setScopeOpen(false)
    const restoredDraft = draftsBySessionRef.current.get(staffAgentDraftKey(null)) || ''
    currentMessageDraftRef.current = restoredDraft
    setMessage(restoredDraft)
    setSessionNotice(restoredDraft.trim()
      ? 'Your draft is still here. This conversation will be saved when you send it.'
      : 'This conversation will be saved when you send the first message.')
    messageRef.current?.focus()
  }

  async function submit(event) {
    event.preventDefault()
    const submittedDraft = message
    const content = submittedDraft.trim()
    if (
      !content
      || loading
      || sending
      || sendClosed
      || attachmentDraftRef.current?.hasPendingAttachments()
    ) return
    voiceInputRef.current?.cancel({ announce: false, restoreFocus: false })
    setSending(true)
    setSessionNotice('')
    setError(null)
    let operation = 'send'
    try {
      let sessionId = activeSessionId
      if (!sessionId) {
        operation = 'create'
        const session = await workbenchApi.createStaffAgentSession(token, NEW_SESSION_TITLE, newSessionModel)
        setSessions((current) => [session, ...current])
        sessionId = session.session_id
        const unsavedDraft = currentMessageDraftRef.current
        draftsBySessionRef.current.delete(staffAgentDraftKey(null))
        draftsBySessionRef.current.set(staffAgentDraftKey(sessionId), unsavedDraft)
        activeSessionIdRef.current = sessionId
        setActiveSessionId(sessionId)
        onSessionChangeRef.current(sessionId)
        operation = 'send'
      }
      const response = await workbenchApi.sendStaffAgentMessage(
        token,
        sessionId,
        content,
        selectedClaimIds,
      )
      if (currentMessageDraftRef.current === submittedDraft) {
        currentMessageDraftRef.current = ''
        draftsBySessionRef.current.set(staffAgentDraftKey(sessionId), '')
        setMessage('')
      }
      setMessages((current) => [
        ...current,
        response.staff_message,
        response.assistant_message,
      ])
      setSessions((current) => [
        response.session,
        ...current.filter((item) => item.session_id !== response.session.session_id),
      ])
      onConversationChanged()
    } catch (nextError) {
      setError(agentError(nextError, operation, { hasAlternativeModel: models.length > 1 }))
    } finally {
      setSending(false)
    }
  }

  async function executeDraft(sourceMessage, draft) {
    if (
      !sourceMessage?.session_id
      || !sourceMessage?.message_id
      || !draft?.draft_id
      || !draft?.claim_id
      || !draft?.action_code
      || !draft?.target_ref
    ) {
      throw new Error('This Staff Agent draft is informational and cannot execute a business action.')
    }

    const latestClaim = await workbenchApi.claim(token, draft.claim_id)
    const execute = () => workbenchApi.executeStaffAgentDraft(
      token,
      sourceMessage.session_id,
      sourceMessage.message_id,
      draft.draft_id,
      latestClaim.revision,
      draft.payload || {},
    )
    const response = onBusinessActionMutation
      ? await onBusinessActionMutation(draft.claim_id, execute)
      : await execute()

    try {
      await onBusinessActionExecuted?.(response)
    } catch (refreshError) {
      setError({
        title: 'Action executed; refresh required',
        message: refreshError?.message
          || 'The registered action succeeded, but the latest Workbench projection could not be loaded automatically. Refresh the Claim before taking another action.',
        requestId: refreshError?.requestId || null,
      })
    }
    return response
  }

  function toggleClaim(claimId) {
    setSelectedClaimIds((current) => {
      if (current.includes(claimId)) return current.filter((item) => item !== claimId)
      if (current.length >= MAX_CLAIM_SCOPE) return current
      return [...current, claimId]
    })
  }

  function updateComposerDraft(nextMessage) {
    currentMessageDraftRef.current = nextMessage
    draftsBySessionRef.current.set(staffAgentDraftKey(activeSessionIdRef.current), nextMessage)
    setMessage(nextMessage)
    setSessionNotice('')
  }

  function beginDrag(event) {
    if (event.button !== 0 || compactLayout) return
    if (event.currentTarget.classList.contains('staff-agent__header')
      && event.target.closest('button, select, input, textarea')) return
    const widget = widgetRef.current
    if (!widget) return
    const rect = widget.getBoundingClientRect()
    dragRef.current = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
    }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }

  function drag(event) {
    const dragState = dragRef.current
    const widget = widgetRef.current
    if (!dragState || !widget) return
    if (!dragState.moved) {
      const movedX = Math.abs(event.clientX - dragState.startX)
      const movedY = Math.abs(event.clientY - dragState.startY)
      if (Math.max(movedX, movedY) < DRAG_THRESHOLD) return
      dragState.moved = true
    }
    setPosition(clampWidgetPosition(
      event.clientX - dragState.offsetX,
      event.clientY - dragState.offsetY,
      widget,
    ))
  }

  function endDrag(event) {
    const moved = dragRef.current?.moved
    dragRef.current = null
    if (moved && event.currentTarget.classList.contains('staff-agent__bubble')) {
      suppressClickRef.current = true
    }
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture?.(event.pointerId)
    }
  }

  function cancelDrag(event) {
    dragRef.current = null
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture?.(event.pointerId)
    }
  }

  // The focused checkbox unmounts with the list, so return focus to the toggle that opened it.
  function closeScope() {
    setScopeOpen(false)
    scopeToggleRef.current?.focus()
  }

  function handlePanelKeyDown(event) {
    if (embedded || !panelRef.current?.contains(event.target)) return
    if (event.key === 'Escape') {
      event.preventDefault()
      if (scopeOpen) {
        closeScope()
        return
      }
      onOpenChange(false)
      return
    }
    containTabFocus(event, panelRef.current)
  }

  function openAgent() {
    if (suppressClickRef.current) {
      suppressClickRef.current = false
      return
    }
    onOpenChange(true)
  }

  return (
    <div ref={widgetRef} className={`staff-agent${embedded ? ' staff-agent--embedded' : ''}${open ? ' is-open' : ''}`} style={!embedded && !compactLayout && position ? { left: position.left, top: position.top, right: 'auto', bottom: 'auto' } : undefined}>
      {!open && !embedded && (
        <button ref={bubbleRef} className="staff-agent__bubble" type="button" onClick={openAgent} onPointerDown={beginDrag} onPointerMove={drag} onPointerUp={endDrag} onPointerCancel={cancelDrag} aria-label={t('Open Staff Agent')} title={t('Draft with AI')}>
          <Bot size={23} />
        </button>
      )}
      {open && (
        <section
          ref={panelRef}
          className="staff-agent__panel"
          role={embedded ? undefined : 'dialog'}
          aria-labelledby="staff-agent-title"
          tabIndex={embedded ? undefined : -1}
          onKeyDown={handlePanelKeyDown}
        >
          <header className="staff-agent__header" onPointerDown={embedded ? undefined : beginDrag} onPointerMove={embedded ? undefined : drag} onPointerUp={embedded ? undefined : endDrag} onPointerCancel={embedded ? undefined : cancelDrag}>
            <span className="staff-agent__grip" aria-hidden="true"><GripHorizontal size={18} /></span>
            <div className="staff-agent__identity">
              <h2 id="staff-agent-title">{t('Staff Agent')}</h2>
              <small>{t('Private Workbench assistance')}</small>
            </div>
            <button className="icon-button" type="button" onClick={() => onOpenChange(false)} aria-label={t('Close Staff Agent')}><X size={16} /></button>
          </header>

          <div className="agent-context">
            <div className="agent-session-bar">
              <label>
                <span>{t('Session')}</span>
                <select value={activeSessionId || ''} onChange={(event) => selectSession(event.target.value)} disabled={loading || sending || !sessions.length}>
                  {!activeSessionId && <option value="">{t('New conversation (not saved)')}</option>}
                  {sessions.map((session) => <option value={session.session_id} key={session.session_id}>{sessionLabel(session)}</option>)}
                </select>
              </label>
              <label>
                <span>{t('New session model')}</span>
                <select value={newSessionModel} onChange={(event) => setNewSessionModel(event.target.value)} disabled={loading || sending || !models.length}>
                  {!models.length && <option value="">{t('No published model')}</option>}
                  {models.map((model) => <option value={model.id} key={model.id}>{model.label}</option>)}
                </select>
              </label>
              <button className="agent-session-bar__new" type="button" onClick={beginNewSession} disabled={loading || sending} aria-label={t('Start a new Staff Agent session')}>
                <MessageSquarePlus size={16} />
                <span>{t('New')}</span>
              </button>
            </div>

            <div className="agent-scope">
              <button ref={scopeToggleRef} type="button" className="agent-scope__toggle" aria-expanded={scopeOpen} aria-controls="staff-agent-claim-scope" onClick={() => setScopeOpen((value) => !value)}>
                <span className="agent-scope__summary"><strong>{t('Claim Scope')}</strong><small>{scopeLabel(selectedClaimIds, claims)}</small></span>
                <ChevronDown size={15} />
              </button>
              {scopeOpen && (
                <fieldset id="staff-agent-claim-scope" className="agent-scope__options">
                  <legend className="sr-only">{t('Choose Claims for Staff Agent context')}</legend>
                  <div className="agent-scope__options-header">
                    <span>
                      <strong>{t('Attach Claim context')}</strong>
                      <small>{t('Choose one Claim for focused help, or several to compare.')}</small>
                    </span>
                    <span className="agent-scope__count">{selectedClaimIds.length} of {MAX_CLAIM_SCOPE}</span>
                  </div>
                  <div className="agent-scope__list">
                    {claims.map((claim) => {
                      const checked = selectedClaimIds.includes(claim.claim_id)
                      const disabled = !checked && selectedClaimIds.length >= MAX_CLAIM_SCOPE
                      return (
                        <label className={`${checked ? 'is-selected' : ''}${disabled ? ' is-disabled' : ''}`.trim()} key={claim.claim_id}>
                          <input type="checkbox" checked={checked} disabled={disabled} onChange={() => toggleClaim(claim.claim_id)} />
                          <span className="agent-scope__check" aria-hidden="true">{checked && <Check size={12} />}</span>
                          <span className="agent-scope__claim"><strong>{claim.display_reference || claim.claim_id}</strong><small>{claim.incident?.summary || claim.claim_id}</small></span>
                        </label>
                      )
                    })}
                    {!claims.length && <p>{t('No Claims are available to attach.')}</p>}
                  </div>
                  <div className="agent-scope__footer">
                    <small className="agent-scope__status" aria-live="polite">{scopeStatus(selectedClaimIds.length)}</small>
                    <button className="agent-scope__done" type="button" onClick={closeScope}>{t('Done')}</button>
                  </div>
                </fieldset>
              )}
            </div>
          </div>

          <div className="agent-conversation">
            <div className="agent-messages" aria-live="polite">
              {loading && <p className="agent-state">{t('Loading Staff Agent sessions...')}</p>}
              {!loading && !messages.length && (
                <div className="agent-empty">
                  <span className="agent-empty__icon" aria-hidden="true"><Bot size={20} /></span>
                  <p>{t('Ask a general question or explicitly attach up to five Claims.')}</p>
                  <small>{t('The Agent can advise and draft. Registered business actions execute only after explicit staff confirmation.')}</small>
                </div>
              )}
              {messages.map((item) => (
                <AgentMessage
                  message={item}
                  key={item.message_id}
                  onExecuteDraft={executeDraft}
                />
              ))}
            </div>

            {unavailableReason && (
              <div className="agent-notice agent-notice--unavailable" id="staff-agent-unavailable" role="status">
                <AlertCircle size={16} aria-hidden="true" />
                <span>
                  <strong>{t('Staff Agent cannot answer right now')}</strong>
                  <small>{t(unavailableReason)} {t('Messages cannot be sent until a model is available. Your draft and earlier sessions stay here.')}</small>
                </span>
              </div>
            )}
            {sessionNotice && (
              <div className="agent-notice" role="status">
                <CheckCircle2 size={16} aria-hidden="true" />
                <span><strong>{t('New conversation ready')}</strong><small>{sessionNotice}</small></span>
              </div>
            )}
            {error && (
              <div className="agent-error" role="alert">
                <AlertCircle size={16} aria-hidden="true" />
                <span>
                  <strong>{error.title}</strong>
                  <small>{error.message}</small>
                  {error.requestId && <small className="agent-error__reference">Reference: {error.requestId}</small>}
                </span>
                <button className="agent-feedback__dismiss" type="button" onClick={() => setError(null)} aria-label={t('Dismiss Staff Agent error')}><X size={14} /></button>
              </div>
            )}
            <AttachmentDraftControl
              ref={attachmentDraftRef}
              available={!loading && !sending}
              idPrefix="staff-agent-attachment"
              triggerClassName="agent-composer__attachment compact-composer__tool"
            >
              {({ attachmentsPending, describedBy, preview, trigger }) => (
                <form className="agent-composer" onSubmit={submit}>
                  {selectedClaimIds.length > 0 && (
                    <div className="agent-composer__context">
                      <button
                        type="button"
                        className="agent-composer__context-chip"
                        aria-expanded={scopeOpen}
                        aria-controls="staff-agent-claim-scope"
                        onClick={() => setScopeOpen((value) => !value)}
                        title="Review selected Claim context"
                      >
                        <span>{compactScopeLabel(selectedClaimIds, claims)}</span>
                        <ChevronDown size={15} aria-hidden="true" />
                      </button>
                    </div>
                  )}
                  {preview}
                  <div className="agent-composer__input compact-composer__input">
                    {trigger}
                    <VoiceInputControl
                      ref={voiceInputRef}
                      available={!loading && !sending}
                      draft={message}
                      onDraft={updateComposerDraft}
                      statusId="staff-agent-voice-status"
                      textareaRef={messageRef}
                    />
                    <CompactComposerTextarea
                      id="staff-agent-message"
                      ref={messageRef}
                      value={message}
                      describedBy={[describedBy, unavailableReason ? 'staff-agent-unavailable' : null].filter(Boolean).join(' ') || undefined}
                      onValueChange={updateComposerDraft}
                      placeholder={t('Ask about selected Claims or policy…')}
                      label={t('Message Staff Agent')}
                      submitDisabled={!message.trim() || loading || sending || attachmentsPending || sendClosed}
                    />
                    <button
                      className="agent-composer__send compact-composer__send"
                      type="submit"
                      disabled={!message.trim() || loading || sending || attachmentsPending || sendClosed}
                      aria-busy={sending}
                      aria-label={t('Send to Staff Agent')}
                      title={attachmentsPending ? 'Remove attachments to send text; file delivery is not available yet' : sending ? 'Sending to Staff Agent' : 'Send to Staff Agent'}
                    >
                      {sending
                        ? <LoaderCircle className="compact-composer__spinner" size={18} aria-hidden="true" />
                        : <Send size={18} aria-hidden="true" />}
                    </button>
                  </div>
                </form>
              )}
            </AttachmentDraftControl>
          </div>
        </section>
      )}
    </div>
  )
}

function clampWidgetPosition(left, top, widget) {
  const maxLeft = Math.max(0, window.innerWidth - widget.offsetWidth)
  const maxTop = Math.max(0, window.innerHeight - widget.offsetHeight)
  return {
    left: Math.max(0, Math.min(maxLeft, left)),
    top: Math.max(0, Math.min(maxTop, top)),
  }
}

function AgentMessage({ message, onExecuteDraft }) {
  return (
    <article className={`agent-message agent-message--${message.role}`}>
      <header><strong>{message.role === 'assistant' ? 'Staff Agent' : 'You'}</strong><small>{message.claim_ids?.length ? `${message.claim_ids.length} Claim${message.claim_ids.length > 1 ? 's' : ''} attached` : 'General scope'}</small></header>
      <p>{message.content}</p>
      {message.drafts?.map((draft, index) => (
        <AgentDraft
          draft={draft}
          sourceMessage={message}
          onExecute={onExecuteDraft}
          key={draft.draft_id || `${message.message_id}-draft-${index}`}
        />
      ))}
      {!!message.source_refs?.length && <details><summary>{t('Sources used')}</summary><ul>{message.source_refs.map((source) => <li key={source}>{source}</li>)}</ul></details>}
    </article>
  )
}

function AgentDraft({ draft, sourceMessage, onExecute }) {
  const [content, setContent] = useState(draft.content)
  const [reviewing, setReviewing] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [execution, setExecution] = useState(null)
  const [executionError, setExecutionError] = useState(null)
  const executable = Boolean(
    draft.draft_id
    && draft.claim_id
    && draft.action_code
    && draft.target_ref
    && sourceMessage?.session_id
    && sourceMessage?.message_id
  )

  async function execute() {
    if (!executable || executing || execution) return
    setExecuting(true)
    setExecutionError(null)
    try {
      const result = await onExecute(sourceMessage, draft)
      setExecution(result)
      setReviewing(false)
    } catch (error) {
      setExecutionError(draftExecutionError(error))
    } finally {
      setExecuting(false)
    }
  }

  return (
    <section className={`agent-draft${executable ? ' agent-draft--executable' : ''}`}>
      <header>
        <span><strong>{draft.title}</strong><small>{draft.kind.replaceAll('_', ' ')}</small></span>
        <button type="button" className="icon-button icon-button--small" onClick={() => navigator.clipboard.writeText(content)} aria-label={`Copy ${draft.title}`}><Clipboard size={14} /></button>
      </header>
      <textarea
        value={content}
        readOnly={executable}
        onChange={executable ? undefined : (event) => setContent(event.target.value)}
        aria-label={executable ? `Review ${draft.title}` : `Edit ${draft.title}`}
      />
      {draft.claim_id && <small>Draft for {draft.claim_id}</small>}
      {executable && (
        <div className="agent-draft__action">
          <div>
            <strong>{t('Registered action')}</strong>
            <small>{draft.action_code} · target {draft.target_ref}</small>
          </div>
          {!reviewing && !execution && (
            <button className="button button--quiet" type="button" onClick={() => setReviewing(true)}>
              Review action
            </button>
          )}
        </div>
      )}
      {executable && reviewing && !execution && (
        <div className="agent-draft__confirm">
          <p>{t('The Agent proposed this action. The Workbench will reload the Claim, use its current revision, and let the registered backend action decide whether execution is authorised.')}</p>
          <div className="form-actions">
            <button className="button button--ghost" type="button" disabled={executing} onClick={() => setReviewing(false)}>{t('Cancel')}</button>
            <button className="button button--primary" type="button" disabled={executing} onClick={execute}>
              {executing ? 'Executing...' : 'Confirm and execute'}
            </button>
          </div>
        </div>
      )}
      {execution && (() => {
        const presentation = draftExecutionPresentation(execution)
        return (
          <div className="agent-draft__execution" role="status">
            <CheckCircle2 size={16} aria-hidden="true" />
            <span>
              <strong>Workbench outcome: {presentation.outcome}</strong>
              {presentation.details.map((detail) => <small key={detail}>{detail}</small>)}
            </span>
          </div>
        )
      })()}
      {executionError && (
        <div className="agent-draft__execution agent-draft__execution--error" role="alert">
          <AlertCircle size={16} aria-hidden="true" />
          <span><strong>{executionError.title}</strong><small>{executionError.message}</small></span>
        </div>
      )}
      {executable && <small>{t('The saved registered payload is executed unchanged. To change the business action, ask Staff Agent to prepare a new draft.')}</small>}
    </section>
  )
}

function draftExecutionPresentation(execution) {
  const runtimeExecution = execution?.runtime_execution || {}
  const result = runtimeExecution.result || execution?.result || {}
  const details = []
  const add = (label, value) => {
    if (value === undefined || value === null || value === '') return
    details.push(`${label}: ${value}`)
  }

  add('Handoff status', result.handoff?.status ? words(result.handoff.status) : null)
  add('Handoff', result.handoff?.handoff_id)
  add('Work item status', result.action?.status ? words(result.action.status) : null)
  add('Work item', result.action?.action_id)
  add(
    'Signal decision',
    result.signal_decision?.decision ? words(result.signal_decision.decision) : null,
  )
  add('Decision', result.signal_decision?.signal_decision_id)
  add('Request status', result.request?.status ? words(result.request.status) : null)
  add('Request', result.request?.request_id)
  add('Message recorded', result.message?.message_id)
  add(
    'Result',
    result.action?.result?.summary
      || result.signal_decision?.summary
      || result.customer_update?.summary
      || null,
  )

  const revision = runtimeExecution.resulting_revision
    ?? result.revision
    ?? result.claim_revision
    ?? null
  add('Claim revision', revision)

  if (!details.length) {
    details.push('The registered handler returned a persisted result with no additional staff-facing fields.')
  }

  return {
    outcome: words(runtimeExecution.outcome || execution?.outcome || 'executed'),
    details,
  }
}

function draftExecutionError(error) {
  const reference = error?.requestId ? ` Reference: ${error.requestId}` : ''
  if (
    error?.code === 'NETWORK_ERROR'
    || error?.code === 'DRAFT_EXECUTION_UNKNOWN'
    || error?.status === 0
    || (error?.status >= 500
      && !['DEPENDENCY_UNAVAILABLE', 'DEPENDENCY_FAILED'].includes(error?.code))
  ) {
    return {
      title: 'Execution outcome unknown',
      message: `${error?.message || 'The Workbench could not confirm the execution result.'} Retry this same saved draft to reconcile the authoritative result before preparing another action.${reference}`,
    }
  }
  if (error?.code === 'REVISION_CONFLICT') {
    return {
      title: 'Action not executed',
      message: `The Claim changed before execution. Reload the latest Claim and review the draft again.${reference}`,
    }
  }
  if (error?.code === 'ACCESS_DENIED') {
    return {
      title: 'Action not executed',
      message: `This staff identity is not authorised to execute the proposed action.${reference}`,
    }
  }
  if (error?.code === 'IDEMPOTENCY_CONFLICT') {
    return {
      title: 'Action not executed',
      message: `This draft no longer matches the original execution identity and was not run again.${reference}`,
    }
  }
  if (error?.code === 'DEPENDENCY_UNAVAILABLE' || error?.code === 'DEPENDENCY_FAILED') {
    return {
      title: 'Action not executed',
      message: `A required service is unavailable, so the action was not reported as completed.${reference}`,
    }
  }
  if (error?.code === 'CONFIRMATION_REQUIRED') {
    return {
      title: 'Action not executed',
      message: `The backend did not receive valid explicit confirmation, so nothing was executed.${reference}`,
    }
  }
  return {
    title: 'Action not executed',
    message: `${error?.message || 'The registered action could not be executed.'}${reference}`,
  }
}

function scopeLabel(selectedClaimIds, claims) {
  if (!selectedClaimIds.length) return 'General question, no Claim attached'
  const references = selectedClaimIds.map((claimId) => claims.find((claim) => claim.claim_id === claimId)?.display_reference || claimId)
  const count = `${selectedClaimIds.length} Claim${selectedClaimIds.length > 1 ? 's' : ''} attached`
  return `${count} · ${references.join(', ')}`
}

function scopeStatus(selectedCount) {
  if (!selectedCount) return 'No Claims attached. This stays a general question.'
  return `${selectedCount} Claim${selectedCount > 1 ? 's' : ''} attached. Changes apply immediately.`
}

function compactScopeLabel(selectedClaimIds, claims) {
  if (selectedClaimIds.length > 1) return `${selectedClaimIds.length} Claims selected`
  const claimId = selectedClaimIds[0]
  const reference = claims.find((claim) => claim.claim_id === claimId)?.display_reference || claimId
  return `Claim ${reference}`
}

function staffAgentDraftKey(sessionId) {
  return sessionId || 'new-session'
}

function sessionLabel(session) {
  if (session.title !== NEW_SESSION_TITLE || !session.created_at) return session.title
  return `Created ${formatDateTime(session.created_at)}`
}

function agentError(error, operation, { hasAlternativeModel = false } = {}) {
  const requestId = error?.requestId || null
  if (operation === 'send' && error?.code === 'DEPENDENCY_FAILED') {
    const nextStep = hasAlternativeModel
      ? 'Try again later, or choose another model and start a new session.'
      : 'Try again later, or ask the runtime administrator to check the selected model.'
    return {
      title: 'The model could not complete this request',
      message: `Your draft is preserved and no Claim data changed. Claim Scope was not the cause. ${nextStep}`,
      requestId,
    }
  }
  if (operation === 'send' && error?.code === 'DEPENDENCY_UNAVAILABLE') {
    return {
      title: 'Staff Agent is temporarily unavailable',
      message: 'No Staff Agent message was saved, and your Claim data is unchanged. Your draft is still here. Try again after the model service is available.',
      requestId,
    }
  }
  if (operation === 'send' && (error?.status === 0 || error?.code === 'NETWORK_ERROR')) {
    return {
      title: 'The result could not be confirmed',
      message: 'Your draft is still here. Reopen this session to check whether a response was saved before sending it again.',
      requestId,
    }
  }
  if (operation === 'create') {
    return {
      title: 'New session was not created',
      message: `${error?.message || 'The Staff Agent session request failed.'} Choose a published model and try sending again.`,
      requestId,
    }
  }
  if (operation === 'load') {
    return {
      title: 'Staff Agent could not load',
      message: `${error?.message || 'The Staff Agent session could not be loaded.'} Close and reopen the panel to try again.`,
      requestId,
    }
  }
  return {
    title: 'Message not sent',
    message: `${error?.message || 'The Staff Agent request failed.'} Your draft is still here. Review the message and attached Claim Scope, then try again.`,
    requestId,
  }
}
