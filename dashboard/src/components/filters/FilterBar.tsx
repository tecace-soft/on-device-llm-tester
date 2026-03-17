import { useDevices, useModels, useCategories } from '@/hooks/useResults'
import type { Filters } from '@/types'

interface Props {
  filters: Filters
  onFilter: <K extends keyof Filters>(key: K, value: Filters[K]) => void
  onReset: () => void
}

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string | undefined
  options: string[]
  onChange: (v: string | undefined) => void
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </label>
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || undefined)}
        className="rounded-lg px-3 py-1.5 text-sm outline-none cursor-pointer"
        style={{
          background: 'var(--surface-2)',
          border: '1px solid var(--border)',
          color: 'var(--text-primary)',
          minWidth: 140,
        }}
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </div>
  )
}

export function FilterBar({ filters, onFilter, onReset }: Props) {
  const { data: devices } = useDevices()
  const { data: models } = useModels(filters.device)
  const { data: categories } = useCategories()

  const hasActive =
    filters.device || filters.model || filters.category || filters.backend || filters.status

  return (
    <div
      className="flex flex-wrap items-end gap-4 px-6 py-4 border-b"
      style={{ borderColor: 'var(--border)' }}
    >
      <Select
        label="Device"
        value={filters.device}
        options={devices ?? []}
        onChange={(v) => onFilter('device', v)}
      />
      <Select
        label="Model"
        value={filters.model}
        options={models ?? []}
        onChange={(v) => onFilter('model', v)}
      />
      <Select
        label="Category"
        value={filters.category}
        options={categories ?? []}
        onChange={(v) => onFilter('category', v)}
      />
      <Select
        label="Backend"
        value={filters.backend}
        options={['CPU', 'GPU']}
        onChange={(v) => onFilter('backend', v)}
      />
      <Select
        label="Status"
        value={filters.status}
        options={['success', 'error']}
        onChange={(v) => onFilter('status', v as Filters['status'])}
      />

      {hasActive && (
        <button
          onClick={onReset}
          className="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors self-end"
          style={{
            background: 'var(--surface-2)',
            border: '1px solid var(--border)',
            color: 'var(--text-secondary)',
          }}
        >
          Reset
        </button>
      )}
    </div>
  )
}