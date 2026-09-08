import StatusBadge from './StatusBadge.jsx'
import { resourceId, resourceName } from '../resource.js'

export default function ResourceList({ title, items, selectedId, onSelect, emptyMessage }) {
  return (
    <section className="resource-list" aria-labelledby={`${title}-heading`}>
      <h2 id={`${title}-heading`}>{title}</h2>
      {items.length === 0 ? (
        <p className="empty">{emptyMessage || 'No records are available.'}</p>
      ) : (
        <ul>
          {items.map((item) => {
            const id = resourceId(item)
            const name = resourceName(item)
            return (
              <li key={id}>
                <button type="button" aria-pressed={id === selectedId} className={id === selectedId ? 'resource-row selected' : 'resource-row'} onClick={() => onSelect(item)}>
                  <span>
                    <strong>{name}</strong>
                    <small>{id}</small>
                  </span>
                  <StatusBadge value={item.state || item.health} />
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
