import { formatDateTime, words } from '../format.js'
import { translate as t } from '../i18n.js'

const SUMMARY_LIMIT = 6

export default function SourceSummary({ summary = {} }) {
  const items = summary.items || []
  const status = summary.status || 'unavailable'

  return (
    <section className="detail-section source-summary" aria-labelledby="source-summary-title">
      <div className="section-heading">
        <div><p className="eyebrow">{t('Traceability')}</p><h2 id="source-summary-title">{t('Source')}</h2></div>
        <span className="count-badge">{words(status)} · {items.length}</span>
      </div>
      {summary.limitation && <p className="attention-note">{summary.limitation}</p>}
      {status === 'unavailable' && <p className="empty-note">{t('Source context is unavailable. Open the supporting sections later to retry the unavailable records.')}</p>}
      {status === 'empty' && <p className="empty-note">{t('No source context is recorded for this Claim.')}</p>}
      {items.length > 0 && <div className="record-list">{items.slice(0, SUMMARY_LIMIT).map((item) => <SourceItem item={item} key={item.record_ref} />)}</div>}
      {items.length > SUMMARY_LIMIT && (
        <details className="purpose-disclosure">
          <summary>{t('Show {count} more source records', { count: items.length - SUMMARY_LIMIT })}</summary>
          <div className="record-list">{items.slice(SUMMARY_LIMIT).map((item) => <SourceItem item={item} key={item.record_ref} />)}</div>
        </details>
      )}
    </section>
  )
}

function SourceItem({ item }) {
  return (
    <details className="record-row">
      <summary>
        <span><strong>{item.label}</strong><small>{item.context}</small></span>
        <span>{item.source_label} · {words(item.status)}</span>
      </summary>
      <dl>
        <dt>{t('Record type')}</dt><dd>{words(item.kind)}</dd>
        <dt>{t('Traceability references')}</dt><dd>{item.source_refs?.join(', ') || t('None recorded')}</dd>
        {item.related_fields?.length > 0 && <><dt>{t('Related fields')}</dt><dd>{item.related_fields.map(words).join(', ')}</dd></>}
        {item.needed_for?.length > 0 && <><dt>{t('Needed for')}</dt><dd>{item.needed_for.map(words).join(', ')}</dd></>}
        {item.responsible_party && <><dt>{t('Responsible party')}</dt><dd>{words(item.responsible_party)}</dd></>}
        {item.confidence !== null && item.confidence !== undefined && <><dt>{t('Confidence')}</dt><dd>{Math.round(item.confidence * 100)}%</dd></>}
        {item.updated_at && <><dt>{t('Updated')}</dt><dd>{formatDateTime(item.updated_at)}</dd></>}
      </dl>
    </details>
  )
}
