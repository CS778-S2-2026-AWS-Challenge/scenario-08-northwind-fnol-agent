import { CheckCircle2, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { formatDateTime, words } from '../format.js'

export function HandoffResolution({ handoff, allowedAction, onResolve }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (!handoff || !allowedAction || !['accepted', 'in_progress'].includes(handoff.status)) return null

  async function submit(event) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setBusy(true)
    setError('')
    try {
      const payload = structuredClone(allowedAction.payload_defaults)
      payload.result.summary = String(data.get('result.summary')).trim()
      payload.customer_update.summary = String(data.get('customer_update.summary')).trim()
      await onResolve(handoff, payload)
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
        <span className="assigned-chip">{allowedAction.label}</span>
      </div>
      <p>{handoff.requested_action}</p>
      <HandoffContext handoff={handoff} />
      {!open && <button className="button button--secondary" type="button" onClick={() => setOpen(true)}>Record resolution</button>}
      {open && (
        <form className="action-form" onSubmit={submit}>
          {allowedAction.inputs.map((input) => <ActionInput input={input} key={input.field_code} />)}
          <p>{allowedAction.confirmation?.message}</p>
          <div className="form-actions"><button className="button button--ghost" type="button" onClick={() => setOpen(false)}>Cancel</button><button className="button button--primary" type="submit" disabled={busy}>{busy ? 'Recording...' : 'Resolve handoff'}</button></div>
          {error && <p className="form-error" role="alert">{error}</p>}
        </form>
      )}
    </section>
  )
}

export function SignalReviews({ signals, allowedActions = [], onDecision }) {
  return (
    <section className="resource-view">
      <header className="content-header"><div><p className="eyebrow">Internal review only</p><h2>Signals</h2></div><span>{signals.length} records</span></header>
      <div className="record-list">
        {signals.length ? signals.map((signal, index) => <SignalRecord key={signal.signal_id || signal.code || index} signal={signal} allowedAction={allowedActions.find((action) => action.action_code === 'signal.record_decision' && action.target_ref === (signal.signal_id || signal.code) && action.availability === 'confirmation_required')} onDecision={onDecision} />) : <p className="empty-note">No review signals are recorded for this Claim.</p>}
      </div>
    </section>
  )
}

function SignalRecord({ signal, allowedAction, onDecision }) {
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
        ...structuredClone(allowedAction.payload_defaults),
        decision: data.get('decision'),
        reason_codes: [String(data.get('reason_codes.0')).trim()],
        summary: String(data.get('summary')).trim(),
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
        {allowedAction ? <form className="action-form" onSubmit={submit}>
          {allowedAction.inputs.map((input) => <ActionInput input={input} key={input.field_code} />)}
          <p>{allowedAction.confirmation?.message}</p>
          <div className="form-actions"><span>This decision is internal and source-linked.</span><button className="button button--primary" type="submit" disabled={busy}>{busy ? 'Recording...' : 'Record decision'}</button></div>
          {error && <p className="form-error" role="alert">{error}</p>}
        </form> : <p className="record-note">Signal details are read-only with your current Claim access.</p>}
      </div>
    </details>
  )
}

export function StaffActions({ actions, allowedActions = [], onUpdate }) {
  return (
    <section className="action-ledger" aria-labelledby="staff-actions-title">
      <header className="content-header"><div><p className="eyebrow">Audited work</p><h2 id="staff-actions-title">Staff actions</h2></div><span>{actions.length} records</span></header>
      <div className="record-list">
        {actions.length ? actions.map((action) => <StaffActionRecord key={action.action_id} action={action} allowedAction={allowedActions.find((candidate) => candidate.action_code === 'work_item.update' && candidate.target_ref === action.action_id && candidate.availability === 'confirmation_required')} onUpdate={onUpdate} />) : <p className="empty-note">No staff actions have been recorded.</p>}
      </div>
    </section>
  )
}

function StaffActionRecord({ action, allowedAction, onUpdate }) {
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
      const payload = completing
        ? structuredClone(allowedAction.payload_defaults)
        : { result: null, state_changes: [], customer_update: null }
      payload.status = status
      if (completing) {
        payload.result.summary = String(data.get('result.summary')).trim()
        if (payload.customer_update) {
          payload.customer_update.summary = String(data.get('customer_update.summary')).trim()
        }
      }
      await onUpdate(action.action_id, payload)
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
        {!final && allowedAction && <form className="action-form" onSubmit={update}>{allowedAction.inputs.map((input) => <ActionInput input={input} key={input.field_code} />)}<p>{allowedAction.confirmation?.message}</p><div className="form-actions"><span>Completion writes the registered audited result.</span><button className="button button--primary" type="submit" disabled={busy}>{busy ? 'Recording...' : 'Update action'}</button></div>{error && <p className="form-error" role="alert">{error}</p>}</form>}
        {!final && !allowedAction && <p className="record-note">This action is read-only because no matching target action is projected for you.</p>}
      </div>
    </details>
  )
}

function ActionInput({ input }) {
  if (input.control === 'select') {
    return <label>{input.label}<select name={input.field_code} required={input.required}>{input.choices.map((choice) => <option value={choice.value} key={choice.value}>{choice.label}</option>)}</select></label>
  }
  if (input.control === 'textarea') {
    return <label>{input.label}<textarea name={input.field_code} rows="3" required={input.required} /></label>
  }
  return <label>{input.label}<input name={input.field_code} required={input.required} /></label>
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
