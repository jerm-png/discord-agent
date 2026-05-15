import { cn } from '../lib/utils'
import {
  Briefcase,
  FolderKanban,
  Heart,
  Code2,
  MessageSquare,
  Power,
  Terminal,
  Brain,
} from 'lucide-react'
import { logout } from '../api/client'
import { useAuthStore } from '../store/authStore'
import type { Workspace } from '../api/client'
import type { ReactNode } from 'react'

interface WorkspaceConfig {
  icon: ReactNode
  color: string
}

const SLUG_CONFIG: Record<string, WorkspaceConfig> = {
  'chief-of-staff': { icon: <Briefcase className="w-4 h-4" />, color: 'cyan' },
  director: { icon: <FolderKanban className="w-4 h-4" />, color: 'pink' },
  health: { icon: <Heart className="w-4 h-4" />, color: 'green' },
  engineering: { icon: <Code2 className="w-4 h-4" />, color: 'yellow' },
  general: { icon: <MessageSquare className="w-4 h-4" />, color: 'orange' },
}

const colorClasses: Record<
  string,
  { icon: string; border: string; glow: string; bg: string }
> = {
  cyan: { icon: 'text-neon-cyan', border: 'bg-neon-cyan', glow: 'glow-cyan', bg: 'bg-neon-cyan/10' },
  pink: { icon: 'text-neon-pink', border: 'bg-neon-pink', glow: 'glow-pink', bg: 'bg-neon-pink/10' },
  green: { icon: 'text-neon-green', border: 'bg-neon-green', glow: 'glow-green', bg: 'bg-neon-green/10' },
  yellow: { icon: 'text-neon-yellow', border: 'bg-neon-yellow', glow: 'glow-yellow', bg: 'bg-neon-yellow/10' },
  orange: { icon: 'text-neon-orange', border: 'bg-neon-orange', glow: 'glow-pink', bg: 'bg-neon-orange/10' },
}

interface WorkspaceSidebarProps {
  workspaces: Workspace[]
  activeWorkspace: string
  onWorkspaceChange: (slug: string) => void
  // Optional toggle for the Memory Browser overlay. When omitted (e.g.
  // for non-admin users) the button is hidden.
  onOpenMemoryBrowser?: () => void
  memoryBrowserActive?: boolean
}

