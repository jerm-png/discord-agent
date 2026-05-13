import { useEffect, useState } from 'react'
import { useAuthStore } from './store/authStore'
import { LoginPage } from './pages/LoginPage'
import { DashboardPage } from './pages/DashboardPage'
import { getMe } from './api/client'

export default function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const setUser = useAuthStore((s) => s.setUser)
  const clearUser = useAuthStore((s) => s.clearUser)
  const [checking, setChecking] = useState(true)

  // Rehydrate auth on mount — if the cookie is still valid the server
  // will return the user info, otherwise we drop to LoginPage.
  useEffect(() => {
    let cancelled = false
    getMe()
      .then((u) => {
        if (cancelled) return
        if (u) setUser(u.user_id, u.role)
        else clearUser()
      })
      .catch(() => {
        if (!cancelled) clearUser()
      })
      .finally(() => {
        if (!cancelled) setChecking(false)
      })
    return () => {
      cancelled = true
    }
  }, [setUser, clearUser])

  if (checking) {
    return (
      <div className="h-screen w-screen bg-background scanlines flex items-center justify-center">
        <span className="font-mono text-[10px] text-muted-foreground/40 uppercase tracking-widest">
          [ Initializing... ]
        </span>
      </div>
    )
  }

  return isAuthenticated ? <DashboardPage /> : <LoginPage />
}
