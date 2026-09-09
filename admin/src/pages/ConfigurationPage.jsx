import { useMemo, useState } from 'react'
import { Plus, Save } from 'lucide-react'
import { adminMutation, getToken, withQuery } from '../api.js'
import ActionPanel from '../components/ActionPanel.jsx'
import CollectionState from '../components/CollectionState.jsx'
import { Feedback, Field, JsonField } from '../components/FormControls.jsx'
import { parseJson } from '../formUtils.js'
import PageHeader from '../components/PageHeader.jsx'
import ResourceWorkspace from '../components/ResourceWorkspace.jsx'
import useAdminCollection from '../hooks/useAdminCollection.js'
import useMutation from '../hooks/useMutation.js'
import useSelection from '../hooks/useSelection.js'

const DEFAULT_VALUES = '{\n  "feature_version": "features-v1",\n  "model_assisted_turns": true,\n  "knowledge_retrieval": true\n}'
const DEFAULT_SCENARIOS = '[\n  {\n    "scenario_id": "configuration-check",\n    "outcome": "passed",\n    "evidence": "Validated against the named acceptance scenario."\n  }\n]'

function ConfigurationActionForm({ action, item, onDone, setFeedback }) {
  const [reason, setReason] = useState('Apply the reviewed configuration lifecycle action.')
  const [values, setValues] = useState(JSON.stringify(item.values, null, 2))
  const [secretReferences, setSecretReferences] = useState(JSON.stringify(item.secret_references || {}, null, 2))
  const [scenarios, setScenarios] = useState(DEFAULT_SCENARIOS)
  const [decision, setDecision] = useState('approved')
  const [rollbackTarget, setRollbackTarget] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const token = getToken()
  const needsConfirmation = action.availability === 'confirmation_required'

  async function submit(event) {
    event.preventDefault()
    setFeedback({ kind: 'working', message: 'Applying the action to the current server state...' })
    try {
      const base = `/internal/v1/admin/configurations/${item.configuration_id}`
      let result
      if (action.action_code === 'admin.configuration.patch') {
        result = await adminMutation(base, { token, method: 'PATCH', revision: action.expected_revision, body: { values: parseJson(values, 'Values'), secret_references: parseJson(secretReferences, 'Secret references'), reason } })
      } else if (action.action_code === 'admin.configuration.validate') {
        result = await adminMutation(`${base}/validate`, { token, revision: action.expected_revision, body: { scenario_results: parseJson(scenarios, 'Scenario results') } })
      } else if (action.action_code === 'admin.configuration.approve') {
        result = await adminMutation(`${base}/approval`, { token, revision: action.expected_revision, body: { decision, reason } })
      } else {
        const suffix = action.action_code.split('.').at(-1)
        const body = { reason }
        if (suffix === 'rollback') body.rollback_target = rollbackTarget
        result = await adminMutation(`${base}/${suffix}`, { token, revision: action.expected_revision, body })
      }
      setFeedback({ kind: 'success', message: `${action.action_code} completed and the server state was reloaded.` })
      onDone(result)
    } catch (error) {
      setFeedback({ kind: 'error', error })
    }
  }

  return (
    <form className="control-form" onSubmit={submit}>
      {action.action_code === 'admin.configuration.patch' && <><JsonField label="Values" value={values} onChange={setValues} /><JsonField label="Secret references" value={secretReferences} onChange={setSecretReferences} rows={4} hint="References only. Never enter secret values." /></>}
      {action.action_code === 'admin.configuration.validate' && <JsonField label="Scenario results" value={scenarios} onChange={setScenarios} />}
      {action.action_code === 'admin.configuration.approve' && <Field label="Decision"><select value={decision} onChange={(event) => setDecision(event.target.value)}><option value="approved">Approve</option><option value="rejected">Reject</option></select></Field>}
      {!['admin.configuration.validate', 'admin.configuration.patch'].includes(action.action_code) && <Field label="Reason"><textarea rows="3" value={reason} onChange={(event) => setReason(event.target.value)} required /></Field>}
      {action.action_code === 'admin.configuration.patch' && <Field label="Reason"><textarea rows="3" value={reason} onChange={(event) => setReason(event.target.value)} required /></Field>}
      {action.action_code === 'admin.configuration.rollback' && <Field label="Rollback target configuration ID"><input value={rollbackTarget} onChange={(event) => setRollbackTarget(event.target.value)} required /></Field>}
      {needsConfirmation && <label className="confirmation"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>I confirm this action against revision {action.expected_revision}.</span></label>}
      <button className="primary" disabled={needsConfirmation && !confirmed}><Save aria-hidden="true" />Apply action</button>
    </form>
  )
}

function CreateConfiguration({ onDone }) {
  const [domain, setDomain] = useState('feature')
  const [impact, setImpact] = useState('normal')
  const [values, setValues] = useState(DEFAULT_VALUES)
  const [secretReferences, setSecretReferences] = useState('{}')
  const [reason, setReason] = useState('Create a versioned configuration draft.')
  const mutation = useMutation(onDone)

  function submit(event) {
    event.preventDefault()
    mutation.run(
      () => adminMutation('/internal/v1/admin/configurations', { token: getToken(), body: { domain, impact, values: parseJson(values, 'Values'), secret_references: parseJson(secretReferences, 'Secret references'), reason } }),
      'The configuration draft was created.',
    )
  }

  return (
    <details className="create-panel">
      <summary><Plus aria-hidden="true" />Create configuration draft</summary>
      <form className="control-form form-grid" onSubmit={submit}>
        <Field label="Domain"><input value={domain} onChange={(event) => setDomain(event.target.value)} required /></Field>
        <Field label="Impact"><select value={impact} onChange={(event) => setImpact(event.target.value)}><option value="normal">Normal</option><option value="high">High</option></select></Field>
        <JsonField label="Values" value={values} onChange={setValues} />
        <JsonField label="Secret references" value={secretReferences} onChange={setSecretReferences} rows={4} hint="Use protected references only." />
        <Field label="Reason"><textarea rows="3" value={reason} onChange={(event) => setReason(event.target.value)} required /></Field>
        <button className="primary"><Plus aria-hidden="true" />Create draft</button>
      </form>
      <Feedback state={mutation.feedback} />
    </details>
  )
}

export default function ConfigurationPage() {
  const [domain, setDomain] = useState('')
  const endpoint = useMemo(() => withQuery('/internal/v1/admin/configurations', { domain }), [domain])
  const collection = useAdminCollection(endpoint, getToken())
  const [selected, setSelected] = useSelection(collection.items)

  return (
    <>
      <PageHeader title="Configurations" summary={`${collection.items.length} records from the versioned configuration repository`} onRefresh={collection.reload}>
        <label className="compact-filter"><span>Domain</span><input value={domain} onChange={(event) => setDomain(event.target.value)} placeholder="All domains" /></label>
      </PageHeader>
      <CreateConfiguration onDone={collection.reload} />
      <CollectionState {...collection} label="Configurations">
        <ResourceWorkspace label="Configurations" items={collection.items} selected={selected} onSelect={setSelected}>
          <ActionPanel actions={selected?.allowed_actions} renderForm={(action, setFeedback) => <ConfigurationActionForm key={`${action.action_code}-${selected.revision}`} action={action} item={selected} setFeedback={setFeedback} onDone={collection.reload} />} />
        </ResourceWorkspace>
      </CollectionState>
    </>
  )
}
