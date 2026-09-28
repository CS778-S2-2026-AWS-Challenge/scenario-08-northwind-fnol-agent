import { AlertTriangle, ShieldAlert } from 'lucide-react'
import { words } from '../format.js'
import { translate as t } from '../i18n.js'

export default function SignalsSummary({ items = [], onOpen }) {
  return (
    <section className="disclosure-summary" aria-labelledby="signals-summary-title">
      <div className="section-heading">
        <div><p className="eyebrow">{t('Signals')}</p><h2 id="signals-summary-title">{t('Needs attention')}</h2></div>
        <span className="attention-count"><ShieldAlert size={18} />{items.length}</span>
      </div>
      {items.length ? (
        <>
          <ul className="missing-list">
            {items.slice(0, 3).map((item) => <li key={item.signal_id}><AlertTriangle size={16} /><span><strong>{item.label}</strong><small>{words(item.attention_level)} · {item.summary}</small></span></li>)}
          </ul>
          <button className="button button--quiet" type="button" onClick={onOpen}>{t('Review signals')}</button>
        </>
      ) : <p className="empty-note">{t('No risk signal currently needs attention.')}</p>}
    </section>
  )
}
