import { Download, Eye, FileWarning, LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import { formatDateTime, words } from '../format.js'
import { translate as t } from '../i18n.js'

export default function EvidenceRecords({ claimId, records, readings = {}, onLoadEvidence }) {
  const [preview, setPreview] = useState(null)
  const [loadingId, setLoadingId] = useState(null)
  const [error, setError] = useState('')

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
    <section className="resource-view">
      <header className="content-header">
        <div><p className="eyebrow">{t('Files and source-linked records')}</p><h2>{t('Evidence')}</h2></div>
        <span>{t('{count} records', { count: records.length })}</span>
      </header>
      {error && <p className="inline-error" role="alert"><FileWarning size={16} />{error}</p>}
      <div className="record-list">
        {records.length ? records.map((item) => {
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
                  {readings[item.evidence_id] && <><dt>{t('Assistant read it as')}</dt><dd>{words(readings[item.evidence_id])}</dd></>}
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
        }) : <p className="empty-note">{t('No evidence records are available for this Claim.')}</p>}
      </div>
      <span className="sr-only">{t('Evidence for {claimId}', { claimId })}</span>
    </section>
  )
}

function joinValues(values) {
  return values?.length ? values.map(words).join(', ') : t('None recorded')
}
