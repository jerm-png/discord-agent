import { useCallback, useEffect, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Activity,
  Beaker,
  CalendarClock,
  ClipboardList,
  ArrowUp,
  ArrowDown,
  Minus,
  Plus,
  CheckCircle2,
  Upload,
} from 'lucide-react'
import { cn } from '../lib/utils'
import { ChatPanel, type ChatMessage } from '../components/ChatPanel'
import { CommandBar } from '../components/CommandBar'
import {
  getMedbayProtocol,
  getMedbayLatestLabs,
  getMedbayFollowups,
  getMedbayChanges,
  completeMedbayFollowup,
  type MedbayProtocolItem,
  type MedbayLatestLab,
  type MedbayFollowup,
  type MedbayChange,
  type Thread,
} from '../api/client'

export type MedbaySection = 'protocol' | 'labs' | 'followups' | 'changes'

interface MedBayPageProps {
  hasActiveThread: boolean
  // ChatPanel + landing-page props
  messages: ChatMessage[]
  isThinking: boolean
  statusText: string
  isConnected: boolean
  workspaceLabel: string
  workspaceSlug: string
  threadTitle: string
  onSendMessage: (content: string) => void
  // Landing-page actions
  onNewThread?: () => void
  threads: Thread[]
  onOpenThread?: (thread: Thread) => void
  // Refetch signal — increments when a medbay_update WS frame for a
  // given section arrives. Keyed by section so the matching effect
  // re-runs without redrawing the others.
  refetchTokens: Record<MedbaySection, number>
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
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

function statusColor(status: string | null | undefined): string {
  if (status === 'high') return 'text-neon-pink'
  if (status === 'low') return 'text-neon-yellow'
  if (status === 'normal') return 'text-neon-green'
  return 'text-muted-foreground'
}

interface SectionShellProps {
  title: string
  count?: number
  accent: 'green' | 'cyan' | 'amber' | 'pink'
  icon: React.ReactNode
  defaultOpen?: boolean
  children: React.ReactNode
}

function SectionShell({
  title,
  count,
  accent,
  icon,
  defaultOpen = false,
  children,
}: SectionShellProps) {
  const [open, setOpen] = useState(defaultOpen)
  const accentBorder = {
    green: 'border-neon-green/40',
    cyan: 'border-neon-cyan/40',
    amber: 'border-neon-yellow/40',
    pink: 'border-neon-pink/40',
  }[accent]
  const accentText = {
    green: 'text-neon-green glow-green-text',
    cyan: 'text-neon-cyan glow-cyan-text',
    amber: 'text-neon-yellow',
    pink: 'text-neon-pink glow-pink-text',
  }[accent]
  return (
    <div className={cn('industrial-inset border-l-2 mb-3', accentBorder)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-white/[0.02] transition-colors"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />
        )}
        <span className={cn('flex items-center gap-1.5', accentText)}>
          {icon}
        </span>
        <span
          className={cn(
            'font-mono text-[11px] uppercase tracking-wider font-bold',
            accentText,
          )}
        >
          {title}
        </span>
        {typeof count === 'number' && (
          <span className="ml-auto font-mono text-[10px] text-muted-foreground/70">
            {count}
          </span>
        )}
      </button>
      {open && <div className="px-3 pb-3 pt-1">{children}</div>}
    </div>
  )
}

