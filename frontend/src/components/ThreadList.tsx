import { useState } from 'react'
import { cn } from '../lib/utils'
import { Plus, MessageSquare } from 'lucide-react'
import type { Thread } from '../api/client'

interface ThreadListProps {
  threads: Thread[]
  activeThread: Thread | null
  onThreadChange: (thread: Thread) => void
  onCreateThread: (title: string) => void
  workspaceLabel: string
  isLoading: boolean
}

type DateGroup = 'today' | 'yesterday' | 'this-week' | 'older'

function getDateGroup(dateStr: string | null): DateGroup {
  if (!dateStr) return 'older'
  const date = new Date(dateStr)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  const weekAgo = new Date(today)
  weekAgo.setDate(weekAgo.getDate() - 7)

  if (date >= today) return 'today'
  if (date >= yesterday) return 'yesterday'
  if (date >= weekAgo) return 'this-week'
  return 'older'
}

function relativeTime(dateStr: string | null): string {
  if (!dateStr) return ''
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diff = now - then
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)
  if (minutes < 1) return 'now'
  if (minutes < 60) return `${minutes}m`
  if (hours < 24) return `${hours}h`
  if (days === 1) return 'Yesterday'
  if (days < 7)
    return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][
      new Date(dateStr).getDay()
    ]
  return new Date(dateStr).toLocaleDateString()
}

function previewText(thread: Thread): string {
  if (thread.message_count === 0) return 'No messages yet'
  return `${thread.message_count} message${thread.message_count === 1 ? '' : 's'}`
}

