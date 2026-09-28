import { BookOpenCheck, History, Info } from 'lucide-react'
import { formatDateTime, words } from '../format.js'
import { languageLocale, translate as t } from '../i18n.js'

export default function ReferenceRecords({ records }) {
  const policyRecords = records.filter((item) => item.kind === 'policy')
  const historyRecords = records.filter((item) => item.kind === 'claim_history')
  return (
    <section className="resource-view">
      <header className="content-header">
        <div><p className="eyebrow">{t('Source-linked records')}</p><h2>{t('Reference checks')}</h2></div>
        <span>{t('{count} records', { count: records.length })}</span>
      </header>
      <p className="section-intro">{t('Policy and Claim history remain distinct sources. Open a record to inspect provenance, facts, and uncertainty.')}</p>
      <ReferenceGroup title={t('Policy records')} emptyMessage={t('No policy records are recorded for this Claim.')} icon={<BookOpenCheck size={18} />} records={policyRecords} />
      <ReferenceGroup title={t('Claim history')} emptyMessage={t('No claim history records are recorded for this Claim.')} icon={<History size={18} />} records={historyRecords} />
    </section>
  )
}

function ReferenceGroup({ title, emptyMessage, icon, records }) {
  return (
    <section className="source-group">
      <div className="section-heading"><div className="source-group__title">{icon}<h3>{title}</h3></div><span className="count-badge">{records.length}</span></div>
      {records.length ? <div className="record-list">{records.map((record) => <ReferenceRecord record={record} key={record.retrieval_id} />)}</div> : <p className="empty-note">{emptyMessage}</p>}
    </section>
  )
}

function ReferenceRecord({ record }) {
  const factEntries = Object.entries(record.facts || {})
  const uncertainty = record.uncertainty || []
  return (
    <details className="record-row source-record">
      <summary>
        <span><strong>{primaryReference(record)}</strong><small>{words(record.kind)} · {record.source.system}</small></span>
        <span className={`record-status${uncertainty.length ? ' record-status--attention' : ' record-status--confirmed'}`}>{t(uncertainty.length ? 'Review uncertainty' : 'Source recorded')}</span>
      </summary>
      <div className="record-body">
        <div className="record-summary-grid">
          <SummaryFact label={t('Retrieved')} value={formatDateTime(record.source.retrieved_at)} />
          <SummaryFact label={t('Source reference')} value={record.source.reference} />
          <SummaryFact label={t('Confidence')} value={t('Not provided by this source contract')} />
        </div>
        <dl>{factEntries.map(([key, value]) => <Fact key={key} label={words(key)} value={value} />)}</dl>
        {uncertainty.length > 0 && (
          <section className="record-notices" aria-label={t('Recorded uncertainty')}>
            <div className="record-notices__heading"><Info size={16} /><strong>{t('Uncertainty requiring judgement')}</strong></div>
            {uncertainty.map((item) => <p key={`${item.code}:${item.detail}`}><strong>{words(item.code)}</strong>{item.detail}</p>)}
          </section>
        )}
      </div>
    </details>
  )
}

function SummaryFact({ label, value }) {
  return <div><span>{label}</span><strong>{value || t('Not recorded')}</strong></div>
}

function Fact({ label, value }) {
  return <><dt>{label}</dt><dd>{formatValue(value)}</dd></>
}

function primaryReference(record) {
  return record.facts?.policy_reference
    || record.facts?.history_reference
    || record.source.reference
}

function formatValue(value) {
  if (value === null || value === undefined || value === '') return t('Not recorded')
  if (Array.isArray(value)) return value.length ? value.map(words).join(', ') : t('None recorded')
  if (typeof value === 'number') return new Intl.NumberFormat(languageLocale()).format(value)
  return words(String(value))
}
