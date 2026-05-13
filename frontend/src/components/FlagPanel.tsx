import { useEffect, useState } from 'react'
import { X, AlertTriangle, Check } from 'lucide-react'
import type { ContentFlag } from '../api/client'
import { reviewFlag } from '../api/client'
import { cn } from '../lib/utils'

interface FlagPanelProps {
  flags: ContentFlag[]
  onClose: () => void
  onReviewed: (id: number) => void
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return iso
  }
}

export function FlagPanel({ flags, onClose, onReviewed }: FlagPanelProps) {
  const [pending, setPending] = useState<number | null>(null)
  const [animateIn, setAnimateIn] = useState(false)

  useEffect(() => {
    // Trigger slide-in on mount.
    const t = window.setTimeout(() => setAnimateIn(true), 10)
    return () => window.clearTimeout(t)
  }, [])

  const handleReview = async (flag: ContentFlag) => {
    setPending(flag.id)
    try {
      await reviewFlag(flag.id)
      onReviewed(flag.id)
    } catch (e) {
      console.error('Failed to review flag:', e)
    } finally {
      setPending(null)
    }
  }

  return (
    <>
      {/* Click-away scrim */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
      />
      <aside
        className={cn(
          'fixed top-0 right-0 bottom-0 w-[420px] z-50 flex flex-col',
          'bg-gradient-to-b from-[#0c0c12] to-[#08080d] industrial-panel',
          'border-l-2 border-neon-pink/40 transition-transform duration-300',
          animateIn ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        {/* Header */}
        <div className="p-4 industrial-raised relative flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-1.5 industrial-inset border border-neon-pink/40">
              <AlertTriangle className="w-4 h-4 text-neon-pink" />
            </div>
            <div>
              <h2 className="font-mono text-xs text-neon-pink glow-pink-text uppercase tracking-wider font-bold">
                Content Flags
              </h2>
              <p className="font-mono text-[10px] text-neon-cyan/60 mt-0.5">
                {`{${flags.length} unreviewed}`}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 industrial-inset border border-[#00f0ff]/30 text-[#00f0ff] hover:text-[#ff2a6d] hover:border-[#ff2a6d]/40 transition-all cursor-pointer"
            title="Close"
          >
            <X className="w-3.5 h-3.5" />
          </button>
          <div className="absolute -bottom-[3px] left-0 right-0 industrial-divider-h" />
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {flags.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 gap-2 text-muted-foreground/40">
              <span className="font-mono text-[10px] uppercase tracking-widest">
                No flags pending
              </span>
            </div>
          ) : (
            flags.map((flag) => (
              <div
                key={flag.id}
                className="industrial-inset border border-neon-pink/20 p-3 space-y-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[10px] text-neon-yellow/70 tabular-nums">
                    {formatTime(flag.flagged_at)}
                  </span>
                  <span className="font-mono text-[9px] text-muted-foreground/50 uppercase tracking-wider">
                    user: {flag.user_id}
                  </span>
                </div>

                <div>
                  <p className="font-mono text-[9px] uppercase tracking-wider text-neon-pink/70 mb-1">
                    Reason
                  </p>
                  <p className="font-sans text-xs text-neon-pink/90 italic">
                    {flag.reason}
                  </p>
                </div>

                <div>
                  <p className="font-mono text-[9px] uppercase tracking-wider text-neon-cyan/70 mb-1">
                    Message
                  </p>
                  <p className="font-sans text-xs text-foreground/80 whitespace-pre-wrap line-clamp-4">
                    {flag.message_content}
                  </p>
                </div>

                <div>
                  <p className="font-mono text-[9px] uppercase tracking-wider text-neon-cyan/70 mb-1">
                    Drift response
                  </p>
                  <p className="font-sans text-xs text-muted-foreground/70 whitespace-pre-wrap line-clamp-4">
                    {flag.response_content}
                  </p>
                </div>

                <div className="pt-2 border-t border-[#1a1a22] flex justify-end">
                  <button
                    onClick={() => handleReview(flag)}
                    disabled={pending === flag.id}
                    className={cn(
                      'flex items-center gap-1.5 px-3 py-1.5',
                      'industrial-raised border border-neon-green/40 text-neon-green',
                      'hover:border-neon-green hover:glow-green transition-all cursor-pointer',
                      'disabled:opacity-40 disabled:cursor-not-allowed',
                    )}
                  >
                    <Check className="w-3 h-3" />
                    <span className="font-mono text-[10px] uppercase tracking-wider font-bold">
                      {pending === flag.id ? 'Reviewing...' : 'Mark Reviewed'}
                    </span>
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </aside>
    </>
  )
}
