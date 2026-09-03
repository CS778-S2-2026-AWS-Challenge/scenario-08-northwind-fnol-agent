import { CheckCircle2, ClipboardCheck, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { formatDateTime, words } from '../format.js'

export function HandoffResolution({ handoff, profile, onResolve }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (!handoff || !['accepted', 'in_progress'].includes(handoff.status)) return null
  const assignedToCurrentStaff = !handoff.assigned_to || handoff.assigned_to === profile?.staff_id

  async function submit(event) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setBusy(true)
    setError('')
    try {
      await onResolve(handoff, {
        result: {
          outcome: String(data.get('outcome')).trim(),
          summary: String(data.get('internal_summary')).trim(),
          reason_codes: [String(data.get('reason_code')).trim()],
          source_refs: handoff.packet?.source_refs || [],
        },
        state_changes: [],
        customer_update: {
          summary: String(data.get('customer_update')).trim(),
          responsible_party: data.get('responsible_party'),
          related_refs: [handoff.handoff_id],
        },
      })
      setOpen(false)
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="action-panel" aria-labelledby="handoff-resolution-title">
      <div className="action-panel__heading">
        <div><p className="eyebrow">Accepted handoff</p><h2 id="handoff-resolution-title">Continue and resolve staff assistance</h2></div>
        <span className="assigned-chip">Assigned to {handoff.assigned_to === profile?.staff_id ? 'you' : handoff.assigned_to}</span>
      </div>
      <p>{handoff.requested_action}</p>
      <HandoffContext handoff={handoff} />
      {assignedToCurrentStaff && !open && <button className="button button--secondary" type="button" onClick={() => setOpen(true)}>Record resolution</button>}
      {open && (
        <form className="action-form" onSubmit={submit}>
          <label>Outcome code<input name="outcome" defaultValue="support_completed" required /></label>
          <label>Reason code<input name="reason_code" defaultValue="STAFF_SUPPORT_COMPLETED" required /></label>
          <label>Internal result summary<textarea name="internal_summary" rows="3" required /></label>
          <label>Claimant update<textarea name="customer_update" rows="3" required /></label>
          <label>Who acts next<select name="responsible_party" defaultValue="claimant"><option value="claimant">Claimant</option><option value="claims_professional">Claims professional</option><option value="external_party">External party</option></select></label>
          <div className="form-actions"><button className="button button--ghost" type="button" onClick={() => setOpen(false)}>Cancel</button><button className="button button--primary" type="submit" disabled={busy}>{busy ? 'Recording...' : 'Resolve handoff'}</button></div>
          {error && <p className="form-error" role="alert">{error}</p>}
        </form>
      )}
    </section>
  )
}

export function SignalReviews({ signals, onDecision }) {
  return (
    <section className="resource-view">
      <header className="content-header"><div><p className="eyebrow">Internal review only</p><h2>Signals</h2></div><span>{signals.length} records</span></header>
      <div className="record-list">
        {signals.length ? signals.map((signal, index) => <SignalRecord key={signal.signal_id || signal.code || index} signal={signal} onDecision={onDecision} />) : <p className="empty-note">No review signals are recorded for this Claim.</p>}
      </div>
    </section>
  )
}

function SignalRecord({ signal, onDecision }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const signalId = signal.signal_id || signal.code
  const decisions = signal.decisions || []
  const latest = decisions.at(-1)

  async function submit(event) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setBusy(true)
    setError('')
    try {
      await onDecision(signalId, {
        decision: data.get('decision'),
        reason_codes: [String(data.get('reason_code')).trim()],
        summary: String(data.get('summary')).trim(),
        evidence_refs: String(data.get('evidence_refs') || '').split(',').map((value) => value.trim()).filter(Boolean),
      })
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <details className="record-row">
      <summary><span><strong>{words(signal.label || signal.code || signalId)}</strong><small>{signalId}</small></span><span className="record-status record-status--attention">{latest ? words(latest.decision) : 'Needs decision'}</span></summary>
      <div className="record-body">
        <p className="record-summary">{signal.summary || signal.reason || 'Review the source-linked signal before recording a decision.'}</p>
        {latest && <p className="decision-history"><CheckCircle2 size={16} /><span><strong>{words(latest.decision)}</strong>{latest.summary} · {formatDateTime(latest.created_at)}</span></p>}
        <form className="action-form" onSubmit={submit}>
          <label>Decision<select name="decision" defaultValue="dismissed"><option value="confirmed">Confirm for review</option><option value="dismissed">Dismiss signal</option><option value="overridden">Override signal</option><option value="resolved">Resolve signal</option></select></label>
          <label>Reason code<input name="reason_code" placeholder="SOURCE_RECORD_REVIEWED" required /></label>
          <label>Decision summary<textarea name="summary" rows="2" required /></label>
          <label>Evidence references<input name="evidence_refs" placeholder="Comma-separated evidence IDs" /></label>
          <div className="form-actions"><span>This decision is internal and source-linked.</span><button className="button button--primary" type="submit" disabled={busy}>{busy ? 'Recording...' : 'Record decision'}</button></div>
          {error && <p className="form-error" role="alert">{error}</p>}
        </form>
      </div>
    </details>
  )
}

export function StaffActions({ actions, onCreate, onUpdate }) {
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  async function create(event) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    setCreating(true)
    setError('')
    try {
      await onCreate({
        action_type: String(data.get('action_type')).trim(),
        requested_outcome: String(data.get('requested_outcome')).trim(),
        source_refs: String(data.get('source_refs') || '').split(',').map((value) => value.trim()).filter(Boolean),
      })
      form.reset()
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setCreating(false)
    }
  }

  return (
    <section className="action-ledger" aria-labelledby="staff-actions-title">
      <header className="content-header"><div><p className="eyebrow">Audited work</p><h2 id="staff-actions-title">Staff actions</h2></div><span>{actions.length} records</span></header>
      <form className="action-form action-form--create" onSubmit={create}>
        <div className="section-heading"><div><p className="eyebrow">New action</p><h3>Record a bounded task</h3></div><ClipboardCheck size={19} /></div>
        <label>Action type<input name="action_type" placeholder="coverage_review" required /></label>
        <label>Requested outcome<textarea name="requested_outcome" rows="2" required /></label>
        <label>Source references<input name="source_refs" placeholder="Comma-separated source IDs" /></label>
        <div className="form-actions"><span>Creating this record does not complete or change Claim state.</span><button className="button button--primary" type="submit" disabled={creating}>{creating ? 'Creating...' : 'Create action'}</button></div>
        {error && <p className="form-error" role="alert">{error}</p>}
      </form>
      <div className="record-list">
        {actions.length ? actions.map((action) => <StaffActionRecord key={action.action_id} action={action} onUpdate={onUpdate} />) : <p className="empty-note">No staff actions have been recorded.</p>}
      </div>
    </section>
  )
}

