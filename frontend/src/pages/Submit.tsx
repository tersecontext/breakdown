import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createTask, getBranches, indexRepo, listRepos } from '../api'
import Nav from '../components/Nav'
import type { RepoInfo } from '../types'

const MAX_FILE_SIZE = 512 * 1024 // 512 KB

async function extractText(file: File): Promise<string> {
  if (file.type === 'application/pdf') {
    const pdfjsLib = await import('pdfjs-dist')
    pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
      'pdfjs-dist/build/pdf.worker.mjs',
      import.meta.url,
    ).toString()
    const buffer = await file.arrayBuffer()
    const pdf = await pdfjsLib.getDocument({ data: buffer }).promise
    const pages = await Promise.all(
      Array.from({ length: pdf.numPages }, (_, i) =>
        pdf.getPage(i + 1).then(p => p.getTextContent()).then(c => c.items.map((it: any) => it.str).join(' '))
      )
    )
    return pages.join('\n')
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = e => resolve(e.target?.result as string)
    reader.onerror = reject
    reader.readAsText(file)
  })
}

const ACCEPTED_TYPES = [
  'application/pdf',
  'text/plain', 'text/markdown', 'text/html', 'text/csv',
  'application/json',
]
const ACCEPTED_EXTS = ['.md', '.txt', '.rst', '.html', '.csv', '.json', '.pdf', '.doc', '.docx']

function isAccepted(file: File) {
  if (ACCEPTED_TYPES.includes(file.type)) return true
  return ACCEPTED_EXTS.some(ext => file.name.toLowerCase().endsWith(ext))
}

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
const [submitting, setSubmitting] = useState(false)
  const [indexing, setIndexing] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)
  const [error, setError] = useState('')
  const dropRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    listRepos().then(r => {
      setRepos(r)
      if (r.length > 0) setRepo(r[0].name)
    }).catch(e => setError(String(e)))
  }, [])

  useEffect(() => {
    if (!repo) return
    getBranches(repo).then(b => {
      setBranches(b)
      setBranch(b.includes('main') ? 'main' : (b[0] ?? ''))
    }).catch(e => setError(String(e)))
  }, [repo])

  async function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setIsDragOver(false)
    const files = Array.from(e.dataTransfer.files).filter(isAccepted)
    for (const file of files) {
      if (file.size > MAX_FILE_SIZE) {
        setError(`${file.name} exceeds 512 KB limit`)
        continue
      }
      try {
        const text = await extractText(file)
        const entry = `[Document: ${file.name}]\n${text}`
        setContextPills(p => p.includes(entry) ? p : [...p, entry])
      } catch {
        setError(`Failed to read ${file.name}`)
      }
    }
  }

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
    try {
      const task = await createTask({
        feature_name: featureName,
        description,
        repo,
        branch_from: branch,
        additional_context: contextPills,
        optional_answers: {},
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
              <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  backgroundColor: selectedRepo.tc_indexed ? '#16a34a' : '#dc2626',
                  display: 'inline-block', flexShrink: 0,
                }} />
                <span>
                  {selectedRepo.tc_indexed
                    ? [
                        selectedRepo.tc_node_count != null ? `${selectedRepo.tc_node_count} nodes` : null,
                        selectedRepo.tc_last_indexed ? `last indexed ${new Date(selectedRepo.tc_last_indexed).toLocaleDateString()}` : null,
                      ].filter(Boolean).join(' · ') || 'Indexed'
                    : 'Not indexed'}
                </span>
                <button
                  type="button"
                  disabled={indexing}
                  onClick={async () => {
                    setIndexing(true)
                    setError('')
                    try {
                      await indexRepo(repo)
                      const updated = await listRepos()
                      setRepos(updated)
                    } catch (e) {
                      setError(String(e))
                    } finally {
                      setIndexing(false)
                    }
                  }}
                  style={{
                    padding: '2px 8px', borderRadius: 4, border: '1px solid #d1d5db',
                    background: '#f9fafb', fontSize: 11, cursor: 'pointer',
                    opacity: indexing ? 0.5 : 1,
                  }}
                >
                  {indexing ? 'Indexing…' : 'Index now'}
                </button>
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
            <label style={labelStyle}>Additional context</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input value={contextInput} onChange={e => setContextInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addPill())}
                placeholder="src/path/to/file.py" style={{ ...inputStyle, flex: 1, marginBottom: 0 }} />
              <button type="button" onClick={addPill}
                style={{ padding: '8px 14px', borderRadius: 4, border: '1px solid #d1d5db', background: '#f9fafb', fontSize: 14 }}>
                Add
              </button>
            </div>
            <div
              ref={dropRef}
              onDragOver={e => { e.preventDefault(); setIsDragOver(true) }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={handleDrop}
              style={{
                marginTop: 8, padding: '10px 14px', borderRadius: 4, fontSize: 13,
                border: `2px dashed ${isDragOver ? '#2563eb' : '#d1d5db'}`,
                background: isDragOver ? '#eff6ff' : '#f9fafb',
                color: '#6b7280', textAlign: 'center', transition: 'all 0.15s',
              }}
            >
              Drop documents here (PDF, Markdown, text)
            </div>
            {contextPills.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                {contextPills.map(p => {
                  const isDoc = p.startsWith('[Document:')
                  const label = isDoc ? p.match(/\[Document: (.+?)\]/)?.[1] ?? p : p
                  return (
                    <span key={p} style={{
                      background: isDoc ? '#dbeafe' : '#e5e7eb',
                      border: isDoc ? '1px solid #bfdbfe' : '1px solid transparent',
                      borderRadius: 4, padding: '3px 8px',
                      fontSize: 13, display: 'flex', alignItems: 'center', gap: 4,
                    }}>
                      {isDoc && <span style={{ fontSize: 11 }}>📄</span>}
                      {label}
                      <button type="button" onClick={() => removePill(p)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280', fontSize: 15, lineHeight: 1, padding: 0 }}>
                        ×
                      </button>
                    </span>
                  )
                })}
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
