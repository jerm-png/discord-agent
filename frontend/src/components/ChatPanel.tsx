import { useState, useEffect, useRef } from 'react'
import { cn } from '../lib/utils'
import {
  Send,
  Paperclip,
  Mic,
  Bot,
  User,
  Zap,
  Cpu,
  Database,
  Network,
  Shield,
  Terminal,
} from 'lucide-react'
import { CyberFrame } from './CyberFrame'
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

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return ts
  }
}

export function ChatPanel({
  messages,
  isThinking,
  statusText,
  isConnected,
  threadTitle,
  onSendMessage,
}: ChatPanelProps) {
  const [inputValue, setInputValue] = useState('')
  const [cycles, setCycles] = useState(0)
  const [hexStream, setHexStream] = useState<string[]>([])
  const [activeNodes, setActiveNodes] = useState<number[]>([])
  const [dataPackets, setDataPackets] = useState(0)
  const [hackPhase, setHackPhase] = useState('')
  const [waveHeights, setWaveHeights] = useState<number[]>(Array(50).fill(0.3))
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll on new messages or thinking state change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isThinking])

  useEffect(() => {
    if (isThinking) {
      const interval = setInterval(() => {
        setCycles(Math.floor(Math.random() * 9000 + 1000))
        setDataPackets((prev) => prev + Math.floor(Math.random() * 50))
      }, 100)
      return () => clearInterval(interval)
    } else {
      setDataPackets(0)
    }
  }, [isThinking])

  useEffect(() => {
    if (isThinking) {
      const interval = setInterval(() => {
        const newHex = Array(8)
          .fill(0)
          .map(() =>
            Math.floor(Math.random() * 256)
              .toString(16)
              .padStart(2, '0')
              .toUpperCase()
          )
          .join(' ')
        setHexStream((prev) => [...prev.slice(-5), newHex])
      }, 150)
      return () => clearInterval(interval)
    } else {
      setHexStream([])
    }
  }, [isThinking])

  useEffect(() => {
    if (isThinking) {
      const interval = setInterval(() => {
        const numActive = Math.floor(Math.random() * 4) + 2
        const nodes = Array(numActive)
          .fill(0)
          .map(() => Math.floor(Math.random() * 6))
        setActiveNodes(nodes)
      }, 300)
      return () => clearInterval(interval)
    } else {
      setActiveNodes([])
    }
  }, [isThinking])

  useEffect(() => {
    if (isThinking) {
      const phases = [
        'INITIALIZING NEURAL LINK',
        'PARSING DATA STREAMS',
        'DECRYPTING PAYLOAD',
        'COMPILING RESPONSE',
        'SYNCING MEMORY BANKS',
        'ROUTING THROUGH PROXY',
        'BYPASSING FIREWALL',
      ]
      const interval = setInterval(() => {
        setHackPhase(phases[Math.floor(Math.random() * phases.length)])
      }, 800)
      return () => clearInterval(interval)
    } else {
      setHackPhase('')
    }
  }, [isThinking])

  useEffect(() => {
    if (isThinking) {
      const interval = setInterval(() => {
        setWaveHeights((prev) => prev.map(() => 0.15 + Math.random() * 0.85))
      }, 80)
      return () => clearInterval(interval)
    } else {
      setWaveHeights(Array(50).fill(0.3))
    }
  }, [isThinking])

  const handleSend = () => {
    if (!inputValue.trim()) return
    onSendMessage(inputValue.trim())
    setInputValue('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex-1 h-full flex flex-col bg-gradient-to-b from-[#0a0a10] to-[#08080d] relative scanlines">
      {/* Hacking Node Progress Bar */}
      {isThinking && (
        <div className="absolute top-0 left-0 right-0 z-50">
          {/* Audio Waveform Bar - industrial container */}
          <div className="h-8 w-full bg-gradient-to-b from-[#0c0c14] to-[#06060a] relative overflow-hidden flex items-center justify-center gap-[2px] px-6 border-b-2 border-[#1a1a22]">
            {/* Left bracket decoration */}
            <div className="absolute left-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
              <div className="w-1 h-4 bg-neon-yellow/60" />
              <div className="w-1 h-6 bg-neon-yellow/80" />
            </div>

            {waveHeights.map((height, i) => (
              <div
                key={i}
                className="w-[3px] rounded-sm transition-all duration-75"
                style={{
                  height: `${height * 22}px`,
                  background: `linear-gradient(180deg, #fcee0a ${100 - height * 100}%, #ff6b35 100%)`,
                  boxShadow:
                    height > 0.6 ? '0 0 8px rgba(252, 238, 10, 0.6)' : 'none',
                  opacity: 0.5 + height * 0.5,
                }}
              />
            ))}

            {/* Right bracket decoration */}
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
              <div className="w-1 h-6 bg-neon-yellow/80" />
              <div className="w-1 h-4 bg-neon-yellow/60" />
            </div>
          </div>

          {/* Hacking node interface - industrial style */}
          <div className="bg-gradient-to-b from-[#08080d] to-[#050508] overflow-hidden industrial-panel">
            {/* Top row - Status and nodes */}
            <div className="flex items-center justify-between px-4 py-2.5 border-b-2 border-[#1a1a22]">
              {/* Phase indicator */}
              <div className="flex items-center gap-3 px-3 py-1.5 industrial-inset border border-neon-pink/20">
                <div className="relative">
                  <div className="w-2.5 h-2.5 bg-neon-pink pulse-dot-pink" />
                  <div className="absolute inset-0 w-2.5 h-2.5 bg-neon-pink animate-ping opacity-40" />
                </div>
                <Terminal className="w-3.5 h-3.5 text-neon-cyan" />
                <span className="font-mono text-[10px] text-neon-pink glow-pink-text uppercase tracking-[0.15em] font-bold">
                  {statusText || hackPhase || 'INITIALIZING'}
                </span>
              </div>

              {/* Network nodes visualization */}
              <div className="flex items-center gap-2 px-3 py-1.5 industrial-raised border border-neon-cyan/20">
                {[0, 1, 2, 3, 4, 5].map((node) => (
                  <div
                    key={node}
                    className={cn(
                      'w-3 h-3 border-2 transition-all duration-150',
                      activeNodes.includes(node)
                        ? node % 3 === 0
                          ? 'bg-neon-cyan border-neon-cyan glow-cyan'
                          : node % 3 === 1
                            ? 'bg-neon-pink border-neon-pink glow-pink'
                            : 'bg-neon-green border-neon-green glow-green'
                        : 'bg-[#0a0a10] border-[#2a2a35]'
                    )}
                  />
                ))}
                <div className="w-[2px] h-5 bg-gradient-to-b from-transparent via-neon-yellow/40 to-transparent mx-1" />
                <Network className="w-4 h-4 text-neon-yellow" />
              </div>
            </div>

            {/* Middle row - Hex stream and stats */}
            <div className="flex items-stretch">
              {/* Hex data stream */}
              <div className="flex-1 px-4 py-2 border-r-2 border-[#1a1a22] industrial-inset">
                <div className="flex items-center gap-2 mb-1">
                  <Database className="w-3 h-3 text-neon-green" />
                  <span className="font-mono text-[8px] text-neon-green/70 uppercase tracking-wider font-bold">
                    Data Stream
                  </span>
                </div>
                <div className="font-mono text-[10px] text-neon-cyan/90 h-4 overflow-hidden tracking-wider">
                  {hexStream.length > 0
                    ? hexStream[hexStream.length - 1]
                    : '00 00 00 00 00 00 00 00'}
                </div>
              </div>

              {/* Stats grid - raised panels */}
              <div className="grid grid-cols-3 gap-0 text-center">
                <div className="px-4 py-2 border-r-2 border-[#1a1a22] industrial-raised">
                  <div className="flex items-center justify-center gap-1 mb-1">
                    <Cpu className="w-3 h-3 text-neon-cyan" />
                    <span className="font-mono text-[8px] text-muted-foreground uppercase font-bold">
                      Cycles
                    </span>
                  </div>
                  <span className="font-mono text-xs text-neon-cyan glow-cyan-text tabular-nums font-bold">
                    {cycles}
                  </span>
                </div>
                <div className="px-4 py-2 border-r-2 border-[#1a1a22] industrial-raised">
                  <div className="flex items-center justify-center gap-1 mb-1">
                    <Shield className="w-3 h-3 text-neon-pink" />
                    <span className="font-mono text-[8px] text-muted-foreground uppercase font-bold">
                      Tokens
                    </span>
                  </div>
                  <span className="font-mono text-xs text-neon-pink glow-pink-text tabular-nums font-bold">
                    {(cycles * 0.8).toFixed(0)}
                  </span>
                </div>
                <div className="px-4 py-2 industrial-raised">
                  <div className="flex items-center justify-center gap-1 mb-1">
                    <Zap className="w-3 h-3 text-neon-yellow" />
                    <span className="font-mono text-[8px] text-muted-foreground uppercase font-bold">
                      Packets
                    </span>
                  </div>
                  <span className="font-mono text-xs text-neon-yellow glow-yellow-text tabular-nums font-bold">
                    {dataPackets}
                  </span>
                </div>
              </div>
            </div>

            {/* Bottom thick decorative bar */}
            <div className="h-1 w-full bg-gradient-to-r from-neon-pink/60 via-neon-cyan/60 to-neon-green/60" />
            <div className="industrial-divider-h" />
          </div>
        </div>
      )}

      {/* Header */}
      <header
        className={cn(
          'px-6 py-4 flex items-center justify-between transition-all industrial-raised relative',
          isThinking && 'mt-[135px]'
        )}
      >
        {/* Corner accents */}
        <div className="absolute top-2 left-2 w-4 h-4 border-l-2 border-t-2 border-neon-cyan/40" />
        <div className="absolute bottom-2 right-2 w-4 h-4 border-r-2 border-b-2 border-neon-pink/40" />

        <div>
          <h2 className="font-mono text-sm text-neon-cyan glow-cyan-text uppercase tracking-wider font-bold">
            {threadTitle}
          </h2>
          <p className="font-mono text-[10px] text-muted-foreground mt-0.5">
            Session:{' '}
            <span className="text-neon-pink">DRIFT-SYS</span>
          </p>
        </div>
        <div
          className={cn(
            'flex items-center gap-2 px-4 py-2 industrial-inset border-2',
            isConnected ? 'border-neon-green/30' : 'border-neon-pink/30'
          )}
        >
          <div
            className={cn(
              'w-2.5 h-2.5',
              isConnected ? 'bg-neon-green pulse-dot-green' : 'bg-neon-pink pulse-dot-pink'
            )}
          />
          <span
            className={cn(
              'font-mono text-[10px] uppercase tracking-wider font-bold',
              isConnected
                ? 'text-neon-green glow-green-text'
                : 'text-neon-pink glow-pink-text'
            )}
          >
            {isConnected ? 'DRIFT: ACTIVE' : 'DRIFT: OFFLINE'}
          </span>
        </div>

        {/* Bottom thick divider */}
        <div className="absolute -bottom-[3px] left-0 right-0 industrial-divider-h" />
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {messages.length === 0 && !isThinking ? (
          <div className="h-full flex flex-col items-center justify-center gap-3">
            <Terminal className="w-12 h-12 text-neon-cyan/20" strokeWidth={1} />
            <span className="font-mono text-sm text-muted-foreground/50">
              [ NO TRANSMISSIONS ]
            </span>
          </div>
        ) : (
          <>
            {messages.map((message) => (
              <div
                key={message.id}
                className={cn(
                  'flex gap-4',
                  message.role === 'user' ? 'justify-end' : 'justify-start'
                )}
              >
                {message.role === 'assistant' && (
                  <div className="w-10 h-10 shrink-0 flex items-center justify-center industrial-raised border-2 border-neon-cyan/50 glow-cyan mt-2">
                    <Bot className="w-5 h-5 text-neon-cyan" />
                  </div>
                )}

                <CyberFrame
                  variant={message.role === 'user' ? 'pink' : 'cyan'}
                  className="max-w-[70%]"
                  cornerSize={12}
                  notchSize={20}
                >
                  <div className="px-5 py-4">
                    <div className="flex items-center gap-2 mb-3">
                      <span
                        className={cn(
                          'font-mono text-[10px] uppercase tracking-wider font-bold px-2 py-0.5',
                          message.role === 'assistant'
                            ? 'text-neon-cyan glow-cyan-text bg-neon-cyan/10 border border-neon-cyan/30'
                            : 'text-neon-pink glow-pink-text bg-neon-pink/10 border border-neon-pink/30'
                        )}
                      >
                        {message.role === 'assistant' ? 'Drift' : 'You'}
                      </span>
                      <span className="font-mono text-[10px] text-neon-yellow/60 tabular-nums">
                        {formatTime(message.timestamp)}
                      </span>
                    </div>
                    {message.role === 'assistant' ? (
                      <div className="drift-prose">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {message.content}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <div className="font-sans text-sm text-foreground whitespace-pre-wrap leading-relaxed">
                        {message.content}
                      </div>
                    )}
                  </div>
                </CyberFrame>

                {message.role === 'user' && (
                  <div className="w-10 h-10 shrink-0 flex items-center justify-center industrial-raised border-2 border-neon-pink/50 glow-pink mt-2">
                    <User className="w-5 h-5 text-neon-pink" />
                  </div>
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input Area */}
      <div className="p-4 relative industrial-panel">
        {/* Top thick divider */}
        <div className="absolute -top-[1px] left-0 right-0 industrial-divider-h" />

        <div className="flex items-end gap-3">
          {/* Toolbar - industrial buttons */}
          <div className="flex items-center gap-1 pb-2">
            <button className="p-2.5 industrial-inset border border-muted-foreground/20 text-muted-foreground hover:text-neon-pink hover:border-neon-pink/40 transition-all group">
              <Paperclip className="w-4 h-4 group-hover:rotate-45 transition-transform" />
            </button>
            <button className="p-2.5 industrial-inset border border-muted-foreground/20 text-muted-foreground hover:text-neon-green hover:border-neon-green/40 transition-all">
              <Mic className="w-4 h-4" />
            </button>
          </div>

          {/* Input - heavy industrial styling */}
          <div className="flex-1 relative">
            <textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Enter command..."
              rows={1}
              className={cn(
                'w-full px-4 py-3 industrial-inset border-2 border-neon-cyan/30',
                'text-foreground placeholder:text-muted-foreground/40',
                'font-sans text-sm resize-none',
                'focus:outline-none focus:border-neon-pink/50 focus:shadow-[0_0_12px_rgba(255,42,109,0.2)]',
                'transition-all duration-200'
              )}
              style={{ minHeight: '48px', maxHeight: '150px' }}
            />
            <div className="absolute bottom-0 left-2 right-2 h-[2px] bg-gradient-to-r from-transparent via-neon-cyan/30 to-transparent" />
          </div>

          {/* Send Button - heavy industrial */}
          <button
            onClick={handleSend}
            disabled={!inputValue.trim()}
            className={cn(
              'p-3.5 industrial-raised border-2 border-neon-cyan/50 text-neon-cyan cyber-button font-bold',
              'hover:border-neon-pink/50 hover:text-neon-pink hover:glow-pink transition-all duration-200',
              'disabled:opacity-30 disabled:cursor-not-allowed disabled:border-muted-foreground/20 disabled:hover:shadow-none'
            )}
          >
            <Send className="w-5 h-5" />
          </button>
        </div>

        <div className="flex items-center justify-between mt-3 px-1">
          <p className="font-mono text-[10px] text-muted-foreground/50">
            Press <span className="text-neon-cyan font-bold">Enter</span> to send |{' '}
            <span className="text-neon-pink font-bold">Shift+Enter</span> for new line
          </p>
          <div className="flex items-center gap-2 px-2 py-1 industrial-inset border border-neon-yellow/20">
            <Zap className="w-3 h-3 text-neon-yellow" />
            <span className="font-mono text-[10px] text-neon-yellow/80 font-bold">READY</span>
          </div>
        </div>
      </div>
    </div>
  )
}
