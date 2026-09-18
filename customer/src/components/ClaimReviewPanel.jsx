import { claimReviewRequirements, claimReviewSections } from '../claimReviewProjection.js'
import './ClaimReviewPanel.css'

function ContentsReviewItem({ item, fieldSourceLabel, fieldStatusLabel }) {
  return (
    <div className="claim-field" data-review-item={item.item_id}>
      <div className="field-heading">
        <span>{item.description}</span>
        <span className={`field-status status-${item.status}`}>
          {fieldStatusLabel(item.status)}
        </span>
      </div>
      {item.category && <p className="field-value">{item.category}</p>}
      <p className="field-source">{fieldSourceLabel(item.source)}</p>
    </div>
  )
}

export default function ClaimReviewPanel({
  form,
  contentsItems,
  dynamicForm,
  proposedFields,
  proposedContentsItems,
  editingField,
  editValue,
  setEditValue,
  beginEdit,
  cancelEdit,
  saveFieldCorrection,
  confirmProposedFields,
  fieldLabel,
  fieldStatusLabel,
  fieldSourceLabel,
  fieldValueText,
  busy,
  status,
  stepActive,
}) {
  const sections = claimReviewSections(form, contentsItems)
  const requirements = claimReviewRequirements(dynamicForm)
  const hasReviewItems = sections.length > 0

  return (
    <>
      <div className="claim-details-section-heading">
        {stepActive && <p className="eyebrow">Step 2 of 4 · Review information</p>}
        <h3>{stepActive ? 'Check your claim information' : 'What we have so far'}</h3>
        <p className="panel-subtitle">Review or correct anything here</p>
      </div>

      {requirements.available && requirements.missingRequiredNow.length > 0 && (
        <section
          className="confirmation-bar"
          aria-labelledby="claim-review-missing-title"
          role="alert"
        >
          <p className="confirmation-kicker">Required before you can continue</p>
          <h2 id="claim-review-missing-title">Still needed</h2>
          <ul className="confirmation-list">
            {requirements.missingRequiredNow.map((fieldCode) => (
              <li key={fieldCode}>{fieldLabel(fieldCode)}</li>
            ))}
          </ul>
          <p>Add these details in the conversation. This review updates from the shared Claim state.</p>
        </section>
      )}

      {!hasReviewItems ? (
        <p className="empty-details">Details from your conversation will appear here.</p>
      ) : (
        <div className="field-list">
          {sections.map((section) => (
            <section className="claim-review-section" key={section.id} aria-labelledby={`claim-review-${section.id}-title`}>
              <h4 id={`claim-review-${section.id}-title`}>{section.title}</h4>
              {section.fields.map(([fieldCode, field]) => (
                <div className="claim-field" key={fieldCode} data-review-field={fieldCode}>
                  <div className="field-heading">
                    <span>{fieldLabel(fieldCode)}</span>
                    <span className={`field-status status-${field.status}`}>
                      {fieldStatusLabel(field.status)}
                    </span>
                  </div>
                  {editingField === fieldCode ? (
                    <div className="field-editor">
                      <textarea
                        aria-label={`Correct ${fieldLabel(fieldCode)}`}
                        value={editValue}
                        onChange={(event) => setEditValue(event.target.value)}
                        rows="3"
                      />
                      <div className="field-actions">
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={cancelEdit}
                          disabled={busy}
                        >
                          Cancel
                        </button>
                        <button
                          className="primary-button compact-button"
                          type="button"
                          onClick={() => saveFieldCorrection(fieldCode, field)}
                          disabled={!editValue.trim() || busy}
                        >
                          {status === 'saving' ? 'Saving...' : 'Save correction'}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="field-value">{fieldValueText(field)}</p>
                      <p className="field-source">{fieldSourceLabel(field.source)}</p>
                      <button
                        className="text-button"
                        type="button"
                        onClick={() => beginEdit(fieldCode, field.value)}
                        disabled={busy}
                      >
                        Edit
                      </button>
                    </>
                  )}
                </div>
              ))}
              {section.contentsItems.map((item) => (
                <ContentsReviewItem
                  key={item.item_id}
                  item={item}
                  fieldSourceLabel={fieldSourceLabel}
                  fieldStatusLabel={fieldStatusLabel}
                />
              ))}
            </section>
          ))}
        </div>
      )}

      {(proposedFields.length > 0 || proposedContentsItems.length > 0) && editingField === null && (
        <section className="confirmation-bar" aria-labelledby="confirmation-title">
          <p className="confirmation-kicker">Review before we continue</p>
          <h2 id="confirmation-title">Check these details</h2>
          <ul className="confirmation-list">
            {proposedFields.map(([fieldCode]) => (
              <li key={fieldCode}>{fieldLabel(fieldCode)} needs your review.</li>
            ))}
            {proposedContentsItems.map((item) => (
              <li key={item.item_id}>{item.description} needs your review.</li>
            ))}
          </ul>
          <p>Use the conversation to correct anything in your own words, or edit a detail here.</p>
          <button
            className="primary-button"
            type="button"
            onClick={confirmProposedFields}
            disabled={busy}
          >
            {status === 'confirming' ? 'Confirming...' : 'Confirm details'}
          </button>
        </section>
      )}
    </>
  )
}