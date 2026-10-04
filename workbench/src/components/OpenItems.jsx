import { translate as t } from '../i18n.js'
import { openWaitingCount, waitingListItems } from '../waiting-list.js'

// What the claimant, Northwind or a third party still owes on this Claim, from
// the server's open-item projection. Questions and contact requests are settled
// on the Waiting list page; this list points there.

const OWNER_LABELS = {
  claimant: 'Claimant will send',
  northwind: 'Question for Northwind',
  third_party: 'Northwind is obtaining',
}

const STATE_LABELS = {
  open: 'Open',
  done: 'Done',
  not_available: 'Claimant does not have it',
}

function itemTitle(item) {
  return item.kind === 'question' ? item.subject : item.subject.replaceAll('_', ' ')
}

export default function OpenItems({ items = [], onOpenWaitingList }) {
  const waiting = new Set(waitingListItems(items).map((item) => item.item_id))
  const documents = items.filter((item) => !waiting.has(item.item_id))
  const waitingOpen = openWaitingCount(items)
  if (documents.length === 0 && waiting.size === 0) return null
  const openCount = documents.filter((item) => item.state === 'open').length
  return (
    <section className="detail-section" aria-labelledby="open-items-title">
      <div className="section-heading">
        <div><p className="eyebrow">{t('Open items')}</p><h2 id="open-items-title">{t('Still owed on this Claim')}</h2></div>
        <span className="count-badge">{openCount}</span>
      </div>
      {waitingOpen > 0 && onOpenWaitingList && (
        <p className="waiting-list-pointer">
          <span>{t('{count} items on the waiting list', { count: waitingOpen })}</span>
          <button className="button button--secondary" type="button" onClick={onOpenWaitingList}>{t('Open waiting list')}</button>
        </p>
      )}
      <ul className="open-item-records">
        {documents.map((item) => (
          <li className="open-item-record" key={item.item_id}>
            <div className="open-item-record__heading">
              <strong>{itemTitle(item)}</strong>
              <span className="status-pill">{t(STATE_LABELS[item.state] || item.state)}</span>
            </div>
            <p className="record-meta">{t(OWNER_LABELS[item.owner] || item.owner)}{item.service_identity ? ` · ${item.service_identity}` : ''}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}
