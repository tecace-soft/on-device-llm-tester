/**
 * Architecture: DEPLOYMENT_ARCHITECTURE.md §9
 * Used by: App.tsx (unauthenticated route)
 * Depends on: POST /auth/login (api/main.py)
 *
 * Why server-side verification: keeps DASHBOARD_PASSWORD out of the JS bundle.
 * Auth state stored in sessionStorage — clears when the browser tab is closed.
 */
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

const API_BASE = import.meta.env.VITE_API_URL ?? ''
import { AUTH_KEY } from '@/lib/auth'

export default function Login() {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      if (res.ok) {
        sessionStorage.setItem(AUTH_KEY, 'true')
        navigate('/', { replace: true })
      } else {
        setError('Incorrect password. Please try again.')
      }
    } catch {
      setError('Could not reach the server. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--background)',
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 360,
          padding: '2.5rem 2rem',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 16,
          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        }}
      >
        {/* Logo / Title */}
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: 12,
              background: 'var(--accent)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: '1rem',
              fontSize: 22,
            }}
          >
            🤖
          </div>
          <h1
            style={{
              fontSize: '1.125rem',
              fontWeight: 600,
              color: 'var(--text-primary)',
              marginBottom: 4,
            }}
          >
            LLM Benchmark Dashboard
          </h1>
          <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
            Enter your password to continue
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit}>
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            style={{
              width: '100%',
              padding: '0.625rem 0.875rem',
              borderRadius: 8,
              border: `1px solid ${error ? 'var(--error)' : 'var(--border)'}`,
              background: 'var(--surface-2)',
              color: 'var(--text-primary)',
              fontSize: 14,
              outline: 'none',
              marginBottom: error ? 8 : 16,
              transition: 'border-color 0.15s',
            }}
            onFocus={(e) =>
              ((e.target as HTMLInputElement).style.borderColor = 'var(--accent)')
            }
            onBlur={(e) =>
              ((e.target as HTMLInputElement).style.borderColor = error
                ? 'var(--error)'
                : 'var(--border)')
            }
          />

          {error && (
            <p
              style={{
                fontSize: 12,
                color: 'var(--error)',
                marginBottom: 12,
              }}
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading || !password}
            style={{
              width: '100%',
              padding: '0.625rem',
              borderRadius: 8,
              border: 'none',
              background: loading || !password ? 'var(--border)' : 'var(--accent)',
              color: loading || !password ? 'var(--text-secondary)' : '#fff',
              fontSize: 14,
              fontWeight: 500,
              cursor: loading || !password ? 'not-allowed' : 'pointer',
              transition: 'background 0.15s',
            }}
            onMouseEnter={(e) => {
              if (!loading && password)
                (e.currentTarget as HTMLButtonElement).style.background =
                  'var(--accent-hover)'
            }}
            onMouseLeave={(e) => {
              if (!loading && password)
                (e.currentTarget as HTMLButtonElement).style.background = 'var(--accent)'
            }}
          >
            {loading ? 'Verifying…' : 'Enter Dashboard'}
          </button>
        </form>
      </div>
    </div>
  )
}
