import { useEffect, useMemo, useState } from 'react'
import { X, AlertTriangle, AlertOctagon, Info, Check, ChevronDown, ChevronRight } from 'lucide-react'
import type { ContentFlag, FlagCategory, FlagSeverity } from '../api/client'
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

const CATEGORY_LABEL: Record<FlagCategory, string> = {
  stranger: 'STRANGER',
  social_pressure: 'SOCIAL',
  money_scam: 'MONEY',
  body_sleep: 'BODY / SLEEP',
  violence: 'VIOLENCE',
  distress: 'DISTRESS',
  family: 'FAMILY',
  personal_info: 'PERSONAL INFO',
  other: 'OTHER',
}

const CATEGORY_COLOR: Record<FlagCategory, string> = {
  stranger: 'text-[#ff0040] border-[#ff0040]/40',
  social_pressure: 'text-neon-orange border-neon-orange/40',
  money_scam: 'text-neon-yellow border-neon-yellow/40',
  body_sleep: 'text-neon-cyan border-neon-cyan/40',
  violence: 'text-neon-pink border-neon-pink/40',
  distress: 'text-[#ff0040] border-[#ff0040]/40',
  family: 'text-neon-cyan border-neon-cyan/40',
  personal_info: 'text-[#ff0040] border-[#ff0040]/40',
  other: 'text-muted-foreground border-muted-foreground/40',
}

function FlagCard({
  flag,
  pending,
  onReview,
}: {
  flag: ContentFlag
  pending: boolean
  onReview: () => void
}) {
  const severityBorder =
    flag.severity === 'urgent'
      ? 'border-[#ff0040]/50'
      : flag.severity === 'review'
        ? 'border-neon-pink/30'
        : 'border-neon-cyan/20'

  return (
    <div className={cn('industrial-inset border p-3 space-y-2', severityBorder)}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="font-mono text-[10px] text-neon-yellow/70 tabular-nums">
          {formatTime(flag.flagged_at)}
        </span>
        <span
          className={cn(
            'font-mono text-[9px] uppercase tracking-wider px-1.5 py-0.5 border',
            CATEGORY_COLOR[flag.category] ?? CATEGORY_COLOR.other,
          )}
        >
          {CATEGORY_LABEL[flag.category] ?? CATEGORY_LABEL.other}
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
          onClick={onReview}
          disabled={pending}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5',
            'industrial-raised border border-neon-green/40 text-neon-green',
            'hover:border-neon-green hover:glow-green transition-all cursor-pointer',
            'disabled:opacity-40 disabled:cursor-not-allowed',
          )}
        >
          <Check className="w-3 h-3" />
          <span className="font-mono text-[10px] uppercase tracking-wider font-bold">
            {pending ? 'Reviewing...' : 'Mark Reviewed'}
          </span>
        </button>
      </div>
    </div>
  )
}

export function FlagPanel({ flags, onClose, onReviewed }: FlagPanelProps) {
  const [pending, setPending] = useState<number | null>(null)
  const [animateIn, setAnimateIn] = useState(false)
  const [infoExpanded, setInfoExpanded] = useState(false)

  useEffect(() => {
    const t = window.setTimeout(() => setAnimateIn(true), 10)
    return () => window.clearTimeout(t)
  }, [])

  const grouped = useMemo(() => {
    const buckets: Record<FlagSeverity, ContentFlag[]> = {
      urgent: [],
      review: [],
      info: [],
    }
    for (const f of flags) {
      const tier = (
        ['urgent', 'review', 'info'].includes(f.severity)
          ? f.severity
          : 'review'
      ) as FlagSeverity
      buckets[tier].push(f)
    }
    return buckets
  }, [flags])

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

  const counts = {
    urgent: grouped.urgent.length,
    review: grouped.review.length,
    info: grouped.info.length,
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
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
              <p className="font-mono text-[10px] text-neon-cyan/60 mt-0.5 tabular-nums">
                {counts.urgent > 0 && (
                  <span className="text-[#ff0040] font-bold">
                    {counts.urgent} urgent
                  </span>
                )}
                {counts.urgent > 0 && (counts.review > 0 || counts.info > 0) && ' · '}
                {counts.review > 0 && <span>{counts.review} review</span>}
                {counts.review > 0 && counts.info > 0 && ' · '}
                {counts.info > 0 && (
                  <span className="text-muted-foreground/60">
                    {counts.info} info
                  </span>
                )}
                {counts.urgent + counts.review + counts.info === 0 && (
                  <span>all clear</span>
                )}
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

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-3 space-y-4">
          {flags.length === 0 && (
            <div className="flex flex-col items-center justify-center h-32 gap-2 text-muted-foreground/40">
              <span className="font-mono text-[10px] uppercase tracking-widest">
                No flags pending
              </span>
            </div>
          )}

          {grouped.urgent.length > 0 && (
            <section className="space-y-2">
              <div className="flex items-center gap-2 px-1">
                <AlertOctagon className="w-3 h-3 text-[#ff0040]" />
                <h3 className="font-mono text-[10px] uppercase tracking-widest text-[#ff0040] font-bold">
                  URGENT — review now
                </h3>
              </div>
              {grouped.urgent.map((flag) => (
                <FlagCard
                  key={flag.id}
                  flag={flag}
                  pending={pending === flag.id}
                  onReview={() => handleReview(flag)}
                />
              ))}
            </section>
          )}

          {grouped.review.length > 0 && (
            <section className="space-y-2">
              <div className="flex items-center gap-2 px-1">
                <AlertTriangle className="w-3 h-3 text-neon-pink" />
                <h3 className="font-mono text-[10px] uppercase tracking-widest text-neon-pink font-bold">
                  Review
                </h3>
              </div>
              {grouped.review.map((flag) => (
                <FlagCard
                  key={flag.id}
                  flag={flag}
                  pending={pending === flag.id}
                  onReview={() => handleReview(flag)}
                />
              ))}
            </section>
          )}

          {grouped.info.length > 0 && (
            <section className="space-y-2">
              <button
                onClick={() => setInfoExpanded((v) => !v)}
                className="w-full flex items-center justify-between gap-2 px-2 py-1.5 industrial-inset border border-neon-cyan/20 hover:border-neon-cyan/40 transition-all cursor-pointer"
              >
                <div className="flex items-center gap-2">
                  {infoExpanded ? (
                    <ChevronDown className="w-3 h-3 text-neon-cyan/70" />
                  ) : (
                    <ChevronRight className="w-3 h-3 text-neon-cyan/70" />
                  )}
                  <Info className="w-3 h-3 text-neon-cyan/70" />
                  <h3 className="font-mono text-[10px] uppercase tracking-widest text-neon-cyan/80 font-bold">
                    FYI ({grouped.info.length})
                  </h3>
                </div>
                <span className="font-mono text-[9px] text-muted-foreground/40 uppercase tracking-wider">
                  {infoExpanded ? 'hide' : 'show'}
                </span>
              </button>
              {infoExpanded &&
                grouped.info.map((flag) => (
                  <FlagCard
                    key={flag.id}
                    flag={flag}
                    pending={pending === flag.id}
                    onReview={() => handleReview(flag)}
                  />
                ))}
            </section>
          )}
        </div>
      </aside>
    </>
  )
}
