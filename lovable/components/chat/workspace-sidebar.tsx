"use client"

import { cn } from "@/lib/utils"
import { 
  Briefcase, 
  FolderKanban, 
  Heart, 
  Code2, 
  MessageSquare,
  Terminal
} from "lucide-react"

interface Workspace {
  id: string
  name: string
  icon: React.ReactNode
  color: string
}

const workspaces: Workspace[] = [
  { id: "chief-of-staff", name: "Chief of Staff", icon: <Briefcase className="w-4 h-4" />, color: "cyan" },
  { id: "director", name: "Director", icon: <FolderKanban className="w-4 h-4" />, color: "pink" },
  { id: "health", name: "Health", icon: <Heart className="w-4 h-4" />, color: "green" },
  { id: "engineering", name: "Engineering", icon: <Code2 className="w-4 h-4" />, color: "yellow" },
  { id: "general", name: "General", icon: <MessageSquare className="w-4 h-4" />, color: "orange" },
]

const colorClasses: Record<string, { icon: string; border: string; glow: string; bg: string }> = {
  cyan: { icon: "text-neon-cyan", border: "bg-neon-cyan", glow: "glow-cyan", bg: "bg-neon-cyan/10" },
  pink: { icon: "text-neon-pink", border: "bg-neon-pink", glow: "glow-pink", bg: "bg-neon-pink/10" },
  green: { icon: "text-neon-green", border: "bg-neon-green", glow: "glow-green", bg: "bg-neon-green/10" },
  yellow: { icon: "text-neon-yellow", border: "bg-neon-yellow", glow: "glow-yellow", bg: "bg-neon-yellow/10" },
  orange: { icon: "text-neon-orange", border: "bg-neon-orange", glow: "glow-pink", bg: "bg-neon-orange/10" },
}

interface WorkspaceSidebarProps {
  activeWorkspace: string
  onWorkspaceChange: (id: string) => void
}

export function WorkspaceSidebar({ activeWorkspace, onWorkspaceChange }: WorkspaceSidebarProps) {
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
            NEXUS_AI
          </h1>
        </div>
        <div className="flex items-center gap-2 mt-2">
          <div className="w-1.5 h-1.5 bg-neon-green pulse-dot-green" />
          <p className="font-mono text-[10px] text-neon-green/80 uppercase tracking-widest">
            v2.077 // ONLINE
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
          const colors = colorClasses[workspace.color]
          const isActive = activeWorkspace === workspace.id
          
          return (
            <button
              key={workspace.id}
              onClick={() => onWorkspaceChange(workspace.id)}
              className={cn(
                "w-full flex items-center gap-3 px-3 py-3 text-sm transition-all duration-200",
                "group relative border-l-[3px] border-transparent",
                isActive
                  ? `text-foreground industrial-raised ${colors.bg}`
                  : "text-muted-foreground hover:industrial-raised hover:text-foreground"
              )}
            >
              {/* Active indicator - thick glowing left border */}
              {isActive && (
                <div
                  className={cn(
                    "absolute left-0 top-1 bottom-1 w-[3px]",
                    colors.border,
                    colors.glow
                  )}
                />
              )}
              
              {/* Icon container */}
              <div className={cn(
                "p-1.5 border transition-all",
                isActive 
                  ? `border-current industrial-inset ${colors.icon}` 
                  : "border-muted-foreground/20 group-hover:border-neon-cyan/30"
              )}>
                {workspace.icon}
              </div>
              
              <span className={cn(
                "font-sans font-medium",
                isActive && colors.icon
              )}>
                {workspace.name}
              </span>
              
              {isActive && (
                <span className={cn(
                  "ml-auto w-2 h-2",
                  colors.border,
                  "pulse-dot"
                )} />
              )}
            </button>
          )
        })}
      </nav>

      {/* Footer - recessed status */}
      <div className="p-4 relative industrial-inset border-t-2 border-[#1a1a22]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-neon-green pulse-dot-green" />
            <span className="font-mono text-[10px] text-neon-green uppercase tracking-wider font-bold">
              Online
            </span>
          </div>
          <div className="px-2 py-1 industrial-raised border border-neon-cyan/20">
            <span className="font-mono text-[9px] text-neon-cyan/70">
              {`{SYS_OK}`}
            </span>
          </div>
        </div>
      </div>
    </aside>
  )
}
