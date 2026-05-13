import { useState } from 'react'
import { Terminal } from 'lucide-react'
import { login } from '../api/client'
import { useAuthStore } from '../store/authStore'

export function LoginPage() {
  const setUser = useAuthStore((s) => s.setUser)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit() {
    if (!password || loading) return
    setLoading(true)
    setError('')
    try {
      const result = await login(password)
      setUser(result.user_id, result.role)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Authentication failed')
    } finally {
      setLoading(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') handleSubmit()
  }

  return (
    <div className="h-screen w-screen bg-background scanlines flex items-center justify-center">
      {/* Corner accents */}
      <div className="fixed top-4 left-4 w-8 h-8 border-t-2 border-l-2 border-neon-cyan/40" />
      <div className="fixed top-4 right-4 w-8 h-8 border-t-2 border-r-2 border-neon-pink/40" />
      <div className="fixed bottom-4 left-4 w-8 h-8 border-b-2 border-l-2 border-neon-pink/40" />
      <div className="fixed bottom-4 right-4 w-8 h-8 border-b-2 border-r-2 border-neon-cyan/40" />

      <div className="w-full max-w-[400px] px-4">
        {/* Outer glow wrapper */}
        <div className="cyber-frame-cyan" style={{ filter: 'drop-shadow(0 0 8px rgba(0, 240, 255, 0.4)) drop-shadow(0 0 20px rgba(0, 240, 255, 0.2))' }}>
          <div className="relative industrial-panel p-8 space-y-6 cyber-frame">
            {/* Inner corner accents */}
            <div className="absolute top-2 left-2 w-3 h-3 border-l-2 border-t-2 border-neon-cyan/50" />
            <div className="absolute top-2 right-2 w-3 h-3 border-r-2 border-t-2 border-neon-pink/50" />
            <div className="absolute bottom-2 left-2 w-3 h-3 border-b-2 border-l-2 border-neon-pink/50" />
            <div className="absolute bottom-2 right-2 w-3 h-3 border-b-2 border-r-2 border-neon-cyan/50" />

            {/* Logo section */}
            <div className="flex flex-col items-center gap-3">
              <div className="p-3 industrial-raised border-2 border-neon-cyan/50 glow-cyan">
                <Terminal className="w-8 h-8 text-neon-cyan" strokeWidth={1.5} />
              </div>
              <div className="text-center">
                <h1 className="font-mono text-xl tracking-[0.3em] text-neon-cyan glow-cyan-text font-bold">
                  DRIFT
                </h1>
                <p className="font-mono text-[10px] text-muted-foreground tracking-widest uppercase mt-1">
                  v1.0 // AUTHENTICATION REQUIRED
                </p>
              </div>
            </div>

            {/* System status */}
            <div className="flex items-center justify-center gap-2 px-3 py-2 industrial-inset border border-neon-green/20">
              <div className="w-2 h-2 bg-neon-green pulse-dot-green" />
              <span className="font-mono text-[10px] text-neon-green/80 uppercase tracking-widest">
                SYSTEM ONLINE
              </span>
            </div>

            <div className="industrial-divider-h" />

            {/* Form */}
            <div className="space-y-4">
              <div>
                <label className="block font-mono text-[10px] text-neon-pink/70 uppercase tracking-widest mb-2">
                  [ ACCESS CODE ]
                </label>
                <div className="relative">
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="••••••••••••"
                    className="w-full industrial-inset border-2 border-neon-cyan/30 px-4 py-3 font-mono text-sm bg-transparent text-foreground placeholder:text-muted-foreground/40 focus:border-neon-pink/50 focus:outline-none focus:shadow-[0_0_12px_rgba(255,42,109,0.2)] transition-all duration-200"
                    autoFocus
                  />
                  <div className="absolute bottom-0 left-2 right-2 h-[2px] bg-gradient-to-r from-transparent via-neon-cyan/30 to-transparent" />
                </div>
              </div>

              {error && (
                <div className="px-3 py-2 industrial-inset border border-neon-pink/30">
                  <p className="font-mono text-[11px] text-neon-pink glow-pink-text text-center">
                    {error}
                  </p>
                </div>
              )}

              <button
                onClick={handleSubmit}
                disabled={loading || !password}
                className="w-full py-3 industrial-raised border-2 border-neon-cyan/50 text-neon-cyan hover:text-neon-pink hover:border-neon-pink/50 hover:bg-neon-pink/5 font-mono text-xs uppercase tracking-wider transition-all duration-200 cyber-button flex items-center justify-center gap-2 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                {loading ? (
                  <>
                    <div className="w-2 h-2 bg-neon-cyan pulse-dot" />
                    AUTHENTICATING...
                  </>
                ) : (
                  'ACCESS SYSTEM'
                )}
              </button>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between">
              <div className="h-[1px] flex-1 bg-gradient-to-r from-transparent via-neon-cyan/20 to-transparent" />
              <p className="font-mono text-[9px] text-muted-foreground/40 px-3">
                DRIFT // PERSISTENT COGNITION SYSTEM
              </p>
              <div className="h-[1px] flex-1 bg-gradient-to-r from-transparent via-neon-pink/20 to-transparent" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
