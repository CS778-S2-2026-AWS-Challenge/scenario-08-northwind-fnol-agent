import { useState } from 'react'
import { PackageCheck, Plus } from 'lucide-react'
import { adminMutation, getToken } from '../api.js'
import ActionPanel from '../components/ActionPanel.jsx'
import CollectionState from '../components/CollectionState.jsx'
import { Feedback, Field, JsonField } from '../components/FormControls.jsx'
import { parseJson } from '../formUtils.js'
import PageHeader from '../components/PageHeader.jsx'
import ResourceWorkspace from '../components/ResourceWorkspace.jsx'
import useAdminCollection from '../hooks/useAdminCollection.js'
import useMutation from '../hooks/useMutation.js'
import useSelection from '../hooks/useSelection.js'

const SCENARIOS = '[\n  {\n    "scenario_id": "runtime-load",\n    "outcome": "passed",\n    "evidence": "All pinned records resolved as published and compatible."\n  }\n]'

function CreateRelease({ onDone }) {
  const [environment, setEnvironment] = useState('test')
  const [runtimeProfile, setRuntimeProfile] = useState('fixture')
  const [configurationRefs, setConfigurationRefs] = useState('{}')
  const [integrationRefs, setIntegrationRefs] = useState('{}')
  const [knowledgeRefs, setKnowledgeRefs] = useState('{}')
  const [reason, setReason] = useState('Assemble one complete runtime configuration boundary.')
  const mutation = useMutation(onDone)

  function submit(event) {
    event.preventDefault()
    mutation.run(
      () => adminMutation('/internal/v1/admin/release-sets', { token: getToken(), body: { environment, runtime_profile: runtimeProfile, configuration_refs: parseJson(configurationRefs, 'Configuration references'), integration_refs: parseJson(integrationRefs, 'Integration references'), knowledge_refs: parseJson(knowledgeRefs, 'Knowledge references'), reason } }),
      'The Release Set draft was created.',
    )
  }
  return (
    <details className="create-panel">
      <summary><Plus aria-hidden="true" />Create Release Set</summary>
      <form className="control-form form-grid" onSubmit={submit}>
        <Field label="Environment"><input value={environment} onChange={(event) => setEnvironment(event.target.value)} required /></Field>
        <Field label="Runtime profile"><input value={runtimeProfile} onChange={(event) => setRuntimeProfile(event.target.value)} required /></Field>
        <JsonField label="Configuration references" value={configurationRefs} onChange={setConfigurationRefs} hint={'Map domains to {"configuration_id", "revision"}.'} />
        <JsonField label="Integration references" value={integrationRefs} onChange={setIntegrationRefs} hint="Map registered service IDs to immutable references." />
        <JsonField label="Knowledge references" value={knowledgeRefs} onChange={setKnowledgeRefs} hint="Map product IDs to immutable knowledge references." />
        <Field label="Reason"><textarea rows="3" value={reason} onChange={(event) => setReason(event.target.value)} required /></Field>
        <button className="primary"><PackageCheck aria-hidden="true" />Create Release Set</button>
      </form>
      <Feedback state={mutation.feedback} />
    </details>
  )
}

function ReleaseActionForm({ action, item, setFeedback, onDone }) {
  const [reason, setReason] = useState('Apply the reviewed Release Set transition.')
  const [scenarios, setScenarios] = useState(SCENARIOS)
  const [rollbackTarget, setRollbackTarget] = useState('')
  const [confirmed, setConfirmed] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setFeedback({ kind: 'working', message: 'Applying the Release Set transition...' })
    try {
      const actionName = action.action_code.split('.').at(-1)
      const body = actionName === 'validate' ? { scenario_results: parseJson(scenarios, 'Scenario results') } : { reason }
      if (actionName === 'rollback') body.rollback_target = rollbackTarget
      await adminMutation(`/internal/v1/admin/release-sets/${item.release_set_id}/${actionName}`, { token: getToken(), revision: action.expected_revision, body })
      setFeedback({ kind: 'success', message: 'The Release Set state was updated and reloaded.' })
      onDone()
    } catch (error) {
      setFeedback({ kind: 'error', error })
    }
  }
  return (
    <form className="control-form" onSubmit={submit}>
      {action.action_code.endsWith('.validate') ? <JsonField label="Scenario results" value={scenarios} onChange={setScenarios} /> : <Field label="Reason"><textarea rows="3" value={reason} onChange={(event) => setReason(event.target.value)} required /></Field>}
      {action.action_code.endsWith('.rollback') && <Field label="Rollback target Release Set ID"><input value={rollbackTarget} onChange={(event) => setRollbackTarget(event.target.value)} required /></Field>}
      {action.availability === 'confirmation_required' && <label className="confirmation"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>I confirm this transition against revision {action.expected_revision}.</span></label>}
      <button className="primary" disabled={action.availability === 'confirmation_required' && !confirmed}><PackageCheck aria-hidden="true" />Apply transition</button>
    </form>
  )
}

export default function ReleasePage() {
  const collection = useAdminCollection('/internal/v1/admin/release-sets', getToken())
  const [selected, setSelected] = useSelection(collection.items)
  return (
    <>
      <PageHeader title="Release Sets" summary={`${collection.items.length} complete runtime publication boundaries`} onRefresh={collection.reload} />
      <CreateRelease onDone={collection.reload} />
      <CollectionState {...collection} label="Release Sets">
        <ResourceWorkspace label="Release Sets" items={collection.items} selected={selected} onSelect={setSelected}>
          <ActionPanel actions={selected?.allowed_actions} renderForm={(action, setFeedback) => <ReleaseActionForm key={`${action.action_code}-${selected.revision}`} action={action} item={selected} setFeedback={setFeedback} onDone={collection.reload} />} />
        </ResourceWorkspace>
      </CollectionState>
    </>
  )
}
