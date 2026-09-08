export function parseJson(value, label) {
  try {
    return JSON.parse(value)
  } catch {
    throw new Error(`${label} must contain valid JSON.`)
  }
}