function ProtocolSection({ refetchToken }: { refetchToken: number }) {
  const [items, setItems] = useState<MedbayProtocolItem[]>([])
  const [showStopped, setShowStopped] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    getMedbayProtocol(true)
      .then(setItems)
      .catch(console.error)
      .finally(() => setLoaded(true))
  }, [refetchToken])

  const active = items.filter((i) => i.status === 'active')
  const stopped = items.filter((i) => i.status === 'stopped')

  return (
    <SectionShell
      title="Protocol"
      count={active.length}
      accent="green"
      icon={<Activity className="w-3.5 h-3.5" />}
      defaultOpen
    >
      {!loaded ? (
        <p className="font-mono text-[10px] text-muted-foreground/60">
          Loading...
        </p>
      ) : active.length === 0 ? (
        <p className="font-mono text-[10px] text-muted-foreground/60">
          No active supplements.
        </p>
      ) : (
        <ul className="space-y-2">
          {active.map((p) => (
            <li
              key={p.id}
              className="industrial-raised border border-neon-green/20 p-2"
            >
              <div className="font-sans text-xs font-bold text-foreground">
                {p.supplement_name}
              </div>
              {(p.dose || p.frequency) && (
                <div className="font-mono text-[10px] text-neon-green/80 mt-0.5">
                  {[p.dose, p.frequency].filter(Boolean).join(' • ')}
                </div>
              )}
              {p.reason && (
                <div className="font-sans text-[11px] text-muted-foreground/80 mt-1">
                  {p.reason}
                </div>
              )}
              {p.target_marker && (
                <div className="font-mono text-[9px] text-muted-foreground/60 mt-1 uppercase tracking-wider">
                  → {p.target_marker}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {stopped.length > 0 && (
        <div className="mt-3 pt-2 border-t border-[#12121a]">
          <button
            type="button"
            onClick={() => setShowStopped((v) => !v)}
            className="flex items-center gap-1 font-mono text-[10px] text-muted-foreground/60 hover:text-muted-foreground"
          >
            {showStopped ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronRight className="w-3 h-3" />
            )}
            Stopped ({stopped.length})
          </button>
          {showStopped && (
            <ul className="mt-2 space-y-1">
              {stopped.map((p) => (
                <li
                  key={p.id}
                  className="font-sans text-[11px] text-muted-foreground/60 line-through"
                >
                  {p.supplement_name}
                  {p.stopped_at && (
                    <span className="ml-2 font-mono text-[9px] text-muted-foreground/40">
                      {formatDate(p.stopped_at)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </SectionShell>
  )
}

function KeyMarkersSection({ refetchToken }: { refetchToken: number }) {
  const [labs, setLabs] = useState<MedbayLatestLab[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    getMedbayLatestLabs()
      .then(setLabs)
      .catch(console.error)
      .finally(() => setLoaded(true))
  }, [refetchToken])

  return (
    <SectionShell
      title="Key Markers"
      count={labs.length}
      accent="cyan"
      icon={<Beaker className="w-3.5 h-3.5" />}
      defaultOpen
    >
      {!loaded ? (
        <p className="font-mono text-[10px] text-muted-foreground/60">
          Loading...
        </p>
      ) : labs.length === 0 ? (
        <p className="font-mono text-[10px] text-muted-foreground/60">
          No lab results yet.
        </p>
      ) : (
        <ul className="space-y-2">
          {labs.map((l) => {
            let trend: React.ReactNode = (
              <Minus className="w-3 h-3 text-muted-foreground/50" />
            )
            if (l.previous_value != null) {
              if (l.value > l.previous_value)
                trend = (
                  <ArrowUp className="w-3 h-3 text-neon-pink" />
                )
              else if (l.value < l.previous_value)
                trend = (
                  <ArrowDown className="w-3 h-3 text-neon-cyan" />
                )
            }
            return (
              <li
                key={`${l.marker_name}-${l.id}`}
                className="industrial-raised border border-neon-cyan/20 p-2"
              >
                <div className="flex items-baseline gap-2">
                  <span className="font-sans text-xs font-bold text-foreground">
                    {l.marker_name}
                  </span>
                  <span
                    className={cn(
                      'ml-auto font-mono text-sm font-bold',
                      statusColor(l.status),
                    )}
                  >
                    {l.value}
                    {l.unit && (
                      <span className="text-[10px] ml-1 opacity-70">
                        {l.unit}
                      </span>
                    )}
                  </span>
                  {trend}
                </div>
                <div className="flex items-center justify-between mt-1">
                  <span className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground/60">
                    {l.status ?? 'unknown'}
                  </span>
                  <span className="font-mono text-[9px] text-muted-foreground/50">
                    {formatDate(l.test_date)}
                  </span>
                </div>
                {l.previous_value != null && (
                  <div className="font-mono text-[9px] text-muted-foreground/40 mt-1">
                    prev: {l.previous_value}
                    {l.unit ? l.unit : ''}{' '}
                    {l.previous_date && `(${formatDate(l.previous_date)})`}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </SectionShell>
  )
}

function FollowupsSection({
  refetchToken,
  onChanged,
}: {
  refetchToken: number
  onChanged: () => void
}) {
  const [items, setItems] = useState<MedbayFollowup[]>([])
  const [loaded, setLoaded] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)

  useEffect(() => {
    getMedbayFollowups(false)
      .then(setItems)
      .catch(console.error)
      .finally(() => setLoaded(true))
  }, [refetchToken])

  async function handleComplete(id: number) {
    setBusyId(id)
    try {
      await completeMedbayFollowup(id)
      // Optimistic remove from the pending list.
      setItems((prev) => prev.filter((f) => f.id !== id))
      onChanged()
    } catch (e) {
      console.error('Failed to complete followup:', e)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <SectionShell
      title="Follow-ups"
      count={items.length}
      accent="amber"
      icon={<CalendarClock className="w-3.5 h-3.5" />}
    >
      {!loaded ? (
        <p className="font-mono text-[10px] text-muted-foreground/60">
          Loading...
        </p>
      ) : items.length === 0 ? (
        <p className="font-mono text-[10px] text-muted-foreground/60">
          No pending follow-ups.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((f) => (
            <li
              key={f.id}
              className="industrial-raised border border-neon-yellow/20 p-2 flex gap-2"
            >
              <button
                type="button"
                onClick={() => handleComplete(f.id)}
                disabled={busyId === f.id}
                title="Mark complete"
                className="shrink-0 mt-0.5 text-muted-foreground/50 hover:text-neon-green transition-colors disabled:opacity-50"
              >
                <CheckCircle2 className="w-4 h-4" />
              </button>
              <div className="flex-1 min-w-0">
                <div className="font-sans text-xs text-foreground">
                  {f.description}
                </div>
                {f.reason && (
                  <div className="font-sans text-[11px] text-muted-foreground/70 mt-1">
                    {f.reason}
                  </div>
                )}
                {f.suggested_date && (
                  <div className="font-mono text-[9px] text-neon-yellow/70 mt-1 uppercase tracking-wider">
                    by {formatDate(f.suggested_date)}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </SectionShell>
  )
}

function ChangesSection({ refetchToken }: { refetchToken: number }) {
  const [items, setItems] = useState<MedbayChange[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    getMedbayChanges(50)
      .then(setItems)
      .catch(console.error)
      .finally(() => setLoaded(true))
  }, [refetchToken])

  function badgeFor(change_type: string): {
    label: string
    cls: string
  } {
    if (change_type === 'added')
      return {
        label: 'ADDED',
        cls: 'text-neon-green border-neon-green/40',
      }
    if (change_type === 'dose_change')
      return {
        label: 'DOSE CHANGE',
        cls: 'text-neon-cyan border-neon-cyan/40',
      }
    if (change_type === 'stopped')
      return {
        label: 'STOPPED',
        cls: 'text-neon-pink border-neon-pink/40',
      }
    return {
      label: change_type.toUpperCase(),
      cls: 'text-muted-foreground border-muted-foreground/30',
    }
  }

  return (
    <SectionShell
      title="Changes"
      count={items.length}
      accent="pink"
      icon={<ClipboardList className="w-3.5 h-3.5" />}
    >
      {!loaded ? (
        <p className="font-mono text-[10px] text-muted-foreground/60">
          Loading...
        </p>
      ) : items.length === 0 ? (
        <p className="font-mono text-[10px] text-muted-foreground/60">
          No changes logged yet.
        </p>
      ) : (
        <ul className="space-y-2">
          {items.map((c) => {
            const b = badgeFor(c.change_type)
            return (
              <li
                key={c.id}
                className="industrial-raised border border-neon-pink/20 p-2"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      'px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider font-bold border',
                      b.cls,
                    )}
                  >
                    {b.label}
                  </span>
                  <span className="font-sans text-xs font-bold text-foreground truncate">
                    {c.item_name}
                  </span>
                  <span className="ml-auto font-mono text-[9px] text-muted-foreground/50 shrink-0">
                    {formatDate(c.created_at)}
                  </span>
                </div>
                {(c.old_value || c.new_value) && (
                  <div className="font-mono text-[10px] text-muted-foreground/70 mt-1">
                    {c.old_value && (
                      <span className="line-through opacity-60">
                        {c.old_value}
                      </span>
                    )}
                    {c.old_value && c.new_value && (
                      <span className="mx-1">→</span>
                    )}
                    {c.new_value && <span>{c.new_value}</span>}
                  </div>
                )}
                {c.reason && (
                  <div className="font-sans text-[11px] text-muted-foreground/80 mt-1">
                    {c.reason}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </SectionShell>
  )
}

interface SidePanelProps {
  tokens: Record<MedbaySection, number>
  bumpAll: () => void
}

function MedBaySidePanel({ tokens, bumpAll }: SidePanelProps) {
  return (
    <aside className="w-[35%] min-w-[280px] max-w-[480px] industrial-panel border-l border-neon-green/20 flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-neon-green/20 flex items-center gap-2">
        <Activity className="w-4 h-4 text-neon-green glow-green" />
        <span className="font-mono text-xs uppercase tracking-widest text-neon-green glow-green-text font-bold">
          Med-Bay
        </span>
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        <ProtocolSection refetchToken={tokens.protocol} />
        <KeyMarkersSection refetchToken={tokens.labs} />
        <FollowupsSection
          refetchToken={tokens.followups}
          onChanged={bumpAll}
        />
        <ChangesSection refetchToken={tokens.changes} />
      </div>
    </aside>
  )
}

// ── Landing page (no thread selected) ─────────────────────────
interface LandingCardProps {
  title: string
  accent: 'green' | 'cyan' | 'amber' | 'pink'
  icon: React.ReactNode
  count: number
  preview: React.ReactNode
}

function LandingCard({
  title,
  accent,
  icon,
  count,
  preview,
}: LandingCardProps) {
  const accentBorder = {
    green: 'border-neon-green/40',
    cyan: 'border-neon-cyan/40',
    amber: 'border-neon-yellow/40',
    pink: 'border-neon-pink/40',
  }[accent]
  const accentText = {
    green: 'text-neon-green glow-green-text',
    cyan: 'text-neon-cyan glow-cyan-text',
    amber: 'text-neon-yellow',
    pink: 'text-neon-pink glow-pink-text',
  }[accent]
  return (
    <div
      className={cn(
        'industrial-raised border-l-2 p-4 flex flex-col gap-2 min-h-[140px]',
        accentBorder,
      )}
    >
      <div className="flex items-center gap-2">
        <span className={accentText}>{icon}</span>
        <span
          className={cn(
            'font-mono text-[11px] uppercase tracking-wider font-bold',
            accentText,
          )}
        >
          {title}
        </span>
        <span className="ml-auto font-mono text-2xl text-foreground font-bold">
          {count}
        </span>
      </div>
      <div className="font-sans text-[11px] text-muted-foreground/70 flex-1">
        {preview}
      </div>
    </div>
  )
}

function LandingPage({
  onNewThread,
  threads,
  onOpenThread,
  tokens,
}: {
  onNewThread?: () => void
  threads: Thread[]
  onOpenThread?: (t: Thread) => void
  tokens: Record<MedbaySection, number>
}) {
  const [protocol, setProtocol] = useState<MedbayProtocolItem[]>([])
  const [labs, setLabs] = useState<MedbayLatestLab[]>([])
  const [followups, setFollowups] = useState<MedbayFollowup[]>([])
  const [changes, setChanges] = useState<MedbayChange[]>([])

  useEffect(() => {
    getMedbayProtocol(false).then(setProtocol).catch(console.error)
  }, [tokens.protocol])
  useEffect(() => {
    getMedbayLatestLabs().then(setLabs).catch(console.error)
  }, [tokens.labs])
  useEffect(() => {
    getMedbayFollowups(false).then(setFollowups).catch(console.error)
  }, [tokens.followups])
  useEffect(() => {
    getMedbayChanges(5).then(setChanges).catch(console.error)
  }, [tokens.changes])

  return (
    <div className="flex-1 overflow-y-auto bg-[#040406] scanlines">
      <div className="max-w-5xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="font-mono text-[10px] text-neon-green/70 uppercase tracking-widest mb-1">
              workspace
            </div>
            <h1 className="font-mono text-2xl text-neon-green glow-green-text uppercase tracking-wider font-bold">
              Med-Bay
            </h1>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onNewThread}
              className="px-3 py-1.5 industrial-raised border border-neon-green/50 text-neon-green hover:glow-green transition-all flex items-center gap-1.5"
            >
              <Plus className="w-3.5 h-3.5" />
              <span className="font-mono text-[10px] uppercase tracking-wider font-bold">
                New Thread
              </span>
            </button>
            <button
              type="button"
              disabled
              title="Upload coming soon"
              className="px-3 py-1.5 industrial-inset border border-muted-foreground/30 text-muted-foreground/60 cursor-not-allowed flex items-center gap-1.5"
            >
              <Upload className="w-3.5 h-3.5" />
              <span className="font-mono text-[10px] uppercase tracking-wider font-bold">
                Upload Labs
              </span>
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <LandingCard
            title="Protocol"
            accent="green"
            icon={<Activity className="w-3.5 h-3.5" />}
            count={protocol.length}
            preview={
              protocol.length === 0
                ? 'No active supplements.'
                : protocol
                    .slice(0, 3)
                    .map((p) => p.supplement_name)
                    .join(' · ')
            }
          />
          <LandingCard
            title="Key Markers"
            accent="cyan"
            icon={<Beaker className="w-3.5 h-3.5" />}
            count={labs.length}
            preview={
              labs.length === 0
                ? 'No lab results yet.'
                : labs
                    .slice(0, 3)
                    .map(
                      (l) =>
                        `${l.marker_name}: ${l.value}${l.unit ?? ''}`,
                    )
                    .join(' · ')
            }
          />
          <LandingCard
            title="Follow-ups"
            accent="amber"
            icon={<CalendarClock className="w-3.5 h-3.5" />}
            count={followups.length}
            preview={
              followups.length === 0
                ? 'No pending follow-ups.'
                : followups
                    .slice(0, 3)
                    .map((f) => f.description)
                    .join(' · ')
            }
          />
          <LandingCard
            title="Changes"
            accent="pink"
            icon={<ClipboardList className="w-3.5 h-3.5" />}
            count={changes.length}
            preview={
              changes.length === 0
                ? 'No changes logged yet.'
                : changes
                    .slice(0, 3)
                    .map((c) => `${c.change_type}: ${c.item_name}`)
                    .join(' · ')
            }
          />
        </div>

        {threads.length > 0 && (
          <div>
            <div className="font-mono text-[10px] text-muted-foreground/60 uppercase tracking-widest mb-2">
              Recent threads
            </div>
            <ul className="space-y-1">
              {threads.slice(0, 8).map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => onOpenThread?.(t)}
                    className="w-full text-left px-3 py-2 industrial-inset border border-neon-green/20 hover:border-neon-green/60 hover:bg-neon-green/[0.04] transition-all"
                  >
                    <span className="font-sans text-xs text-foreground">
                      {t.title}
                    </span>
                    {t.last_message_at && (
                      <span className="ml-2 font-mono text-[9px] text-muted-foreground/50">
                        {formatDate(t.last_message_at)}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

// ── MedBayPage entrypoint ────────────────────────────────────
export function MedBayPage(props: MedBayPageProps) {
  const {
    hasActiveThread,
    messages,
    isThinking,
    statusText,
    isConnected,
    workspaceLabel,
    workspaceSlug,
    threadTitle,
    onSendMessage,
    onNewThread,
    threads,
    onOpenThread,
    refetchTokens,
  } = props

  // Local bumps for optimistic updates after the user marks a followup
  // complete (and similar). Combined with the WS-driven refetchTokens.
  const [localBumps, setLocalBumps] = useState<Record<MedbaySection, number>>({
    protocol: 0,
    labs: 0,
    followups: 0,
    changes: 0,
  })
  const bumpAll = useCallback(() => {
    setLocalBumps((prev) => ({
      protocol: prev.protocol + 1,
      labs: prev.labs + 1,
      followups: prev.followups + 1,
      changes: prev.changes + 1,
    }))
  }, [])

  const tokens: Record<MedbaySection, number> = {
    protocol: refetchTokens.protocol + localBumps.protocol,
    labs: refetchTokens.labs + localBumps.labs,
    followups: refetchTokens.followups + localBumps.followups,
    changes: refetchTokens.changes + localBumps.changes,
  }

  if (!hasActiveThread) {
    return (
      <LandingPage
        onNewThread={onNewThread}
        threads={threads}
        onOpenThread={onOpenThread}
        tokens={tokens}
      />
    )
  }

  return (
    <div className="flex-1 flex overflow-hidden">
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <ChatPanel
          messages={messages}
          isThinking={isThinking}
          statusText={statusText}
          isConnected={isConnected}
          workspaceLabel={workspaceLabel}
          workspaceSlug={workspaceSlug}
          threadTitle={threadTitle}
          onSendMessage={onSendMessage}
        />
      </div>
      <MedBaySidePanel tokens={tokens} bumpAll={bumpAll} />
    </div>
  )
}

// Re-export CommandBar so future Med-Bay-specific tweaks can shadow it
// without DashboardPage having to know about the swap.
export { CommandBar }
