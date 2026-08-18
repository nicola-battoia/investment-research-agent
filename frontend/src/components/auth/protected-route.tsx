import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '@/lib/auth'

export function ProtectedRoute() {
  const { isLoading, session } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <main className="grid min-h-svh place-items-center bg-background px-6">
        <p className="text-sm text-muted-foreground">Loading your session…</p>
      </main>
    )
  }

  if (!session) {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