function StaffActionRecord({ action, onUpdate }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const final = ['completed', 'cancelled'].includes(action.status)

  async function update(event) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const status = data.get('status')
    const completing = status === 'completed'
    setBusy(true)
    setError('')
    try {
      await onUpdate(action.action_id, {
        status,
        result: completing ? {
          outcome: String(data.get('outcome')).trim(),
          summary: String(data.get('summary')).trim(),
          reason_codes: [String(data.get('reason_code')).trim()],
          source_refs: action.source_refs || [],
        } : null,
        state_changes: [],
        customer_update: null,
      })
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <details className="record-row">
      <summary><span><strong>{words(action.action_type)}</strong><small>{action.requested_outcome}</small></span><span className={`record-status record-status--${action.status}`}>{words(action.status)}</span></summary>
      <div className="record-body">
        <dl><dt>Assigned to</dt><dd>{action.assigned_to}</dd><dt>Sources</dt><dd>{action.source_refs?.join(', ') || 'None recorded'}</dd><dt>Created</dt><dd>{formatDateTime(action.created_at)}</dd>{action.result && <><dt>Outcome</dt><dd>{words(action.result.outcome)}</dd><dt>Result</dt><dd>{action.result.summary}</dd></>}</dl>
        {!final && <form className="action-form" onSubmit={update}><label>Status<select name="status" defaultValue="in_progress"><option value="in_progress">In progress</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></select></label><label>Outcome code<input name="outcome" defaultValue="review_completed" /></label><label>Reason code<input name="reason_code" defaultValue="STAFF_REVIEW_COMPLETED" /></label><label>Result summary<textarea name="summary" rows="2" /></label><div className="form-actions"><span>Completion writes an audited result. It does not send a claimant update.</span><button className="button button--primary" type="submit" disabled={busy}>{busy ? 'Recording...' : 'Update action'}</button></div>{error && <p className="form-error" role="alert">{error}</p>}</form>}
      </div>
    </details>
  )
}

function HandoffContext({ handoff }) {
  const packet = handoff.packet || {}
  return (
    <details className="handoff-context">
      <summary>Review handoff context</summary>
      <dl>
        <dt>Reason</dt><dd>{handoff.reason}</dd>
        <dt>Priority</dt><dd>{words(handoff.priority)}</dd>
        <dt>Incident</dt><dd>{packet.incident_summary || 'No incident summary recorded'}</dd>
        <dt>Missing items</dt><dd>{packet.missing_items?.join(', ') || 'None recorded'}</dd>
        <dt>Pending items</dt><dd>{packet.pending_items?.join(', ') || 'None recorded'}</dd>
        <dt>Conflicts</dt><dd>{packet.conflicts?.join(', ') || 'None recorded'}</dd>
        <dt>Promised next step</dt><dd>{packet.promised_next_step}</dd>
      </dl>
      {(packet.conflicts?.length || packet.low_confidence_items?.length) ? <p className="attention-note"><ShieldAlert size={16} />Review uncertainty before resolving this handoff.</p> : null}
    </details>
  )
}
