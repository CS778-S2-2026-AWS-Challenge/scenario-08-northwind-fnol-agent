import { ChevronDown, X } from 'lucide-react'
import { useState } from 'react'

export default function ClaimTabs({ tabs, activeId, onActivate, onClose }) {
  const [showList, setShowList] = useState(false)
  if (!tabs.length) return null

  return (
    <div className="claim-tabs-wrap">
      <div className="claim-tabs" role="tablist" aria-label="Open claims">
        {tabs.map((tab, index) => (
          <div className={`claim-tab${tab.claimId === activeId ? ' is-active' : ''}`} key={tab.claimId}>
            <button
              type="button"
              role="tab"
              id={`open-claim-tab-${tab.claimId}`}
              aria-controls="open-claim-panel"
              aria-selected={tab.claimId === activeId}
              tabIndex={tab.claimId === activeId ? 0 : -1}
              onClick={() => onActivate(tab.claimId)}
              onKeyDown={(event) => moveClaimTabFocus(event, tabs, index, onActivate, onClose)}
            >
              {tab.label}
              {tab.draft && <span className="draft-dot" title="Unsent draft" />}
            </button>
            <button type="button" className="icon-button icon-button--small" onClick={() => onClose(tab.claimId)} aria-label={`Close ${tab.label}`}>
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
      <button className="icon-button tab-overflow" type="button" onClick={() => setShowList((value) => !value)} aria-expanded={showList} aria-controls="open-claim-list" aria-label="Show all open claims">
        <ChevronDown size={17} />
      </button>
      {showList && (
        <div className="tab-menu" id="open-claim-list">
          {tabs.map((tab) => (
            <button type="button" key={tab.claimId} onClick={() => { onActivate(tab.claimId); setShowList(false) }}>
              {tab.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function moveClaimTabFocus(event, tabs, currentIndex, onActivate, onClose) {
  if (event.key === 'Delete') {
    event.preventDefault()
    onClose(tabs[currentIndex].claimId)
    return
  }
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  let nextIndex = currentIndex
  if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length
  if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % tabs.length
  if (event.key === 'Home') nextIndex = 0
  if (event.key === 'End') nextIndex = tabs.length - 1
  onActivate(tabs[nextIndex].claimId)
  event.currentTarget.closest('[role="tablist"]')?.querySelectorAll('[role="tab"]')[nextIndex]?.focus()
}
