import {
  Bot,
  Check,
  ChevronDown,
  Clipboard,
  GripHorizontal,
  MessageSquarePlus,
  Send,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { workbenchApi } from '../api.js'

const MAX_CLAIM_SCOPE = 5

export default function StaffAgent({
  open,
  onOpenChange,
  requestedSessionId,
  token,
  onSessionChange,
  onConversationChanged,
}) {
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [claims, setClaims] = useState([])
  const [selectedClaimIds, setSelectedClaimIds] = useState([])
  const [scopeOpen, setScopeOpen] = useState(false)
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [position, setPosition] = useState(null)
  const panelRef = useRef(null)
  const dragRef = useRef(null)

  const loadMessages = useCallback(async (sessionId) => {
    if (!sessionId) {
      setMessages([])
      return
    }
    const response = await workbenchApi.staffAgentMessages(token, sessionId)
    setMessages(response.items || [])
  }, [token])

  const selectSession = useCallback(async (sessionId) => {
    setActiveSessionId(sessionId)
    onSessionChange(sessionId)
    setSelectedClaimIds([])
    await loadMessages(sessionId)
  }, [loadMessages, onSessionChange])

  const loadAgent = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [sessionResponse, claimResponse] = await Promise.all([
        workbenchApi.staffAgentSessions(token),
        workbenchApi.claims(token, { limit: 100 }),
      ])
      const nextSessions = sessionResponse.items || []
      setSessions(nextSessions)
      setClaims(claimResponse.items || [])
      const nextSessionId = requestedSessionId || nextSessions[0]?.session_id || null
      if (nextSessionId) await selectSession(nextSessionId)
    } catch (nextError) {
      setError(agentError(nextError))
    } finally {
      setLoading(false)
    }
  }, [requestedSessionId, selectSession, token])

  useEffect(() => {
    if (!open) return undefined
    const task = window.setTimeout(loadAgent, 0)
    return () => window.clearTimeout(task)
  }, [open, loadAgent])

  async function createSession() {
    setLoading(true)
    setError('')
    try {
      const session = await workbenchApi.createStaffAgentSession(token)
      setSessions((current) => [session, ...current])
      await selectSession(session.session_id)
      onConversationChanged()
    } catch (nextError) {
      setError(agentError(nextError))
    } finally {
      setLoading(false)
    }
  }

  async function submit(event) {
    event.preventDefault()
    const content = message.trim()
    if (!content || sending) return
    setSending(true)
    setError('')
    try {
      let sessionId = activeSessionId
      if (!sessionId) {
        const session = await workbenchApi.createStaffAgentSession(token)
        setSessions((current) => [session, ...current])
        sessionId = session.session_id
        setActiveSessionId(sessionId)
        onSessionChange(sessionId)
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
      setError(agentError(nextError))
    } finally {
      setSending(false)
    }
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
        <section className="staff-agent__panel" aria-label="Staff Agent" ref={panelRef}>
          <header onPointerDown={beginDrag} onPointerMove={drag} onPointerUp={endDrag}>
            <span className="staff-agent__grip" aria-hidden="true"><GripHorizontal size={18} /></span>
            <div><strong>Staff Agent</strong><small>Private Workbench assistance</small></div>
            <button className="icon-button" type="button" onClick={() => onOpenChange(false)} aria-label="Close Staff Agent"><X size={16} /></button>
          </header>

          <div className="agent-session-bar">
            <label>
              <span>Session</span>
              <select value={activeSessionId || ''} onChange={(event) => selectSession(event.target.value)} disabled={loading || !sessions.length}>
                {!sessions.length && <option value="">No saved session</option>}
                {sessions.map((session) => <option value={session.session_id} key={session.session_id}>{session.title}</option>)}
              </select>
            </label>
            <button className="icon-button" type="button" onClick={createSession} disabled={loading} aria-label="Start a new Staff Agent session"><MessageSquarePlus size={17} /></button>
          </div>

          <div className="agent-scope">
            <button type="button" className="agent-scope__toggle" aria-expanded={scopeOpen} aria-controls="staff-agent-claim-scope" onClick={() => setScopeOpen((value) => !value)}>
              <span><strong>Claim scope</strong><small>{scopeLabel(selectedClaimIds, claims)}</small></span>
              <ChevronDown size={15} />
            </button>
            {scopeOpen && (
              <fieldset id="staff-agent-claim-scope" className="agent-scope__options">
                <legend>Select up to five Claims for the next question</legend>
                {claims.map((claim) => {
                  const checked = selectedClaimIds.includes(claim.claim_id)
                  const disabled = !checked && selectedClaimIds.length >= MAX_CLAIM_SCOPE
                  return (
                    <label key={claim.claim_id}>
                      <input type="checkbox" checked={checked} disabled={disabled} onChange={() => toggleClaim(claim.claim_id)} />
                      <span className="agent-scope__check" aria-hidden="true">{checked && <Check size={12} />}</span>
                      <span><strong>{claim.display_reference}</strong><small>{claim.incident?.summary || claim.claim_id}</small></span>
                    </label>
                  )
                })}
                {!claims.length && <p>No Claims are available to attach.</p>}
              </fieldset>
            )}
          </div>

          <div className="agent-messages" aria-live="polite">
            {loading && <p className="agent-state">Loading Staff Agent sessions...</p>}
            {!loading && !messages.length && (
              <div className="agent-empty"><Bot size={22} /><p>Ask a general question or explicitly attach up to five Claims.</p><small>The Agent can advise and draft, but cannot execute business actions.</small></div>
            )}
            {messages.map((item) => <AgentMessage message={item} key={item.message_id} />)}
          </div>

          {error && <p className="agent-error" role="alert">{error}</p>}
          <form className="agent-composer" onSubmit={submit}>
            <label className="sr-only" htmlFor="staff-agent-message">Message Staff Agent</label>
            <textarea id="staff-agent-message" rows="2" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Ask about selected Claims or policy" />
            <button className="icon-button" type="submit" disabled={!message.trim() || sending} aria-label="Send to Staff Agent"><Send size={16} /></button>
          </form>
        </section>
      )}
    </div>
  )
}

