import { Download, Eye, Files, FileWarning, LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import { formatDateTime, words } from '../format.js'
import { translate as t } from '../i18n.js'
import { canSubmitProjectedAction, findProjectedAction } from '../projected-action.js'
import ResourceEmptyState, { ResourcePageHeader } from './ResourceEmptyState.jsx'

// A handler changes how a claimant file is read with an explicit Change button;
// their reading then wins over the assistant's wherever files are counted.
function ReadingEditor({ item, action, onCorrect }) {
  const choices = action.inputs?.find((input) => input.field_code === 'kind')?.choices || []
  const [kind, setKind] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  if (!open) {
    return <button className="button button--quiet" type="button" onClick={() => setOpen(true)}>{t('Change')}</button>
  }
  return (
    <form
      className="reading-editor"
      onSubmit={async (event) => {
        event.preventDefault()
        if (!kind) return
        setBusy(true)
        setError('')
        try {
          await onCorrect(action, kind)
          setOpen(false)
        } catch (failure) {
          setError(failure?.message || t('The file type was not saved. Refresh the Claim and try again.'))
        } finally {
          setBusy(false)
        }
      }}
    >
      <label htmlFor={`reading-${item.evidence_id}`}>{t('File type')}</label>
      <select id={`reading-${item.evidence_id}`} value={kind} onChange={(event) => setKind(event.target.value)}>
        <option value="">{t('Choose…')}</option>
        {choices.map((choice) => <option key={choice.value} value={choice.value}>{t(choice.label)}</option>)}
      </select>
      <button className="button" type="submit" disabled={busy || !kind}>{t('Save')}</button>
      <button className="button button--quiet" type="button" disabled={busy} onClick={() => setOpen(false)}>{t('Cancel')}</button>
      {error && <p className="form-error" role="alert">{error}</p>}
    </form>
  )
}

export default function EvidenceRecords({ claimId, records, readings = {}, staffReadings = [], actions = [], onLoadEvidence, onCorrectReading }) {
  const [preview, setPreview] = useState(null)
  const [loadingId, setLoadingId] = useState(null)
  const [error, setError] = useState('')

  function readingAction(item) {
    const action = findProjectedAction(actions, 'evidence.correct_reading', item.evidence_id)
    return canSubmitProjectedAction(action) ? action : null
  }

  async function load(item) {
    setLoadingId(item.evidence_id)
    setError('')
    try {
      const content = await onLoadEvidence(item.evidence_id)
      setPreview({
        evidenceId: item.evidence_id,
        filename: content.filename,
        mediaType: content.media_type,
        url: `data:${content.media_type};base64,${content.base64_data}`,
      })
    } catch (nextError) {
      setPreview(null)
      setError(nextError.message)
    } finally {
      setLoadingId(null)
    }
  }

  return (
    <section className="resource-view" aria-labelledby="evidence-title">
      <ResourcePageHeader
        title="Evidence"
        subtitle="Files and source-linked records for this Claim."
        countLabel={t('{count} records', { count: records.length })}
        titleId="evidence-title"
      />
      {error && <p className="inline-error" role="alert"><FileWarning size={16} />{error}</p>}
      {records.length ? (
        <div className="record-list">
          {records.map((item) => {
            const canOpen = Boolean(item.media_type)
            const itemPreview = preview?.evidenceId === item.evidence_id ? preview : null
            return (
              <details className="record-row" key={item.evidence_id}>
                <summary>
                  <span><strong>{item.original_filename || words(item.kind)}</strong><small>{item.evidence_id}</small></span>
                  <span className={`record-status record-status--${item.status}`}>{words(item.status)}</span>
                </summary>
                <div className="record-body">
                  <dl>
                    <dt>{t('File status')}</dt><dd>{words(item.file_status)}</dd>
                    <dt>{t('Source')}</dt><dd>{words(item.source)}</dd>
                    {(readings[item.evidence_id] || readingAction(item)) && (
                      <>
                        <dt>{t(staffReadings.includes(item.evidence_id) ? 'Set by a handler as' : 'Assistant read it as')}</dt>
                        <dd className="reading-value">
                          <span>{readings[item.evidence_id] ? words(readings[item.evidence_id]) : t('Not read yet')}</span>
                          {onCorrectReading && readingAction(item) && <ReadingEditor item={item} action={readingAction(item)} onCorrect={onCorrectReading} />}
                        </dd>
                      </>
                    )}
                    <dt>{t('Responsible party')}</dt><dd>{words(item.responsible_party)}</dd>
                    <dt>{t('Needed for')}</dt><dd>{joinValues(item.needed_for)}</dd>
                    <dt>{t('Related fields')}</dt><dd>{joinValues(item.related_fields)}</dd>
                    <dt>{t('Expected')}</dt><dd>{item.expected_by ? formatDateTime(item.expected_by) : item.expected_timing || t('No timing recorded')}</dd>
                    <dt>{t('Updated')}</dt><dd>{formatDateTime(item.updated_at)}</dd>
                  </dl>
                  {item.context_summary && <p className="record-summary">{item.context_summary}</p>}
                  {item.claimant_note && <p className="record-note"><strong>{t('Claimant note')}</strong>{item.claimant_note}</p>}
                  <div className="record-actions">
                    <button className="button button--secondary" type="button" disabled={!canOpen || loadingId === item.evidence_id} onClick={() => load(item)}>
                      {loadingId === item.evidence_id ? <LoaderCircle className="spin" size={16} /> : <Eye size={16} />}
                      {t(loadingId === item.evidence_id ? 'Loading...' : 'View file')}
                    </button>
                    {!canOpen && <span>{t('No uploaded file is available for this evidence record.')}</span>}
                  </div>
                  {itemPreview && (
                    <div className="evidence-preview">
                      <div><strong>{itemPreview.filename}</strong><a className="button button--secondary" href={itemPreview.url} download={itemPreview.filename}><Download size={16} />{t('Download')}</a></div>
                      {itemPreview.mediaType.startsWith('image/') ? (
                        <img src={itemPreview.url} alt={t('Evidence preview: {filename}', { filename: itemPreview.filename })} />
                      ) : itemPreview.mediaType === 'application/pdf' ? (
                        <iframe src={itemPreview.url} title={t('Evidence preview: {filename}', { filename: itemPreview.filename })} />
                      ) : (
                        <p>{t('This file type can be downloaded for review.')}</p>
                      )}
                    </div>
                  )}
                </div>
              </details>
            )
          })}
        </div>
      ) : (
        <ResourceEmptyState
          icon={Files}
          title="No evidence records"
          description="Uploaded files and source-linked material will appear here once they are recorded."
        />
      )}
      <span className="sr-only">{t('Evidence for {claimId}', { claimId })}</span>
    </section>
  )
}

function joinValues(values) {
  return values?.length ? values.map(words).join(', ') : t('None recorded')
}
