const STATE_COLORS: Record<string, string> = {
  submitted: '#6b7280',
  researching: '#d97706',
  researched: '#2563eb',
  approved: '#16a34a',
  rejected: '#dc2626',
  failed: '#dc2626',
}

export default function StateBadge({ state }: { state: string }) {
  const color = STATE_COLORS[state] ?? '#6b7280'
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 4,
      fontSize: 12,
      fontWeight: 600,
      color: '#fff',
      backgroundColor: color,
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
    }}>
      {state}
    </span>
  )
}
