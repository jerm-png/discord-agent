import { useState } from 'react'
import { Brain, Search, Users, X } from 'lucide-react'
import { cn } from '../lib/utils'

interface CommandBarProps {
  onSendMessage: (content: string) => void
  workspaceSlug: string
  onRosterClick?: () => void
}

type ActiveCmd = 'remember' | 'search' | null

const PLACEHOLDERS: Record<Exclude<ActiveCmd, null>, string> = {
  remember: 'What should I remember?',
  search: 'Search query...',
}

export function CommandBar({
  onSendMessage,
  workspaceSlug,
  onRosterClick,
}: CommandBarProps) {
  const [active, setActive] = useState<ActiveCmd>(null)
  const [value, setValue] = useState('')

  const showRoster = workspaceSlug === 'director'

  const cancel = () => {
    setActive(null)
    setValue('')
  }

  const submit = () => {
    const text = value.trim()
    if (!text || !active) return
    onSendMessage(`!${active} ${text}`)
    cancel()
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      submit()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      cancel()
    }
  }

  return (
    <div className="h-[30px] flex items-center gap-1 px-2 bg-[#08080d] border-t border-b border-[#1a1a22] relative">
      {/* Subtle scan line accent matching chat area aesthetic */}
      <div className="absolute left-0 right-0 top-0 h-[1px] bg-gradient-to-r from-transparent via-neon-cyan/15 to-transparent pointer-events-none" />

      {active ? (
        <>
          <span className="font-mono text-[10px] uppercase tracking-wider text-neon-cyan glow-cyan-text font-bold px-1.5 py-0.5 border border-neon-cyan/40 bg-neon-cyan/5">
            ! {active}
          </span>
          <input
            autoFocus
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={PLACEHOLDERS[active]}
            className="flex-1 bg-transparent border-none outline-none font-sans text-xs text-foreground placeholder:text-muted-foreground/40 px-2 h-full"
          />
          <button
            onClick={cancel}
            title="Cancel (Esc)"
            className="p-1 text-muted-foreground/60 hover:text-neon-pink transition-colors"
          >
            <X className="w-3 h-3" />
          </button>
        </>
      ) : (
        <>
          <button
            onClick={() => setActive('remember')}
            title="Remember (!remember)"
            className={cn(
              'relative p-1 industrial-inset border border-neon-cyan/20 text-neon-cyan/70',
              'hover:text-neon-cyan hover:border-neon-cyan/60 hover:glow-cyan transition-all',
              'group',
            )}
          >
            <Brain className="w-3.5 h-3.5" />
            {/* Circuit-style accent dot — only on hover */}
            <span className="absolute -top-0.5 -right-0.5 w-1 h-1 bg-neon-cyan rounded-full opacity-0 group-hover:opacity-100 group-hover:pulse-dot transition-opacity" />
          </button>

          <button
            onClick={() => setActive('search')}
            title="Search (!search)"
            className={cn(
              'p-1 industrial-inset border border-neon-cyan/20 text-neon-cyan/70',
              'hover:text-neon-cyan hover:border-neon-cyan/60 hover:glow-cyan transition-all',
            )}
          >
            <Search className="w-3.5 h-3.5" />
          </button>

          {showRoster && (
            <button
              onClick={() => {
                if (onRosterClick) {
                  // Navigate back to the roster view by deselecting the
                  // active thread (handled by parent). Falls back to the
                  // legacy !roster chat command only if no handler is wired.
                  onRosterClick()
                } else {
                  onSendMessage('!roster')
                }
              }}
              title="Roster"
              className={cn(
                'p-1 industrial-inset border border-neon-cyan/20 text-neon-cyan/70',
                'hover:text-neon-cyan hover:border-neon-cyan/60 hover:glow-cyan transition-all',
              )}
            >
              <Users className="w-3.5 h-3.5" />
            </button>
          )}

          <div className="flex-1" />

          <span className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground/30">
            cmd
          </span>
        </>
      )}
    </div>
  )
}
