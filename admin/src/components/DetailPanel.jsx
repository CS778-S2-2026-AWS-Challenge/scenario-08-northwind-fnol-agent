import StatusBadge from './StatusBadge.jsx'
import { resourceId } from '../resource.js'

function Value({ value }) {
  if (value === null || value === undefined) return <span className="muted">Not provided</span>
  if (typeof value === 'object') return <pre>{JSON.stringify(value, null, 2)}</pre>
  return <span>{String(value)}</span>
}

export default function DetailPanel({ item, title, children }) {
  if (!item) return <section className="detail empty-detail"><p>Select a record to inspect its server-side state.</p></section>
  const entries = Object.entries(item).filter(([key]) => key !== 'allowed_actions' && (key !== 'values' || item.values))
  return (
    <section className="detail" aria-labelledby="detail-heading">
      <div className="detail-header">
        <div>
          <p className="eyebrow">{title}</p>
          <h2 id="detail-heading">{resourceId(item)}</h2>
        </div>
        {(item.state || item.health) && <StatusBadge value={item.state || item.health} />}
      </div>
      <dl>
        {entries.map(([key, value]) => (
          <div key={key}>
            <dt>{key.replaceAll('_', ' ')}</dt>
            <dd><Value value={value} /></dd>
          </div>
        ))}
      </dl>
      {children}
    </section>
  )
}
