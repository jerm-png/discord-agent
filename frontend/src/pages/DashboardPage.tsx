import { useEffect, useState, useCallback } from 'react'
import { SystemStatusBar } from '../components/SystemStatusBar'
import { WorkspaceSidebar } from '../components/WorkspaceSidebar'
import { ThreadList } from '../components/ThreadList'
import { ChatPanel } from '../components/ChatPanel'
import { RosterPage } from '../components/RosterPage'
import { EntityHeader } from '../components/EntityHeader'
import { MedBayPage, type MedbaySection } from './MedBayPage'
import { useWebSocket } from '../hooks/useWebSocket'
import type { WSMessage } from '../hooks/useWebSocket'
import { useDriftStore } from '../store/driftStore'
import { useAuthStore } from '../store/authStore'
import {
  getWorkspaces,
  getThreads,
  createThread,
  archiveThread,
  getMessages,
} from '../api/client'
import type { Thread, Entity } from '../api/client'
import type { ChatMessage } from '../components/ChatPanel'

export function DashboardPage() {
  const userId = useAuthStore((s) => s.userId)
  const isParker = userId === 'parker'
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
  // medbay_update WS frames bump these counters per section; MedBayPage
  // watches the matching counter in a useEffect and refetches.
  const [medbayTokens, setMedbayTokens] = useState<
    Record<MedbaySection, number>
  >({ protocol: 0, labs: 0, followups: 0, changes: 0 })

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
    } else if (msg.type === 'medbay_update') {
      const sections = msg.sections ?? []
      if (sections.length === 0) return
      setMedbayTokens((prev) => {
        const next = { ...prev }
        for (const s of sections) {
          if (s === 'protocol' || s === 'labs' || s === 'followups' || s === 'changes') {
            next[s] = (prev[s] ?? 0) + 1
          }
        }
        return next
      })
    }
  }, [])

  const { isConnected, isThinking, statusText, sendMessage, connect, disconnect } =
    useWebSocket(handleWSMessage)

  // Load workspaces on mount
  useEffect(() => {
    getWorkspaces()
      .then((ws) => {
        setWorkspaces(ws)
        // If the current activeWorkspace isn't visible to this user
        // (e.g. Parker auto-routed to "parker.exe", or admin's default
        // not in the filtered list), switch to the first available so
        // getThreads doesn't 4xx on an inaccessible slug.
        if (
          ws.length > 0 &&
          !ws.some((w) => w.slug === activeWorkspace)
        ) {
          setActiveWorkspace(ws[0].slug)
        }
      })
      .catch(console.error)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setWorkspaces, setActiveWorkspace])

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

  // Roster: deselect any active thread so the empty-state branch renders
  // RosterPage. Only meaningful in the director workspace.
  function handleRosterClick() {
    setActiveThread(null)
  }

  // Create a new thread pre-linked to an entity, then open it. Used by
  // the EntityCard "+ New Thread" button on the roster page.
  async function handleCreateEntityThread(entity: Entity) {
    try {
      const thread = await createThread(
        activeWorkspace,
        `Coaching: ${entity.name}`,
        entity.id,
      )
      addThread(thread)
      setActiveThread(thread)
    } catch (e) {
      console.error('Failed to create entity-linked thread:', e)
    }
  }
    
  function handleSendMessage(content: string, fileIds?: string[]) {
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
    sendMessage(content, fileIds && fileIds.length ? { fileIds } : undefined)
  }

  const activeWorkspaceLabel =
    workspaces.find((w) => w.slug === activeWorkspace)?.label ??
    activeWorkspace

  return (
    <div className="h-screen w-screen overflow-hidden flex flex-col bg-[#0a0a0f]">
      <SystemStatusBar />
      <div className="flex-1 flex overflow-hidden">
        {/* Parker has only one workspace so the sidebar is suppressed —
            keeps the simplified layout the spec calls for. */}
        {!isParker && (
          <WorkspaceSidebar
            workspaces={workspaces}
            activeWorkspace={activeWorkspace}
            onWorkspaceChange={handleWorkspaceChange}
          />
        )}
        <ThreadList
          threads={threads}
          activeThread={activeThread}
          onThreadChange={handleThreadChange}
          onCreateThread={handleCreateThread}
          onDeleteThread={handleDeleteThread}
          workspaceLabel={activeWorkspaceLabel}
          isLoading={threadsLoading}
        />
        {activeWorkspace === 'health' ? (
          <MedBayPage
            hasActiveThread={!!activeThread}
            messages={messages}
            isThinking={isThinking}
            statusText={statusText}
            isConnected={isConnected}
            workspaceLabel={activeWorkspaceLabel}
            workspaceSlug={activeWorkspace}
            threadTitle={activeThread?.title ?? ''}
            onSendMessage={handleSendMessage}
            onNewThread={() => handleCreateThread('New conversation')}
            threads={threads}
            onOpenThread={(t) => setActiveThread(t)}
            refetchTokens={medbayTokens}
          />
        ) : activeThread ? (
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Collapsible entity profile bar — only when the thread is
                linked to a roster entity. */}
            {activeThread.entity_id != null && (
              <EntityHeader entityId={activeThread.entity_id} />
            )}
            <div className="flex-1 flex flex-col overflow-hidden">
              <ChatPanel
                messages={messages}
                isThinking={isThinking}
                statusText={statusText}
                isConnected={isConnected}
                workspaceLabel={activeWorkspaceLabel}
                workspaceSlug={activeWorkspace}
                threadTitle={activeThread.title}
                onSendMessage={handleSendMessage}
                onRosterClick={
                  activeWorkspace === 'director'
                    ? handleRosterClick
                    : undefined
                }
              />
            </div>
          </div>
        ) : activeWorkspace === 'director' ? (
          <RosterPage
            onOpenThread={(t) => setActiveThread(t)}
            onCreateEntityThread={handleCreateEntityThread}
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
