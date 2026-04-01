import type { ResearchOutput } from '../types'

const CHANGE_COLORS: Record<string, string> = {
  create: '#16a34a',
  modify: '#d97706',
  delete: '#dc2626',
}

export default function ResearchView({ research }: { research: ResearchOutput }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Summary */}
      <section>
        <h3 style={sectionHeading}>Summary</h3>
        <p style={{ margin: 0, lineHeight: 1.6 }}>{research.summary}</p>
      </section>

      {/* Affected code */}
      <section>
        <h3 style={sectionHeading}>Affected Files</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {research.affected_code.map((f, i) => (
            <div key={i} style={{
              background: '#f9fafb', borderRadius: 6, padding: '10px 14px',
              display: 'flex', alignItems: 'flex-start', gap: 10,
            }}>
              <span style={{
                display: 'inline-block', padding: '2px 7px', borderRadius: 4,
                fontSize: 11, fontWeight: 600, color: '#fff',
                backgroundColor: CHANGE_COLORS[f.change_type] ?? '#6b7280',
                textTransform: 'uppercase', whiteSpace: 'nowrap', marginTop: 2,
              }}>
                {f.change_type}
              </span>
              <div>
                <code style={{ fontSize: 13, fontWeight: 600 }}>{f.file}</code>
                <p style={{ margin: '4px 0 0', fontSize: 13, color: '#6b7280' }}>{f.description}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Complexity */}
      <section>
        <h3 style={sectionHeading}>Complexity</h3>
        <div style={{
          background: '#f9fafb', borderRadius: 8, padding: '16px 20px',
          display: 'flex', gap: 20, alignItems: 'flex-start',
        }}>
          <div style={{ textAlign: 'center', minWidth: 60 }}>
            <div style={{ fontSize: 40, fontWeight: 700, lineHeight: 1 }}>
              {research.complexity.score}
            </div>
            <span style={{
              display: 'inline-block', marginTop: 4, padding: '2px 8px', borderRadius: 4,
              fontSize: 11, fontWeight: 600, color: '#fff', textTransform: 'uppercase',
              backgroundColor: { low: '#16a34a', medium: '#d97706', high: '#dc2626' }[research.complexity.label] ?? '#6b7280',
            }}>
              {research.complexity.label}
            </span>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
              Estimated effort: {research.complexity.estimated_effort}
            </div>
            <p style={{ margin: 0, fontSize: 13, color: '#6b7280', lineHeight: 1.5 }}>
              {research.complexity.reasoning}
            </p>
          </div>
        </div>
      </section>

      {/* Metrics */}
      <section>
        <h3 style={sectionHeading}>Metrics</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 16 }}>
          {[
            ['Files affected', research.metrics.files_affected],
            ['Files created', research.metrics.files_created],
            ['Files modified', research.metrics.files_modified],
            ['Services affected', research.metrics.services_affected],
            ['Contract changes', research.metrics.contract_changes ? 'Yes' : 'No'],
          ].map(([label, value]) => (
            <div key={label as string} style={{
              background: '#f9fafb', borderRadius: 6, padding: '10px 14px',
              fontSize: 13,
            }}>
              <div style={{ color: '#6b7280', marginBottom: 2 }}>{label}</div>
              <div style={{ fontWeight: 600 }}>{value}</div>
            </div>
          ))}
        </div>
        {research.metrics.new_dependencies.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>New dependencies</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {research.metrics.new_dependencies.map(dep => (
                <span key={dep} style={{
                  background: '#dbeafe', color: '#1d4ed8', borderRadius: 4,
                  padding: '2px 8px', fontSize: 12, fontWeight: 500,
                }}>
                  {dep}
                </span>
              ))}
            </div>
          </div>
        )}
        {research.metrics.risk_areas.length > 0 && (
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Risk areas</div>
            <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13, color: '#6b7280', lineHeight: 1.8 }}>
              {research.metrics.risk_areas.map(r => <li key={r}>{r}</li>)}
            </ul>
          </div>
        )}
      </section>
    </div>
  )
}

const sectionHeading: React.CSSProperties = {
  fontSize: 15, fontWeight: 600, margin: '0 0 12px', color: '#374151',
}
