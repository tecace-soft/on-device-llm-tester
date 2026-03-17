import { Inbox } from 'lucide-react'

interface Props {
  message?: string
  description?: string
}

export function EmptyState({ message = 'No data', description = 'Try adjusting your filters.' }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <Inbox size={40} style={{ color: 'var(--text-secondary)' }} />
      <div>
        <p className="font-semibold" style={{ color: 'var(--text-primary)' }}>{message}</p>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>{description}</p>
      </div>
    </div>
  )
}