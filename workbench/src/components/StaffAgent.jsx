import {
  AlertCircle,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  Clipboard,
  GripHorizontal,
  MessageSquarePlus,
  Send,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { workbenchApi } from '../api.js'
import { formatDateTime } from '../format.js'

const MAX_CLAIM_SCOPE = 5
const NEW_SESSION_TITLE = 'New Staff Agent session'

export default function StaffAgent({
  open,
  onOpenChange,
  requestedSessionId,
  token,
  onSessionChange,
  onConversationChanged,
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
  const [creatingSession, setCreatingSession] = useState(false)
  const [sending, setSending] = useState(false)
  const [sessionNotice, setSessionNotice] = useState('')
  const [error, setError] = useState(null)
  const [position, setPosition] = useState(null)
  const panelRef = useRef(null)
  const messageRef = useRef(null)
  const dragRef = useRef(null)
  const activeSessionIdRef = useRef(null)
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
    setSessionNotice('')
    setError(null)
    activeSessionIdRef.current = sessionId
    setActiveSessionId(sessionId)
    onSessionChangeRef.current(sessionId)
    setSelectedClaimIds([])
    await loadMessages(sessionId)
  }, [loadMessages])

  const loadAgent = useCallback(async () => {
    setLoading(true)
    setSessionNotice('')
    setError(null)
    try {
      const [sessionResponse, claimResponse, capabilityResponse] = await Promise.all([
        workbenchApi.staffAgentSessions(token),
        workbenchApi.claims(token, { limit: 100 }),
        workbenchApi.staffAgentCapabilities(token),
      ])
      const nextSessions = sessionResponse.items || []
      setSessions(nextSessions)
      setClaims(claimResponse.items || [])
      const nextModels = capabilityResponse.models || []
      setModels(nextModels)
      if (capabilityResponse.default_model_profile_id) setNewSessionModel(capabilityResponse.default_model_profile_id)
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

  async function createSession() {
    setCreatingSession(true)
    setSessionNotice('')
    setError(null)
    let sessionCreated = false
    try {
      const session = await workbenchApi.createStaffAgentSession(token, NEW_SESSION_TITLE, newSessionModel)
      sessionCreated = true
      setSessions((current) => [session, ...current.filter((item) => item.session_id !== session.session_id)])
      await selectSession(session.session_id)
      setSessionNotice(message.trim() ? 'Your draft is still here and ready to send.' : 'Ask a general question or attach Claim context to begin.')
      messageRef.current?.focus()
      onConversationChanged()
    } catch (nextError) {
      setError(agentError(nextError, sessionCreated ? 'load' : 'create'))
    } finally {
      setCreatingSession(false)
    }
  }

  async function submit(event) {
    event.preventDefault()
    const content = message.trim()
    if (!content || loading || creatingSession || sending) return
    setSending(true)
    setSessionNotice('')
    setError(null)
    try {
      let sessionId = activeSessionId
      if (!sessionId) {
        const session = await workbenchApi.createStaffAgentSession(token, NEW_SESSION_TITLE, newSessionModel)
        setSessions((current) => [session, ...current])
        sessionId = session.session_id
        activeSessionIdRef.current = sessionId
        setActiveSessionId(sessionId)
        onSessionChangeRef.current(sessionId)
      }
      const response = await workbenchApi.sendStaffAgentMessage(
        token,
        sessionId,
        content,
        selectedClaimIds,
      )
      setMessage('')
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
      setError(agentError(nextError, 'send', { hasAlternativeModel: models.length > 1 }))
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
    const response = await workbenchApi.executeStaffAgentDraft(
      token,
      sourceMessage.session_id,
      sourceMessage.message_id,
      draft.draft_id,
      latestClaim.revision,
      draft.payload || {},
    )

    await onBusinessActionExecuted?.(response)
    return response
  }

  function toggleClaim(claimId) {
    setSelectedClaimIds((current) => {
      if (current.includes(claimId)) return current.filter((item) => item !== claimId)
      if (current.length >= MAX_CLAIM_SCOPE) return current
      return [...current, claimId]
    })
  }

  function beginDrag(event) {
    if (event.target.closest('button, select, input, textarea')) return
    const panel = panelRef.current
    if (!panel) return
    const rect = panel.getBoundingClientRect()
    dragRef.current = { offsetX: event.clientX - rect.left, offsetY: event.clientY - rect.top }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function drag(event) {
    if (!dragRef.current || !panelRef.current) return
    const width = panelRef.current.offsetWidth
    const height = panelRef.current.offsetHeight
    setPosition({
      left: Math.max(0, Math.min(window.innerWidth - width, event.clientX - dragRef.current.offsetX)),
      top: Math.max(0, Math.min(window.innerHeight - height, event.clientY - dragRef.current.offsetY)),
    })
  }

  function endDrag(event) {
    dragRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  return (
    <div className={`staff-agent${open ? ' is-open' : ''}`} style={position ? { left: position.left, top: position.top, right: 'auto', bottom: 'auto' } : undefined}>
      {!open && (
        <button className="staff-agent__bubble" type="button" onClick={() => onOpenChange(true)} aria-label="Open Staff Agent">
          <Bot size={23} />
        </button>
      )}
      {open && (
        <section className="staff-agent__panel" aria-labelledby="staff-agent-title" ref={panelRef}>
          <header className="staff-agent__header" onPointerDown={beginDrag} onPointerMove={drag} onPointerUp={endDrag}>
            <span className="staff-agent__grip" aria-hidden="true"><GripHorizontal size={18} /></span>
            <div className="staff-agent__identity">
              <h2 id="staff-agent-title">Staff Agent</h2>
              <small>Private Workbench assistance</small>
            </div>
            <button className="icon-button" type="button" onClick={() => onOpenChange(false)} aria-label="Close Staff Agent"><X size={16} /></button>
          </header>

          <div className="agent-context">
            <div className="agent-session-bar">
              <label>
                <span>Session</span>
                <select value={activeSessionId || ''} onChange={(event) => selectSession(event.target.value)} disabled={loading || creatingSession || sending || !sessions.length}>
                  {!sessions.length && <option value="">No saved session</option>}
                  {sessions.map((session) => <option value={session.session_id} key={session.session_id}>{sessionLabel(session)}</option>)}
                </select>
              </label>
              <label>
                <span>New session model</span>
                <select value={newSessionModel} onChange={(event) => setNewSessionModel(event.target.value)} disabled={loading || creatingSession || sending || !models.length}>
                  {!models.length && <option value="">No published model</option>}
                  {models.map((model) => <option value={model.id} key={model.id}>{model.label}</option>)}
                </select>
              </label>
              <button className="agent-session-bar__new" type="button" onClick={createSession} disabled={loading || creatingSession || sending} aria-busy={creatingSession} aria-label="Start a new Staff Agent session">
                <MessageSquarePlus size={16} />
                <span>{creatingSession ? 'Starting...' : 'New'}</span>
              </button>
            </div>

            <div className="agent-scope">
              <button type="button" className="agent-scope__toggle" aria-expanded={scopeOpen} aria-controls="staff-agent-claim-scope" onClick={() => setScopeOpen((value) => !value)}>
                <span className="agent-scope__summary"><strong>Claim Scope</strong><small>{scopeLabel(selectedClaimIds, claims)}</small></span>
                <ChevronDown size={15} />
              </button>
              {scopeOpen && (
                <fieldset id="staff-agent-claim-scope" className="agent-scope__options">
                  <legend className="sr-only">Choose Claims for Staff Agent context</legend>
                  <div className="agent-scope__options-header">
                    <span>
                      <strong>Attach Claim context</strong>
                      <small>Choose one Claim for focused help, or several to compare.</small>
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
                    {!claims.length && <p>No Claims are available to attach.</p>}
                  </div>
                  <div className="agent-scope__footer">
                    <small className="agent-scope__status" aria-live="polite">{scopeStatus(selectedClaimIds.length)}</small>
                    <button className="agent-scope__done" type="button" onClick={() => setScopeOpen(false)}>Done</button>
                  </div>
                </fieldset>
              )}
            </div>
          </div>

          <div className="agent-conversation">
            <div className="agent-messages" aria-live="polite">
              {loading && <p className="agent-state">Loading Staff Agent sessions...</p>}
              {!loading && !messages.length && (
                <div className="agent-empty">
                  <span className="agent-empty__icon" aria-hidden="true"><Bot size={20} /></span>
                  <p>Ask a general question or explicitly attach up to five Claims.</p>
                  <small>The Agent can advise and draft, but cannot execute business actions.</small>
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

            {sessionNotice && (
              <div className="agent-notice" role="status">
                <CheckCircle2 size={16} aria-hidden="true" />
                <span><strong>New session ready</strong><small>{sessionNotice}</small></span>
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
                <button className="agent-feedback__dismiss" type="button" onClick={() => setError(null)} aria-label="Dismiss Staff Agent error"><X size={14} /></button>
              </div>
            )}
            <form className="agent-composer" onSubmit={submit}>
              <label className="sr-only" htmlFor="staff-agent-message">Message Staff Agent</label>
              <textarea id="staff-agent-message" ref={messageRef} rows="2" value={message} onChange={(event) => { setMessage(event.target.value); setSessionNotice('') }} placeholder="Ask about selected Claims or policy" />
              <button className="agent-composer__send" type="submit" disabled={!message.trim() || loading || creatingSession || sending} aria-busy={sending} aria-label="Send to Staff Agent">
                <Send size={15} />
                <span>{sending ? 'Sending...' : 'Send'}</span>
              </button>
            </form>
          </div>
        </section>
      )}
    </div>
  )
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
      {!!message.source_refs?.length && <details><summary>Sources used</summary><ul>{message.source_refs.map((source) => <li key={source}>{source}</li>)}</ul></details>}
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
            <strong>Registered action</strong>
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
          <p>The Agent proposed this action. The Workbench will reload the Claim, use its current revision, and let the registered backend action decide whether execution is authorised.</p>
          <div className="form-actions">
            <button className="button button--ghost" type="button" disabled={executing} onClick={() => setReviewing(false)}>Cancel</button>
            <button className="button button--primary" type="button" disabled={executing} onClick={execute}>
              {executing ? 'Executing...' : 'Confirm and execute'}
            </button>
          </div>
        </div>
      )}
      {execution && (
        <div className="agent-draft__execution" role="status">
          <CheckCircle2 size={16} aria-hidden="true" />
          <span>
            <strong>Executed by Workbench</strong>
            <small>{execution.action_code} completed at Claim revision {execution.runtime_execution?.resulting_revision ?? 'not reported'}.</small>
          </span>
        </div>
      )}
      {executionError && (
        <div className="agent-draft__execution agent-draft__execution--error" role="alert">
          <AlertCircle size={16} aria-hidden="true" />
          <span><strong>Action not executed</strong><small>{executionError}</small></span>
        </div>
      )}
      {executable && <small>The saved registered payload is executed unchanged. To change the business action, ask Staff Agent to prepare a new draft.</small>}
    </section>
  )
}

function draftExecutionError(error) {
  const reference = error?.requestId ? ` Reference: ${error.requestId}` : ''
  if (error?.code === 'REVISION_CONFLICT') return `The Claim changed before execution. The latest Claim projection was kept; review the draft again.${reference}`
  if (error?.code === 'ACCESS_DENIED') return `This staff identity is not authorised to execute the proposed action.${reference}`
  if (error?.code === 'IDEMPOTENCY_CONFLICT') return `This draft no longer matches the original execution identity and was not run again.${reference}`
  if (error?.code === 'DEPENDENCY_UNAVAILABLE' || error?.code === 'DEPENDENCY_FAILED') return `A required service is unavailable, so the action was not reported as completed.${reference}`
  if (error?.code === 'CONFIRMATION_REQUIRED') return `The backend did not receive valid explicit confirmation, so nothing was executed.${reference}`
  return `${error?.message || 'The registered action could not be executed.'}${reference}`
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
      message: `${error?.message || 'The Staff Agent session request failed.'} Choose a published model and try New again.`,
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
