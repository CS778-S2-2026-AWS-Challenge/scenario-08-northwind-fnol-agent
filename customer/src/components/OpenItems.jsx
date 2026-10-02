import { useEffect, useRef, useState } from 'react'

import {
  claimantOwedItems,
  openItemGroups,
  openItemStatusText,
  openItemTitle,
  openItemsBarText,
} from '../openItems.js'

// What is still owed on the Claim, from claim.open_items. The bar sits above
// the composer whenever something is outstanding; the section lists every item
// in the case panel. Receipts are chips under the reply (TurnAttachments).

function UploadButton({ item, label = 'Upload', onUpload, busy }) {
  const input = useRef(null)
  if (!onUpload) return null
  return (
    <>
      <input
        ref={input}
        className="sr-only"
        type="file"
        accept="image/jpeg,image/png,application/pdf"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onUpload(item, file)
          event.target.value = ''
        }}
      />
      <button
        className="open-item-upload"
        type="button"
        disabled={busy}
        onClick={() => input.current?.click()}
      >
        {label}
      </button>
    </>
  )
}

const RECEIVED_NOTICE_MS = 2000

export function OpenItemsBar({ items, onUpload, onOpenPanel, busy }) {
  // A document that arrives stays as "Received" for a moment before the bar folds.
  const [received, setReceived] = useState(null)
  const owedBefore = useRef(new Set())
  useEffect(() => {
    const arrived = (items || []).find((item) => (
      item.state === 'done' && owedBefore.current.has(item.item_id)
    ))
    owedBefore.current = new Set(claimantOwedItems(items).map((item) => item.item_id))
    if (!arrived) return undefined
    setReceived(openItemTitle(arrived))
    const timer = setTimeout(() => setReceived(null), RECEIVED_NOTICE_MS)
    return () => clearTimeout(timer)
  }, [items])

  const text = openItemsBarText(items)
  if (!text && received) {
    return (
      <div className="open-items-bar is-done" role="status">
        <span className="open-items-bar-mark" aria-hidden="true">✓</span>
        <span className="open-items-bar-text">{`Received: ${received}`}</span>
      </div>
    )
  }
  if (!text) return null
  const owed = claimantOwedItems(items)
  return (
    <div className="open-items-bar" role="status">
      <span className="open-items-bar-mark" aria-hidden="true">●</span>
      <span className="open-items-bar-text">{text}</span>
      {owed.length === 1 && (
        <UploadButton item={owed[0]} onUpload={onUpload} busy={busy} />
      )}
      <button className="open-items-bar-view" type="button" onClick={onOpenPanel}>
        View
      </button>
    </div>
  )
}

export function OpenItemsSection({ items, onUpload, busy }) {
  const groups = openItemGroups(items)
  if (groups.length === 0) return null
  return (
    <section className="case-panel-section" id="case-panel-open-items" aria-labelledby="case-open-items-title">
      <h3 id="case-open-items-title">Still to do</h3>
      {groups.map((group) => (
        <div className="open-item-group" key={group.key}>
          <h4>{group.title}</h4>
          <ul className="open-item-list">
            {group.items.map((item) => (
              <li className={`open-item is-${item.state}`} key={item.item_id}>
                <span className="open-item-mark" aria-hidden="true">
                  {item.state === 'open' ? '○' : '✓'}
                </span>
                <span className="open-item-copy">
                  <strong>{openItemTitle(item)}</strong>
                  <small>{openItemStatusText(item)}</small>
                  {item.answer && <span className="open-item-answer">{item.answer}</span>}
                </span>
                {item.kind === 'document' && item.owner === 'claimant' && item.state === 'open' && (
                  <UploadButton item={item} onUpload={onUpload} busy={busy} />
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  )
}
