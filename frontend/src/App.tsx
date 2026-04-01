import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { getAccessToken, refreshSession, setAccessToken } from './api'
import Login from './pages/Login'
import Submit from './pages/Submit'
import TaskDetail from './pages/TaskDetail'
import TaskList from './pages/TaskList'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const [checked, setChecked] = useState(false)
  const [authed, setAuthed] = useState(false)

  useEffect(() => {
    if (getAccessToken()) {
      setAuthed(true)
      setChecked(true)
      return
    }
    // Try to restore session from HttpOnly cookie
    refreshSession()
      .then(data => {
        setAccessToken(data.access_token)
        setAuthed(true)
      })
      .catch(() => setAuthed(false))
      .finally(() => setChecked(true))
  }, [])

  if (!checked) return null  // brief flash prevention
  if (!authed) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/tasks" element={<RequireAuth><TaskList /></RequireAuth>} />
        <Route path="/tasks/:id" element={<RequireAuth><TaskDetail /></RequireAuth>} />
        <Route path="/submit" element={<RequireAuth><Submit /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/tasks" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
