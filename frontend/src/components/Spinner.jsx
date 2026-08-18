export default function Spinner({ className = 'h-4 w-4', color = 'currentColor' }) {
  return (
    <svg
      className={className}
      style={{ animation: 'spin-slow 0.8s linear infinite' }}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" stroke={color} strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke={color} strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}
