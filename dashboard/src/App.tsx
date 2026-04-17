import { Component, type ReactNode, Suspense, lazy } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'
import { ErrorFallback } from '@/components/feedback/ErrorFallback'
import { LoadingSkeleton } from '@/components/feedback/LoadingSkeleton'
import { AUTH_KEY } from '@/lib/auth'

const Login         = lazy(() => import('@/pages/Login'))
const Overview      = lazy(() => import('@/pages/Overview'))
const Performance   = lazy(() => import('@/pages/Performance'))
const Compare       = lazy(() => import('@/pages/Compare'))
const DeviceCompare = lazy(() => import('@/pages/DeviceCompare'))
const Resource      = lazy(() => import('@/pages/Resource'))
const QuantCompare  = lazy(() => import('@/pages/QuantCompare'))
const Validation    = lazy(() => import('@/pages/Validation'))
const Responses     = lazy(() => import('@/pages/Responses'))
const RawData       = lazy(() => import('@/pages/RawData'))
const RunHistory    = lazy(() => import('@/pages/RunHistory'))

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

function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen" style={{ background: 'var(--background)' }}>
      <Sidebar />
      <main className="flex flex-col flex-1 min-w-0">
        <Suspense fallback={<div className="p-8"><LoadingSkeleton rows={6} /></div>}>
          {children}
        </Suspense>
      </main>
    </div>
  )
}

/**
 * Renders the full dashboard layout with all routes.
 * Redirects to /login if the session has no auth token.
 *
 * Why separate component: keeps the Navigate call inside BrowserRouter context.
 * Architecture: DEPLOYMENT_ARCHITECTURE.md §9
 */
function ProtectedDashboard() {
  if (sessionStorage.getItem(AUTH_KEY) !== 'true') {
    return <Navigate to="/login" replace />
  }
  return (
    <Layout>
      <Routes>
        <Route path="/"               element={<Overview />} />
        <Route path="/performance"    element={<Performance />} />
        <Route path="/compare"        element={<Compare />} />
        <Route path="/device-compare" element={<DeviceCompare />} />
        <Route path="/resource"       element={<Resource />} />
        <Route path="/quant-compare"  element={<QuantCompare />} />
        <Route path="/validation"     element={<Validation />} />
        <Route path="/responses"      element={<Responses />} />
        <Route path="/raw"            element={<RawData />} />
        <Route path="/runs"           element={<RunHistory />} />
        <Route path="*"               element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Suspense fallback={null}>
          <Routes>
            {/* Login page — no sidebar, no auth check */}
            <Route path="/login" element={<Login />} />
            {/* All other routes — guarded by ProtectedDashboard */}
            <Route path="/*" element={<ProtectedDashboard />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
