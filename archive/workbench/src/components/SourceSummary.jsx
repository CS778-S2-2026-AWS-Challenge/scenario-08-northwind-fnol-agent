import { formatDateTime, words } from '../format.js'

const SUMMARY_LIMIT = 6

export default function SourceSummary({ summary = {} }) {
  const items = summary.items || []
  const status = summary.status || 'unavailable'

  return (
    <section className="detail-section source-summary" aria-labelledby="source-summary-title">
      <div className="section-heading">
        <div><p className="eyebrow">Traceability</p><h2 id="source-summary-title">Source</h2></div>
        <span className="count-badge">{words(status)} · {items.length}</span>
      </div>
      {summary.limitation && <p className="attention-note">{summary.limitation}</p>}
      {status === 'unavailable' && <p className="empty-note">Source context is unavailable. Open the supporting sections later to retry the unavailable records.</p>}
      {status === 'empty' && <p className="empty-note">No source context is recorded for this Claim.</p>}
      {items.length > 0 && <div className="record-list">{items.slice(0, SUMMARY_LIMIT).map((item) => <SourceItem item={item} key={item.record_ref} />)}</div>}
      {items.length > SUMMARY_LIMIT && (
        <details className="purpose-disclosure">
          <summary>Show {items.length - SUMMARY_LIMIT} more source records</summary>
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
        <dt>Record type</dt><dd>{words(item.kind)}</dd>
        <dt>Traceability references</dt><dd>{item.source_refs?.join(', ') || 'None recorded'}</dd>
        {item.related_fields?.length > 0 && <><dt>Related fields</dt><dd>{item.related_fields.map(words).join(', ')}</dd></>}
        {item.needed_for?.length > 0 && <><dt>Needed for</dt><dd>{item.needed_for.map(words).join(', ')}</dd></>}
        {item.responsible_party && <><dt>Responsible party</dt><dd>{words(item.responsible_party)}</dd></>}
        {item.confidence !== null && item.confidence !== undefined && <><dt>Confidence</dt><dd>{Math.round(item.confidence * 100)}%</dd></>}
        {item.updated_at && <><dt>Updated</dt><dd>{formatDateTime(item.updated_at)}</dd></>}
      </dl>
    </details>
  )
}
