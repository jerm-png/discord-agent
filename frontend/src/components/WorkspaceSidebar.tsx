import { Bot, Shield, Activity, Code2, MessageSquare } from 'lucide-react'
import type { Workspace } from '../api/client'
import type { LucideIcon } from 'lucide-react'

interface WorkspaceSidebarProps {
  workspaces: Workspace[]
  activeWorkspace: string
  onWorkspaceChange: (slug: string) => void
}

interface WorkspaceConfig {
  color: string
  glowColor: string
  icon: LucideIcon
}

const WORKSPACE_CONFIG: Record<string, WorkspaceConfig> = {
  'chief-of-staff': {
    color: '#00f0ff',
    glowColor: 'rgba(0,240,255,0.5)',
    icon: Bot,
  },
  director: {
    color: '#ff2a6d',
    glowColor: 'rgba(255,42,109,0.5)',
    icon: Shield,
  },
  health: {
    color: '#05ffa1',
    glowColor: 'rgba(5,255,161,0.5)',
    icon: Activity,
  },
  engineering: {
    color: '#fcee0a',
    glowColor: 'rgba(252,238,10,0.5)',
    icon: Code2,
  },
  general: {
    color: '#ff6b35',
    glowColor: 'rgba(255,107,53,0.5)',
    icon: MessageSquare,
  },
}

const DEFAULT_CONFIG: WorkspaceConfig = {
  color: '#9090a8',
  glowColor: 'rgba(144,144,168,0.4)',
  icon: MessageSquare,
}

export function WorkspaceSidebar({
  workspaces,
  activeWorkspace,
  onWorkspaceChange,
}: WorkspaceSidebarProps) {
  return (
    <div
      className="w-[60px] flex flex-col items-center py-3 gap-1 flex-shrink-0 border-r border-[#ffffff]/5 relative"
      style={{ background: '#08080d' }}
    >
      {/* Logo */}
      <div className="mb-3 pb-3 border-b border-[#ffffff]/5 w-full flex flex-col items-center">
        <span className="font-mono text-[8px] tracking-[0.25em] text-[#00f0ff]/80 glow-cyan-text">
          DFT
        </span>
      </div>

      {/* Workspace buttons */}
      <div className="flex flex-col gap-1 w-full items-center">
        {workspaces.map((ws) => {
          const cfg = WORKSPACE_CONFIG[ws.slug] ?? DEFAULT_CONFIG
          const Icon = cfg.icon
          const isActive = ws.slug === activeWorkspace

          return (
            <button
              key={ws.slug}
              onClick={() => onWorkspaceChange(ws.slug)}
              title={ws.label}
              className="relative w-10 h-10 flex items-center justify-center transition-all group"
              style={{
                background: isActive
                  ? `${cfg.color}14`
                  : 'transparent',
                border: `1px solid ${isActive ? cfg.color + '60' : 'transparent'}`,
                boxShadow: isActive ? `0 0 10px ${cfg.glowColor}` : undefined,
              }}
            >
              <Icon
                className="w-4 h-4 transition-all"
                style={{
                  color: isActive ? cfg.color : '#9090a8',
                  filter: isActive
                    ? `drop-shadow(0 0 4px ${cfg.glowColor})`
                    : undefined,
                }}
                strokeWidth={1.5}
              />
              {/* Active indicator */}
              {isActive && (
                <div
                  className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5"
                  style={{ background: cfg.color, boxShadow: `0 0 6px ${cfg.glowColor}` }}
                />
              )}
              {/* Tooltip */}
              <div className="absolute left-full ml-2 px-2 py-1 bg-[#0d0d14] border border-[#ffffff]/10 font-mono text-[9px] text-[#f0f0f5] tracking-widest uppercase whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-50">
                {ws.label}
              </div>
            </button>
          )
        })}
      </div>

      {/* Bottom label */}
      <div className="mt-auto pt-3 border-t border-[#ffffff]/5 w-full flex flex-col items-center">
        <span className="font-mono text-[7px] tracking-widest text-[#9090a8]/30 uppercase">
          DRIFT
        </span>
      </div>
    </div>
  )
}
