import { useState } from 'react'
import { Brain, Search, Users, X } from 'lucide-react'
import { cn } from '../lib/utils'
import {
  getWorkspaceAccent,
  getWorkspaceAccentAlpha,
} from '../lib/workspace-theme'

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

  const showRoster = workspaceSlug === 'institute'
  // Workspace accent tints the command-bar button borders so the
  // command rail visually belongs to the active workspace. We use
  // inline style for the variable border-color (and the same hue at
  // multiple alpha levels) rather than try to express the workspace
  // accent through Tailwind's neon-* classes, which are fixed.
  const accent = getWorkspaceAccent(workspaceSlug)
  const accentBorder = getWorkspaceAccentAlpha(workspaceSlug, 0.3)
  const accentBg = getWorkspaceAccentAlpha(workspaceSlug, 0.05)
  const buttonStyle = {
    color: accent,
    borderColor: accentBorder,
  } as const

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
    <div className="h-[30px] flex items-center gap-1 px-2 bg-[#080c12] border-t border-b border-[#1a2332] relative">
      {/* Subtle scan line accent matching chat area aesthetic */}
      <div className="absolute left-0 right-0 top-0 h-[1px] bg-gradient-to-r from-transparent via-neon-cyan/15 to-transparent pointer-events-none" />

      {active ? (
        <>
          <span
            className="font-mono text-[10px] uppercase tracking-wider font-bold px-1.5 py-0.5 border"
            style={{
              color: accent,
              borderColor: accentBorder,
              backgroundColor: accentBg,
            }}
          >
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
              'relative p-1 industrial-inset border transition-all group',
            )}
            style={buttonStyle}
          >
            <Brain className="w-3.5 h-3.5" />
            <span
              className="absolute -top-0.5 -right-0.5 w-1 h-1 rounded-full opacity-0 group-hover:opacity-100 group-hover:pulse-dot transition-opacity"
              style={{ backgroundColor: accent }}
            />
          </button>

          <button
            onClick={() => setActive('search')}
            title="Search (!search)"
            className="p-1 industrial-inset border transition-all"
            style={buttonStyle}
          >
            <Search className="w-3.5 h-3.5" />
          </button>

          {showRoster && onRosterClick && (
            <button
              onClick={onRosterClick}
              title="Roster"
              className="p-1 industrial-inset border transition-all"
              style={buttonStyle}
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
