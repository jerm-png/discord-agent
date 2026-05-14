import { useRef, useCallback, useState } from 'react'

export interface WSMessage {
  type:
    | 'connected'
    | 'status'
    | 'response'
    | 'message'
    | 'error'
    | 'medbay_update'
  text?: string
  content?: string
  thread_id?: string
  workspace?: string
  // medbay_update: list of side-panel sections that need refetching,
  // e.g. ['protocol', 'changes']
  sections?: string[]
}

interface UseWebSocketReturn {
  isConnected: boolean
  isThinking: boolean
  statusText: string
  sendMessage: (
    content: string,
    options?: { agentSlug?: string; fileIds?: string[] },
  ) => void
  connect: (workspaceSlug: string, threadId: string) => void
  disconnect: () => void
}

export function useWebSocket(
  onMessage: (msg: WSMessage) => void
): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [isThinking, setIsThinking] = useState(false)
  const [statusText, setStatusText] = useState('')

  const connect = useCallback(
    (workspaceSlug: string, threadId: string) => {
      if (wsRef.current) {
        wsRef.current.close()
      }

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = window.location.host
      const url = `${protocol}//${host}/api/v1/ws/${workspaceSlug}/${threadId}`

      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        setIsConnected(true)
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data) as WSMessage

        if (data.type === 'status') {
          // The orchestrator emits a trailing "Response delivered… Ready."
          // status frame AFTER the terminal response/message/error. Treat
          // those phrases as terminal here too, otherwise the indicator
          // gets re-armed after the response has already landed.
          const txt = data.text || ''
          if (/cancelled|cancel|aborted|complete|delivered|ready/i.test(txt)) {
            setIsThinking(false)
            setStatusText('')
          } else {
            setIsThinking(true)
            setStatusText(txt)
          }
        } else if (
          data.type === 'response' ||
          data.type === 'message' ||
          data.type === 'error'
        ) {
          setIsThinking(false)
          setStatusText('')
          onMessage(data)
        } else {
          onMessage(data)
        }
      }

      ws.onclose = () => {
        setIsConnected(false)
        setIsThinking(false)
        setStatusText('')
      }

      ws.onerror = () => {
        setIsConnected(false)
        setIsThinking(false)
      }
    },
    [onMessage]
  )

  const disconnect = useCallback(() => {
    wsRef.current?.close()
    wsRef.current = null
    setIsConnected(false)
    setIsThinking(false)
    setStatusText('')
  }, [])

  const sendMessage = useCallback(
    (
      content: string,
      options?: { agentSlug?: string; fileIds?: string[] },
    ) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            type: 'message',
            content,
            agent_slug: options?.agentSlug || null,
            file_ids: options?.fileIds ?? [],
          })
        )
        setIsThinking(true)
      }
    },
    [],
  )

  return {
    isConnected,
    isThinking,
    statusText,
    sendMessage,
    connect,
    disconnect,
  }
}
