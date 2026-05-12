import { useState, useEffect, useRef, useCallback } from 'react'
import { Terminal, Send } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

interface ChatPanelProps {
  messages: ChatMessage[]
  isThinking: boolean
  statusText: string
  isConnected: boolean
  workspaceLabel: string
  threadTitle: string
  onSendMessage: (content: string) => void
}

const HEX_CHARS = '0123456789abcdef'

function randomHex(len: number): string {
  return Array.from({ length: len }, () =>
    HEX_CHARS[Math.floor(Math.random() * 16)]
  ).join('')
}

function ThinkingPanel({ statusText }: { statusText: string }) {
  const [hexStream, setHexStream] = useState(() => randomHex(64))
  const [nodes, setNodes] = useState(() =>
    Array.from({ length: 12 }, () => Math.random())
  )

  useEffect(() => {
    const hexId = setInterval(() => setHexStream(randomHex(64)), 80)
    const nodeId = setInterval(
      () => setNodes(Array.from({ length: 12 }, () => Math.random())),
      300
    )
    return () => {
      clearInterval(hexId)
      clearInterval(nodeId)
    }
  }, [])

  return (
    <div className="border border-[#00f0ff]/20 bg-[#0a0a12] mx-4 mb-4 p-3 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="font-mono text-[9px] text-[#00f0ff]/60 tracking-widest uppercase">
          PROCESSING
        </span>
        <div className="w-1.5 h-1.5 rounded-full bg-[#fcee0a] pulse-dot" style={{ animation: 'pulse-glow 0.6s ease-in-out infinite' }} />
      </div>

      {/* Wave bars */}
      <div className="flex items-end gap-[2px] h-6">
        {Array.from({ length: 24 }).map((_, i) => (
          <div
            key={i}
            className="wave-bar flex-1"
            style={{ minHeight: '4px' }}
          />
        ))}
      </div>

      {/* Hex stream */}
      <div
        className="font-mono text-[8px] text-[#00f0ff]/30 tracking-wider overflow-hidden whitespace-nowrap"
        style={{ fontVariantNumeric: 'tabular-nums' }}
      >
        {hexStream}
      </div>

      {/* Node scan */}
      <div className="relative h-3 bg-[#050508] overflow-hidden">
        <div
          className="absolute inset-y-0 w-8 bg-gradient-to-r from-transparent via-[#00f0ff]/20 to-transparent"
          style={{ animation: 'node-scan 1.2s linear infinite' }}
        />
        <div className="absolute inset-0 flex items-center gap-[14px] px-2">
          {nodes.map((v, i) => (
            <div
              key={i}
              className="w-1 h-1 rounded-full flex-shrink-0"
              style={{
                background: v > 0.6 ? '#00f0ff' : v > 0.3 ? '#9090a8' : '#1a1a2a',
                boxShadow: v > 0.6 ? '0 0 4px #00f0ff' : undefined,
              }}
            />
          ))}
        </div>
      </div>

      {/* Status text */}
      {statusText && (
        <div
          className="font-mono text-[9px] text-[#fcee0a]/70 tracking-wider"
          style={{ animation: 'hack-glitch 3s ease-in-out infinite' }}
        >
          &gt; {statusText}
        </div>
      )}
    </div>
  )
}

export function ChatPanel({
  messages,
  isThinking,
  statusText,
  isConnected,
  threadTitle,
  onSendMessage,
}: ChatPanelProps) {
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isThinking])

  const handleSend = useCallback(() => {
    const content = input.trim()
    if (!content) return
    onSendMessage(content)
    setInput('')
    textareaRef.current?.focus()
  }, [input, onSendMessage])

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-[#0a0a0f]">
      {/* Header */}
      <div className="industrial-panel border-b border-[#ffffff]/5 px-4 py-2.5 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="industrial-divider-v h-4" />
          <div className="font-mono text-[11px] text-[#f0f0f5]/80 truncate max-w-xs">
            {threadTitle}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div
            className="w-1.5 h-1.5 rounded-full"
            style={{
              background: isConnected ? '#05ffa1' : '#ff2a6d',
              boxShadow: isConnected
                ? '0 0 6px rgba(5,255,161,0.8)'
                : '0 0 6px rgba(255,42,109,0.8)',
            }}
          />
          <span
            className="font-mono text-[9px] tracking-widest uppercase"
            style={{ color: isConnected ? '#05ffa1' : '#ff2a6d' }}
          >
            DRIFT: {isConnected ? 'ACTIVE' : 'OFFLINE'}
          </span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto py-4 space-y-4">
        {messages.length === 0 && !isThinking ? (
          <div className="h-full flex flex-col items-center justify-center gap-3">
            <Terminal className="w-12 h-12 text-[#00f0ff]/20" strokeWidth={1} />
            <div className="font-mono text-sm text-[#9090a8]/50">
              [ NO TRANSMISSIONS ]
            </div>
            <div className="font-mono text-xs text-[#9090a8]/30">
              Start a new thread to begin
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg) => (
              <div key={msg.id} className="px-4">
                {msg.role === 'user' ? (
                  <div className="flex justify-end">
                    <div className="max-w-[75%]">
                      <div className="font-mono text-[8px] text-[#9090a8]/50 text-right mb-1 tracking-widest uppercase">
                        YOU
                      </div>
                      <div className="bg-[#12121a] border border-[#00f0ff]/15 px-4 py-3 cyber-panel-alt">
                        <p className="font-sans text-sm text-[#f0f0f5] leading-relaxed whitespace-pre-wrap">
                          {msg.content}
                        </p>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex justify-start">
                    <div className="max-w-[80%]">
                      <div className="font-mono text-[8px] text-[#00f0ff]/50 mb-1 tracking-widest uppercase">
                        DRIFT
                      </div>
                      <div className="border border-[#ffffff]/5 bg-[#0d0d14] px-4 py-3 cyber-panel">
                        <div className="prose prose-invert prose-sm max-w-none font-sans text-sm text-[#f0f0f5] leading-relaxed">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {msg.content}
                          </ReactMarkdown>
                        </div>
                      </div>
                      <div className="font-mono text-[8px] text-[#9090a8]/30 mt-1 tracking-wider">
                        {new Date(msg.timestamp).toLocaleTimeString()}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}

            {isThinking && <ThinkingPanel statusText={statusText} />}

            <div ref={bottomRef} />
          </>
        )}
      </div>

      {/* Input area */}
      <div className="industrial-panel border-t border-[#ffffff]/5 p-4 flex-shrink-0">
        <div className="flex gap-3 items-end">
          <div className="flex-1 industrial-inset border border-[#00f0ff]/20 focus-within:border-[#00f0ff]/50 transition-colors">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Transmit message... (Enter to send, Shift+Enter for newline)"
              rows={1}
              className="w-full bg-transparent px-4 py-3 font-sans text-sm text-[#f0f0f5] placeholder-[#9090a8]/30 focus:outline-none resize-none max-h-32 overflow-y-auto"
              style={{ lineHeight: '1.5' }}
            />
          </div>
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            className="cyber-button industrial-raised border border-[#00f0ff]/40 w-10 h-10 flex items-center justify-center text-[#00f0ff] hover:border-[#00f0ff]/80 hover:text-[#00f0ff] disabled:opacity-30 disabled:cursor-not-allowed transition-all flex-shrink-0"
            style={{
              boxShadow: input.trim() ? '0 0 10px rgba(0,240,255,0.2)' : undefined,
            }}
          >
            <Send className="w-4 h-4" strokeWidth={1.5} />
          </button>
        </div>
        <div className="mt-2 flex items-center justify-between">
          <span className="font-mono text-[8px] text-[#9090a8]/30 tracking-widest">
            DRIFT INTERFACE // PERSISTENT COGNITION
          </span>
          <span className="font-mono text-[8px] text-[#9090a8]/30">
            {isConnected ? '● CONNECTED' : '○ OFFLINE'}
          </span>
        </div>
      </div>
    </div>
  )
}
