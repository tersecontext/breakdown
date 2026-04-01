import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createTask, getBranches, listRepos } from '../api'
import Nav from '../components/Nav'
import type { RepoInfo } from '../types'

export default function Submit() {
  const navigate = useNavigate()
  const [repos, setRepos] = useState<RepoInfo[]>([])
  const [branches, setBranches] = useState<string[]>([])
  const [repo, setRepo] = useState('')
  const [branch, setBranch] = useState('main')
  const [featureName, setFeatureName] = useState('')
  const [description, setDescription] = useState('')
  const [contextInput, setContextInput] = useState('')
  const [contextPills, setContextPills] = useState<string[]>([])
  const [showOptional, setShowOptional] = useState(false)
  const [scopeNotes, setScopeNotes] = useState('')
  const [archNotes, setArchNotes] = useState('')
  const [constraints, setConstraints] = useState('')
  const [testingNotes, setTestingNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    listRepos().then(r => {
      setRepos(r)
      if (r.length > 0) setRepo(r[0].name)
    })
  }, [])

  useEffect(() => {
    if (!repo) return
    getBranches(repo).then(b => {
      setBranches(b)
      setBranch(b.includes('main') ? 'main' : (b[0] ?? ''))
    })
  }, [repo])

  function addPill() {
    const val = contextInput.trim()
    if (val && !contextPills.includes(val)) {
      setContextPills(p => [...p, val])
    }
    setContextInput('')
  }

  function removePill(pill: string) {
    setContextPills(p => p.filter(x => x !== pill))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError('')
    const optional_answers: Record<string, string> = {}
    if (scopeNotes) optional_answers.scope_notes = scopeNotes
    if (archNotes) optional_answers.architecture_notes = archNotes
    if (constraints) optional_answers.constraints = constraints
    if (testingNotes) optional_answers.testing_notes = testingNotes
    try {
      const task = await createTask({
        feature_name: featureName,
        description,
        repo,
        branch_from: branch,
        additional_context: contextPills,
        optional_answers,
      })
      navigate(`/tasks/${task.id}`)
    } catch (err) {
      setError(String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const selectedRepo = repos.find(r => r.name === repo)

  return (
    <>
      <Nav />
      <div style={{ maxWidth: 640, margin: '32px auto', padding: '0 16px' }}>
        <h2 style={{ marginBottom: 24 }}>New Feature Request</h2>
        <form onSubmit={handleSubmit} style={{
          background: '#fff', padding: 24, borderRadius: 8,
          boxShadow: '0 2px 8px rgba(0,0,0,.08)', display: 'flex', flexDirection: 'column', gap: 18,
        }}>
          {/* Repo selector */}
          <div>
            <label style={labelStyle}>Repository</label>
            <select value={repo} onChange={e => setRepo(e.target.value)} style={inputStyle}>
              {repos.map(r => (
                <option key={r.name} value={r.name}>{r.name}</option>
              ))}
            </select>
            {selectedRepo && (
              <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  backgroundColor: selectedRepo.tc_indexed ? '#16a34a' : '#dc2626',
                  display: 'inline-block',
                }} />
                {selectedRepo.tc_indexed
                  ? `${selectedRepo.tc_node_count ?? '?'} nodes · last indexed ${selectedRepo.tc_last_indexed ? new Date(selectedRepo.tc_last_indexed).toLocaleDateString() : 'unknown'}`
                  : 'Not indexed'}
              </div>
            )}
          </div>
          {/* Branch */}
          <div>
            <label style={labelStyle}>Branch from</label>
            <select value={branch} onChange={e => setBranch(e.target.value)} style={inputStyle}>
              {branches.map(b => <option key={b} value={b}>{b}</option>)}
            </select>
          </div>
          {/* Feature name */}
          <div>
            <label style={labelStyle}>Feature name</label>
            <input value={featureName} onChange={e => setFeatureName(e.target.value)}
              placeholder="Short name for the feature" required style={inputStyle} />
          </div>
          {/* Description */}
          <div>
            <label style={labelStyle}>Description</label>
            <textarea value={description} onChange={e => setDescription(e.target.value)}
              rows={4} placeholder="Describe what you want to build" required
              style={{ ...inputStyle, resize: 'vertical' }} />
          </div>
          {/* Additional context pills */}
          <div>
            <label style={labelStyle}>Additional context (file paths)</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input value={contextInput} onChange={e => setContextInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addPill())}
                placeholder="src/path/to/file.py" style={{ ...inputStyle, flex: 1, marginBottom: 0 }} />
              <button type="button" onClick={addPill}
                style={{ padding: '8px 14px', borderRadius: 4, border: '1px solid #d1d5db', background: '#f9fafb', fontSize: 14 }}>
                Add
              </button>
            </div>
            {contextPills.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                {contextPills.map(p => (
                  <span key={p} style={{
                    background: '#e5e7eb', borderRadius: 4, padding: '3px 8px',
                    fontSize: 13, display: 'flex', alignItems: 'center', gap: 4,
                  }}>
                    {p}
                    <button type="button" onClick={() => removePill(p)}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280', fontSize: 15, lineHeight: 1, padding: 0 }}>
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
          {/* Optional collapsible */}
          <div>
            <button type="button" onClick={() => setShowOptional(s => !s)}
              style={{ background: 'none', border: 'none', color: '#2563eb', fontSize: 14, padding: 0, fontWeight: 500 }}>
              {showOptional ? '▲ Hide' : '▼ Add more context'}
            </button>
            {showOptional && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 14 }}>
                <div>
                  <label style={labelStyle}>Scope notes</label>
                  <textarea value={scopeNotes} onChange={e => setScopeNotes(e.target.value)}
                    rows={2} style={{ ...inputStyle, resize: 'vertical' }} />
                </div>
                <div>
                  <label style={labelStyle}>Architecture notes</label>
                  <textarea value={archNotes} onChange={e => setArchNotes(e.target.value)}
                    rows={2} style={{ ...inputStyle, resize: 'vertical' }} />
                </div>
                <div>
                  <label style={labelStyle}>Constraints</label>
                  <textarea value={constraints} onChange={e => setConstraints(e.target.value)}
                    rows={2} style={{ ...inputStyle, resize: 'vertical' }} />
                </div>
                <div>
                  <label style={labelStyle}>Testing notes</label>
                  <textarea value={testingNotes} onChange={e => setTestingNotes(e.target.value)}
                    rows={2} style={{ ...inputStyle, resize: 'vertical' }} />
                </div>
              </div>
            )}
          </div>
          {error && <p style={{ color: '#dc2626', fontSize: 13, margin: 0 }}>{error}</p>}
          <button type="submit" disabled={submitting} style={{
            padding: '10px 0', borderRadius: 4, background: '#111',
            color: '#fff', border: 'none', fontSize: 15, fontWeight: 500,
            opacity: submitting ? 0.5 : 1,
          }}>
            {submitting ? 'Submitting…' : 'Submit'}
          </button>
        </form>
      </div>
    </>
  )
}

const labelStyle: React.CSSProperties = {
  display: 'block', marginBottom: 6, fontSize: 14, fontWeight: 500,
}

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '8px 12px', borderRadius: 4,
  border: '1px solid #d1d5db', fontSize: 14, marginBottom: 0,
  background: '#fff',
}
