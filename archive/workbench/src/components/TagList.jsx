import { Info } from 'lucide-react'

const CATEGORY_LABELS = {
  claim_type: 'Claim type',
  incident: 'Incident',
  people_safety: 'People and safety',
  stakeholder: 'Stakeholders',
  impact: 'Impact',
  evidence: 'Evidence',
  progress: 'Progress',
  attention: 'Needs attention',
}

export function TagList({ tags = [], limit, grouped = false }) {
  if (!tags.length) return <p className="empty-note">No source-backed tags are available yet.</p>
  const visible = typeof limit === 'number' ? tags.slice(0, limit) : tags

  if (!grouped) {
    return (
      <div className="tag-list" aria-label="Claim tags">
        {visible.map((tag) => <Tag key={tag.tag_instance_id} tag={tag} />)}
        {visible.length < tags.length && <span className="tag-more">+{tags.length - visible.length} more</span>}
      </div>
    )
  }

  const groups = Object.entries(
    visible.reduce((result, tag) => {
      result[tag.category] ||= []
      result[tag.category].push(tag)
      return result
    }, {}),
  )
  return (
    <div className="tag-groups">
      {groups.map(([category, values]) => (
        <section className="tag-group" key={category}>
          <h4>{CATEGORY_LABELS[category] || category}</h4>
          <div className="tag-list">
            {values.map((tag) => <Tag key={tag.tag_instance_id} tag={tag} expanded />)}
          </div>
        </section>
      ))}
    </div>
  )
}

function Tag({ tag, expanded = false }) {
  const title = `${tag.description}\nBasis: ${tag.basis}\nSources: ${tag.source_refs.join(', ')}`
  return (
    <span className={`tag tag--${tag.category}`} title={title}>
      {tag.label}
      {expanded && <Info size={13} aria-label={`Source details for ${tag.label}`} />}
    </span>
  )
}
