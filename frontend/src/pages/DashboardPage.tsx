import { useEffect, useState, useCallback } from 'react'
import { SystemStatusBar } from '../components/SystemStatusBar'
import { WorkspaceSidebar } from '../components/WorkspaceSidebar'
import { ThreadList } from '../components/ThreadList'
import { ChatPanel } from '../components/ChatPanel'
import { useWebSocket } from '../hooks/useWebSocket'
import type { WSMessage } from '../hooks/useWebSocket'
import { useDriftStore } from '../store/driftStore'
import { getWorkspaces, getThreads, createThread, archiveThread, getMessages } from '../api/client'
import type { Thread, ChatMessage } from '../api/client'

export function DashboardPage() {
  const {
    workspaces,
    activeWorkspace,
    threads,
    activeThread,
    setWorkspaces,
    setActiveWorkspace,
    setThreads,
    setActiveThread,
    addThread,
    removeThread,
  } = useDriftStore()

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [threadsLoading, setThreadsLoading] = useState(false)

  const handleWSMessage = useCallback((msg: WSMessage) => {
    if (msg.type === 'response' || msg.type === 'error') {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-${Math.random()}`,
          role: 'assistant',
          content: msg.content || msg.text || 'An error occurred',
          timestamp: new Date().toISOString(),
        },
      ])
    }
  }, [])

  const { isConnected, isThinking, statusText, sendMessage, connect, disconnect } =
    useWebSocket(handleWSMessage)

  // Load workspaces on mount
  useEffect(() => {
    getWorkspaces()
      .then((ws) => setWorkspaces(ws))
      .catch(console.error)
  }, [setWorkspaces])

  // Load threads when active workspace changes
  useEffect(() => {
    setThreadsLoading(true)
    getThreads(activeWorkspace)
      .then((ts) => setThreads(ts))
      .catch(console.error)
      .finally(() => setThreadsLoading(false))
  }, [activeWorkspace, setThreads])

  // Connect WebSocket and load history when active thread changes
  useEffect(() => {
    if (activeThread) {
      setMessages([])
      connect(activeWorkspace, activeThread.id)
      getMessages(activeThread.id)
        .then((msgs) => setMessages(msgs))
        .catch(console.error)
    } else {
      disconnect()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThread?.id, activeWorkspace])

  function handleWorkspaceChange(slug: string) {
    setActiveWorkspace(slug)
  }

  function handleThreadChange(thread: Thread) {
    setActiveThread(thread)
  }

  async function handleDeleteThread(threadId: string) {
    try {
      await archiveThread(threadId)
      removeThread(threadId)
      if (activeThread?.id === threadId) {
        setActiveThread(null)
      }
    } catch (e) {
      console.error('Failed to archive thread:', e)
    }
  }

  async function handleCreateThread(title: string) {
    try {
      const thread = await createThread(activeWorkspace, title)
      addThread(thread)
      setActiveThread(thread)
    } catch (e) {
      console.error('Failed to create thread:', e)
    }
  }

  function handleSendMessage(content: string) {
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}-${Math.random()}`,
        role: 'user',
        content,
        timestamp: new Date().toISOString(),
      },
    ])
    sendMessage(content)
  }

  const activeWorkspaceLabel =
    workspaces.find((w) => w.slug === activeWorkspace)?.label ??
    activeWorkspace

  return (
    <div className="h-screen w-screen overflow-hidden flex flex-col bg-[#0a0a0f]">
      <SystemStatusBar />
      <div className="flex-1 flex overflow-hidden">
        <WorkspaceSidebar
          workspaces={workspaces}
          activeWorkspace={activeWorkspace}
          onWorkspaceChange={handleWorkspaceChange}
        />
        <ThreadList
          threads={threads}
          activeThread={activeThread}
          onThreadChange={handleThreadChange}
          onCreateThread={handleCreateThread}
          onDeleteThread={handleDeleteThread}
          workspaceLabel={activeWorkspaceLabel}
          isLoading={threadsLoading}
        />
        {activeThread ? (
          <ChatPanel
            messages={messages}
            isThinking={isThinking}
            statusText={statusText}
            isConnected={isConnected}
            workspaceLabel={activeWorkspaceLabel}
            threadTitle={activeThread.title}
            onSendMessage={handleSendMessage}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center bg-[#0a0a0f] scanlines">
            <div className="text-center space-y-3">
              <div className="font-mono text-[10px] text-[#9090a8]/40 uppercase tracking-widest">
                [ SELECT OR CREATE A THREAD ]
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
