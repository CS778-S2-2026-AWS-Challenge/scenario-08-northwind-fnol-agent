export function normalizePhone(value) {
  return value.trim().replaceAll(/\s+/g, ' ')
}

export function validateProfile(values) {
  const errors = {}
  const displayName = values.displayName.trim()
  const email = values.email.trim()
  const phone = normalizePhone(values.phone)

  if (!displayName) errors.displayName = 'Enter the staff member name.'
  if (!email) errors.email = 'Enter a work email address.'
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    errors.email = 'Enter a valid work email address, such as name@example.com.'
  }

  if (phone) {
    const digits = phone.replaceAll(/\D/g, '')
    if (!/^\+?[0-9()\-\s]+$/.test(phone) || digits.length < 7 || digits.length > 15) {
      errors.phone = 'Enter a valid phone number with 7 to 15 digits.'
    }
  }

  return {
    errors,
    values: { displayName, email, phone },
  }
}
