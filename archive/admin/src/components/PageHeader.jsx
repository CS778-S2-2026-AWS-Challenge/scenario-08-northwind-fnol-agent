import { RefreshCw } from 'lucide-react'

export default function PageHeader({ title, summary, onRefresh, children }) {
  return (
    <header className="page-header">
      <div><p className="eyebrow">Administration</p><h1>{title}</h1><p className="muted">{summary}</p></div>
      <div className="header-actions">
        {children}
        {onRefresh && <button type="button" className="icon-button" title={`Refresh ${title.toLowerCase()}`} aria-label={`Refresh ${title.toLowerCase()}`} onClick={onRefresh}><RefreshCw aria-hidden="true" /></button>}
      </div>
    </header>
  )
}
