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
  Sparkles,
} from 'lucide-react'
import { logout } from '../api/client'
import { useAuthStore } from '../store/authStore'
import type { Workspace } from '../api/client'
import type { ReactNode } from 'react'
import {
  getWorkspaceAccent,
  getWorkspaceAccentAlpha,
} from '../lib/workspace-theme'

// Icon per workspace slug. Accent color lives in workspace-theme.ts
// and is applied via inline style so the palette is centralised.
const SLUG_ICON: Record<string, ReactNode> = {
  'chief-of-staff': <Briefcase className="w-4 h-4" />,
  admin: <Sparkles className="w-4 h-4" />,
  institute: <FolderKanban className="w-4 h-4" />,
  health: <Heart className="w-4 h-4" />,
  engineering: <Code2 className="w-4 h-4" />,
  parker: <Terminal className="w-4 h-4" />,
  general: <MessageSquare className="w-4 h-4" />,
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
    <aside className="w-[220px] h-full bg-gradient-to-b from-[#0a0a0e] to-[#040406] flex flex-col relative scanlines industrial-panel">
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
          const icon = SLUG_ICON[workspace.slug] ?? (
            <Terminal className="w-4 h-4" />
          )
          const accent = getWorkspaceAccent(workspace.slug)
          const isActive = activeWorkspace === workspace.slug
          // Active row: full-strength accent bar + tinted bg + 2px
          // left border in accent. Inactive: same 3px bar at low
          // opacity so the row still reads as "owned" by its
          // workspace color, but doesn't compete with the active row.
          return (
            <button
              key={workspace.slug}
              onClick={() => onWorkspaceChange(workspace.slug)}
              className={cn(
                'w-full flex items-center gap-3 pl-4 pr-3 py-3 text-sm transition-all duration-200',
                'group relative',
                isActive
                  ? 'text-foreground industrial-raised'
                  : 'text-muted-foreground hover:industrial-raised hover:text-foreground',
              )}
              style={
                isActive
                  ? {
                      backgroundColor: getWorkspaceAccentAlpha(
                        workspace.slug,
                        0.12,
                      ),
                      borderLeft: `2px solid ${accent}`,
                    }
                  : { borderLeft: '2px solid transparent' }
              }
            >
              {/* 3px accent bar — always visible, dimmed for inactive
                  rows so the row still reads as workspace-coloured
                  without screaming. */}
              <span
                className="absolute left-0 top-1 bottom-1 w-[3px] pointer-events-none transition-opacity"
                style={{
                  backgroundColor: accent,
                  opacity: isActive ? 1 : 0.45,
                }}
              />

              {/* Icon container */}
              <div
                className="p-1.5 border transition-all"
                style={{
                  borderColor: isActive
                    ? accent
                    : 'rgba(144, 144, 168, 0.2)',
                  color: isActive ? accent : undefined,
                }}
              >
                {icon}
              </div>

              <span
                className="font-sans font-medium"
                style={{ color: isActive ? accent : undefined }}
              >
                {workspace.label}
              </span>

              {isActive && (
                <span
                  className="ml-auto w-2 h-2 pulse-dot"
                  style={{ backgroundColor: accent }}
                />
              )}
            </button>
          )
        })}
      </nav>

      {/* Footer - recessed status + logout */}
      <div className="p-4 relative industrial-inset border-t-2 border-[#12121a] space-y-3">
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
