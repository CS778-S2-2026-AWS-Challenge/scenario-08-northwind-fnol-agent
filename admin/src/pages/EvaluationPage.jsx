import { useMemo, useState } from 'react'
import { Plus } from 'lucide-react'
import { adminMutation, getToken, withQuery } from '../api.js'
import CollectionState from '../components/CollectionState.jsx'
import { Feedback, JsonField } from '../components/FormControls.jsx'
import { parseJson } from '../formUtils.js'
import PageHeader from '../components/PageHeader.jsx'
import ResourceWorkspace from '../components/ResourceWorkspace.jsx'
import useAdminCollection from '../hooks/useAdminCollection.js'
import useMutation from '../hooks/useMutation.js'
import useSelection from '../hooks/useSelection.js'

const DEFAULT_EVALUATION = JSON.stringify({ purpose: 'claimant_agent_policy', state: 'succeeded', model_version: 'configured-model-version', knowledge_version: null, rule_version: 'controlled-rules-v1', configuration_id: null, configuration_revision: null, dataset_id: 'northwind-evaluation', dataset_version: 'v1', fixture_version: null, source_versions: [], scenario_results: [{ scenario_id: 'safe-next-action', outcome: 'succeeded', score: 1, evidence: 'The expected structured outcome was observed.' }], metrics: { pass_rate: 1 }, threshold: 0.9, error_code: null }, null, 2)

export default function EvaluationPage() {
  const [purpose, setPurpose] = useState('')
  const [state, setState] = useState('')
  const endpoint = useMemo(() => withQuery('/internal/v1/admin/evaluations', { purpose, state }), [purpose, state])
  const collection = useAdminCollection(endpoint, getToken())
  const [selected, setSelected] = useSelection(collection.items)
  const [payload, setPayload] = useState(DEFAULT_EVALUATION)
  const mutation = useMutation(collection.reload)

  function submit(event) {
    event.preventDefault()
    mutation.run(
      () => adminMutation('/internal/v1/admin/evaluations', { token: getToken(), body: parseJson(payload, 'Evaluation record') }),
      'The immutable evaluation record was stored.',
    )
  }

  return (
    <>
      <PageHeader title="Evaluations" summary={`${collection.items.length} immutable evaluation records`} onRefresh={collection.reload}>
        <label className="compact-filter"><span>Purpose</span><input value={purpose} onChange={(event) => setPurpose(event.target.value)} placeholder="All purposes" /></label>
        <label className="compact-filter"><span>State</span><select value={state} onChange={(event) => setState(event.target.value)}><option value="">All states</option><option value="succeeded">Succeeded</option><option value="failed">Failed</option><option value="unknown">Unknown</option></select></label>
      </PageHeader>
      <details className="create-panel"><summary><Plus aria-hidden="true" />Record evaluation evidence</summary><form className="control-form" onSubmit={submit}><JsonField label="Evaluation record" value={payload} onChange={setPayload} rows={16} /><button className="primary"><Plus aria-hidden="true" />Record evidence</button></form><Feedback state={mutation.feedback} /></details>
      <CollectionState {...collection} label="Evaluations"><ResourceWorkspace label="Evaluations" items={collection.items} selected={selected} onSelect={setSelected} /></CollectionState>
    </>
  )
}
