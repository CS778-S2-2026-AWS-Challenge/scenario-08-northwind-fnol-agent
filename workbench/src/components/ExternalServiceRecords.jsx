import { CircleAlert, Clock3, ExternalLink, ShieldCheck } from 'lucide-react'
import { formatDateTime, words } from '../format.js'

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
          {records.map(({ task, lifecycle }) => {
            return (
              <li key={task.task_id}>
                {lifecycle.needs_attention ? <CircleAlert size={15} /> : <Clock3 size={15} />}
                <span>
                  <strong>{words(lifecycle.service)} — {lifecycle.status_label}</strong>
                  <small>{lifecycle.status_detail}{lifecycle.limitation ? ` ${lifecycle.limitation}` : ''}</small>
                </span>
              </li>
            )
          })}
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

export default function ExternalServiceRecords({ records }) {
  return (
    <section className="resource-view">
      <header className="content-header">
        <div><p className="eyebrow">Connected participants</p><h2>External services</h2></div>
        <span>{records.length} requests</span>
      </header>
      <p className="section-intro">Each request keeps its purpose, disclosure scope, authority, delivery state, and recovery path together.</p>
      {records.length ? <div className="record-list">{records.map((record) => <ExternalServiceRecord record={record} key={record.task.task_id} />)}</div> : <p className="empty-note">No external-service request is recorded for this Claim.</p>}
    </section>
  )
}

function ExternalServiceRecord({ record }) {
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
            <dt>Integration source</dt><dd>{words(task.integration_source)}</dd>
            <dt>Stakeholder</dt><dd>{words(lifecycle.stakeholder)}</dd>
            <dt>Submission</dt><dd>{words(lifecycle.delivery_state)}</dd>
            <dt>Prepared</dt><dd>{request ? formatDateTime(request.prepared_at) : 'Not recorded'}</dd>
            <dt>Sent</dt><dd>{request?.sent_at ? formatDateTime(request.sent_at) : 'Not sent'}</dd>
            <dt>Operation identity</dt><dd>{request?.operation_id || 'Not reserved'}</dd>
            <dt>Result</dt><dd>{lifecycle.result || 'No verified result recorded'}</dd>
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
        {needsAttention && <p className="attention-note"><CircleAlert size={16} />{lifecycle.next_action}</p>}
      </div>
    </details>
  )
}

function OverviewItem({ label, value, attention = false }) {
  return <div className={attention ? 'needs-attention' : ''}><span>{label}</span><strong>{value}</strong></div>
}
