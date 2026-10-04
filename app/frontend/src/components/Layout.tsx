import { useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'

export function Layout({ username, children }: { username?: string; children: ReactNode }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const signOut = async () => {
    await api.logout()
    queryClient.clear()
    navigate('/login')
  }
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <Link to="/" className="font-semibold text-slate-900">
            Workflow Deploy Demo
          </Link>
          {username && (
            <div className="flex items-center gap-3 text-sm text-slate-600">
              <span data-testid="username">{username}</span>
              <button onClick={signOut} className="text-indigo-600 hover:underline">
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
    </div>
  )
}
