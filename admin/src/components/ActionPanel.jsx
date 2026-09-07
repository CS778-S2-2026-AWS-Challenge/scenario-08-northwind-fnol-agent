import { useMemo, useState } from 'react'
import { LockKeyhole, Play } from 'lucide-react'
import { Feedback } from './FormControls.jsx'

export default function ActionPanel({ actions = [], renderForm }) {
  const executable = useMemo(
    () => actions.filter((action) => action.availability !== 'blocked'),
    [actions],
  )
  const blocked = useMemo(
    () => actions.filter((action) => action.availability === 'blocked'),
    [actions],
  )
  const [selectedCode, setSelectedCode] = useState('')
  const [feedback, setFeedback] = useState(null)
  const selected = executable.find((action) => action.action_code === selectedCode) || null

  return (
    <section className="action-panel" aria-labelledby="actions-heading">
      <div className="section-heading">
        <div><p className="eyebrow">Server-authorised controls</p><h3 id="actions-heading">Actions</h3></div>
        <Play aria-hidden="true" />
      </div>
      {executable.length > 0 ? (
        <label className="field">
          <span>Action</span>
          <select value={selectedCode} onChange={(event) => { setSelectedCode(event.target.value); setFeedback(null) }}>
            <option value="">Choose an available action</option>
            {executable.map((action) => <option value={action.action_code} key={action.action_code}>{action.action_code.replaceAll('_', ' ').replaceAll('.', ' · ')}</option>)}
          </select>
        </label>
      ) : <p className="muted">The server exposes no executable action for this record.</p>}
      {selected && renderForm(selected, setFeedback)}
      <Feedback state={feedback} />
      {blocked.length > 0 && (
        <details className="blocked-actions">
          <summary><LockKeyhole aria-hidden="true" />Unavailable actions ({blocked.length})</summary>
          <ul>{blocked.map((action) => <li key={action.action_code}><strong>{action.action_code}</strong><span>{action.reason}</span></li>)}</ul>
        </details>
      )}
    </section>
  )
}
