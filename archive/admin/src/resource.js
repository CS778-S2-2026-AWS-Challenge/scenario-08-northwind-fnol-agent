export function resourceId(item) {
  return item?.configuration_id || item?.knowledge_id || item?.evaluation_id || item?.operation_id || item?.integration_id || item?.customer_id || item?.staff_id || item?.event_id || item?.release_set_id || ''
}

export function resourceName(item) {
  return item?.label || item?.display_name || item?.domain || item?.title || item?.kind || item?.purpose || item?.role || item?.event_type || resourceId(item)
}
