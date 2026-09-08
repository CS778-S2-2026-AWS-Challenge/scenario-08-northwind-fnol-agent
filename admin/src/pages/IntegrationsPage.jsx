import { useEffect, useState } from 'react'
import { Activity } from 'lucide-react'
import { adminFetch, adminMutation, getToken } from '../api.js'
import ActionPanel from '../components/ActionPanel.jsx'
import CollectionState from '../components/CollectionState.jsx'
import PageHeader from '../components/PageHeader.jsx'
import ResourceWorkspace from '../components/ResourceWorkspace.jsx'
import useAdminCollection from '../hooks/useAdminCollection.js'
import useSelection from '../hooks/useSelection.js'

function HealthAction({ item, setFeedback, onDone }) {
  async function submit(event) {
    event.preventDefault()
    setFeedback({ kind: 'working', message: 'Running the bounded connection health check...' })
    try {
      const record = await adminMutation(`/internal/v1/admin/integrations/${item.integration_id}/health-check`, { token: getToken() })
      setFeedback({ kind: 'success', message: `Health check ${record.check_id} completed with ${record.health}.` })
      onDone()
    } catch (error) {
      setFeedback({ kind: 'error', error })
    }
  }
  return <form className="control-form" onSubmit={submit}><p className="muted">This reads adapter connectivity and records an Operation. It does not invoke a Claim action.</p><button className="primary"><Activity aria-hidden="true" />Run health check</button></form>
}

export default function IntegrationsPage() {
  const collection = useAdminCollection('/internal/v1/admin/integrations', getToken())
  const [selected, setSelected] = useSelection(collection.items)
  const [historyResult, setHistoryResult] = useState({ integrationId: '', items: [] })
  useEffect(() => {
    if (!selected) return
    const integrationId = selected.integration_id
    adminFetch(`/internal/v1/admin/integrations/${integrationId}/health-checks`, { token: getToken() })
      .then((payload) => setHistoryResult({ integrationId, items: payload.items || [] }))
      .catch(() => setHistoryResult({ integrationId, items: [] }))
  }, [selected])
  const history = historyResult.integrationId === selected?.integration_id ? historyResult.items : []
  return (
    <>
      <PageHeader title="Integrations" summary={`${collection.items.length} registered runtime capabilities`} onRefresh={collection.reload} />
      <CollectionState {...collection} label="Integrations">
        <ResourceWorkspace label="Integrations" items={collection.items} selected={selected} onSelect={setSelected}>
          <ActionPanel actions={selected?.allowed_actions} renderForm={(action, setFeedback) => <HealthAction action={action} item={selected} setFeedback={setFeedback} onDone={collection.reload} />} />
          {history.length > 0 && <section className="history"><h3>Health history</h3><ul>{history.map((record) => <li key={record.check_id}><strong>{record.health}</strong><span>{new Date(record.checked_at).toLocaleString()}</span><span>{record.failure_code || 'No failure reported'}</span></li>)}</ul></section>}
        </ResourceWorkspace>
      </CollectionState>
    </>
  )
}
