import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Login from './pages/Login'
import Submit from './pages/Submit'
import TaskDetail from './pages/TaskDetail'
import TaskList from './pages/TaskList'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const username = localStorage.getItem('username')
  if (!username) return <Navigate to="/login" replace />
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
