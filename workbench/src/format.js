export function formatDateTime(value) {
  if (!value) return 'Not recorded'
  return new Intl.DateTimeFormat('en-NZ', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export function words(value) {
  if (!value) return 'Not confirmed'
  return String(value)
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function initials(value = '') {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('') || 'NW'
}
