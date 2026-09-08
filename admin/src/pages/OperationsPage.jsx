import { useEffect, useMemo, useState } from 'react'
import { adminFetch, getToken, withQuery } from '../api.js'
import CollectionState from '../components/CollectionState.jsx'
import PageHeader from '../components/PageHeader.jsx'
import ResourceWorkspace from '../components/ResourceWorkspace.jsx'
import useAdminCollection from '../hooks/useAdminCollection.js'
import useSelection from '../hooks/useSelection.js'

function costLabel(cost) {
  if (cost.status === 'unconfigured') return 'Cost unconfigured'
  const amount = (cost.estimated_microunits / 1_000_000).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  })
  return `${cost.currency} ${amount}${cost.status === 'partial' ? ' partial' : ''}`
}

export default function OperationsPage() {
  const [kind, setKind] = useState('')
  const [state, setState] = useState('')
  const [metrics, setMetrics] = useState(null)
  const [metricsError, setMetricsError] = useState(false)
  const endpoint = useMemo(() => withQuery('/internal/v1/admin/operations', { kind, state }), [kind, state])
  const collection = useAdminCollection(endpoint, getToken())
  const [selected, setSelected] = useSelection(collection.items)

  useEffect(() => {
    adminFetch('/internal/v1/admin/operations/metrics', { token: getToken() })
      .then((nextMetrics) => {
        setMetrics(nextMetrics)
        setMetricsError(false)
      })
      .catch(() => {
        setMetrics(null)
        setMetricsError(true)
      })
  }, [collection.items])

  return (
    <>
      <PageHeader title="Operations" summary={`${collection.items.length} operation records${metrics ? ` · ${metrics.total} total` : ''}`} onRefresh={collection.reload}>
        <label className="compact-filter"><span>Kind</span><input value={kind} onChange={(event) => setKind(event.target.value)} placeholder="All kinds" /></label>
        <label className="compact-filter"><span>State</span><select value={state} onChange={(event) => setState(event.target.value)}><option value="">All states</option><option value="queued">Queued</option><option value="running">Running</option><option value="succeeded">Succeeded</option><option value="failed">Failed</option><option value="unknown">Unknown</option><option value="cancelled">Cancelled</option></select></label>
      </PageHeader>
      {metricsError && (
        <section className="notice error" role="alert">
          Operational metrics could not be loaded. The operation list remains available; refresh to try again.
        </section>
      )}
      {metrics && (
        <>
          <section className="metric-strip" aria-label="Operation totals" aria-live="polite">
            <div><strong>{metrics.total}</strong><span>operations</span></div>
            <div><strong>{metrics.usage.calls}</strong><span>model calls</span></div>
            <div><strong>{metrics.usage.total_tokens.toLocaleString()}</strong><span>reported tokens</span></div>
            <div><strong>{costLabel(metrics.cost)}</strong><span>estimated model cost</span></div>
            <div><strong>{metrics.rate_limit.events_in_window}</strong><span>{metrics.rate_limit.status === 'unconfigured' ? 'rate window unconfigured' : `rate limits in ${metrics.rate_limit.window_seconds}s`}</span></div>
          </section>
          {metrics.alerts.length > 0 && (
            <section className="history" aria-labelledby="operations-alerts-heading">
              <div className="section-heading"><h2 id="operations-alerts-heading">Configured alerts</h2></div>
              <ul>{metrics.alerts.map((alert) => <li key={alert.alert_code}><strong>{alert.status}</strong><span>{alert.metric.replaceAll('_', ' ')}</span><span>{alert.observed ?? 'Unknown'} / {alert.threshold}</span></li>)}</ul>
            </section>
          )}
        </>
      )}
      <CollectionState {...collection} label="Operations"><ResourceWorkspace label="Operations" items={collection.items} selected={selected} onSelect={setSelected} /></CollectionState>
    </>
  )
}
