import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, ApiError } from './api'
import { Layout } from './components/Layout'
import { Button, ErrorNote } from './components/ui'
import { AdminPage } from './pages/AdminPage'
import { CatalogPage } from './pages/CatalogPage'
import { LoginPage } from './pages/LoginPage'
import { WorkflowPage } from './pages/WorkflowPage'

function RequireUser({ children }: { children: (username: string) => ReactNode }) {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  if (me.error instanceof ApiError && me.error.status === 401) return <Navigate to="/login" replace />
  if (me.error) {
    return (
      <Layout>
        <div className="space-y-3">
          <ErrorNote error={me.error} />
          <Button onClick={() => me.refetch()}>Try again</Button>
        </div>
      </Layout>
    )
  }
  if (!me.data) return null
  return <Layout username={me.data.username}>{children(me.data.username)}</Layout>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/admin"
        element={
          <Layout>
            <AdminPage />
          </Layout>
        }
      />
      <Route path="/" element={<RequireUser>{() => <CatalogPage />}</RequireUser>} />
      <Route path="/workflows/:id" element={<RequireUser>{() => <WorkflowPage />}</RequireUser>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
