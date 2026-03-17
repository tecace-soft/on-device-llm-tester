import { Header } from '@/components/layout/Header'

export default function Overview() {
  return (
    <div className="flex flex-col flex-1">
      <Header title="Overview" subtitle="Overall benchmark summary" />
      <div className="p-6 text-sm" style={{ color: 'var(--text-secondary)' }}>
        Step 3에서 구현 예정
      </div>
    </div>
  )
}