import { useState } from 'react'
import { BookOpenCheck, Plus } from 'lucide-react'
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

const VALIDATION = '[\n  {\n    "scenario_id": "retrieval-grounding",\n    "outcome": "passed",\n    "evidence": "The expected source and section were returned."\n  }\n]'
const RETRIEVAL = JSON.stringify({ question: 'What evidence is required?', jurisdiction: 'NZ', visibility: 'claimant', authority: 'approved_policy', version: 'v1', insurer: 'Northwind', product: 'motor', effective_at: '2026-09-07T00:00:00+12:00', limit: 5 }, null, 2)

function CreateKnowledge({ onDone }) {
  const [form, setForm] = useState({ document_id: '', version: 'v1', source_key: '', title: '', document_type: 'policy_guidance', source_uri: '', jurisdiction: 'NZ', insurer: 'Northwind', product: 'motor', authority: 'approved_policy', visibility: 'claimant', content: '' })
  const mutation = useMutation(onDone)
  const update = (key) => (event) => setForm((value) => ({ ...value, [key]: event.target.value }))

  function submit(event) {
    event.preventDefault()
    const body = { ...form }
    if (!body.content.trim()) delete body.content
    mutation.run(
      () => adminMutation('/internal/v1/admin/knowledge', { token: getToken(), body }),
      'The governed knowledge draft was created.',
    )
  }
  return (
    <details className="create-panel">
      <summary><Plus aria-hidden="true" />Create knowledge version</summary>
      <form className="control-form form-grid" onSubmit={submit}>
        <Field label="Document ID"><input value={form.document_id} onChange={update('document_id')} required /></Field>
        <Field label="Version"><input value={form.version} onChange={update('version')} required /></Field>
        <Field label="Title"><input value={form.title} onChange={update('title')} required /></Field>
        <Field label="Document type"><input value={form.document_type} onChange={update('document_type')} required /></Field>
        <Field label="Source key"><input value={form.source_key} onChange={update('source_key')} required /></Field>
        <Field label="Source URI"><input value={form.source_uri} onChange={update('source_uri')} required /></Field>
        <Field label="Jurisdiction"><input value={form.jurisdiction} onChange={update('jurisdiction')} required /></Field>
        <Field label="Insurer"><input value={form.insurer} onChange={update('insurer')} /></Field>
        <Field label="Product"><input value={form.product} onChange={update('product')} /></Field>
        <Field label="Authority"><input value={form.authority} onChange={update('authority')} required /></Field>
        <Field label="Visibility"><input value={form.visibility} onChange={update('visibility')} required /></Field>
        <Field label="Markdown content" hint="Optional source content written through the configured object-store adapter."><textarea rows="8" value={form.content} onChange={update('content')} /></Field>
        <button className="primary"><BookOpenCheck aria-hidden="true" />Create version</button>
      </form>
      <Feedback state={mutation.feedback} />
    </details>
  )
}

function KnowledgeActionForm({ action, item, setFeedback, onDone }) {
  const [scenarios, setScenarios] = useState(VALIDATION)
  const [retrieval, setRetrieval] = useState(RETRIEVAL)
  const [confirmed, setConfirmed] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setFeedback({ kind: 'working', message: 'Applying the knowledge lifecycle action...' })
    try {
      const name = action.action_code.split('.').at(-1)
      let body
      if (name === 'validate') body = { scenario_results: parseJson(scenarios, 'Scenario results') }
      if (name === 'retrieval_check') body = parseJson(retrieval, 'Retrieval request')
      await adminMutation(`/internal/v1/admin/knowledge/${item.knowledge_id}/${name.replace('_', '-')}`, { token: getToken(), body })
      setFeedback({ kind: 'success', message: 'The knowledge record and operation state were reloaded.' })
      onDone()
    } catch (error) {
      setFeedback({ kind: 'error', error })
    }
  }
  return (
    <form className="control-form" onSubmit={submit}>
      {action.action_code.endsWith('.validate') && <JsonField label="Scenario results" value={scenarios} onChange={setScenarios} />}
      {action.action_code.endsWith('.retrieval_check') && <JsonField label="Retrieval request" value={retrieval} onChange={setRetrieval} />}
      {action.availability === 'confirmation_required' && <label className="confirmation"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>I confirm this knowledge lifecycle action.</span></label>}
      <button className="primary" disabled={action.availability === 'confirmation_required' && !confirmed}><BookOpenCheck aria-hidden="true" />Apply action</button>
    </form>
  )
}

export default function KnowledgePage() {
  const collection = useAdminCollection('/internal/v1/admin/knowledge', getToken())
  const [selected, setSelected] = useSelection(collection.items)
  return (
    <>
      <PageHeader title="Knowledge" summary={`${collection.items.length} governed source versions`} onRefresh={collection.reload} />
      <CreateKnowledge onDone={collection.reload} />
      <CollectionState {...collection} label="Knowledge">
        <ResourceWorkspace label="Knowledge versions" items={collection.items} selected={selected} onSelect={setSelected}>
          <ActionPanel actions={selected?.allowed_actions} renderForm={(action, setFeedback) => <KnowledgeActionForm key={`${action.action_code}-${selected.revision}`} action={action} item={selected} setFeedback={setFeedback} onDone={collection.reload} />} />
        </ResourceWorkspace>
      </CollectionState>
    </>
  )
}