function AgentMessage({ message }) {
  return (
    <article className={`agent-message agent-message--${message.role}`}>
      <header><strong>{message.role === 'assistant' ? 'Staff Agent' : 'You'}</strong><small>{message.claim_ids?.length ? `${message.claim_ids.length} Claim${message.claim_ids.length > 1 ? 's' : ''} attached` : 'General scope'}</small></header>
      <p>{message.content}</p>
      {message.drafts?.map((draft, index) => <AgentDraft draft={draft} key={`${message.message_id}-draft-${index}`} />)}
      {!!message.source_refs?.length && <details><summary>Sources used</summary><ul>{message.source_refs.map((source) => <li key={source}>{source}</li>)}</ul></details>}
    </article>
  )
}

function AgentDraft({ draft }) {
  const [content, setContent] = useState(draft.content)
  return (
    <section className="agent-draft">
      <header><span><strong>{draft.title}</strong><small>{draft.kind.replaceAll('_', ' ')}</small></span><button type="button" className="icon-button icon-button--small" onClick={() => navigator.clipboard.writeText(content)} aria-label={`Copy ${draft.title}`}><Clipboard size={14} /></button></header>
      <textarea value={content} onChange={(event) => setContent(event.target.value)} aria-label={`Edit ${draft.title}`} />
      {draft.claim_id && <small>Draft for {draft.claim_id}</small>}
    </section>
  )
}

function scopeLabel(selectedClaimIds, claims) {
  if (!selectedClaimIds.length) return 'General question, no Claim attached'
  const references = selectedClaimIds.map((claimId) => claims.find((claim) => claim.claim_id === claimId)?.display_reference || claimId)
  return references.join(', ')
}

function agentError(error) {
  if (error?.code === 'DEPENDENCY_UNAVAILABLE') {
    return 'Staff Agent is unavailable because its model profile is not configured. Keep your draft and try again after the runtime is connected.'
  }
  return `${error?.message || 'The Staff Agent request failed.'} Review the selected Claim scope and try again.`
}