export function WorkspaceSidebar({
  workspaces,
  activeWorkspace,
  onWorkspaceChange,
  onOpenMemoryBrowser,
  memoryBrowserActive,
}: WorkspaceSidebarProps) {
  const clearUser = useAuthStore((s) => s.clearUser)

  const handleLogout = async () => {
    try {
      await logout()
    } catch (e) {
      // Even if the server clear fails, drop the client-side auth so
      // the UI returns to LoginPage; the cookie will expire on its own.
      console.error('Logout request failed:', e)
    }
    clearUser()
  }

  return (
    <aside className="w-[220px] h-full bg-gradient-to-b from-[#0a0a10] to-[#06060a] flex flex-col relative scanlines industrial-panel">
      {/* Right edge thick divider */}
      <div className="absolute top-0 bottom-0 right-0 industrial-divider-v" />

      {/* Logo/Brand - raised header */}
      <div className="p-4 relative industrial-raised">
        {/* Corner accents */}
        <div className="absolute top-2 left-2 w-3 h-3 border-l-2 border-t-2 border-neon-cyan/50" />
        <div className="absolute top-2 right-2 w-3 h-3 border-r-2 border-t-2 border-neon-pink/50" />

        <div className="flex items-center gap-2">
          <Terminal className="w-5 h-5 text-neon-cyan" />
          <h1 className="font-mono text-base tracking-wider text-neon-cyan glow-cyan-text font-bold">
            DRIFT
          </h1>
        </div>
        <div className="flex items-center gap-2 mt-2">
          <div className="w-1.5 h-1.5 bg-neon-green pulse-dot-green" />
          <p className="font-mono text-[10px] text-neon-green/80 uppercase tracking-widest">
            v1.0 // ONLINE
          </p>
        </div>

        {/* Bottom thick divider */}
        <div className="absolute -bottom-[3px] left-0 right-0 industrial-divider-h" />
      </div>

      {/* Workspaces List */}
      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        <div className="px-2 py-2 mb-2 industrial-inset">
          <p className="font-mono text-[10px] text-neon-pink/70 uppercase tracking-widest">
            [ Workspaces ]
          </p>
        </div>
        {workspaces.map((workspace) => {
          const cfg = SLUG_CONFIG[workspace.slug] ?? {
            icon: <Terminal className="w-4 h-4" />,
            color: 'cyan',
          }
          const colors = colorClasses[cfg.color]
          const isActive = activeWorkspace === workspace.slug

          return (
            <button
              key={workspace.slug}
              onClick={() => onWorkspaceChange(workspace.slug)}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-3 text-sm transition-all duration-200',
                'group relative border-l-[3px] border-transparent',
                isActive
                  ? `text-foreground industrial-raised ${colors.bg}`
                  : 'text-muted-foreground hover:industrial-raised hover:text-foreground'
              )}
            >
              {/* Active indicator - thick glowing left border */}
              {isActive && (
                <div
                  className={cn(
                    'absolute left-0 top-1 bottom-1 w-[3px]',
                    colors.border,
                    colors.glow
                  )}
                />
              )}

              {/* Icon container */}
              <div
                className={cn(
                  'p-1.5 border transition-all',
                  isActive
                    ? `border-current industrial-inset ${colors.icon}`
                    : 'border-muted-foreground/20 group-hover:border-neon-cyan/30'
                )}
              >
                {cfg.icon}
              </div>

              <span className={cn('font-sans font-medium', isActive && colors.icon)}>
                {workspace.label}
              </span>

              {isActive && (
                <span className={cn('ml-auto w-2 h-2', colors.border, 'pulse-dot')} />
              )}
            </button>
          )
        })}
      </nav>

      {/* Footer - recessed status + logout */}
      <div className="p-4 relative industrial-inset border-t-2 border-[#1a1a22] space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-neon-green pulse-dot-green" />
            <span className="font-mono text-[10px] text-neon-green uppercase tracking-wider font-bold">
              Online
            </span>
          </div>
          <div className="px-2 py-1 industrial-raised border border-neon-cyan/20">
            <span className="font-mono text-[9px] text-neon-cyan/70">{`{SYS_OK}`}</span>
          </div>
        </div>

        {onOpenMemoryBrowser && (
          <button
            onClick={onOpenMemoryBrowser}
            title={memoryBrowserActive ? 'Close Memory Browser' : 'Open Memory Browser'}
            className={cn(
              'w-full flex items-center justify-center gap-2 py-2',
              'industrial-raised border transition-all cursor-pointer',
              memoryBrowserActive
                ? 'border-neon-cyan/70 text-neon-cyan glow-cyan'
                : 'border-neon-cyan/30 text-neon-cyan/70 hover:text-neon-cyan hover:border-neon-cyan/60 hover:glow-cyan',
            )}
          >
            <Brain className="w-3.5 h-3.5" />
            <span className="font-mono text-[10px] uppercase tracking-wider font-bold">
              Memory
            </span>
          </button>
        )}

        <button
          onClick={handleLogout}
          title="Log out"
          className={cn(
            'w-full flex items-center justify-center gap-2 py-2',
            'industrial-raised border border-neon-pink/30 text-neon-pink/70',
            'hover:text-neon-pink hover:border-neon-pink/60 hover:glow-pink',
            'transition-all cursor-pointer',
          )}
        >
          <Power className="w-3.5 h-3.5" />
          <span className="font-mono text-[10px] uppercase tracking-wider font-bold">
            Log Out
          </span>
        </button>
      </div>
    </aside>
  )
}
