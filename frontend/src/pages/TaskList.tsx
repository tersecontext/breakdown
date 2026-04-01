import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listTasks } from '../api'
import Nav from '../components/Nav'
import StateBadge from '../components/StateBadge'
import type { TaskListItem } from '../types'

export default function TaskList() {
  const [tasks, setTasks] = useState<TaskListItem[]>([])
  const navigate = useNavigate()

  function load() {
    listTasks().then(setTasks).catch(console.error)
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [])

  return (
    <>
      <Nav />
      <div style={{ maxWidth: 960, margin: '32px auto', padding: '0 16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ margin: 0 }}>Tasks</h2>
          <button onClick={() => navigate('/submit')} style={{
            padding: '8px 16px', borderRadius: 4, background: '#111',
            color: '#fff', border: 'none', fontSize: 14, fontWeight: 500,
          }}>
            New request
          </button>
        </div>
        {tasks.length === 0 ? (
          <p style={{ color: '#6b7280' }}>No tasks yet.</p>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', background: '#fff', borderRadius: 8, overflow: 'hidden', boxShadow: '0 2px 8px rgba(0,0,0,.08)' }}>
            <thead>
              <tr style={{ background: '#f9fafb', borderBottom: '1px solid #e5e7eb' }}>
                {['Feature', 'Repo', 'State', 'Submitter', 'Created'].map(h => (
                  <th key={h} style={{ padding: '10px 16px', textAlign: 'left', fontSize: 13, fontWeight: 600, color: '#6b7280' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tasks.map(t => (
                <tr key={t.id} onClick={() => navigate(`/tasks/${t.id}`)}
                  style={{ borderBottom: '1px solid #f3f4f6', cursor: 'pointer' }}
                  onMouseEnter={e => (e.currentTarget.style.background = '#f9fafb')}
                  onMouseLeave={e => (e.currentTarget.style.background = '')}>
                  <td style={cell}>{t.feature_name}</td>
                  <td style={cell}><code style={{ fontSize: 13 }}>{t.repo}</code></td>
                  <td style={cell}><StateBadge state={t.state} /></td>
                  <td style={cell}>{t.submitter_username}</td>
                  <td style={cell}>{new Date(t.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}

const cell: React.CSSProperties = { padding: '12px 16px', fontSize: 14 }
