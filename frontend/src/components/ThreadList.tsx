import { useState, useRef, useEffect } from 'react'
import { Plus, Check, X, MessageSquare } from 'lucide-react'
import type { Thread } from '../api/client'

interface ThreadListProps {
  threads: Thread[]
  activeThread: Thread | null
  onThreadChange: (thread: Thread) => void
  onCreateThread: (title: string) => void
  workspaceLabel: string
  isLoading: boolean
}

type DateGroup = 'Today' | 'Yesterday' | 'This Week' | 'Older'

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

function relativeTime(dateStr: string | null): string {
  if (!dateStr) return ''
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diff = now - then
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m`
  if (hours < 24) return `${hours}h`
  if (days < 7) return `${days}d`
  return new Date(dateStr).toLocaleDateString()
}

function getGroup(thread: Thread): DateGroup {
  const ref = thread.last_message_at || thread.created_at
  const date = new Date(ref)
  const now = new Date()
  const todayStart = startOfDay(now)
  const yesterdayStart = new Date(todayStart)
  yesterdayStart.setDate(yesterdayStart.getDate() - 1)
  const weekStart = new Date(todayStart)
  weekStart.setDate(weekStart.getDate() - 7)

  if (date >= todayStart) return 'Today'
  if (date >= yesterdayStart) return 'Yesterday'
  if (date >= weekStart) return 'This Week'
  return 'Older'
}

const GROUP_ORDER: DateGroup[] = ['Today', 'Yesterday', 'This Week', 'Older']

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
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (creating) inputRef.current?.focus()
  }, [creating])

  function handleConfirm() {
    const title = newTitle.trim()
    if (title) {
      onCreateThread(title)
    }
    setCreating(false)
    setNewTitle('')
  }

  function handleCancel() {
    setCreating(false)
    setNewTitle('')
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') handleConfirm()
    if (e.key === 'Escape') handleCancel()
  }

  const grouped: Record<DateGroup, Thread[]> = {
    Today: [],
    Yesterday: [],
    'This Week': [],
    Older: [],
  }
  for (const t of threads) {
    grouped[getGroup(t)].push(t)
  }

  return (
    <div
      className="w-[240px] flex flex-col flex-shrink-0 border-r border-[#ffffff]/5"
      style={{ background: '#0a0a0f' }}
    >
      {/* Header */}
      <div className="industrial-panel border-b border-[#ffffff]/5 px-3 py-2.5 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <div className="font-mono text-[9px] text-[#9090a8]/60 tracking-widest uppercase">
              WORKSPACE
            </div>
            <div className="font-mono text-[11px] text-[#f0f0f5]/90 tracking-wide mt-0.5">
              {workspaceLabel}
            </div>
          </div>
          <button
            onClick={() => setCreating(true)}
            title="New thread"
            className="w-6 h-6 flex items-center justify-center border border-[#00f0ff]/20 text-[#00f0ff]/60 hover:border-[#00f0ff]/50 hover:text-[#00f0ff] transition-all"
          >
            <Plus className="w-3 h-3" strokeWidth={2} />
          </button>
        </div>

        {/* Inline new thread input */}
        {creating && (
          <div className="mt-2 flex items-center gap-1">
            <input
              ref={inputRef}
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Thread title..."
              className="industrial-inset border border-[#00f0ff]/30 font-mono text-xs w-full px-3 py-2 bg-transparent text-[#f0f0f5] placeholder-[#9090a8]/40 focus:outline-none focus:border-[#00f0ff]/60"
            />
            <button
              onClick={handleConfirm}
              className="flex-shrink-0 w-6 h-6 flex items-center justify-center border border-[#05ffa1]/30 text-[#05ffa1]/60 hover:border-[#05ffa1]/60 hover:text-[#05ffa1] transition-all"
            >
              <Check className="w-3 h-3" strokeWidth={2} />
            </button>
            <button
              onClick={handleCancel}
              className="flex-shrink-0 w-6 h-6 flex items-center justify-center border border-[#ff2a6d]/20 text-[#ff2a6d]/50 hover:border-[#ff2a6d]/50 hover:text-[#ff2a6d] transition-all"
            >
              <X className="w-3 h-3" strokeWidth={2} />
            </button>
          </div>
        )}
      </div>

      {/* Thread list */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-2 space-y-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="industrial-inset h-14 w-full animate-pulse"
                style={{ opacity: 0.5 - i * 0.1 }}
              />
            ))}
          </div>
        ) : threads.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 gap-2">
            <MessageSquare className="w-6 h-6 text-[#9090a8]/20" strokeWidth={1} />
            <span className="font-mono text-[9px] text-[#9090a8]/40 tracking-widest uppercase">
              No threads
            </span>
          </div>
        ) : (
          <div className="py-1">
            {GROUP_ORDER.filter((g) => grouped[g].length > 0).map((group) => (
              <div key={group}>
                <div className="px-3 pt-3 pb-1">
                  <span className="font-mono text-[8px] text-[#9090a8]/40 tracking-widest uppercase">
                    {group}
                  </span>
                </div>
                {grouped[group].map((thread) => {
                  const isActive = activeThread?.id === thread.id
                  const timestamp = relativeTime(
                    thread.last_message_at || thread.created_at
                  )
                  const preview =
                    thread.message_count === 0
                      ? 'No messages yet'
                      : `${thread.message_count} message${thread.message_count === 1 ? '' : 's'}`

                  return (
                    <button
                      key={thread.id}
                      onClick={() => onThreadChange(thread)}
                      className="w-full text-left px-3 py-2.5 transition-all border-l-2 group"
                      style={{
                        borderLeftColor: isActive
                          ? '#00f0ff'
                          : 'transparent',
                        background: isActive
                          ? 'rgba(0,240,255,0.05)'
                          : 'transparent',
                      }}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="font-mono text-[11px] text-[#f0f0f5]/80 truncate leading-tight group-hover:text-[#f0f0f5] transition-colors">
                          {thread.title}
                        </div>
                        <div className="font-mono text-[9px] text-[#9090a8]/50 flex-shrink-0">
                          {timestamp}
                        </div>
                      </div>
                      <div className="font-mono text-[9px] text-[#9090a8]/40 mt-0.5 truncate">
                        {preview}
                      </div>
                    </button>
                  )
                })}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