export function ThreadList({
  threads,
  activeThread,
  onThreadChange,
  onCreateThread,
  workspaceLabel,
  isLoading,
}: ThreadListProps) {
  const [creating, setCreating] = useState(false)
  const [newTitle, setNewTitle] = useState('')

  const grouped: Record<DateGroup, Thread[]> = {
    today: [],
    yesterday: [],
    'this-week': [],
    older: [],
  }
  for (const t of threads) {
    grouped[getDateGroup(t.last_message_at || t.created_at)].push(t)
  }

  function handleConfirm() {
    const title = newTitle.trim()
    if (title) onCreateThread(title)
    setCreating(false)
    setNewTitle('')
  }

  function handleInputKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') handleConfirm()
    if (e.key === 'Escape') {
      setCreating(false)
      setNewTitle('')
    }
  }

  const renderGroup = (
    label: string,
    groupThreads: Thread[],
    color: string,
    borderColor: string
  ) => {
    if (groupThreads.length === 0) return null

    return (
      <div className="mb-2">
        {/* Group header - recessed */}
        <div
          className={cn(
            'mx-3 px-3 py-2 mb-1 industrial-inset border-l-2',
            borderColor
          )}
        >
          <p
            className={cn(
              'font-mono text-[10px] uppercase tracking-widest font-bold',
              color
            )}
          >
            {'// '}
            {label}
          </p>
        </div>

        <div className="space-y-0.5 px-2">
          {groupThreads.map((thread) => {
            const isActive = activeThread?.id === thread.id
            return (
              <button
                key={thread.id}
                onClick={() => onThreadChange(thread)}
                className={cn(
                  'w-full text-left px-3 py-3 transition-all duration-200 relative border-l-[3px]',
                  'group',
                  isActive
                    ? 'industrial-raised border-l-neon-pink bg-neon-pink/5'
                    : 'border-transparent hover:industrial-raised'
                )}
              >
                {/* Active glow */}
                {isActive && (
                  <div className="absolute left-0 top-2 bottom-2 w-[3px] bg-neon-pink glow-pink" />
                )}

                <div className="flex items-start justify-between gap-2 mb-1">
                  <h3
                    className={cn(
                      'font-sans text-sm truncate font-medium',
                      isActive
                        ? 'text-neon-cyan glow-cyan-text'
                        : 'text-muted-foreground group-hover:text-foreground'
                    )}
                  >
                    {thread.title}
                  </h3>
                  <span
                    className={cn(
                      'font-mono text-[10px] shrink-0 tabular-nums px-1.5 py-0.5',
                      isActive
                        ? 'text-neon-pink bg-neon-pink/10 border border-neon-pink/30'
                        : 'text-muted-foreground/60'
                    )}
                  >
                    {relativeTime(thread.last_message_at || thread.created_at)}
                  </span>
                </div>
                <p className="font-sans text-xs text-muted-foreground/50 truncate group-hover:text-muted-foreground/70">
                  {previewText(thread)}
                </p>
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <aside className="w-[280px] h-full bg-gradient-to-b from-[#0c0c12] to-[#08080d] flex flex-col relative scanlines industrial-panel">
      {/* Right edge thick divider */}
      <div className="absolute top-0 bottom-0 right-0 industrial-divider-v" />

      {/* Header - raised panel */}
      <div className="p-4 relative industrial-raised">
        {/* Corner accents */}
        <div className="absolute top-2 left-2 w-3 h-3 border-l-2 border-t-2 border-neon-pink/50" />
        <div className="absolute top-2 right-2 w-3 h-3 border-r-2 border-t-2 border-neon-cyan/50" />

        <div className="flex items-center gap-2">
          <div className="p-1.5 industrial-inset border border-neon-pink/30">
            <MessageSquare className="w-4 h-4 text-neon-pink" />
          </div>
          <h2 className="font-mono text-xs text-neon-pink glow-pink-text uppercase tracking-wider font-bold">
            {workspaceLabel}
          </h2>
        </div>
        <p className="font-mono text-[10px] text-neon-cyan/60 mt-2 ml-9">
          {`{${threads.length} threads active}`}
        </p>

        {/* Bottom thick divider */}
        <div className="absolute -bottom-[3px] left-0 right-0 industrial-divider-h" />
      </div>

      {/* Thread List */}
      <div className="flex-1 overflow-y-auto py-3">
        {isLoading ? (
          <div className="px-2 space-y-0.5">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="industrial-inset h-14 w-full animate-pulse"
                style={{ opacity: 0.5 - i * 0.12 }}
              />
            ))}
          </div>
        ) : threads.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 gap-2 text-muted-foreground/40">
            <span className="font-mono text-[10px] uppercase tracking-widest">
              No threads yet
            </span>
          </div>
        ) : (
          <>
            {renderGroup('Today', grouped.today, 'text-neon-green', 'border-l-neon-green')}
            {renderGroup('Yesterday', grouped.yesterday, 'text-neon-yellow', 'border-l-neon-yellow')}
            {renderGroup('This Week', grouped['this-week'], 'text-neon-orange', 'border-l-neon-orange')}
            {renderGroup('Older', grouped.older, 'text-muted-foreground', 'border-l-muted-foreground')}
          </>
        )}
      </div>

      {/* New Thread Button / Inline Input */}
      <div className="p-4 relative">
        {/* Top thick divider */}
        <div className="absolute -top-[1px] left-0 right-0 industrial-divider-h" />

        {creating ? (
          <input
            autoFocus
            type="text"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={handleInputKey}
            placeholder="Thread title..."
            className="w-full font-mono text-xs industrial-inset border border-[#00f0ff]/30 px-3 py-2 bg-transparent text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:border-neon-cyan/60"
          />
        ) : (
          <button
            onClick={() => setCreating(true)}
            className="w-full py-3 industrial-raised hover:bg-neon-cyan/5 text-neon-cyan hover:text-neon-pink font-mono text-xs uppercase tracking-wider transition-all border-2 border-neon-cyan/30 hover:border-neon-pink/50 cyber-button flex items-center justify-center gap-2 group"
          >
            <div className="p-1 industrial-inset border border-current/30 group-hover:border-neon-pink/50 transition-colors">
              <Plus className="w-3 h-3 group-hover:rotate-90 transition-transform duration-300" />
            </div>
            <span className="font-bold">New Thread</span>
          </button>
        )}
      </div>
    </aside>
  )
}
