"use client"

import { cn } from "@/lib/utils"
import { Plus, MessageSquare } from "lucide-react"

interface Thread {
  id: string
  title: string
  preview: string
  timestamp: string
  dateGroup: "today" | "yesterday" | "this-week"
}

const mockThreads: Thread[] = [
  {
    id: "1",
    title: "Q2 Strategic Planning",
    preview: "Let me analyze the quarterly objectives and provide recommendations...",
    timestamp: "14:32",
    dateGroup: "today"
  },
  {
    id: "2",
    title: "Budget Analysis",
    preview: "Based on the current expenditure patterns, I suggest...",
    timestamp: "11:45",
    dateGroup: "today"
  },
  {
    id: "3",
    title: "Team Sync Notes",
    preview: "Here are the key takeaways from yesterday's meeting...",
    timestamp: "Yesterday",
    dateGroup: "yesterday"
  },
  {
    id: "4",
    title: "Project Roadmap Review",
    preview: "The timeline needs adjustment considering the new requirements...",
    timestamp: "Yesterday",
    dateGroup: "yesterday"
  },
  {
    id: "5",
    title: "Performance Metrics",
    preview: "KPI analysis shows significant improvement in...",
    timestamp: "Mon",
    dateGroup: "this-week"
  },
  {
    id: "6",
    title: "Resource Allocation",
    preview: "Optimal distribution would be to assign 40% to...",
    timestamp: "Sun",
    dateGroup: "this-week"
  },
]

interface ThreadListProps {
  activeThread: string
  onThreadChange: (id: string) => void
  workspaceName: string
}

export function ThreadList({ activeThread, onThreadChange, workspaceName }: ThreadListProps) {
  const groupedThreads = {
    today: mockThreads.filter(t => t.dateGroup === "today"),
    yesterday: mockThreads.filter(t => t.dateGroup === "yesterday"),
    "this-week": mockThreads.filter(t => t.dateGroup === "this-week"),
  }

  const renderGroup = (label: string, threads: Thread[], color: string, borderColor: string) => {
    if (threads.length === 0) return null
    
    return (
      <div className="mb-2">
        {/* Group header - recessed */}
        <div className={cn(
          "mx-3 px-3 py-2 mb-1 industrial-inset border-l-2",
          borderColor
        )}>
          <p className={cn(
            "font-mono text-[10px] uppercase tracking-widest font-bold",
            color
          )}>
            {"// "}{label}
          </p>
        </div>
        
        <div className="space-y-0.5 px-2">
          {threads.map((thread) => (
            <button
              key={thread.id}
              onClick={() => onThreadChange(thread.id)}
              className={cn(
                "w-full text-left px-3 py-3 transition-all duration-200 relative border-l-[3px]",
                "group",
                activeThread === thread.id
                  ? "industrial-raised border-l-neon-pink bg-neon-pink/5"
                  : "border-transparent hover:industrial-raised"
              )}
            >
              {/* Active glow */}
              {activeThread === thread.id && (
                <div className="absolute left-0 top-2 bottom-2 w-[3px] bg-neon-pink glow-pink" />
              )}
              
              <div className="flex items-start justify-between gap-2 mb-1">
                <h3 className={cn(
                  "font-sans text-sm truncate font-medium",
                  activeThread === thread.id 
                    ? "text-neon-cyan glow-cyan-text" 
                    : "text-muted-foreground group-hover:text-foreground"
                )}>
                  {thread.title}
                </h3>
                <span className={cn(
                  "font-mono text-[10px] shrink-0 tabular-nums px-1.5 py-0.5",
                  activeThread === thread.id 
                    ? "text-neon-pink bg-neon-pink/10 border border-neon-pink/30" 
                    : "text-muted-foreground/60"
                )}>
                  {thread.timestamp}
                </span>
              </div>
              <p className="font-sans text-xs text-muted-foreground/50 truncate group-hover:text-muted-foreground/70">
                {thread.preview}
              </p>
            </button>
          ))}
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
            {workspaceName.replace(/-/g, ' ')}
          </h2>
        </div>
        <p className="font-mono text-[10px] text-neon-cyan/60 mt-2 ml-9">
          {`{${mockThreads.length} threads active}`}
        </p>
        
        {/* Bottom thick divider */}
        <div className="absolute -bottom-[3px] left-0 right-0 industrial-divider-h" />
      </div>

      {/* Thread List */}
      <div className="flex-1 overflow-y-auto py-3">
        {renderGroup("Today", groupedThreads.today, "text-neon-green", "border-l-neon-green")}
        {renderGroup("Yesterday", groupedThreads.yesterday, "text-neon-yellow", "border-l-neon-yellow")}
        {renderGroup("This Week", groupedThreads["this-week"], "text-neon-orange", "border-l-neon-orange")}
      </div>

      {/* New Thread Button - industrial style */}
      <div className="p-4 relative">
        {/* Top thick divider */}
        <div className="absolute -top-[1px] left-0 right-0 industrial-divider-h" />
        
        <button className="w-full py-3 industrial-raised hover:bg-neon-cyan/5 text-neon-cyan hover:text-neon-pink font-mono text-xs uppercase tracking-wider transition-all border-2 border-neon-cyan/30 hover:border-neon-pink/50 cyber-button flex items-center justify-center gap-2 group">
          <div className="p-1 industrial-inset border border-current/30 group-hover:border-neon-pink/50 transition-colors">
            <Plus className="w-3 h-3 group-hover:rotate-90 transition-transform duration-300" />
          </div>
          <span className="font-bold">New Thread</span>
        </button>
      </div>
    </aside>
  )
}
