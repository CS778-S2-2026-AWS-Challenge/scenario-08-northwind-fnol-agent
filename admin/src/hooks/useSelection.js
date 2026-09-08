import { useState } from 'react'
import { resourceId } from '../resource.js'

export default function useSelection(items) {
  const [selectedId, setSelectedId] = useState('')
  const selected = items.find((item) => resourceId(item) === selectedId) || null
  const select = (item) => setSelectedId(resourceId(item))
  return [selected, select]
}
