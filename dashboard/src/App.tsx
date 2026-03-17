import { Component, type ReactNode, Suspense, lazy } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { LoadingSkeleton } from '@/components/feedback/LoadingSkeleton'

// Lazy-loaded pages (Step 3+)
const Overview = lazy(() => import('@/pages/Overview'))
const Performance = lazy(() => import('@/pages/Performance'))
const Compare = lazy(() => import('@/pages/Compare'))
const Responses = lazy(() => import('@/pages/Responses'))
const RawData = lazy(() => import('@/pages/RawData'))

// ── Error Boundary ─────────────────────────────────────────────────────────────
interface EBState { error: string | null }
class ErrorBoundary extends Component<{ children: ReactNode }, EBState> {
  state: EBState = { error: null }
  static getDerivedStateFromError(err: Error): EBState {
    return { error: err.message }
  }
  render() {
    if (this.state.error) {
      return (
        <div className="flex items-center justify-center h-screen">
          <ErrorFallback
            error={this.state.error}
            onRetry={() => this.setState({ error: null })}
          />
        </div>
      )
    }
    return this.props.children
  }
}

// ── Layout ─────────────────────────────────────────────────────────────────────
function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen" style={{ background: 'var(--background)' }}>
      <Sidebar />
      <main className="flex flex-col flex-1 min-w-0">
        <Suspense
          fallback={
            <div className="p-8">
              <LoadingSkeleton rows={6} />
            </div>
          }
        >
          {children}
        </Suspense>
      </main>
    </div>
  )
}

// ── App ────────────────────────────────────────────────────────────────────────
export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/performance" element={<Performance />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/responses" element={<Responses />} />
            <Route path="/raw" element={<RawData />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </ErrorBoundary>
  )
}