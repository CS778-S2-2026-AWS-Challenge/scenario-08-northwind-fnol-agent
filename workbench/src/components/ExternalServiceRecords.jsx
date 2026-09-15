import { CircleAlert, Clock3, ExternalLink, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { formatDateTime, words } from '../format.js'
import { canSubmitProjectedAction, isProjectedInputRequired } from '../projected-action.js'
import { ActionDetails, ProjectedActionInput, ProjectedActionState } from './ProjectedAction.jsx'

export function ExternalServiceSummary({ resource }) {
  if (resource?.loading) return <SummaryState message="Loading third-party tasks..." />
  if (resource?.error) return <SummaryState message={resource.error} error />
  if (resource?.status === 'unavailable') {
    return <SummaryState message={resource.limitation || 'Third-party task records are unavailable.'} error />
  }

  const records = resource?.items || []
  return (
    <section className="detail-section" aria-labelledby="third-party-summary-title">
      <div className="section-heading">
        <div><p className="eyebrow">External services</p><h2 id="third-party-summary-title">Third-party tasks</h2></div>
        <span className="count-badge">{records.length}</span>
      </div>
      {records.length ? (
        <ul className="missing-list">
          {records.map(({ task, lifecycle }) => (
            <li key={task.task_id}>
              {lifecycle.needs_attention ? <CircleAlert size={15} /> : <Clock3 size={15} />}
              <span>
                <strong>{words(lifecycle.service)} — {lifecycle.status_label}</strong>
                <small>{lifecycle.status_detail}{lifecycle.limitation ? ` ${lifecycle.limitation}` : ''}</small>
              </span>
            </li>
          ))}
        </ul>
      ) : <p className="empty-note">No third-party task is recorded for this Claim.</p>}
    </section>
  )
}

function SummaryState({ message, error = false }) {
  return (
    <section className="detail-section" aria-labelledby="third-party-summary-title">
      <div className="section-heading"><div><p className="eyebrow">External services</p><h2 id="third-party-summary-title">Third-party tasks</h2></div></div>
      <p className={error ? 'inline-error' : 'empty-note'} role={error ? 'alert' : 'status'}>{message}</p>
    </section>
  )
}

export default function ExternalServiceRecords({
  records,
  allowedActions = [],
  claimRevision,
  onAction,
}) {
  return (
    <section className="resource-view">
      <header className="content-header">
        <div><p className="eyebrow">Connected participants</p><h2>External services</h2></div>
        <span>{records.length} requests</span>
      </header>
      <p className="section-intro">Each request keeps its purpose, disclosure scope, authority, delivery state, and recovery path together.</p>
      {records.length ? (
        <div className="record-list">
          {records.map((record) => (
            <ExternalServiceRecord
              record={record}
              actions={projectedTaskActions(allowedActions, record.task.task_id, claimRevision)}
              onAction={onAction}
              key={record.task.task_id}
            />
          ))}
        </div>
      ) : <p className="empty-note">No external-service request is recorded for this Claim.</p>}
    </section>
  )
}

function ExternalServiceRecord({ record, actions, onAction }) {
  const { task, request } = record
  const { lifecycle } = record
  const needsAttention = lifecycle.needs_attention
  return (
    <details className="record-row external-record">
      <summary>
        <span><strong>{words(lifecycle.service)}</strong><small>{words(lifecycle.request_type)} · Updated {formatDateTime(task.updated_at)}</small></span>
        <span className={`record-status record-status--${needsAttention ? 'attention' : task.status}`}>{lifecycle.status_label}</span>
      </summary>
      <div className="record-body">
        <div className="external-overview">
          <OverviewItem label="Purpose" value={request?.purpose || 'Request details have not been prepared.'} />
          <OverviewItem label="Data sharing" value={request ? `${request.disclosed_fields.length} registered fields` : 'No disclosure manifest recorded'} />
          <OverviewItem label="Authority" value={`${words(lifecycle.authority_state)} · consent ${words(lifecycle.consent_state)}`} />
          <OverviewItem label="Pending owner" value={words(lifecycle.pending_owner)} />
          <OverviewItem label="Verification" value={words(lifecycle.verification_state)} attention={needsAttention} />
          <OverviewItem label="Next step" value={lifecycle.next_action} attention={needsAttention} />
        </div>
        {lifecycle.limitation && <p className="record-note"><strong>Capability limitation</strong>{lifecycle.limitation}</p>}
        <section className="external-disclosure" aria-label="External request detail">
          <div className="section-heading"><div><p className="eyebrow">Request detail</p><h3>Disclosure and delivery</h3></div><ExternalLink size={18} /></div>
          <dl>
            <dt>Catalogue reference</dt><dd>{lifecycle.catalogue_reference || 'Not mapped'}</dd>
            <dt>Integration source</dt><dd>{words(task.integration_source)}</dd>
            <dt>Observed provenance</dt><dd>{words(lifecycle.provenance)}</dd>
            <dt>Operation status</dt><dd>{words(task.status)}</dd>
            <dt>Stakeholder</dt><dd>{words(lifecycle.stakeholder)}</dd>
            <dt>Submission</dt><dd>{words(lifecycle.delivery_state)}</dd>
            <dt>Prepared</dt><dd>{request ? formatDateTime(request.prepared_at) : 'Not recorded'}</dd>
            <dt>Sent</dt><dd>{request?.sent_at ? formatDateTime(request.sent_at) : 'Not sent'}</dd>
            <dt>Operation identity</dt><dd>{request?.operation_id || 'Not reserved'}</dd>
            <dt>Provider reference</dt><dd>{lifecycle.provider_reference || 'Not recorded'}</dd>
            <dt>Result</dt><dd>{lifecycle.result || 'No verified result recorded'}</dd>
            <dt>Result source</dt><dd>{lifecycle.result_source ? `${words(lifecycle.result_source.system)} · ${lifecycle.result_source.reference}` : 'No result source recorded'}</dd>
            <dt>Result received</dt><dd>{lifecycle.result_received_at ? formatDateTime(lifecycle.result_received_at) : 'Not recorded'}</dd>
            <dt>Result verification</dt><dd>{lifecycle.result_verification_state ? words(lifecycle.result_verification_state) : 'No result to verify'}</dd>
            <dt>Verified</dt><dd>{lifecycle.result_verified_at ? formatDateTime(lifecycle.result_verified_at) : 'Not verified'}</dd>
            <dt>Checked Claim revision</dt><dd>{lifecycle.result_verified_against_revision || 'Not checked'}</dd>
            <dt>Result evidence</dt><dd>{lifecycle.result_evidence?.length ? lifecycle.result_evidence.map((item) => `${item.evidence_id} — ${words(item.status)} / ${words(item.file_status)}`).join('; ') : 'No evidence linked'}</dd>
            <dt>Failure</dt><dd>{task.failure_code ? words(task.failure_code) : 'None recorded'}</dd>
          </dl>
        </section>
        {request && (
          <section className="external-authority" aria-label="Authority and disclosed fields">
            <div><ShieldCheck size={16} /><strong>Authority checked at Claim revision {request.authorisation.authorised_revision}</strong></div>
            <dl>
              <dt>Northwind authority</dt><dd>{request.authorisation.northwind_authority_ref}</dd>
              <dt>Claimant consent</dt><dd>{request.authorisation.claimant_consent_ref}</dd>
              <dt>Shared fields</dt><dd>{request.disclosed_fields.join(', ')}</dd>
            </dl>
          </section>
        )}
        {actions.map((action) => (
          <ExternalTaskAction
            action={action}
            onAction={onAction}
            key={`${action.action_code}:${action.target_ref}`}
          />
        ))}
        {needsAttention && <p className="attention-note"><CircleAlert size={16} />{lifecycle.next_action}</p>}
      </div>
    </details>
  )
}

function ExternalTaskAction({ action, onAction }) {
  const inputs = action.inputs || []
  const [expanded, setExpanded] = useState(false)
  const [values, setValues] = useState(() => initialValues(inputs))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const executable = canSubmitProjectedAction(action)
  const supported = ['external.accept_review', 'external.reconcile_response'].includes(action.action_code)
  const missingRequiredInput = inputs.some((input) => (
    isProjectedInputRequired(input, values) && !String(values[input.field_code] || '').trim()
  ))
  const titleId = `external-action-${action.action_code.replaceAll('.', '-')}-${action.target_ref}`

  async function submit(event) {
    event.preventDefault()
    if (!executable || !supported || missingRequiredInput || busy) return
    setBusy(true)
    setError('')
    try {
      const payload = Object.fromEntries(
        inputs.map((input) => [input.field_code, String(values[input.field_code] || '').trim()]),
      )
      await onAction(action, payload)
      setExpanded(false)
      setValues(initialValues(inputs))
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="action-panel action-panel--compact" aria-labelledby={titleId}>
      <div className="action-panel__heading">
        <div>
          <p className="eyebrow">Projected staff action</p>
          <h3 id={titleId}>{action.label}</h3>
        </div>
      </div>
      <p>{action.purpose}</p>
      <p className="record-note"><strong>Exact task</strong>{action.target_ref} · Claim revision {action.based_on_revision}</p>
      <ActionDetails action={action} />
      {!supported && (
        <p className="record-note record-note--blocked" role="status">
          <strong>Action unavailable in this Workbench build</strong>
          Refresh after the client is updated to the server-published action contract.
        </p>
      )}
      {supported && !executable && (
        <ProjectedActionState
          action={action}
          absentMessage="No external-task action is projected for this exact task."
        />
      )}
      {supported && executable && !expanded && (
        <button className="button button--secondary" type="button" onClick={() => setExpanded(true)}>
          Review {action.label}
        </button>
      )}
      {supported && executable && expanded && (
        <form className="action-form" onSubmit={submit} aria-busy={busy}>
          {inputs.map((input) => (
            <ProjectedActionInput
              key={input.field_code}
              input={input}
              value={values[input.field_code] || ''}
              required={isProjectedInputRequired(input, values)}
              onChange={(event) => setValues((current) => ({
                ...current,
                [input.field_code]: event.target.value,
              }))}
            />
          ))}
          {action.confirmation?.message && <p>{action.confirmation.message}</p>}
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="form-actions">
            <button className="button button--ghost" type="button" disabled={busy} onClick={() => setExpanded(false)}>Cancel</button>
            <button className="button button--primary" type="submit" disabled={busy || missingRequiredInput}>
              {busy ? 'Working...' : action.label}
            </button>
          </div>
        </form>
      )}
    </section>
  )
}

function projectedTaskActions(actions, taskId, revision) {
  return actions.filter((action) => (
    action.target_type === 'external_task'
    && action.target_ref === taskId
    && action.based_on_revision === revision
  ))
}

function initialValues(inputs) {
  return Object.fromEntries(
    inputs.map((input) => [input.field_code, input.choices?.[0]?.value || '']),
  )
}

function OverviewItem({ label, value, attention = false }) {
  return <div className={attention ? 'needs-attention' : ''}><span>{label}</span><strong>{value}</strong></div>
}
