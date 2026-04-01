import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, setAccessToken } from '../api'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) return
    setLoading(true)
    setError('')
    try {
      const data = await login(username.trim(), password)
      setAccessToken(data.access_token)
      localStorage.setItem('role', data.user.role)
      navigate('/tasks')
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      display: 'flex', justifyContent: 'center', alignItems: 'center',
      minHeight: '100vh', backgroundColor: '#f5f5f5',
    }}>
      <form onSubmit={handleSubmit} style={{
        background: '#fff', padding: 32, borderRadius: 8,
        boxShadow: '0 2px 8px rgba(0,0,0,.12)', width: 320,
      }}>
        <h2 style={{ margin: '0 0 24px', fontSize: 22 }}>Breakdown</h2>
        <label style={{ display: 'block', marginBottom: 8, fontSize: 14, fontWeight: 500 }}>
          Username
        </label>
        <input
          value={username}
          onChange={e => setUsername(e.target.value)}
          placeholder="your-username"
          style={{
            width: '100%', padding: '8px 12px', borderRadius: 4,
            border: '1px solid #d1d5db', fontSize: 15, marginBottom: 16,
          }}
        />
        <label style={{ display: 'block', marginBottom: 8, fontSize: 14, fontWeight: 500 }}>
          Password
        </label>
        <input
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="••••••••"
          style={{
            width: '100%', padding: '8px 12px', borderRadius: 4,
            border: '1px solid #d1d5db', fontSize: 15, marginBottom: 16,
          }}
        />
        {error && <p style={{ color: '#dc2626', fontSize: 13, margin: '0 0 12px' }}>{error}</p>}
        <button
          type="submit"
          disabled={loading || !username.trim() || !password}
          style={{
            width: '100%', padding: '9px 0', borderRadius: 4,
            background: '#111', color: '#fff', border: 'none',
            fontSize: 15, fontWeight: 500,
            opacity: loading || !username.trim() || !password ? 0.5 : 1,
          }}
        >
          {loading ? 'Logging in…' : 'Login'}
        </button>
      </form>
    </div>
  )
}
