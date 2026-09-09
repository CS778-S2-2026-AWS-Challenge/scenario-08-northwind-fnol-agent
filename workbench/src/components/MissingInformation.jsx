import { ChevronRight } from 'lucide-react'
import { useId, useState } from 'react'
import { words } from '../format.js'

const SUMMARY_LIMIT = 6

export default function MissingInformation({ items = [] }) {
  const summary = items.slice(0, SUMMARY_LIMIT)
  const [expanded, setExpanded] = useState(false)
  const panelId = useId()
  return (
    <section className="detail-section missing-information" aria-labelledby="missing-information-title">
      <div className="section-heading">
        <div><p className="eyebrow">Operational context</p><h2 id="missing-information-title">Gap</h2></div>
        <span className="count-badge">{items.length}</span>
      </div>
      {items.length ? <MissingList items={summary} /> : <p className="empty-note">No missing, disputed, conflicting, pending, unavailable, or uncertain gap is projected.</p>}
      {items.length > SUMMARY_LIMIT && (
        <div className="missing-information__all">
          <button className="disclosure-button" type="button" aria-expanded={expanded} aria-controls={panelId} onClick={() => setExpanded((value) => !value)}>{expanded ? 'Hide all gaps' : 'Show all gaps'}</button>
          <div id={panelId} hidden={!expanded}><MissingList items={items} /></div>
        </div>
      )}
    </section>
  )
}

function MissingList({ items }) {
  return (
    <ul className="missing-list">
      {items.map((item) => (
        <li key={`${item.kind}:${item.code}`}>
          <ChevronRight size={16} aria-hidden="true" />
          <span>
            <strong>{item.label}</strong>
            <small>{words(item.status)} · {words(item.attention)} · {words(item.responsible_party)}</small>
            <details>
              <summary>Traceability</summary>
              <MissingDetails item={item} />
            </details>
          </span>
        </li>
      ))}
    </ul>
  )
}

function MissingDetails({ item }) {
  return (
    <dl className="missing-item-details">
      <dt>Source references</dt><dd>{item.source_refs?.join(', ') || 'None recorded'}</dd>
      <dt>Blocked action</dt><dd>{item.blocked_action ? words(item.blocked_action.replaceAll('.', '_')) : 'None recorded'}</dd>
    </dl>
  )
}
