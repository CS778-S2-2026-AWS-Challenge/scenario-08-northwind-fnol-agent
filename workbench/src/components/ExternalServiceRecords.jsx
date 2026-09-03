import { CircleAlert, ExternalLink, ShieldCheck } from 'lucide-react'
import { formatDateTime, words } from '../format.js'

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
  const needsAttention = ['retryable_failure', 'terminal_failure', 'unknown_outcome'].includes(task.status)
  return (
    <details className="record-row external-record">
      <summary>
        <span><strong>{words(task.service_identity)}</strong><small>{words(task.requested_action)} · Updated {formatDateTime(task.updated_at)}</small></span>
        <span className={`record-status record-status--${needsAttention ? 'attention' : task.status}`}>{words(task.status)}</span>
      </summary>
      <div className="record-body">
        <div className="external-overview">
          <OverviewItem label="Purpose" value={request?.purpose || 'Request details have not been prepared.'} />
          <OverviewItem label="Data sharing" value={request ? `${request.disclosed_fields.length} registered fields` : 'No disclosure manifest recorded'} />
          <OverviewItem label="Authority" value={request ? 'Northwind authority and claimant consent recorded' : 'Not yet recorded'} />
          <OverviewItem label="Next step" value={nextStep(task)} attention={needsAttention} />
        </div>
        <section className="external-disclosure" aria-label="External request detail">
          <div className="section-heading"><div><p className="eyebrow">Request detail</p><h3>Disclosure and delivery</h3></div><ExternalLink size={18} /></div>
          <dl>
            <dt>Integration source</dt><dd>{words(task.integration_source)}</dd>
            <dt>Delivery</dt><dd>{words(task.delivery)}</dd>
            <dt>Prepared</dt><dd>{request ? formatDateTime(request.prepared_at) : 'Not recorded'}</dd>
            <dt>Sent</dt><dd>{request?.sent_at ? formatDateTime(request.sent_at) : 'Not sent'}</dd>
            <dt>Operation identity</dt><dd>{request?.operation_id || 'Not reserved'}</dd>
            <dt>Provider reference</dt><dd>{task.provider_reference || 'Not provided'}</dd>
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
        {needsAttention && <p className="attention-note"><CircleAlert size={16} />{nextStep(task)}</p>}
      </div>
    </details>
  )
}

function OverviewItem({ label, value, attention = false }) {
  return <div className={attention ? 'needs-attention' : ''}><span>{label}</span><strong>{value}</strong></div>
}

function nextStep(task) {
  const steps = {
    prepared: 'Review the purpose, shared fields, consent, and authority before sending.',
    accepted: 'Track the provider result and verify it before reconciling Claim State.',
    retryable_failure: 'Correct the reported dependency problem, then retry with the same operation identity.',
    terminal_failure: 'A claims professional must review the failure before another request is attempted.',
    unknown_outcome: 'Reconcile by operation or provider reference before any retry.',
  }
  return steps[task.status] || 'Review the current request record before continuing.'
}
