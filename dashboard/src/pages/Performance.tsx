import { Header } from '@/components/layout/Header'

export default function Performance() {
  return (
    <div className="flex flex-col flex-1">
      <Header title="Performance" subtitle="Latency, TPS, TTFT analysis" />
      <div className="p-6 text-sm" style={{ color: 'var(--text-secondary)' }}>
        Step 4에서 구현 예정
      </div>
    </div>
  )
}
