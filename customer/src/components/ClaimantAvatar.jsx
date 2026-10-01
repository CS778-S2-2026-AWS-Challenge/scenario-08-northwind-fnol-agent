// Signed-in claimants see their initials; anonymous claimants see a generic
// person icon rather than placeholder letters.
export default function ClaimantAvatar({ displayName, className }) {
  const initials = displayName?.trim().slice(0, 2).toUpperCase()
  return (
    <span className={`${className} ${initials ? '' : 'is-anonymous'}`.trim()} aria-hidden="true">
      {initials || (
        <svg className="claimant-avatar-icon" viewBox="0 0 24 24" data-testid="anonymous-avatar">
          <circle cx="12" cy="8" r="4" />
          <path d="M4 20c0-4 3.6-6 8-6s8 2 8 6" />
        </svg>
      )}
    </span>
  )
}
