import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Button, Card, ErrorNote } from '../components/ui'

export function LoginPage() {
  const [username, setUsername] = useState('')
  const [passcode, setPasscode] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const me = await api.login(username, passcode)
      queryClient.setQueryData(['me'], me)
      navigate('/')
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <h1 className="text-lg font-semibold">Workflow Deploy Demo</h1>
        <p className="mt-1 text-sm text-slate-600">
          Pick any username (3–20 letters, digits or dashes) and enter the demo passcode.
        </p>
        <form onSubmit={submit} className="mt-5 space-y-4">
          <label className="block text-sm">
            <span className="font-medium">Username</span>
            <input
              name="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="font-medium">Passcode</span>
            <input
              name="passcode"
              type="password"
              value={passcode}
              onChange={(e) => setPasscode(e.target.value)}
              autoComplete="current-password"
              required
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2"
            />
          </label>
          <ErrorNote error={error} />
          <Button type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
      </Card>
    </div>
  )
}
