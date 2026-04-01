import { Link, useNavigate } from 'react-router-dom'

export default function Nav() {
  const navigate = useNavigate()
  const username = localStorage.getItem('username') ?? ''
  const role = localStorage.getItem('role') ?? 'member'

  function logout() {
    localStorage.removeItem('username')
    localStorage.removeItem('role')
    navigate('/login')
  }

  return (
    <nav style={{
      display: 'flex', alignItems: 'center', gap: 16,
      padding: '0 24px', height: 52,
      backgroundColor: '#111', color: '#fff',
    }}>
      <span style={{ fontWeight: 700, fontSize: 18, marginRight: 16 }}>Breakdown</span>
      <Link to="/submit" style={{ color: '#d1d5db' }}>New request</Link>
      <Link to="/tasks" style={{ color: '#d1d5db' }}>Tasks</Link>
      <span style={{ flex: 1 }} />
      <span style={{ color: '#d1d5db', fontSize: 14 }}>{username}</span>
      <span style={{
        padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
        backgroundColor: role === 'admin' ? '#7c3aed' : '#374151',
        color: '#fff', textTransform: 'uppercase',
      }}>
        {role}
      </span>
      <button onClick={logout} style={{
        background: 'none', border: '1px solid #4b5563',
        color: '#d1d5db', padding: '4px 10px', borderRadius: 4, fontSize: 13,
      }}>
        Logout
      </button>
    </nav>
  )
}
