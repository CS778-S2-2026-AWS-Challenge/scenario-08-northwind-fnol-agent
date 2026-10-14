import { languageLocale, translate } from './i18n.js'

export function formatDateTime(value) {
  if (!value) return translate('Not recorded')
  return new Intl.DateTimeFormat(languageLocale(), {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export function formatCompactDateTime(value) {
  if (!value) return translate('Not recorded')
  const date = new Intl.DateTimeFormat(languageLocale(), {
    day: 'numeric',
    month: 'short',
    year: '2-digit',
  }).format(new Date(value))
  return `${date} · ${formatTime(value)}`
}

export function formatQueueDateTime(value) {
  if (!value) return translate('Not recorded')
  const dateParts = new Intl.DateTimeFormat(languageLocale(), {
    day: 'numeric',
    month: 'short',
  }).formatToParts(new Date(value))
  const day = dateParts.find((part) => part.type === 'day')?.value
  const month = dateParts.find((part) => part.type === 'month')?.value.slice(0, 3)
  const time = new Intl.DateTimeFormat(languageLocale(), {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
  return `${day} ${month} · ${time}`
}

export function formatDate(value) {
  if (!value) return translate('Not recorded')
  return new Intl.DateTimeFormat(languageLocale(), {
    dateStyle: 'medium',
  }).format(new Date(value))
}

export function formatTime(value) {
  if (!value) return translate('Not recorded')
  return new Intl.DateTimeFormat(languageLocale(), {
    timeStyle: 'short',
  }).format(new Date(value))
}

const CLAIM_FIELD_CURRENCIES = new Map([
  ['loss.estimated_amount', 'NZD'],
])

const DATE_ONLY_VALUE = /^\d{4}-\d{2}-\d{2}$/
const ISO_DATE_TIME_VALUE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/
const TEMPORAL_FIELD_CODE = /(?:^|\.)(?:.*_at|.*_date|date|time)$/
const ENUM_VALUE = /^[a-z]+(?:_[a-z]+)*$/
const ENUM_FIELD_CODE = /(?:^|\.)(?:.*_)?(?:category|condition|family|kind|method|permission|preference|role|severity|state|status|type)$/

export function isClaimFieldValuePresent(value) {
  if (value === null || value === undefined) return false
  if (typeof value === 'string') return value.trim().length > 0
  if (Array.isArray(value)) return value.some(isClaimFieldValuePresent)
  if (typeof value === 'object') return Object.values(value).some(isClaimFieldValuePresent)
  return true
}

export function formatClaimFieldValue(code, value) {
  if (!isClaimFieldValuePresent(value)) return translate('Not recorded')
  if (typeof value === 'boolean') return translate(value ? 'Yes' : 'No')
  if (typeof value === 'number') {
    const currency = CLAIM_FIELD_CURRENCIES.get(code)
    return currency ? formatCurrency(value, currency) : new Intl.NumberFormat(languageLocale()).format(value)
  }
  if (Array.isArray(value)) return formatClaimFieldCollection(code, value)
  if (typeof value === 'object') return formatClaimFieldObject(code, value)

  const temporalValue = formatTemporalFieldValue(code, value)
  if (temporalValue) return temporalValue
  if (ENUM_VALUE.test(value) && (value.includes('_') || ENUM_FIELD_CODE.test(code))) {
    return translate(words(value))
  }
  return value
}

function formatClaimFieldCollection(code, values) {
  const presentValues = values.filter(isClaimFieldValuePresent)
  const containsStructure = presentValues.some((value) => typeof value === 'object')
  const formatted = presentValues.map((value, index) => {
    const item = formatClaimFieldValue(`${code}.${index + 1}`, value)
    return containsStructure ? `${index + 1}. ${item}` : item
  })
  return formatted.join(containsStructure ? '\n' : ', ')
}

function formatClaimFieldObject(code, value) {
  const keys = Object.keys(value)
  const isMoney = keys.length > 0
    && keys.every((key) => key === 'amount' || key === 'currency')
    && typeof value.amount === 'number'
    && typeof value.currency === 'string'
  if (isMoney) {
    return formatCurrency(value.amount, value.currency)
  }

  return Object.entries(value)
    .filter(([, entryValue]) => isClaimFieldValuePresent(entryValue))
    .map(([key, entryValue]) => (
      `${translate(words(key))}: ${formatClaimFieldValue(`${code}.${key}`, entryValue)}`
    ))
    .join('\n')
}

function formatTemporalFieldValue(code, value) {
  if (typeof value !== 'string' || !TEMPORAL_FIELD_CODE.test(code)) return null
  if (!DATE_ONLY_VALUE.test(value) && !ISO_DATE_TIME_VALUE.test(value)) return null
  if (Number.isNaN(new Date(value).getTime())) return null
  if (!DATE_ONLY_VALUE.test(value)) return formatDateTime(value)
  return new Intl.DateTimeFormat(languageLocale(), {
    dateStyle: 'medium',
    timeZone: 'UTC',
  }).format(new Date(`${value}T00:00:00Z`))
}

function formatCurrency(amount, currency) {
  try {
    return new Intl.NumberFormat(languageLocale(), {
      style: 'currency',
      currency,
      currencyDisplay: 'narrowSymbol',
    }).format(amount)
  } catch {
    return `${new Intl.NumberFormat(languageLocale()).format(amount)} ${currency}`
  }
}

export function words(value) {
  if (!value) return translate('Not confirmed')
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
