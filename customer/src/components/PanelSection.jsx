import { useId } from 'react'

// One archive section of the case panel. The title text itself opens and closes
// it; sections are separated by a thin line rather than boxed.
export default function PanelSection({ id, title, label = title, open, onToggle, children }) {
  const bodyId = useId()
  return (
    <section className={`case-panel-section is-collapsible ${open ? 'is-open' : ''}`} id={`case-panel-${id}`} aria-label={label}>
      <h3 className="case-panel-section-title">
        <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={onToggle}>
          <span>{title}</span>
          <span className="case-panel-section-chevron" aria-hidden="true">{open ? '−' : '+'}</span>
        </button>
      </h3>
      <div id={bodyId} hidden={!open}>{children}</div>
    </section>
  )
}
