import { useRef, useCallback, useState } from 'react'

export interface WSMessage {
  type: 'connected' | 'status' | 'response' | 'error' | 'done' | 'plan' | 'gate'
  text?: string
  content?: string
  thread_id?: string
  workspace?: string
  goal?: string
  steps?: string[]
  gate_kind?: string
}

interface UseWebSocketReturn {
  isConnected: boolean
  isThinking: boolean
  statusText: string
  sendMessage: (content: string, agentSlug?: string) => void
  connect: (workspaceSlug: string, threadId: string) => void
  disconnect: () => void
  resetThinking: () => void
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
          const txt = data.text || ''
          if (/cancelled|cancel|aborted|complete/i.test(txt)) {
            setIsThinking(false)
            setStatusText('')
          } else {
            setIsThinking(true)
            setStatusText(txt)
          }
        } else if (data.type === 'done') {
          // Terminal signal — always resets thinking
          setIsThinking(false)
          setStatusText('')
        } else if (
          data.type === 'response' ||
          data.type === 'error' ||
          data.type === 'plan' ||
          data.type === 'gate'
        ) {
          // Terminal for this turn (plan/gate hand control back to the user)
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

  const resetThinking = useCallback(() => {
    setIsThinking(false)
    setStatusText('')
  }, [])

  const sendMessage = useCallback((content: string, agentSlug?: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'message',
          content,
          agent_slug: agentSlug || null,
        })
      )
      setIsThinking(true)
    }
  }, [])

  return {
    isConnected,
    isThinking,
    statusText,
    sendMessage,
    connect,
    disconnect,
    resetThinking,
  }
}
