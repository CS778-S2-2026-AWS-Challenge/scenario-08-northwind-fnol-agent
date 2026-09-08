export function findProjectedAction(actions = [], actionCode, targetRef) {
  if (!actionCode || !targetRef) return undefined
  return actions.find((action) => (
    action.action_code === actionCode && action.target_ref === targetRef
  ))
}

export function canSubmitProjectedAction(action) {
  return ['available', 'confirmation_required'].includes(action?.availability)
}

export function findPrimaryProjectedAction(actions = [], actionCode, targetRef) {
  const action = findProjectedAction(actions, actionCode, targetRef)
  return canSubmitProjectedAction(action) ? action : undefined
}

export function isProjectedInputRequired(input, values) {
  return input.required || (
    input.required_when
    && values[input.required_when.field_code] === input.required_when.equals
  )
}
