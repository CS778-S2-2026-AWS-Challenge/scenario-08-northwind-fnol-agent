export function maskPolicyNumber(value = '') {
  const compact = value.replace(/\s/g, '')
  if (!compact) return 'Not provided'
  if (compact.length <= 4) return '••••'
  return `••••${compact.slice(-4)}`
}
