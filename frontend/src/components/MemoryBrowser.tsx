import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Brain,
  X,
  Search,
  ChevronDown,
  ChevronRight,
  Pin,
  PinOff,
  CheckCircle2,
  Trash2,
  AlertTriangle,
} from 'lucide-react'
import { cn } from '../lib/utils'
import {
  getMemories,
  confirmMemory,
  togglePinMemory,
  archiveMemoryRow,
  type MemoryLayer,
  type MemoryRow,
  type MemoryStatusFilter,
} from '../api/client'

interface MemoryBrowserProps {
  onClose: () => void
}

// Layer accent palette. Spec calls for purple/cyan/green — we map
// "purple" onto the existing neon-pink token (closest in this theme)
// while keeping a real purple inline-color fallback for the badge.
const LAYER_STYLES: Record<
  MemoryLayer,
  { badge: string; border: string; label: string }
> = {
  strategic: {
    badge:
      'bg-[#9b5cff]/15 border-[#9b5cff]/60 text-[#c89dff]',
    border: 'border-[#9b5cff]/50',
    label: 'STRATEGIC',
  },
  operational: {
    badge:
      'bg-neon-cyan/10 border-neon-cyan/50 text-neon-cyan glow-cyan-text',
    border: 'border-neon-cyan/40',
    label: 'OPERATIONAL',
  },
  analytical: {
    badge:
      'bg-neon-green/10 border-neon-green/50 text-neon-green glow-green-text',
    border: 'border-neon-green/40',
    label: 'ANALYTICAL',
  },
}

const ALL_LAYERS: MemoryLayer[] = [
  'strategic',
  'operational',
  'analytical',
]

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return iso
  }
}

function daysAgo(iso: string | null): string {
  if (!iso) return 'never'
  try {
    const ms = Date.now() - new Date(iso).getTime()
    const days = Math.floor(ms / (1000 * 60 * 60 * 24))
    if (days <= 0) return 'today'
    if (days === 1) return '1 day ago'
    return `${days} days ago`
  } catch {
    return iso
  }
}

interface MemoryCardProps {
  memory: MemoryRow
  expanded: boolean
  onToggleExpand: () => void
  onConfirm: () => void
  onTogglePin: () => void
  onDelete: () => void
  busy: boolean
}

