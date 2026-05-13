"use client"

import { useState } from "react"
import { WorkspaceSidebar } from "@/components/chat/workspace-sidebar"
import { ThreadList } from "@/components/chat/thread-list"
import { ChatPanel } from "@/components/chat/chat-panel"
import { SystemStatusBar } from "@/components/chat/system-status-bar"

const workspaceNames: Record<string, string> = {
  "chief-of-staff": "Chief of Staff",
  "director": "Director",
  "health": "Health",
  "engineering": "Engineering",
  "general": "General",
}

export default function Home() {
  const [activeWorkspace, setActiveWorkspace] = useState("chief-of-staff")
  const [activeThread, setActiveThread] = useState("1")

  return (
    <main className="h-screen w-screen overflow-hidden flex flex-col bg-background">
      <SystemStatusBar />
      <div className="flex-1 flex overflow-hidden">
        <WorkspaceSidebar 
        activeWorkspace={activeWorkspace}
        onWorkspaceChange={setActiveWorkspace}
      />
      <ThreadList 
        activeThread={activeThread}
        onThreadChange={setActiveThread}
        workspaceName={workspaceNames[activeWorkspace]}
      />
      <ChatPanel 
        workspaceName={workspaceNames[activeWorkspace]}
      />
      </div>
    </main>
  )
}
