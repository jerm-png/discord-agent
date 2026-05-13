import { useEffect, useState, useCallback } from 'react'
import { SystemStatusBar } from '../components/SystemStatusBar'
import { WorkspaceSidebar } from '../components/WorkspaceSidebar'
import { ThreadList } from '../components/ThreadList'
import { ChatPanel } from '../components/ChatPanel'
import { useWebSocket } from '../hooks/useWebSocket'
import type { WSMessage } from '../hooks/useWebSocket'
import { useDriftStore } from '../store/driftStore'
import { getWorkspaces, getThreads, createThread, archiveThread, getMessages } from '../api/client'
import type { Thread } from '../api/client'
import type { ChatMessage } from '../components/ChatPanel'

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
    if (msg.type === 'response' || msg.type === 'message' || msg.type === 'error') {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-${Math.random()}`,
          role: 'assistant',
          content: msg.content || msg.text || 'An error occurred',
          timestamp: new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' }),
        },
      ])
    } else if (msg.type === 'plan') {
      setMessages((prev) => [
        ...prev,
        {
          id: `plan-${Date.now()}`,
          role: 'assistant',
          content: msg.content || msg.text || 'Plan ready for approval.',
          timestamp: new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' }),
          actionType: 'plan',
        },
      ])
    } else if (msg.type === 'gate') {
      setMessages((prev) => [
        ...prev,
        {
          id: `gate-${Date.now()}`,
          role: 'assistant',
          content: msg.content || msg.text || 'Goal paused at gate.',
          timestamp: new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' }),
          actionType: 'gate',
        },
      ])
    }
  }, [])

  const { isConnected, isThinking, statusText, sendMessage, connect, disconnect, resetThinking, markThinking } =
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
    
  async function handleAction(action: 'approve' | 'cancel' | 'modify' | 'continue' | 'adjust' | 'skip' | 'retry', changes?: string) {
    if (!activeThread) return
    // Resolve the CURRENT plan/gate messages synchronously, before the POST.
    // If we did this after `await postThreadAction(...)`, a fresh `plan`/`gate`
    // frame dispatched by the backend's fire-and-forget execute_goal could
    // land in `messages` first and get incorrectly marked resolved by this map.
    setMessages((prev) =>
      prev.map((m) =>
        m.actionType === 'plan' || m.actionType === 'gate'
          ? { ...m, actionType: undefined, actionResolved: action }
          : m
      )
    )
    // Show the thinking indicator immediately for actions that trigger backend
    // work. From here on, the backend's WebSocket frames manage isThinking —
    // status frames keep it on, plan/gate/response/error/message turn it off.
    // Cancel is excluded because the backend emits a response frame instantly
    // and we'd just flash the indicator. Don't reset in `finally` either, or
    // we'd race the backend frames and kill the indicator the moment the HTTP
    // response arrives.
    if (action !== 'cancel') {
      markThinking()
    }
    try {
      const { postThreadAction } = await import('../api/client')
      await postThreadAction(activeThread.id, action, changes)
    } catch (e) {
      console.error('Action failed:', e)
      // Only reset on failure — otherwise the WS frames are the authority.
      resetThinking()
    }
  }

  function handleSendMessage(content: string) {
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}-${Math.random()}`,
        role: 'user',
        content,
        timestamp: new Date().toLocaleTimeString('en-US', {
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
        }),
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
            workspaceSlug={activeWorkspace}
            threadTitle={activeThread.title}
            onSendMessage={handleSendMessage}
            onAction={handleAction}
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