function MemoryCard({
  memory,
  expanded,
  onToggleExpand,
  onConfirm,
  onTogglePin,
  onDelete,
  busy,
}: MemoryCardProps) {
  const layerStyle = LAYER_STYLES[memory.layer]
  // Border priority: pinned > stale > layer default. Both cyan/amber
  // here so they stay distinguishable from layer accent colors.
  const borderClass = memory.pinned
    ? 'border-neon-cyan/70 glow-cyan'
    : memory.stale
      ? 'border-neon-yellow/60'
      : layerStyle.border

  return (
    <div
      className={cn(
        'industrial-raised border-l-2 bg-[#0a0a0e] p-3 transition-colors',
        borderClass,
      )}
    >
      <button
        type="button"
        onClick={onToggleExpand}
        className="w-full text-left flex items-start gap-2"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 mt-1 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 mt-1 text-muted-foreground shrink-0" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1.5">
            <span
              className={cn(
                'px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider font-bold border',
                layerStyle.badge,
              )}
            >
              {layerStyle.label}
            </span>
            {memory.project_tag && memory.project_tag !== 'global' && (
              <span className="px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted-foreground border border-muted-foreground/30">
                {memory.project_tag}
              </span>
            )}
            {memory.pinned && (
              <span className="px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider font-bold text-neon-cyan border border-neon-cyan/60 glow-cyan-text flex items-center gap-1">
                <Pin className="w-2.5 h-2.5" />
                PINNED
              </span>
            )}
            {memory.stale && (
              <span className="px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider font-bold text-neon-yellow border border-neon-yellow/60 flex items-center gap-1">
                <AlertTriangle className="w-2.5 h-2.5" />
                STALE
              </span>
            )}
            {memory.confidence != null && (
              <span className="ml-auto font-mono text-[9px] text-muted-foreground/70 uppercase tracking-wider">
                conf {memory.confidence.toFixed(2)}
              </span>
            )}
          </div>
          <div
            className={cn(
              'font-sans text-sm text-foreground/90 leading-relaxed',
              !expanded && 'line-clamp-2',
            )}
          >
            {memory.content || '[empty]'}
          </div>
        </div>
      </button>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-[#12121a] space-y-2">
          <div className="grid grid-cols-2 gap-3 text-[10px] font-mono uppercase tracking-wider">
            <div>
              <span className="text-muted-foreground/50">Created</span>
              <div className="text-foreground/80 mt-0.5 normal-case">
                {formatDate(memory.created_at)}
              </div>
            </div>
            <div>
              <span className="text-muted-foreground/50">Last confirmed</span>
              <div className="text-foreground/80 mt-0.5 normal-case">
                {formatDate(memory.last_confirmed)}
                {memory.last_confirmed && (
                  <span className="ml-1 text-muted-foreground/50 text-[9px]">
                    ({daysAgo(memory.last_confirmed)})
                  </span>
                )}
              </div>
            </div>
            {memory.flag_after_days != null && (
              <div>
                <span className="text-muted-foreground/50">Flags after</span>
                <div className="text-foreground/80 mt-0.5 normal-case">
                  {memory.flag_after_days} days
                </div>
              </div>
            )}
            {memory.channel_name && (
              <div>
                <span className="text-muted-foreground/50">Channel</span>
                <div className="text-foreground/80 mt-0.5 normal-case">
                  {memory.channel_name}
                </div>
              </div>
            )}
          </div>
          <div className="flex flex-wrap gap-2 pt-1">
            <button
              type="button"
              onClick={onConfirm}
              disabled={busy}
              title="Refresh last-confirmed timestamp"
              className="px-3 py-1.5 industrial-raised border border-neon-green/40 text-neon-green hover:glow-green transition-all flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span className="font-mono text-[10px] uppercase tracking-wider font-bold">
                Still true
              </span>
            </button>
            <button
              type="button"
              onClick={onTogglePin}
              disabled={busy}
              className="px-3 py-1.5 industrial-raised border border-neon-cyan/40 text-neon-cyan hover:glow-cyan transition-all flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {memory.pinned ? (
                <>
                  <PinOff className="w-3.5 h-3.5" />
                  <span className="font-mono text-[10px] uppercase tracking-wider font-bold">
                    Unpin
                  </span>
                </>
              ) : (
                <>
                  <Pin className="w-3.5 h-3.5" />
                  <span className="font-mono text-[10px] uppercase tracking-wider font-bold">
                    Pin
                  </span>
                </>
              )}
            </button>
            <button
              type="button"
              onClick={onDelete}
              disabled={busy}
              title="Archive this memory (soft delete)"
              className="px-3 py-1.5 industrial-raised border border-neon-pink/40 text-neon-pink hover:glow-pink transition-all flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed ml-auto"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span className="font-mono text-[10px] uppercase tracking-wider font-bold">
                Delete
              </span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export function MemoryBrowser({ onClose }: MemoryBrowserProps) {
  const [memories, setMemories] = useState<MemoryRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [layerFilter, setLayerFilter] = useState<MemoryLayer | null>(null)
  const [statusFilter, setStatusFilter] = useState<MemoryStatusFilter | null>(
    null,
  )
  const [searchInput, setSearchInput] = useState('')
  // Debounce text-search to one network call per ~200ms of typing.
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const debounceRef = useRef<number | null>(null)
  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
    debounceRef.current = window.setTimeout(() => {
      setDebouncedSearch(searchInput.trim())
    }, 200)
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current)
    }
  }, [searchInput])

  const [expandedKey, setExpandedKey] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)

  const keyOf = (m: MemoryRow) => `${m.layer}:${m.id}`

  const refetch = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getMemories({
        layer: layerFilter ?? undefined,
        search: debouncedSearch || undefined,
        status: statusFilter ?? undefined,
      })
      setMemories(res.memories)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [layerFilter, statusFilter, debouncedSearch])

  useEffect(() => {
    refetch()
  }, [refetch])

  const counts = useMemo(() => {
    const total = memories.length
    const stale = memories.filter((m) => m.stale).length
    const pinned = memories.filter((m) => m.pinned).length
    return { total, stale, pinned }
  }, [memories])

  async function handleConfirm(m: MemoryRow) {
    const k = keyOf(m)
    setBusyKey(k)
    try {
      await confirmMemory(m.layer, m.id)
      // Optimistically refresh just this row's stale flag; a full
      // refetch happens at the end of the action for the canonical
      // last_confirmed timestamp from the server.
      setMemories((prev) =>
        prev.map((row) =>
          keyOf(row) === k
            ? { ...row, stale: false, last_confirmed: new Date().toISOString() }
            : row,
        ),
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }

  async function handleTogglePin(m: MemoryRow) {
    const k = keyOf(m)
    setBusyKey(k)
    try {
      const res = await togglePinMemory(m.layer, m.id)
      setMemories((prev) =>
        prev.map((row) =>
          keyOf(row) === k ? { ...row, pinned: res.pinned } : row,
        ),
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }

  async function handleDelete(m: MemoryRow) {
    const k = keyOf(m)
    if (!window.confirm(
      `Archive this ${m.layer} memory? It will be removed from active retrieval.`,
    )) return
    setBusyKey(k)
    try {
      await archiveMemoryRow(m.layer, m.id)
      setMemories((prev) => prev.filter((row) => keyOf(row) !== k))
      if (expandedKey === k) setExpandedKey(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <div className="flex-1 h-full flex flex-col bg-gradient-to-b from-[#0a0a0e] to-[#040406] relative scanlines">
      {/* Header */}
      <div className="px-4 py-3 border-b border-neon-cyan/20 industrial-panel flex items-center gap-3">
        <Brain className="w-5 h-5 text-neon-cyan glow-cyan" />
        <span className="font-mono text-xs uppercase tracking-widest text-neon-cyan glow-cyan-text font-bold">
          Memory Browser
        </span>
        <span className="font-mono text-[10px] text-muted-foreground/60 uppercase tracking-wider">
          · {counts.total} active
          {counts.stale > 0 && ` · ${counts.stale} stale`}
          {counts.pinned > 0 && ` · ${counts.pinned} pinned`}
        </span>
        <button
          type="button"
          onClick={onClose}
          title="Close (Esc)"
          className="ml-auto p-1.5 industrial-inset border border-muted-foreground/30 text-muted-foreground hover:text-neon-pink hover:border-neon-pink/50 transition-all"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Filter bar */}
      <div className="px-4 py-3 border-b border-[#12121a] flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="w-3.5 h-3.5 text-muted-foreground/60 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search memory content..."
            className="w-full pl-8 pr-3 py-1.5 industrial-inset border border-neon-cyan/30 bg-transparent text-foreground placeholder:text-muted-foreground/40 font-sans text-sm focus:outline-none focus:border-neon-pink/50"
          />
        </div>

        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setLayerFilter(null)}
            className={cn(
              'px-2.5 py-1 industrial-inset border font-mono text-[10px] uppercase tracking-wider transition-all',
              layerFilter === null
                ? 'border-neon-cyan/70 text-neon-cyan glow-cyan-text'
                : 'border-muted-foreground/30 text-muted-foreground hover:text-foreground',
            )}
          >
            All layers
          </button>
          {ALL_LAYERS.map((l) => {
            const active = layerFilter === l
            return (
              <button
                key={l}
                type="button"
                onClick={() => setLayerFilter(active ? null : l)}
                className={cn(
                  'px-2.5 py-1 industrial-inset border font-mono text-[10px] uppercase tracking-wider transition-all',
                  active
                    ? LAYER_STYLES[l].badge
                    : 'border-muted-foreground/30 text-muted-foreground hover:text-foreground',
                )}
              >
                {LAYER_STYLES[l].label}
              </button>
            )
          })}
        </div>

        <div className="flex gap-1 ml-auto">
          <button
            type="button"
            onClick={() => setStatusFilter(null)}
            className={cn(
              'px-2.5 py-1 industrial-inset border font-mono text-[10px] uppercase tracking-wider transition-all',
              statusFilter === null
                ? 'border-neon-cyan/70 text-neon-cyan glow-cyan-text'
                : 'border-muted-foreground/30 text-muted-foreground hover:text-foreground',
            )}
          >
            All
          </button>
          <button
            type="button"
            onClick={() =>
              setStatusFilter(statusFilter === 'stale' ? null : 'stale')
            }
            className={cn(
              'px-2.5 py-1 industrial-inset border font-mono text-[10px] uppercase tracking-wider transition-all',
              statusFilter === 'stale'
                ? 'border-neon-yellow/70 text-neon-yellow'
                : 'border-muted-foreground/30 text-muted-foreground hover:text-foreground',
            )}
          >
            Stale
          </button>
          <button
            type="button"
            onClick={() =>
              setStatusFilter(statusFilter === 'pinned' ? null : 'pinned')
            }
            className={cn(
              'px-2.5 py-1 industrial-inset border font-mono text-[10px] uppercase tracking-wider transition-all',
              statusFilter === 'pinned'
                ? 'border-neon-cyan/70 text-neon-cyan glow-cyan-text'
                : 'border-muted-foreground/30 text-muted-foreground hover:text-foreground',
            )}
          >
            Pinned
          </button>
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {error && (
          <div className="mb-3 px-3 py-2 industrial-inset border border-neon-pink/60 text-neon-pink font-mono text-xs">
            {error}
          </div>
        )}
        {loading && memories.length === 0 ? (
          <p className="text-center font-mono text-[10px] uppercase tracking-wider text-muted-foreground/50 py-8">
            Loading memories...
          </p>
        ) : memories.length === 0 ? (
          <p className="text-center font-mono text-[10px] uppercase tracking-wider text-muted-foreground/50 py-8">
            No memories match the current filters.
          </p>
        ) : (
          <ul className="space-y-2">
            {memories.map((m) => {
              const k = keyOf(m)
              return (
                <li key={k}>
                  <MemoryCard
                    memory={m}
                    expanded={expandedKey === k}
                    onToggleExpand={() =>
                      setExpandedKey(expandedKey === k ? null : k)
                    }
                    onConfirm={() => handleConfirm(m)}
                    onTogglePin={() => handleTogglePin(m)}
                    onDelete={() => handleDelete(m)}
                    busy={busyKey === k}
                  />
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
