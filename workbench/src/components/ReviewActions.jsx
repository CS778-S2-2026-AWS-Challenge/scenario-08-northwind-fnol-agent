import { CheckCircle2, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { formatDateTime, words } from '../format.js'
import {
  ProjectedActionInput,
  ProjectedActionState,
} from './ProjectedAction.jsx'
import { canSubmitProjectedAction, findProjectedAction, isProjectedInputRequired } from '../projected-action.js'
import { translate as t } from '../i18n.js'
import ResourceEmptyState, { ResourcePageHeader } from './ResourceEmptyState.jsx'

export function HandoffResolution({
  handoff,
  allowedAction,
  onResolve,
  eyebrow = 'Accepted handoff',
  title = 'Continue and resolve staff assistance',
  actionLabel = 'Record resolution',
  submitLabel = 'Resolve handoff',
  compact = false,
  inline = false,
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (!handoff || !['accepted', 'in_progress'].includes(handoff.status)) return null
  const executable = canSubmitProjectedAction(allowedAction)

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

  const controls = (
    <>
      <ProjectedActionState action={allowedAction} absentMessage={t('No handoff-resolution action is projected for this handoff.')} />
      {!open && executable && <button className={`button ${inline ? 'button--quiet' : 'button--secondary'}`} type="button" onClick={() => setOpen(true)}>{t(actionLabel)}</button>}
      {open && executable && (
        <form className="action-form" onSubmit={submit}>
          {allowedAction.inputs.map((input) => <ProjectedActionInput input={input} key={input.field_code} />)}
          <p>{allowedAction.confirmation?.message}</p>
          <div className="form-actions"><button className="button button--ghost" type="button" onClick={() => setOpen(false)}>{t('Cancel')}</button><button className={compact ? 'button button--secondary' : 'button button--primary'} type="submit" disabled={busy}>{busy ? t('Recording...') : t(submitLabel)}</button></div>
          {error && <p className="form-error" role="alert">{error}</p>}
        </form>
      )}
    </>
  )

  if (inline) return <div className="handoff-resolution-inline">{controls}</div>

  return (
    <section className={`action-panel${compact ? ' action-panel--compact' : ''}`} aria-labelledby="handoff-resolution-title">
      <div className="action-panel__heading">
        <div><p className="eyebrow">{t(eyebrow)}</p><h2 id="handoff-resolution-title">{t(title)}</h2></div>
        {allowedAction && <span className="assigned-chip">{allowedAction.label}</span>}
      </div>
      <p>{handoff.requested_action}</p>
      {!compact && <HandoffContext handoff={handoff} />}
      {controls}
    </section>
  )
}

export function SignalReviews({ signals, allowedActions = [], onDecision }) {
  return (
    <section className="resource-view" aria-labelledby="signals-title">
      <ResourcePageHeader
        title="Signals"
        subtitle="Source-linked review signals for professional assessment."
        countLabel={t('{count} records', { count: signals.length })}
        titleId="signals-title"
      />
      {signals.length ? (
        <div className="record-list">
          {signals.map((signal, index) => <SignalRecord key={signal.signal_id || signal.code || index} signal={signal} allowedAction={findProjectedAction(allowedActions, 'signal.record_decision', signal.signal_id || signal.code)} onDecision={onDecision} />)}
        </div>
      ) : (
        <ResourceEmptyState
          icon={ShieldCheck}
          title="No review signals"
          description="Source-linked signals will appear here when professional review is required."
        />
      )}
    </section>
  )
}

function SignalRecord({ signal, allowedAction, onDecision }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const signalId = signal.signal_id || signal.code
  const decisions = signal.decisions || []
  const latest = decisions.at(-1)
  const executable = canSubmitProjectedAction(allowedAction)

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
      <summary><span><strong>{words(signal.label || signal.code || signalId)}</strong><small>{signalId}</small></span><span className="record-status record-status--attention">{latest ? words(latest.decision) : t('Needs decision')}</span></summary>
      <div className="record-body">
        <p className="record-summary">{signal.summary || signal.reason || t('Review the source-linked signal before recording a decision.')}</p>
        {latest && <p className="decision-history"><CheckCircle2 size={16} /><span><strong>{words(latest.decision)}</strong>{latest.summary} · {formatDateTime(latest.created_at)}</span></p>}
        {executable ? <form className="action-form" onSubmit={submit}>
          {allowedAction.inputs.map((input) => <ProjectedActionInput input={input} key={input.field_code} />)}
          <p>{allowedAction.confirmation?.message}</p>
          <div className="form-actions"><span>{t('This decision is internal and source-linked.')}</span><button className="button button--primary" type="submit" disabled={busy}>{busy ? t('Recording...') : t('Record decision')}</button></div>
          {error && <p className="form-error" role="alert">{error}</p>}
        </form> : <ProjectedActionState action={allowedAction} absentMessage={t('No signal-decision action is projected for this signal.')} />}
      </div>
    </details>
  )
}

export function StaffActions({ actions, hasMore = false, allowedActions = [], onUpdate }) {
  return (
    <section className="action-ledger activity-section" aria-labelledby="staff-actions-title">
      <header className="content-header activity-section__header">
        <p className="eyebrow">{t('Audited work')}</p>
        <h2 id="staff-actions-title">{t('Staff actions')}</h2>
        <span className="activity-section__count">{t('{count} {noun}', { count: `${actions.length}${hasMore ? '+' : ''}`, noun: t(actions.length === 1 && !hasMore ? 'record' : 'records') })}</span>
      </header>
      {actions.length ? (
        <div className="record-list staff-action-list">
          {actions.map((action) => <StaffActionRecord key={action.action_id} action={action} allowedAction={findProjectedAction(allowedActions, 'work_item.update', action.action_id)} onUpdate={onUpdate} />)}
        </div>
      ) : (
        <div className="activity-empty activity-empty--compact">
          <span className="activity-empty__marker" aria-hidden="true" />
          <div>
            <strong>{t('No staff actions yet')}</strong>
            <p>{t('Audited work items will appear here after they are recorded.')}</p>
          </div>
        </div>
      )}
    </section>
  )
}

function StaffActionRecord({ action, allowedAction, onUpdate }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [selectedStatus, setSelectedStatus] = useState(() => (
    allowedAction?.inputs.find((input) => input.field_code === 'status')?.choices?.[0]?.value || ''
  ))
  const final = ['completed', 'cancelled'].includes(action.status)
  const executable = canSubmitProjectedAction(allowedAction)

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
        <dl><dt>{t('Assigned to')}</dt><dd>{action.assigned_to}</dd><dt>{t('Sources')}</dt><dd>{action.source_refs?.join(', ') || t('None recorded')}</dd><dt>{t('Created')}</dt><dd>{formatDateTime(action.created_at)}</dd>{action.result && <><dt>{t('Outcome')}</dt><dd>{words(action.result.outcome)}</dd><dt>{t('Result')}</dt><dd>{action.result.summary}</dd></>}</dl>
        {!final && executable && <form className="action-form" onSubmit={update}>{allowedAction.inputs.map((input) => <ProjectedActionInput input={input} key={input.field_code} required={isProjectedInputRequired(input, { status: selectedStatus })} onChange={input.field_code === 'status' ? (event) => setSelectedStatus(event.target.value) : undefined} />)}<p>{allowedAction.confirmation?.message}</p><div className="form-actions"><span>{t('Completion writes the registered audited result.')}</span><button className="button button--primary" type="submit" disabled={busy}>{busy ? t('Recording...') : t('Update action')}</button></div>{error && <p className="form-error" role="alert">{error}</p>}</form>}
        {!final && !executable && <ProjectedActionState action={allowedAction} absentMessage={t('No work-item update action is projected for this exact record.')} />}
      </div>
    </details>
  )
}

function HandoffContext({ handoff }) {
  const packet = handoff.packet || {}
  return (
    <details className="handoff-context">
      <summary>{t('Review handoff context')}</summary>
      <dl>
        <dt>{t('Reason')}</dt><dd>{handoff.reason}</dd>
        <dt>{t('Priority')}</dt><dd>{words(handoff.priority)}</dd>
        <dt>{t('Incident')}</dt><dd>{packet.incident_summary || t('No incident summary recorded')}</dd>
        <dt>{t('Missing items')}</dt><dd>{packet.missing_items?.join(', ') || t('None recorded')}</dd>
        <dt>{t('Pending items')}</dt><dd>{packet.pending_items?.join(', ') || t('None recorded')}</dd>
        <dt>{t('Conflicts')}</dt><dd>{packet.conflicts?.join(', ') || t('None recorded')}</dd>
        <dt>{t('Promised next step')}</dt><dd>{packet.promised_next_step}</dd>
      </dl>
      {(packet.conflicts?.length || packet.low_confidence_items?.length) ? <p className="attention-note"><ShieldAlert size={16} />{t('Review uncertainty before resolving this handoff.')}</p> : null}
    </details>
  )
}
