import { useState, useEffect } from 'react'
import { Wifi, Database, Cpu, Activity, Zap, Shield, ShieldAlert, Power } from 'lucide-react'
import { useAuthStore } from '../store/authStore'
import { getUnreviewedFlags, logout } from '../api/client'
import type { ContentFlag } from '../api/client'
import { FlagPanel } from './FlagPanel'
import { cn } from '../lib/utils'

export function SystemStatusBar() {
  const role = useAuthStore((s) => s.role)
  const userId = useAuthStore((s) => s.userId)
  const clearUser = useAuthStore((s) => s.clearUser)
  const isAdmin = role === 'admin'
  const isParker = userId === 'parker'

  const handleLogout = async () => {
    try {
      await logout()
    } catch (e) {
      console.error('Logout request failed:', e)
    }
    clearUser()
  }
  const [flags, setFlags] = useState<ContentFlag[]>([])
  const [panelOpen, setPanelOpen] = useState(false)

  // Admin: poll unreviewed flags every 60s.
  useEffect(() => {
    if (!isAdmin) return
    let cancelled = false
    const load = () => {
      getUnreviewedFlags()
        .then((data) => {
          if (!cancelled) setFlags(data)
        })
        .catch((e) => console.error('Failed to load flags:', e))
    }
    load()
    const interval = window.setInterval(load, 60000)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [isAdmin])

  const [time, setTime] = useState<string>('')
  const [memoryUsage, setMemoryUsage] = useState(73)
  const [latency, setLatency] = useState(12)

  useEffect(() => {
    const updateTime = () => {
      const now = new Date()
      setTime(
        now.toLocaleTimeString('en-US', {
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })
      )
    }
    updateTime()
    const interval = setInterval(updateTime, 1000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    const interval = setInterval(() => {
      setMemoryUsage((prev) => {
        const change = (Math.random() - 0.5) * 4
        return Math.min(95, Math.max(60, prev + change))
      })
      setLatency((prev) => {
        const change = (Math.random() - 0.5) * 6
        return Math.max(8, Math.min(35, prev + change))
      })
    }, 2000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="h-9 w-full bg-gradient-to-b from-[#08080c] to-[#040406] flex items-center justify-between px-4 font-mono text-[10px] tracking-wider relative industrial-panel">
      {/* Top edge highlight */}
      <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-neon-cyan/30 to-transparent" />

      {/* Bottom thick border */}
      <div className="absolute bottom-0 left-0 right-0 industrial-divider-h" />

      {/* Left section */}
      <div className="flex items-center gap-4">
        {/* Connection status - recessed panel */}
        <div className="flex items-center gap-2 px-3 py-1 industrial-inset border border-neon-green/20">
          <Shield className="w-3 h-3 text-neon-green" />
          <span className="text-muted-foreground">CONN:</span>
          <span className="text-neon-green glow-green-text font-bold">SECURE</span>
        </div>

        {/* Separator bolt */}
        <div className="w-2 h-2 bg-gradient-to-br from-[#2a2a35] to-[#15151a] border border-black/50 shadow-inner" />

        {/* Latency */}
        <div className="flex items-center gap-2 px-3 py-1 industrial-inset border border-neon-pink/20">
          <Activity className="w-3 h-3 text-neon-pink" />
          <span className="text-muted-foreground">PING:</span>
          <span className={`font-bold ${latency > 25 ? 'text-neon-orange' : 'text-neon-green'}`}>
            {latency.toFixed(0)}ms
          </span>
        </div>

        {/* Memory with thicker bar */}
        <div className="flex items-center gap-2 px-3 py-1 industrial-inset border border-neon-yellow/20">
          <Database className="w-3 h-3 text-neon-yellow" />
          <span className="text-muted-foreground">MEM:</span>
          <span
            className={`font-bold ${memoryUsage > 85 ? 'text-neon-orange glow-yellow-text' : 'text-neon-green'}`}
          >
            {memoryUsage.toFixed(1)}%
          </span>
          <div className="w-20 h-3 bg-[#040406] border-2 border-[#12121a] overflow-hidden relative shadow-inner">
            <div
              className={`h-full transition-all duration-500 ${
                memoryUsage > 85
                  ? 'bg-gradient-to-r from-neon-orange to-neon-pink'
                  : 'bg-gradient-to-r from-neon-cyan to-neon-green'
              }`}
              style={{ width: `${memoryUsage}%` }}
            />
            {/* Grid overlay */}
            <div
              className="absolute inset-0"
              style={{
                backgroundImage:
                  'repeating-linear-gradient(90deg, transparent 0px, transparent 4px, rgba(0,0,0,0.4) 4px, rgba(0,0,0,0.4) 5px)',
              }}
            />
          </div>
        </div>
      </div>

      {/* Center - Model Info - raised panel */}
      <div className="flex items-center gap-3 px-4 py-1.5 industrial-raised border-l-2 border-r-2 border-neon-pink/30">
        <Cpu className="w-3.5 h-3.5 text-neon-pink" />
        <span className="text-muted-foreground">MODEL:</span>
        <span className="text-neon-pink glow-pink-text font-bold">DRIFT // SONNET-4</span>
        <div className="w-[2px] h-4 bg-gradient-to-b from-transparent via-neon-cyan/40 to-transparent" />
        <Zap className="w-3.5 h-3.5 text-neon-yellow" />
        <span className="text-muted-foreground">CTX:</span>
        <span className="text-neon-yellow glow-yellow-text font-bold">200K</span>
      </div>

      {/* Right section */}
      <div className="flex items-center gap-4">
        {isAdmin && (() => {
          // Badge count = urgent + review only. Info-tier flags are
          // browsable in the panel but don't bump the top-bar number,
          // matching the "FYI" intent. Urgent presence flips the
          // accent red so it's distinguishable from a review-only badge.
          const reviewable = flags.filter((f) => f.severity !== 'info')
          const hasUrgent = flags.some((f) => f.severity === 'urgent')
          const count = reviewable.length
          const accentClass = hasUrgent
            ? 'border-[#ff0040]/70 text-[#ff0040] shadow-[0_0_12px_rgba(255,0,64,0.4)] hover:border-[#ff0040]'
            : count > 0
              ? 'border-neon-pink/50 text-neon-pink glow-pink hover:border-neon-pink/70'
              : 'border-muted-foreground/20 text-muted-foreground hover:text-neon-cyan hover:border-neon-cyan/40'
          return (
            <button
              onClick={() => setPanelOpen(true)}
              title={
                count > 0
                  ? `${count} unreviewed flag${count === 1 ? '' : 's'}${hasUrgent ? ' (URGENT)' : ''}`
                  : 'No flags pending'
              }
              className={cn(
                'relative flex items-center gap-2 px-3 py-1 industrial-inset border transition-all cursor-pointer',
                accentClass,
              )}
            >
              {count > 0 ? (
                <ShieldAlert className="w-3 h-3" />
              ) : (
                <Shield className="w-3 h-3" />
              )}
              <span className="text-muted-foreground">FLAGS:</span>
              <span
                className={cn(
                  'font-bold tabular-nums',
                  hasUrgent
                    ? 'text-[#ff0040]'
                    : count > 0
                      ? 'text-neon-pink glow-pink-text'
                      : 'text-neon-cyan/70',
                )}
              >
                {count}
              </span>
              {count > 0 && (
                <span
                  className={cn(
                    'absolute -top-1 -right-1 w-2 h-2 rounded-full',
                    hasUrgent
                      ? 'bg-[#ff0040] pulse-dot-pink'
                      : 'bg-neon-pink pulse-dot-pink',
                  )}
                />
              )}
            </button>
          )
        })()}

        <div className="flex items-center gap-2 px-3 py-1 industrial-inset border border-neon-cyan/20">
          <Wifi className="w-3 h-3 text-neon-green pulse-dot-green" />
          <span className="text-muted-foreground">SID:</span>
          <span className="text-foreground/80">DRIFT-SYS</span>
        </div>

        {/* Separator bolt */}
        <div className="w-2 h-2 bg-gradient-to-br from-[#2a2a35] to-[#15151a] border border-black/50 shadow-inner" />

        <div className="flex items-center gap-2 px-3 py-1 industrial-raised border-2 border-neon-cyan/30">
          <span className="text-neon-pink">SYS:</span>
          <span className="text-neon-cyan glow-cyan-text tabular-nums font-bold">
            {time || '00:00:00'}
          </span>
        </div>

        {isParker && (
          <button
            onClick={handleLogout}
            title="Log out"
            className={cn(
              'flex items-center gap-2 px-3 py-1 industrial-inset border transition-all cursor-pointer',
              'border-neon-pink/30 text-neon-pink/70',
              'hover:text-neon-pink hover:border-neon-pink/60',
            )}
          >
            <Power className="w-3 h-3" />
            <span className="font-bold">LOGOUT</span>
          </button>
        )}
      </div>

      {isAdmin && panelOpen && (
        <FlagPanel
          flags={flags}
          onClose={() => setPanelOpen(false)}
          onReviewed={(id) =>
            setFlags((prev) => prev.filter((f) => f.id !== id))
          }
        />
      )}
    </div>
  )
}
