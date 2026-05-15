import { useEffect, useMemo, useState } from 'react'
import {
  Archive,
  ArchiveRestore,
  ChevronDown,
  ChevronRight,
  MessageSquarePlus,
  Plus,
  Tag,
  UserPlus,
  X,
} from 'lucide-react'
import { cn } from '../lib/utils'
import {
  addEntityTag,
  getEntities,
  getEntityTimeline,
  getEntityThreads,
  patchEntity,
  removeEntityTag,
} from '../api/client'
import type {
  Entity,
  EntityAccentColor,
  EntityRelationshipType,
  EntityTimelineEntry,
  Thread,
} from '../api/client'
import { NewTeamMemberModal } from './NewTeamMemberModal'

interface RosterPageProps {
  onOpenThread: (thread: Thread) => void
  onCreateEntityThread: (entity: Entity) => void
  // Fires whenever the user expands a card (entityId) or collapses
  // the currently expanded one (null). DashboardPage uses this to
  // filter the sidebar thread list to the focused entity.
  onEntityFocused?: (entityId: number | null) => void
}

const ACCENT: Record<
  EntityAccentColor,
  {
    text: string
    border: string
    glow: string
    bgTint: string
    fillBg: string
  }
> = {
  cyan: {
    text: 'text-neon-cyan',
    border: 'border-neon-cyan/50',
    glow: 'glow-cyan',
    bgTint: 'bg-neon-cyan/5',
    fillBg: 'bg-neon-cyan',
  },
  pink: {
    text: 'text-neon-pink',
    border: 'border-neon-pink/50',
    glow: 'glow-pink',
    bgTint: 'bg-neon-pink/5',
    fillBg: 'bg-neon-pink',
  },
  green: {
    text: 'text-neon-green',
    border: 'border-neon-green/50',
    glow: 'glow-green',
    bgTint: 'bg-neon-green/5',
    fillBg: 'bg-neon-green',
  },
  yellow: {
    text: 'text-neon-yellow',
    border: 'border-neon-yellow/50',
    glow: 'glow-yellow',
    bgTint: 'bg-neon-yellow/5',
    fillBg: 'bg-neon-yellow',
  },
}

const RELATIONSHIP_LABEL: Record<EntityRelationshipType, string> = {
  direct_report: 'DIRECT REPORT',
  peer: 'PEER',
  skip_level: 'SKIP-LEVEL',
  stakeholder: 'STAKEHOLDER',
  external: 'EXTERNAL',
}

