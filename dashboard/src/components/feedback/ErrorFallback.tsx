import { AlertTriangle } from 'lucide-react'

interface Props {
  error: string
  onRetry?: () => void
}

export function ErrorFallback({ error, onRetry }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
      <AlertTriangle size={40} style={{ color: 'var(--error)' }} />
      <div>
        <p className="font-semibold" style={{ color: 'var(--text-primary)' }}>Something went wrong</p>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>{error}</p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          style={{ background: 'var(--accent)', color: '#fff' }}
        >
          Retry
        </button>
      )}
    </div>
  )
}