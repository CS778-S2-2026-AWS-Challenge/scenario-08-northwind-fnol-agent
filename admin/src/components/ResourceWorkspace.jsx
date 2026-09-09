import DetailPanel from './DetailPanel.jsx'
import ResourceList from './ResourceList.jsx'
import { resourceId } from '../resource.js'

export default function ResourceWorkspace({ label, items, selected, onSelect, children, emptyMessage }) {
  return (
    <div className="resource-layout">
      <ResourceList title={label} items={items} selectedId={resourceId(selected)} onSelect={onSelect} emptyMessage={emptyMessage} />
      <DetailPanel title={label} item={selected}>{selected && children}</DetailPanel>
    </div>
  )
}
