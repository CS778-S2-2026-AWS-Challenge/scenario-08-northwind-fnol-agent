const WORK_PRIORITY_LEVELS = new Set(['routine', 'standard', 'high', 'urgent', 'immediate'])
const MISSING_INFORMATION_ATTENTION = new Set(['required_now', 'needed_next', 'follow_up'])
const RISK_ATTENTION_LEVELS = new Set(['notice', 'review_required', 'urgent_review', 'immediate_action'])

function assertEnumMember(value, allowedValues, path) {
  if (!allowedValues.has(value)) {
    throw new TypeError(`Browser acceptance fixture has invalid ${path}: ${value}`)
  }
}

export function assertWorkbenchFixtureContract(detail) {
  assertEnumMember(detail.priority_projection.level, WORK_PRIORITY_LEVELS, 'priority_projection.level')

  for (const [index, item] of detail.work_summary.missing_information.entries()) {
    assertEnumMember(item.attention, MISSING_INFORMATION_ATTENTION, `missing_information[${index}].attention`)
  }

  for (const [index, signal] of detail.work_summary.risk_signals.entries()) {
    assertEnumMember(signal.attention_level, RISK_ATTENTION_LEVELS, `risk_signals[${index}].attention_level`)
  }

  return detail
}
