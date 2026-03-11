import { useState } from 'react'
import { Loader2, Terminal } from 'lucide-react'
import { api, setToken } from '../../lib/api'

interface LoginPageProps {
  onLogin: () => void
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { token } = await api.auth.login(username, password)
      setToken(token)
      onLogin()
    } catch {
      setError('Invalid credentials')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen items-center justify-center bg-[var(--color-bg-primary)]">
      <form onSubmit={handleSubmit} className="w-80 space-y-4 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-6">
        <div className="flex items-center justify-center gap-2 text-[var(--color-text-primary)]">
          <Terminal size={20} />
          <h1 className="text-lg font-bold">Claude Hub</h1>
        </div>
        <div className="space-y-3">
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            autoFocus
            className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            className="w-full rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent-blue)] focus:outline-none"
          />
        </div>
        {error && (
          <p className="text-xs text-[var(--color-accent-red)]">{error}</p>
        )}
        <button
          type="submit"
          disabled={loading || !username || !password}
          className="flex w-full items-center justify-center gap-2 rounded bg-[var(--color-accent-blue)] px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {loading && <Loader2 size={14} className="animate-spin" />}
          Sign In
        </button>
      </form>
    </div>
  )
}
