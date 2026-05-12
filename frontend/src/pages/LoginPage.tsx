import { useState } from 'react'
import { Terminal } from 'lucide-react'
import { login } from '../api/client'
import { useAuthStore } from '../store/authStore'

export function LoginPage() {
  const setAuthenticated = useAuthStore((s) => s.setAuthenticated)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit() {
    if (!password || loading) return
    setLoading(true)
    setError('')
    try {
      await login(password)
      setAuthenticated(true)
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
    <div className="h-screen w-screen bg-[#0a0a0f] scanlines flex items-center justify-center">
      {/* Corner accent — top left */}
      <div className="fixed top-4 left-4 w-8 h-8 border-t-2 border-l-2 border-[#00f0ff]/40" />
      {/* Corner accent — top right */}
      <div className="fixed top-4 right-4 w-8 h-8 border-t-2 border-r-2 border-[#ff2a6d]/40" />
      {/* Corner accent — bottom left */}
      <div className="fixed bottom-4 left-4 w-8 h-8 border-b-2 border-l-2 border-[#ff2a6d]/40" />
      {/* Corner accent — bottom right */}
      <div className="fixed bottom-4 right-4 w-8 h-8 border-b-2 border-r-2 border-[#00f0ff]/40" />

      <div className="w-full max-w-[400px] px-4">
        <div className="cyber-frame cyber-frame-cyan industrial-panel p-8 space-y-6">
          {/* Inner corner accents */}
          <div className="absolute top-0 left-0 w-6 h-6 border-t-2 border-l-2 border-[#00f0ff]/60" />
          <div className="absolute top-0 right-0 w-6 h-6 border-t-2 border-r-2 border-[#ff2a6d]/60" />
          <div className="absolute bottom-0 left-0 w-6 h-6 border-b-2 border-l-2 border-[#ff2a6d]/60" />
          <div className="absolute bottom-0 right-0 w-6 h-6 border-b-2 border-r-2 border-[#00f0ff]/60" />

          {/* Logo section */}
          <div className="flex flex-col items-center gap-3">
            <Terminal className="w-10 h-10 text-[#00f0ff]" strokeWidth={1.5} />
            <div className="text-center">
              <div className="font-mono text-xl tracking-[0.3em] text-[#00f0ff] glow-cyan-text">
                DRIFT
              </div>
              <div className="font-mono text-[10px] text-[#9090a8] tracking-widest uppercase mt-1">
                v1.0 // AUTHENTICATION REQUIRED
              </div>
            </div>
          </div>

          {/* System status */}
          <div className="flex items-center justify-center gap-2">
            <div className="w-2 h-2 rounded-full bg-[#05ffa1] pulse-dot-green" />
            <span className="font-mono text-[10px] text-[#05ffa1] tracking-widest uppercase">
              SYSTEM ONLINE
            </span>
          </div>

          <div className="industrial-divider-h" />

          {/* Form */}
          <div className="space-y-4">
            <div>
              <label className="block font-mono text-[10px] text-[#9090a8] uppercase tracking-widest mb-2">
                [ ACCESS CODE ]
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="••••••••••••"
                className="w-full industrial-inset border-2 border-[#00f0ff]/30 px-4 py-3 font-mono text-sm bg-transparent text-[#f0f0f5] placeholder-[#9090a8]/40 focus:border-[#ff2a6d]/50 focus:outline-none transition-colors"
                autoFocus
              />
            </div>

            {error && (
              <div className="font-mono text-[11px] text-[#ff2a6d] glow-pink-text text-center">
                {error}
              </div>
            )}

            <button
              onClick={handleSubmit}
              disabled={loading || !password}
              className="w-full cyber-button industrial-raised border-2 border-[#00f0ff]/50 py-3 font-mono text-xs text-[#00f0ff] uppercase tracking-wider hover:border-[#ff2a6d]/50 hover:text-[#ff2a6d] transition-all disabled:opacity-40 cursor-pointer disabled:cursor-not-allowed"
            >
              {loading ? 'AUTHENTICATING...' : 'ACCESS SYSTEM'}
            </button>
          </div>

          {/* Footer */}
          <div className="font-mono text-[9px] text-[#9090a8]/50 text-center">
            DRIFT // PERSISTENT COGNITION SYSTEM
          </div>
        </div>
      </div>
    </div>
  )
}