function shortDate(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  } catch {
    return ''
  }
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length === 0) return '??'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function EntityCard({
  entity,
  expanded,
  onToggleExpanded,
  onLocalUpdate,
  onOpenThread,
  onCreateEntityThread,
  onArchiveToggle,
}: {
  entity: Entity
  expanded: boolean
  onToggleExpanded: () => void
  onLocalUpdate: (next: Entity) => void
  onOpenThread: (thread: Thread) => void
  onCreateEntityThread: (entity: Entity) => void
  onArchiveToggle: () => void
}) {
  const [timeline, setTimeline] = useState<EntityTimelineEntry[]>([])
  const [linkedThreads, setLinkedThreads] = useState<Thread[]>([])
  const [loadingExpand, setLoadingExpand] = useState(false)
  const [newTagInput, setNewTagInput] = useState('')
  const [addingTag, setAddingTag] = useState(false)
  const accent = ACCENT[entity.accent_color] ?? ACCENT.cyan

  useEffect(() => {
    if (!expanded) return
    let cancelled = false
    setLoadingExpand(true)
    Promise.all([
      getEntityTimeline(entity.id).catch(() => []),
      getEntityThreads(entity.id).catch(() => []),
    ])
      .then(([tl, threads]) => {
        if (cancelled) return
        setTimeline(tl)
        setLinkedThreads(threads)
      })
      .finally(() => {
        if (!cancelled) setLoadingExpand(false)
      })
    return () => {
      cancelled = true
    }
  }, [expanded, entity.id])

  const handleAddTag = async () => {
    const tag = newTagInput.trim()
    if (!tag || addingTag) return
    setAddingTag(true)
    try {
      const tags = await addEntityTag(entity.id, tag)
      onLocalUpdate({ ...entity, tags })
      setNewTagInput('')
    } catch (e) {
      console.error('Failed to add tag:', e)
    } finally {
      setAddingTag(false)
    }
  }

  const handleRemoveTag = async (tag: string) => {
    try {
      const tags = await removeEntityTag(entity.id, tag)
      onLocalUpdate({ ...entity, tags })
    } catch (e) {
      console.error('Failed to remove tag:', e)
    }
  }

  return (
    <div
      className={cn(
        'industrial-panel border-2 transition-all',
        accent.border,
        expanded && 'industrial-raised',
      )}
    >
      {/* Card head — always visible */}
      <div className="p-4 flex items-start gap-3">
        {/* Avatar */}
        <div
          className={cn(
            'shrink-0 w-12 h-12 industrial-inset border-2 flex items-center justify-center font-mono text-sm font-bold',
            accent.border,
            accent.text,
            accent.bgTint,
          )}
        >
          {initials(entity.name)}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3
              className={cn(
                'font-sans text-base font-bold truncate',
                accent.text,
              )}
            >
              {entity.name}
            </h3>
            <span
              className={cn(
                'font-mono text-[9px] uppercase tracking-widest px-1.5 py-0.5 border',
                accent.border,
                accent.text,
              )}
            >
              {RELATIONSHIP_LABEL[entity.relationship_type] ?? 'OTHER'}
            </span>
          </div>
          {entity.role && (
            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70 mt-1">
              {entity.role}
            </p>
          )}
          <div className="flex items-center gap-3 mt-2 flex-wrap">
            <span className="font-mono text-[10px] text-muted-foreground/60">
              {shortDate(entity.updated_at)}
            </span>
            <span className="font-mono text-[10px] text-muted-foreground/60">
              {entity.thread_count} thread
              {entity.thread_count === 1 ? '' : 's'}
            </span>
            {entity.tags.length > 0 && (
              <span className="font-mono text-[10px] text-muted-foreground/60">
                {entity.tags.length} tag
                {entity.tags.length === 1 ? '' : 's'}
              </span>
            )}
          </div>
        </div>

        <div className="flex flex-col items-end gap-1">
          <button
            onClick={onArchiveToggle}
            title={
              entity.status === 'archived' ? 'Restore' : 'Archive'
            }
            className="p-1.5 industrial-inset border border-muted-foreground/20 text-muted-foreground hover:text-neon-pink hover:border-neon-pink/40 transition-all cursor-pointer"
          >
            {entity.status === 'archived' ? (
              <ArchiveRestore className="w-3.5 h-3.5" />
            ) : (
              <Archive className="w-3.5 h-3.5" />
            )}
          </button>
          <button
            onClick={onToggleExpanded}
            title={expanded ? 'Collapse' : 'Expand'}
            className={cn(
              'p-1.5 industrial-inset border transition-all cursor-pointer',
              accent.border,
              accent.text,
              'hover:' + accent.glow,
            )}
          >
            {expanded ? (
              <ChevronDown className="w-3.5 h-3.5" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>

      {/* Tags row — always visible */}
      <div className="px-4 pb-3 flex flex-wrap gap-1.5">
        {entity.tags.map((tag) => (
          <button
            key={tag}
            onClick={() => handleRemoveTag(tag)}
            title="Click to remove"
            className={cn(
              'flex items-center gap-1 px-2 py-0.5 industrial-inset border font-mono text-[10px] uppercase tracking-wider cursor-pointer group transition-all',
              accent.border,
              accent.text,
            )}
          >
            <Tag className="w-2.5 h-2.5 opacity-60" />
            <span>{tag}</span>
            <X className="w-2.5 h-2.5 opacity-0 group-hover:opacity-100" />
          </button>
        ))}
        {expanded && (
          <div className="flex items-center gap-1">
            <input
              value={newTagInput}
              onChange={(e) => setNewTagInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAddTag()
              }}
              placeholder="add tag..."
              className="px-2 py-0.5 industrial-inset border border-muted-foreground/20 font-mono text-[10px] bg-transparent text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:border-neon-cyan/40"
              style={{ width: '80px' }}
            />
            <button
              onClick={handleAddTag}
              disabled={!newTagInput.trim() || addingTag}
              className={cn(
                'p-0.5 industrial-inset border border-neon-cyan/30 text-neon-cyan hover:border-neon-cyan/60 transition-all cursor-pointer',
                (!newTagInput.trim() || addingTag) &&
                  'opacity-30 cursor-not-allowed',
              )}
            >
              <Plus className="w-2.5 h-2.5" />
            </button>
          </div>
        )}
      </div>

      {/* Expanded body */}
      {expanded && (
        <>
          <div className="industrial-divider-h" />
          <div className="p-4 space-y-3">
            {loadingExpand && (
              <p className="font-mono text-[10px] text-muted-foreground/50">
                loading...
              </p>
            )}

            {/* Timeline */}
            <div>
              <p
                className={cn(
                  'font-mono text-[10px] uppercase tracking-widest font-bold mb-1.5',
                  accent.text,
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
                  {timeline.map((entry) => (
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

            {/* Linked threads */}
            <div>
              <p
                className={cn(
                  'font-mono text-[10px] uppercase tracking-widest font-bold mb-1.5',
                  accent.text,
                )}
              >
                // Threads
              </p>
              {linkedThreads.length === 0 ? (
                <p className="font-mono text-[10px] text-muted-foreground/40 italic">
                  no threads yet
                </p>
              ) : (
                <ul className="space-y-1">
                  {linkedThreads.map((t) => (
                    <li key={t.id}>
                      <button
                        onClick={() => onOpenThread(t)}
                        className="w-full text-left industrial-inset border border-muted-foreground/10 px-2 py-1 hover:border-neon-cyan/30 transition-all cursor-pointer flex items-center justify-between gap-2"
                      >
                        <span className="font-sans text-xs text-foreground/80 truncate">
                          {t.title}
                        </span>
                        <span className="font-mono text-[9px] text-muted-foreground/50 tabular-nums shrink-0">
                          {t.message_count} msg
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* New thread CTA */}
            <button
              onClick={() => onCreateEntityThread(entity)}
              className={cn(
                'w-full flex items-center justify-center gap-2 py-2 industrial-raised border-2 transition-all cursor-pointer font-mono text-[10px] uppercase tracking-wider font-bold',
                accent.border,
                accent.text,
                `hover:${accent.glow}`,
              )}
            >
              <MessageSquarePlus className="w-3.5 h-3.5" />
              New Thread with {entity.name}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

export function RosterPage({
  onOpenThread,
  onCreateEntityThread,
  onEntityFocused,
}: RosterPageProps) {
  const [entities, setEntities] = useState<Entity[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [archivedExpanded, setArchivedExpanded] = useState(false)
  // Exclusive expansion: clicking one card collapses any other. This
  // keeps the sidebar entity-filter unambiguous — there's always a
  // single focused entity, never a list to pick from.
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const handleToggleExpanded = (entityId: number) => {
    setExpandedId((prev) => {
      const next = prev === entityId ? null : entityId
      onEntityFocused?.(next)
      return next
    })
  }

  const load = () => {
    setLoading(true)
    getEntities()
      .then(setEntities)
      .catch((e) => console.error('Failed to load entities:', e))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  const handleEntityUpdated = (next: Entity) => {
    setEntities((prev) =>
      prev.map((e) => (e.id === next.id ? next : e)),
    )
  }

  const handleArchiveToggle = async (entity: Entity) => {
    const newStatus = entity.status === 'archived' ? 'active' : 'archived'
    try {
      const updated = await patchEntity(entity.id, { status: newStatus })
      handleEntityUpdated(updated)
    } catch (e) {
      console.error('Failed to toggle archive:', e)
    }
  }

  const { active, archived } = useMemo(() => {
    const a: Entity[] = []
    const ar: Entity[] = []
    for (const e of entities) {
      if (e.status === 'archived') ar.push(e)
      else a.push(e)
    }
    return { active: a, archived: ar }
  }, [entities])

  return (
    <div className="flex-1 h-full overflow-y-auto bg-gradient-to-b from-[#0a0a10] to-[#08080d] scanlines">
      <div className="max-w-[1200px] mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="font-mono text-xl uppercase tracking-widest text-neon-pink glow-pink-text font-bold">
              // TEAM ROSTER
            </h1>
            <p className="font-mono text-[11px] text-muted-foreground/70 mt-1 max-w-[560px]">
              Pick a teammate to review coaching history, or open a thread
              to continue the conversation.
            </p>
          </div>
          <button
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-2 px-3 py-2 industrial-raised border-2 border-neon-cyan/50 text-neon-cyan hover:text-neon-pink hover:border-neon-pink/50 hover:glow-pink transition-all cursor-pointer font-mono text-[10px] uppercase tracking-widest font-bold"
          >
            <UserPlus className="w-3.5 h-3.5" />+ New Team Member
          </button>
        </div>

        <div className="industrial-divider-h" />

        {/* Active grid */}
        {loading ? (
          <div className="font-mono text-[10px] text-muted-foreground/50 uppercase tracking-widest">
            loading roster...
          </div>
        ) : active.length === 0 ? (
          <div className="industrial-inset border border-muted-foreground/20 p-8 text-center space-y-2">
            <p className="font-mono text-[11px] text-muted-foreground/70 uppercase tracking-widest">
              no team members yet
            </p>
            <p className="font-mono text-[10px] text-muted-foreground/50">
              Click "+ New Team Member" to add your first one.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {active.map((e) => (
              <EntityCard
                key={e.id}
                entity={e}
                expanded={expandedId === e.id}
                onToggleExpanded={() => handleToggleExpanded(e.id)}
                onLocalUpdate={handleEntityUpdated}
                onOpenThread={onOpenThread}
                onCreateEntityThread={onCreateEntityThread}
                onArchiveToggle={() => handleArchiveToggle(e)}
              />
            ))}
          </div>
        )}

        {/* Archived section */}
        {archived.length > 0 && (
          <div className="space-y-2 pt-2">
            <button
              onClick={() => setArchivedExpanded((v) => !v)}
              className="w-full flex items-center justify-between gap-2 px-3 py-2 industrial-inset border border-muted-foreground/20 hover:border-muted-foreground/40 transition-all cursor-pointer"
            >
              <div className="flex items-center gap-2">
                {archivedExpanded ? (
                  <ChevronDown className="w-3 h-3 text-muted-foreground/70" />
                ) : (
                  <ChevronRight className="w-3 h-3 text-muted-foreground/70" />
                )}
                <Archive className="w-3 h-3 text-muted-foreground/70" />
                <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground/70 font-bold">
                  Archived ({archived.length})
                </span>
              </div>
              <span className="font-mono text-[9px] text-muted-foreground/40 uppercase tracking-wider">
                {archivedExpanded ? 'hide' : 'show'}
              </span>
            </button>
            {archivedExpanded && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {archived.map((e) => (
                  <EntityCard
                    key={e.id}
                    entity={e}
                    expanded={expandedId === e.id}
                    onToggleExpanded={() => handleToggleExpanded(e.id)}
                    onLocalUpdate={handleEntityUpdated}
                    onOpenThread={onOpenThread}
                    onCreateEntityThread={onCreateEntityThread}
                    onArchiveToggle={() => handleArchiveToggle(e)}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {modalOpen && (
        <NewTeamMemberModal
          onClose={() => setModalOpen(false)}
          onCreated={(entity) => {
            setEntities((prev) => [...prev, entity])
            setModalOpen(false)
          }}
        />
      )}
    </div>
  )
}
