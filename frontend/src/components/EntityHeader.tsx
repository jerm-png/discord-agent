import { useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, Tag } from 'lucide-react'
import { cn } from '../lib/utils'
import { getEntities, getEntityTimeline } from '../api/client'
import type {
  Entity,
  EntityAccentColor,
  EntityTimelineEntry,
} from '../api/client'

interface EntityHeaderProps {
  entityId: number
}

const ACCENT_TEXT: Record<EntityAccentColor, string> = {
  cyan: 'text-neon-cyan',
  pink: 'text-neon-pink',
  green: 'text-neon-green',
  yellow: 'text-neon-yellow',
}

const ACCENT_BORDER: Record<EntityAccentColor, string> = {
  cyan: 'border-neon-cyan/50',
  pink: 'border-neon-pink/50',
  green: 'border-neon-green/50',
  yellow: 'border-neon-yellow/50',
}

const ACCENT_BG: Record<EntityAccentColor, string> = {
  cyan: 'bg-neon-cyan/5',
  pink: 'bg-neon-pink/5',
  green: 'bg-neon-green/5',
  yellow: 'bg-neon-yellow/5',
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length === 0) return '??'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export function EntityHeader({ entityId }: EntityHeaderProps) {
  const [entity, setEntity] = useState<Entity | null>(null)
  const [timeline, setTimeline] = useState<EntityTimelineEntry[]>([])
  const [expanded, setExpanded] = useState(false)

  // Pull entity from /entities and timeline lazily on expand.
  useEffect(() => {
    let cancelled = false
    getEntities()
      .then((all) => {
        if (cancelled) return
        const match = all.find((e) => e.id === entityId) ?? null
        setEntity(match)
      })
      .catch(() => {
        if (!cancelled) setEntity(null)
      })
    return () => {
      cancelled = true
    }
  }, [entityId])

  useEffect(() => {
    if (!expanded || !entity) return
    let cancelled = false
    getEntityTimeline(entity.id)
      .then((tl) => {
        if (!cancelled) setTimeline(tl)
      })
      .catch(() => {
        if (!cancelled) setTimeline([])
      })
    return () => {
      cancelled = true
    }
  }, [expanded, entity])

  if (!entity) return null

  const textColor = ACCENT_TEXT[entity.accent_color] ?? ACCENT_TEXT.cyan
  const borderColor = ACCENT_BORDER[entity.accent_color] ?? ACCENT_BORDER.cyan
  const bgColor = ACCENT_BG[entity.accent_color] ?? ACCENT_BG.cyan

  return (
    <div
      className={cn(
        'industrial-inset border-b-2 transition-all',
        borderColor,
        bgColor,
      )}
    >
      {/* Collapsed bar */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-2 cursor-pointer text-left hover:industrial-raised transition-all"
      >
        <div
          className={cn(
            'w-8 h-8 industrial-inset border-2 flex items-center justify-center font-mono text-[10px] font-bold shrink-0',
            borderColor,
            textColor,
          )}
        >
          {initials(entity.name)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={cn('font-sans text-sm font-bold', textColor)}>
              {entity.name}
            </span>
            {entity.role && (
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
                {entity.role}
              </span>
            )}
          </div>
          {entity.tags.length > 0 && (
            <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
              {entity.tags.slice(0, 4).map((tag) => (
                <span
                  key={tag}
                  className={cn(
                    'flex items-center gap-1 px-1.5 py-0.5 industrial-inset border font-mono text-[9px] uppercase tracking-wider',
                    borderColor,
                    textColor,
                  )}
                >
                  <Tag className="w-2 h-2 opacity-60" />
                  {tag}
                </span>
              ))}
              {entity.tags.length > 4 && (
                <span className="font-mono text-[9px] text-muted-foreground/50">
                  +{entity.tags.length - 4} more
                </span>
              )}
            </div>
          )}
        </div>
        {expanded ? (
          <ChevronDown className={cn('w-3.5 h-3.5', textColor)} />
        ) : (
          <ChevronRight className={cn('w-3.5 h-3.5', textColor)} />
        )}
      </button>

      {/* Expanded — full profile + timeline */}
      {expanded && (
        <div className="px-4 pb-3 pt-1 space-y-3">
          <div className="industrial-divider-h" />

          {entity.tags.length > 0 && (
            <div>
              <p
                className={cn(
                  'font-mono text-[9px] uppercase tracking-widest font-bold mb-1.5',
                  textColor,
                )}
              >
                // Active Situation
              </p>
              <div className="flex flex-wrap gap-1.5">
                {entity.tags.map((tag) => (
                  <span
                    key={tag}
                    className={cn(
                      'flex items-center gap-1 px-1.5 py-0.5 industrial-inset border font-mono text-[10px] uppercase tracking-wider',
                      borderColor,
                      textColor,
                    )}
                  >
                    <Tag className="w-2.5 h-2.5 opacity-60" />
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div>
            <p
              className={cn(
                'font-mono text-[9px] uppercase tracking-widest font-bold mb-1.5',
                textColor,
              )}
            >
              // Timeline
            </p>
            {timeline.length === 0 ? (
              <p className="font-mono text-[10px] text-muted-foreground/40 italic">
                no entries yet
              </p>
            ) : (
              <ul className="space-y-1">
                {timeline.slice(-6).map((entry) => (
                  <li
                    key={entry.id}
                    className="industrial-inset border border-muted-foreground/10 px-2 py-1 flex items-start gap-2"
                  >
                    <span className="font-mono text-[9px] text-neon-yellow/60 tabular-nums shrink-0">
                      {entry.recorded_at.slice(0, 10)}
                    </span>
                    <span className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground/50 shrink-0">
                      {entry.category}
                    </span>
                    <span
                      className={cn(
                        'font-sans text-xs',
                        entry.status === 'active'
                          ? 'text-foreground/80'
                          : 'text-muted-foreground/50 line-through',
                      )}
                    >
                      {entry.fact}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
