export function formatDateTime(value) {
  if (!value) return 'Not recorded'
  return new Intl.DateTimeFormat('en-NZ', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export function formatCompactDateTime(value) {
  if (!value) return 'Not recorded'
  const date = new Intl.DateTimeFormat('en-NZ', {
    day: 'numeric',
    month: 'short',
    year: '2-digit',
  }).format(new Date(value))
  return `${date} · ${formatTime(value)}`
}

export function formatQueueDateTime(value) {
  if (!value) return 'Not recorded'
  const dateParts = new Intl.DateTimeFormat('en-NZ', {
    day: 'numeric',
    month: 'short',
  }).formatToParts(new Date(value))
  const day = dateParts.find((part) => part.type === 'day')?.value
  const month = dateParts.find((part) => part.type === 'month')?.value.slice(0, 3)
  const time = new Intl.DateTimeFormat('en-NZ', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
  return `${day} ${month} · ${time}`
}

export function formatDate(value) {
  if (!value) return 'Not recorded'
  return new Intl.DateTimeFormat('en-NZ', {
    dateStyle: 'medium',
  }).format(new Date(value))
}

export function formatTime(value) {
  if (!value) return 'Not recorded'
  return new Intl.DateTimeFormat('en-NZ', {
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
