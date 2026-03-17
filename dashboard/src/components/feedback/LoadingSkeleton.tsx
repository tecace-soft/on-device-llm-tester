import React from 'react'

interface Props {
  rows?: number
  className?: string
}

function SkeletonBlock({ className = '', style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <div
      className={`animate-pulse rounded-lg ${className}`}
      style={{ background: 'var(--surface-2)', ...style }}
    />
  )
}

export function LoadingSkeleton({ rows = 4 }: Props) {
  return (
    <div className="flex flex-col gap-3 w-full">
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonBlock key={i} className="h-12 w-full" />
      ))}
    </div>
  )
}

export function KpiSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <SkeletonBlock key={i} className="h-28 w-full" />
      ))}
    </div>
  )
}

export function ChartSkeleton({ height = 300 }: { height?: number }) {
  return <SkeletonBlock className="w-full" style={{ height }} />
}