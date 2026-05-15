import { useState, useEffect, useRef, useCallback } from 'react'
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
  X,
  FileText,
  Image as ImageIcon,
  Loader2,
  AlertTriangle,
  Upload,
} from 'lucide-react'
import { CyberFrame } from './CyberFrame'
import { CommandBar } from './CommandBar'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { uploadFile } from '../api/client'
import type { ChatMessage as ApiChatMessage } from '../api/client'
import {
  getWorkspaceAccent,
  getWorkspaceAccentAlpha,
} from '../lib/workspace-theme'

export type ChatMessage = ApiChatMessage

interface ChatPanelProps {
  messages: ChatMessage[]
  isThinking: boolean
  statusText: string
  isConnected: boolean
  workspaceLabel: string
  workspaceSlug: string
  threadTitle: string
  // fileIds carries server-assigned ids for any files the user attached
  // to this message — the parent forwards them on the WS frame so the
  // orchestrator can pull the parsed content out of state.uploaded_files.
  onSendMessage: (content: string, fileIds?: string[]) => void
  onRosterClick?: () => void
}

// Allow-list mirrored from the backend upload endpoint. Used for the
// <input accept=…> attribute AND a client-side gate so unsupported
// files never hit the network.
const ACCEPTED_EXTENSIONS = [
  'pdf', 'txt', 'csv', 'json', 'md',
  'jpg', 'jpeg', 'png', 'webp', 'gif',
] as const
const ACCEPT_ATTR =
  '.pdf,.txt,.csv,.json,.md,.jpg,.jpeg,.png,.webp,.gif,' +
  'application/pdf,image/jpeg,image/png,image/webp,image/gif,' +
  'text/plain,text/csv,application/json,text/markdown'
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024

type AttachmentStatus = 'uploading' | 'ready' | 'error'

interface Attachment {
  localId: string
  file: File
  kind: 'image' | 'pdf' | 'document'
  status: AttachmentStatus
  fileId?: string
  error?: string
  previewUrl?: string
}

function extOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : ''
}

function classifyFile(file: File): Attachment['kind'] | null {
  const ext = extOf(file.name)
  if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(ext)) return null
  if (['jpg', 'jpeg', 'png', 'webp', 'gif'].includes(ext)) return 'image'
  if (ext === 'pdf') return 'pdf'
  return 'document'
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatTime(ts: string): string {
  if (!ts) return ''
  if (/^\d{2}:\d{2}$/.test(ts)) return ts
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return ''
  }
}

export function ChatPanel({
  messages,
  isThinking,
  statusText,
  isConnected,
  workspaceSlug,
  threadTitle,
  onSendMessage,
  onRosterClick,
}: ChatPanelProps) {
  const [inputValue, setInputValue] = useState('')
  // Active workspace accent — applied to thread title, message
  // badges, chat input border, and send button. Falls back to slate
  // for unknown slugs via the workspace-theme helper.
  const accent = getWorkspaceAccent(workspaceSlug)
  const accentTint = getWorkspaceAccentAlpha(workspaceSlug, 0.1)
  const accentBorderTint = getWorkspaceAccentAlpha(workspaceSlug, 0.3)
  // ── Attachments ──────────────────────────────────────────────────
  // Per-message file queue. Files start as "uploading", flip to "ready"
  // when the server returns a file_id, and stay until either the user
  // clicks send (we ship the ids + clear) or the user removes them.
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // dragenter/dragleave fire for every child element, so count nesting
  // depth to avoid the overlay flicker when crossing child boundaries.
  const dragDepthRef = useRef(0)
  // Revoke any object URLs we minted for image previews so we don't
  // leak blobs when the component unmounts.
  useEffect(() => {
    return () => {
      setAttachments((prev) => {
        for (const a of prev) {
          if (a.previewUrl) URL.revokeObjectURL(a.previewUrl)
        }
        return prev
      })
    }
  }, [])

  const [cycles, setCycles] = useState(0)
  const [hexStream, setHexStream] = useState<string[]>([])
  const [activeNodes, setActiveNodes] = useState<number[]>([])
  const [dataPackets, setDataPackets] = useState(0)
  const [hackPhase, setHackPhase] = useState('')
  const [waveHeights, setWaveHeights] = useState<number[]>(Array(50).fill(0.3))
  // Separate waveform state for the inline voice-recording visualizer.
  // 24 bars × ~100ms tick gives a calmer rhythm than the hacking-panel
  // wave (50 × 80ms) which would feel busy at small widths.
  const [voiceWaveHeights, setVoiceWaveHeights] = useState<number[]>(
    Array(24).fill(0.3),
  )
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // ── Voice-to-text (Web Speech API) ────────────────────────────────
  const [isRecording, setIsRecording] = useState(false)
  const [voiceTooltip, setVoiceTooltip] = useState('')
  // Auto-send countdown after a successful voice capture. Null = idle,
  // otherwise the number of seconds remaining (counts down 4..1, then 0
  // is the send trigger). The text to send is captured at countdown
  // start so user edits during the countdown reliably cancel.
  const [autoSendIn, setAutoSendIn] = useState<number | null>(null)
  const autoSendTextRef = useRef('')
  // Stable ref for the parent's onSendMessage so the countdown effect
  // does not re-fire when the parent re-renders.
  const onSendMessageRef = useRef(onSendMessage)
  useEffect(() => {
    onSendMessageRef.current = onSendMessage
  }, [onSendMessage])
  // Detect SpeechRecognition support once so the mic can render as
  // visibly disabled in browsers that don't ship it (Firefox without
  // flags, older Safari) instead of looking broken on click.
  const [speechSupported] = useState(() => {
    if (typeof window === 'undefined') return false
    const w = window as unknown as {
      SpeechRecognition?: unknown
      webkitSpeechRecognition?: unknown
    }
    return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition)
  })
  // Loose ref type — lib.dom's SpeechRecognition interface exists but the
  // constructor isn't a guaranteed global (vendor-prefixed in Chrome/Safari),
  // and pinning to the strict interface trips ResultList iterator/error-code
  // mismatches that don't matter for our duck-typed usage.
  const recognitionRef = useRef<{
    start: () => void
    stop: () => void
    abort: () => void
  } | null>(null)
  const finalTranscriptRef = useRef('')
  const silenceTimerRef = useRef<number | null>(null)

  const showVoiceTooltip = (msg: string) => {
    setVoiceTooltip(msg)
    window.setTimeout(() => {
      setVoiceTooltip((current) => (current === msg ? '' : current))
    }, 3000)
  }

  const clearSilenceTimer = () => {
    if (silenceTimerRef.current !== null) {
      window.clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = null
    }
  }

  const stopRecording = () => {
    clearSilenceTimer()
    try {
      recognitionRef.current?.stop()
    } catch {
      // recognition may already be stopping — ignore
    }
  }

  const resetSilenceTimer = () => {
    clearSilenceTimer()
    silenceTimerRef.current = window.setTimeout(() => {
      // Auto-stop after a few seconds of silence; the recognition's onend
      // handler will commit the final transcript into inputValue.
      stopRecording()
    }, 3000)
  }

  const startRecording = () => {
    // Read through `any` to avoid the lib.dom vs vendor-prefix mismatch.
    const w = window as unknown as {
      SpeechRecognition?: new () => unknown
      webkitSpeechRecognition?: new () => unknown
    }
    const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition
    if (!Ctor) {
      showVoiceTooltip('Voice input not supported in this browser')
      return
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rec: any = new Ctor()
    rec.continuous = true
    rec.interimResults = true
    rec.lang = 'en-US'

    finalTranscriptRef.current = ''

    rec.onresult = (event: { results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => {
      let finalText = ''
      let interimText = ''
      for (let i = 0; i < event.results.length; i++) {
        const r = event.results[i]
        const transcript = r[0].transcript
        if (r.isFinal) finalText += transcript
        else interimText += transcript
      }
      finalTranscriptRef.current = finalText
      // Live display: final + interim. Textarea is styled italic/dim
      // while isRecording is true so the user knows it's a draft.
      setInputValue((finalText + interimText).trimStart())
      resetSilenceTimer()
    }

    rec.onerror = (event: { error: string }) => {
      if (
        event.error === 'not-allowed' ||
        event.error === 'service-not-allowed'
      ) {
        showVoiceTooltip('Microphone access denied')
      } else if (event.error === 'no-speech') {
        // Common and expected — onend will fire next; no tooltip.
      } else {
        showVoiceTooltip(`Voice error: ${event.error}`)
      }
    }

    rec.onend = () => {
      clearSilenceTimer()
      setIsRecording(false)
      const finalText = finalTranscriptRef.current.trim()
      setInputValue(finalText)
      if (finalText) startAutoSend(finalText)
      recognitionRef.current = null
    }

    recognitionRef.current = rec
    try {
      rec.start()
      setIsRecording(true)
      resetSilenceTimer()
    } catch {
      showVoiceTooltip('Could not start voice input')
      recognitionRef.current = null
    }
  }

  const cancelAutoSend = () => {
    setAutoSendIn(null)
  }

  const startAutoSend = (text: string) => {
    if (!text.trim()) return
    autoSendTextRef.current = text
    setAutoSendIn(4)
  }

  // Countdown tick. Each render with a non-null autoSendIn schedules the
  // next decrement 1s later; reaching 0 fires onSendMessage and clears.
  // User-initiated edits / focus / mic-click set autoSendIn to null,
  // which short-circuits the cleanup and prevents the send.
  useEffect(() => {
    if (autoSendIn === null) return
    if (autoSendIn <= 0) {
      const text = autoSendTextRef.current.trim()
      if (text) onSendMessageRef.current(text)
      setInputValue('')
      setAutoSendIn(null)
      return
    }
    const timer = window.setTimeout(() => {
      setAutoSendIn((prev) => (prev === null ? null : prev - 1))
    }, 1000)
    return () => window.clearTimeout(timer)
  }, [autoSendIn])

  const handleMicClick = () => {
    // Any mic interaction during the countdown cancels the auto-send —
    // the user clearly wants to do something different than ship the
    // captured transcript.
    cancelAutoSend()
    if (isRecording) stopRecording()
    else startRecording()
  }

  useEffect(() => {
    // On unmount, make sure any in-flight recognition is aborted so the
    // mic indicator doesn't stay green in the OS tray.
    return () => {
      clearSilenceTimer()
      try {
        recognitionRef.current?.abort()
      } catch {
        // ignore
      }
    }
  }, [])

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

  // Voice-record waveform animation. Matches the hacking-panel pattern
  // but keyed on isRecording so the input-bar visualizer only ticks
  // while the mic is hot. Resets to a flat baseline when recording
  // ends so the bars don't freeze mid-roll if the user toggles fast.
  useEffect(() => {
    if (isRecording) {
      const interval = setInterval(() => {
        setVoiceWaveHeights((prev) =>
          prev.map(() => 0.15 + Math.random() * 0.85),
        )
      }, 100)
      return () => clearInterval(interval)
    } else {
      setVoiceWaveHeights(Array(24).fill(0.3))
    }
  }, [isRecording])

  // ── File upload helpers ─────────────────────────────────────────
  const startUpload = useCallback((attachment: Attachment) => {
    uploadFile(attachment.file)
      .then((res) => {
        setAttachments((prev) =>
          prev.map((a) =>
            a.localId === attachment.localId
              ? { ...a, status: 'ready', fileId: res.file_id }
              : a,
          ),
        )
      })
      .catch((err: Error) => {
        setAttachments((prev) =>
          prev.map((a) =>
            a.localId === attachment.localId
              ? { ...a, status: 'error', error: err.message }
              : a,
          ),
        )
      })
  }, [])

  const enqueueFiles = useCallback(
    (files: FileList | File[]) => {
      const list = Array.from(files)
      const accepted: Attachment[] = []
      const rejected: { name: string; reason: string }[] = []
      for (const file of list) {
        const kind = classifyFile(file)
        if (!kind) {
          rejected.push({
            name: file.name,
            reason: `Unsupported type (.${extOf(file.name) || '?'})`,
          })
          continue
        }
        if (file.size > MAX_UPLOAD_BYTES) {
          rejected.push({ name: file.name, reason: 'Exceeds 10 MB' })
          continue
        }
        const previewUrl = kind === 'image'
          ? URL.createObjectURL(file)
          : undefined
        accepted.push({
          localId: `${Date.now()}-${Math.random()}`,
          file,
          kind,
          status: 'uploading',
          previewUrl,
        })
      }
      if (rejected.length) {
        // Surface rejected files as error-status entries so the user
        // sees why they didn't attach — they can dismiss with the X.
        for (const r of rejected) {
          accepted.push({
            localId: `rej-${Date.now()}-${Math.random()}`,
            file: new File([], r.name),
            kind: 'document',
            status: 'error',
            error: r.reason,
          })
        }
      }
      if (accepted.length) {
        setAttachments((prev) => [...prev, ...accepted])
        for (const a of accepted) {
          if (a.status === 'uploading') startUpload(a)
        }
      }
    },
    [startUpload],
  )

  const removeAttachment = (localId: string) => {
    setAttachments((prev) => {
      const target = prev.find((a) => a.localId === localId)
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl)
      return prev.filter((a) => a.localId !== localId)
    })
  }

  const retryAttachment = (localId: string) => {
    setAttachments((prev) => {
      const target = prev.find((a) => a.localId === localId)
      if (!target || target.status !== 'error') return prev
      const next: Attachment = {
        ...target,
        status: 'uploading',
        error: undefined,
      }
      // Kick off upload outside the setter so React batches consistently.
      queueMicrotask(() => startUpload(next))
      return prev.map((a) => (a.localId === localId ? next : a))
    })
  }

  const handlePickerChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length) {
      enqueueFiles(e.target.files)
    }
    // Reset so picking the same file twice re-fires onChange.
    e.target.value = ''
  }

  // ── Drag-and-drop on the chat area ──────────────────────────────
  const handleDragEnter = (e: React.DragEvent) => {
    if (!Array.from(e.dataTransfer?.types ?? []).includes('Files')) return
    e.preventDefault()
    dragDepthRef.current += 1
    if (dragDepthRef.current === 1) setDragActive(true)
  }
  const handleDragLeave = (e: React.DragEvent) => {
    if (!Array.from(e.dataTransfer?.types ?? []).includes('Files')) return
    e.preventDefault()
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) setDragActive(false)
  }
  const handleDragOver = (e: React.DragEvent) => {
    if (!Array.from(e.dataTransfer?.types ?? []).includes('Files')) return
    e.preventDefault()
  }
  const handleDrop = (e: React.DragEvent) => {
    if (!Array.from(e.dataTransfer?.types ?? []).includes('Files')) return
    e.preventDefault()
    dragDepthRef.current = 0
    setDragActive(false)
    if (e.dataTransfer.files && e.dataTransfer.files.length) {
      enqueueFiles(e.dataTransfer.files)
    }
  }

  // ── Send ────────────────────────────────────────────────────────
  const readyCount = attachments.filter((a) => a.status === 'ready').length
  const uploadingCount = attachments.filter(
    (a) => a.status === 'uploading',
  ).length
  const canSend =
    (inputValue.trim().length > 0 || readyCount > 0) && uploadingCount === 0

  const handleSend = () => {
    if (!canSend) return
    if (autoSendIn !== null) cancelAutoSend()
    const text = inputValue.trim()
    const fileIds = attachments
      .filter((a) => a.status === 'ready' && a.fileId)
      .map((a) => a.fileId!) as string[]
    onSendMessage(text, fileIds.length ? fileIds : undefined)
    setInputValue('')
    // Drop only the attachments we shipped; keep any error rows so the
    // user still sees the rejection message until they dismiss it.
    setAttachments((prev) => {
      const shipped = new Set(
        prev.filter((a) => a.status === 'ready').map((a) => a.localId),
      )
      for (const a of prev) {
        if (shipped.has(a.localId) && a.previewUrl) {
          URL.revokeObjectURL(a.previewUrl)
        }
      }
      return prev.filter((a) => !shipped.has(a.localId))
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div
      className="flex-1 h-full flex flex-col bg-gradient-to-b from-[#0a0a0e] to-[#040406] relative scanlines"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {dragActive && (
        <div className="absolute inset-0 z-[200] pointer-events-none flex items-center justify-center">
          <div className="absolute inset-3 border-2 border-dashed border-neon-cyan/70 bg-neon-cyan/[0.06] animate-pulse" />
          <div className="relative industrial-raised border border-neon-cyan/60 bg-[#0a0a0e]/90 px-5 py-3 flex items-center gap-3 glow-cyan">
            <Upload className="w-5 h-5 text-neon-cyan glow-cyan-text" />
            <span className="font-mono text-xs uppercase tracking-widest text-neon-cyan glow-cyan-text font-bold">
              Drop to attach
            </span>
          </div>
        </div>
      )}
      {isThinking && (
        <div className="absolute top-0 left-0 right-0 z-50">
          <div className="h-8 w-full bg-gradient-to-b from-[#0a0a0e] to-[#040406] relative overflow-hidden flex items-center justify-center gap-[2px] px-6 border-b-2 border-[#12121a]">
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
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
              <div className="w-1 h-6 bg-neon-yellow/80" />
              <div className="w-1 h-4 bg-neon-yellow/60" />
            </div>
          </div>

          <div className="bg-gradient-to-b from-[#040406] to-[#040406] overflow-hidden industrial-panel">
            <div className="flex items-center justify-between px-4 py-2.5 border-b-2 border-[#12121a]">
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
                        : 'bg-[#0a0a0e] border-[#2a2a35]'
                    )}
                  />
                ))}
                <div className="w-[2px] h-5 bg-gradient-to-b from-transparent via-neon-yellow/40 to-transparent mx-1" />
                <Network className="w-4 h-4 text-neon-yellow" />
              </div>
            </div>

            <div className="flex items-stretch">
              <div className="flex-1 px-4 py-2 border-r-2 border-[#12121a] industrial-inset">
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

              <div className="grid grid-cols-3 gap-0 text-center">
                <div className="px-4 py-2 border-r-2 border-[#12121a] industrial-raised">
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
                <div className="px-4 py-2 border-r-2 border-[#12121a] industrial-raised">
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

            <div className="h-1 w-full bg-gradient-to-r from-neon-pink/60 via-neon-cyan/60 to-neon-green/60" />
            <div className="industrial-divider-h" />
          </div>
        </div>
      )}

      <header
        className={cn(
          'px-6 py-4 flex items-center justify-between transition-all industrial-raised relative',
          isThinking && 'mt-[135px]'
        )}
      >
        <div className="absolute top-2 left-2 w-4 h-4 border-l-2 border-t-2 border-neon-cyan/40" />
        <div className="absolute bottom-2 right-2 w-4 h-4 border-r-2 border-b-2 border-neon-pink/40" />

        <div>
          <h2
            className="font-mono text-sm uppercase tracking-wider font-bold"
            style={{ color: accent }}
          >
            {threadTitle}
          </h2>
          <p className="font-mono text-[10px] text-muted-foreground mt-0.5">
            Session: <span className="text-neon-pink">DRIFT-SYS</span>
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

        <div className="absolute -bottom-[3px] left-0 right-0 industrial-divider-h" />
      </header>

      <div className="flex-1 overflow-y-auto p-6 space-y-6 scan-line relative">
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
                        className="font-mono text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 border"
                        style={{
                          color: accent,
                          backgroundColor: accentTint,
                          borderColor: accentBorderTint,
                        }}
                      >
                        {message.role === 'assistant' ? 'Drift' : 'You'}
                      </span>
                      {message.timestamp && (
                        <span className="font-mono text-[10px] text-neon-yellow/60 tabular-nums">
                          {formatTime(message.timestamp)}
                        </span>
                      )}
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
            {isThinking && (
              <div className="flex gap-4 justify-start">
                <div className="w-10 h-10 shrink-0 flex items-center justify-center industrial-raised border-2 border-[#00f0ff]/50 glow-cyan mt-2">
                  <Bot className="w-5 h-5 text-[#00f0ff]" />
                </div>
                <div className="cyber-frame cyber-frame-cyan px-5 py-4">
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className="font-mono text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 border"
                      style={{
                        color: accent,
                        backgroundColor: accentTint,
                        borderColor: accentBorderTint,
                      }}
                    >
                      DRIFT
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 py-2">
                    <span
                      className="w-2 h-2 rounded-full animate-bounce"
                      style={{ backgroundColor: accent, animationDelay: '0ms' }}
                    />
                    <span
                      className="w-2 h-2 rounded-full animate-bounce"
                      style={{ backgroundColor: accent, animationDelay: '150ms' }}
                    />
                    <span
                      className="w-2 h-2 rounded-full animate-bounce"
                      style={{ backgroundColor: accent, animationDelay: '300ms' }}
                    />
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      <CommandBar
        onSendMessage={onSendMessage}
        workspaceSlug={workspaceSlug}
        onRosterClick={onRosterClick}
      />

      <div className="p-4 relative industrial-panel">
        <div className="absolute -top-[1px] left-0 right-0 industrial-divider-h" />

        {attachments.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {attachments.map((a) => {
              const isImage = a.kind === 'image'
              const cardBorder = isImage
                ? 'border-neon-pink/50'
                : 'border-neon-cyan/40'
              const accentText = isImage
                ? 'text-neon-pink'
                : 'text-neon-cyan'
              return (
                <div
                  key={a.localId}
                  className={cn(
                    'relative group flex items-center gap-2 pr-7',
                    'industrial-inset border bg-[#0a0a0e]',
                    a.status === 'error'
                      ? 'border-neon-pink/60'
                      : cardBorder,
                  )}
                  style={{ minWidth: 180, maxWidth: 260 }}
                >
                  <div
                    className={cn(
                      'w-10 h-10 shrink-0 flex items-center justify-center',
                      'border-r',
                      isImage
                        ? 'border-neon-pink/30'
                        : 'border-neon-cyan/30',
                    )}
                  >
                    {isImage && a.previewUrl ? (
                      <img
                        src={a.previewUrl}
                        alt={a.file.name}
                        className="w-10 h-10 object-cover"
                      />
                    ) : a.status === 'error' ? (
                      <AlertTriangle className="w-4 h-4 text-neon-pink" />
                    ) : isImage ? (
                      <ImageIcon className="w-4 h-4 text-neon-pink" />
                    ) : (
                      <FileText className="w-4 h-4 text-neon-cyan" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0 py-1 pr-1">
                    <div
                      className={cn(
                        'font-sans text-[11px] font-bold truncate',
                        a.status === 'error'
                          ? 'text-neon-pink'
                          : 'text-foreground',
                      )}
                      title={a.file.name}
                    >
                      {a.file.name}
                    </div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      {a.status === 'uploading' && (
                        <>
                          <Loader2
                            className={cn(
                              'w-2.5 h-2.5 animate-spin',
                              accentText,
                            )}
                          />
                          <span
                            className={cn(
                              'font-mono text-[9px] uppercase tracking-wider',
                              accentText,
                            )}
                          >
                            Uploading…
                          </span>
                        </>
                      )}
                      {a.status === 'ready' && (
                        <span
                          className={cn(
                            'font-mono text-[9px] uppercase tracking-wider',
                            accentText,
                          )}
                        >
                          {formatBytes(a.file.size)}
                        </span>
                      )}
                      {a.status === 'error' && (
                        <button
                          type="button"
                          onClick={() => retryAttachment(a.localId)}
                          className="font-mono text-[9px] uppercase tracking-wider text-neon-pink hover:underline"
                          title={a.error}
                        >
                          {a.error ?? 'Failed'} · retry
                        </button>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeAttachment(a.localId)}
                    title="Remove"
                    className="absolute top-1 right-1 p-0.5 text-muted-foreground/70 hover:text-neon-pink transition-colors"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              )
            })}
          </div>
        )}

        <div className="flex items-end gap-3">
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT_ATTR}
            multiple
            className="hidden"
            onChange={handlePickerChange}
          />
          <div className="flex items-center gap-1 pb-2">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              title="Attach files (PDF, images, txt/csv/json)"
              className="p-2.5 industrial-inset border border-muted-foreground/20 text-muted-foreground hover:text-neon-pink hover:border-neon-pink/40 transition-all group"
            >
              <Paperclip className="w-4 h-4 group-hover:rotate-45 transition-transform" />
            </button>
            <div className="relative inline-flex">
              {voiceTooltip && (
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 whitespace-nowrap px-2 py-1 industrial-inset border border-neon-pink/40 font-mono text-[10px] text-neon-pink glow-pink-text z-10 pointer-events-none">
                  {voiceTooltip}
                </div>
              )}
              <button
                type="button"
                onClick={handleMicClick}
                disabled={!speechSupported}
                title={
                  !speechSupported
                    ? 'Voice input not supported in this browser'
                    : isRecording
                      ? 'Stop recording'
                      : 'Voice input'
                }
                className={cn(
                  'p-2.5 industrial-inset border transition-all cursor-pointer',
                  !speechSupported &&
                    'opacity-40 cursor-not-allowed border-muted-foreground/20 text-muted-foreground',
                  speechSupported && isRecording &&
                    'border-neon-pink/60 text-neon-pink glow-pink',
                  speechSupported && !isRecording &&
                    'border-muted-foreground/20 text-muted-foreground hover:text-neon-green hover:border-neon-green/40',
                )}
              >
                <Mic
                  className={cn(
                    'w-4 h-4',
                    isRecording && 'animate-pulse',
                  )}
                />
              </button>
            </div>
          </div>

          <div className="flex-1 relative">
            {isRecording ? (
              // While the mic is hot the textarea is read-only anyway,
              // so we swap it out for a flex row: live transcript on
              // the left, animated waveform on the right. As the
              // interim transcript grows it naturally pushes the
              // waveform's flex region narrower until the text fills
              // the bar and the waveform compresses to a sliver.
              <div
                className={cn(
                  'w-full px-4 py-3 industrial-inset border-2 flex items-center gap-3',
                  'border-neon-pink/50 shadow-[0_0_12px_rgba(255,42,109,0.15)]',
                )}
                style={{ minHeight: '48px', maxHeight: '150px' }}
              >
                <div
                  className={cn(
                    'font-sans text-sm italic whitespace-nowrap overflow-hidden text-ellipsis flex-shrink min-w-0',
                    inputValue.trim()
                      ? 'text-foreground'
                      : 'text-muted-foreground/40',
                  )}
                >
                  {inputValue.trim() || 'Listening...'}
                </div>
                <div
                  className="flex-1 min-w-0 h-6 flex items-center justify-end gap-[2px] overflow-hidden"
                  aria-hidden
                >
                  {voiceWaveHeights.map((h, i) => (
                    <div
                      key={i}
                      className="w-[3px] rounded-sm flex-shrink-0 transition-all duration-100"
                      style={{
                        height: `${Math.max(0.12, h) * 100}%`,
                        background: '#ff3366',
                        // Slight per-bar opacity variation so the wave
                        // reads as organic instead of a uniform block.
                        opacity:
                          0.45 + h * 0.4 + ((i % 5) * 0.04),
                      }}
                    />
                  ))}
                </div>
              </div>
            ) : (
              <textarea
                value={inputValue}
                onChange={(e) => {
                  // Any typed change during the countdown means the user is
                  // editing — cancel the auto-send so it can never fire on
                  // text they meant to revise.
                  if (autoSendIn !== null) cancelAutoSend()
                  setInputValue(e.target.value)
                }}
                onFocus={() => {
                  // Focusing the input is also an explicit signal that the
                  // user wants to take over and edit before sending.
                  if (autoSendIn !== null) cancelAutoSend()
                }}
                onKeyDown={handleKeyDown}
                placeholder="Enter command..."
                rows={1}
                className={cn(
                  'w-full px-4 py-3 industrial-inset border-2',
                  'placeholder:text-muted-foreground/40',
                  'font-sans text-sm resize-none',
                  'focus:outline-none transition-all duration-200',
                  'text-foreground',
                )}
                style={{
                  minHeight: '48px',
                  maxHeight: '150px',
                  borderColor: accentBorderTint,
                }}
              />
            )}
            <div className={cn(
              'absolute bottom-0 left-2 right-2 h-[2px]',
              inputValue.trim()
                ? 'bg-gradient-to-r from-transparent via-[#ff2a6d]/60 to-transparent'
                : 'bg-gradient-to-r from-transparent via-[#00f0ff]/30 to-transparent'
            )} />
          </div>

          <button
            onClick={handleSend}
            disabled={!canSend}
            title={
              uploadingCount > 0
                ? 'Waiting for uploads to finish…'
                : 'Send'
            }
            className={cn(
              'p-3.5 industrial-raised border-2 cyber-button font-bold transition-all duration-200',
              'disabled:opacity-30 disabled:cursor-not-allowed disabled:border-muted-foreground/20 disabled:hover:shadow-none',
            )}
            style={
              canSend
                ? { borderColor: accent, color: accent }
                : undefined
            }
          >
            {uploadingCount > 0 ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </div>

        <div className="flex items-center justify-between mt-3 px-1">
          <p className="font-mono text-[10px] text-muted-foreground/50">
            Press <span className="text-neon-cyan font-bold">Enter</span> to send |{' '}
            <span className="text-neon-pink font-bold">Shift+Enter</span> for new line
          </p>
          {autoSendIn !== null ? (
            <div className="flex items-center gap-2 px-2 py-1 industrial-inset border border-neon-pink/50 glow-pink">
              <span className="w-2 h-2 bg-neon-pink rounded-full pulse-dot-pink" />
              <span className="font-mono text-[10px] text-neon-pink glow-pink-text font-bold tabular-nums">
                SENDING IN {autoSendIn}...
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2 px-2 py-1 industrial-inset border border-neon-yellow/20">
              <Zap className="w-3 h-3 text-neon-yellow" />
              <span className="font-mono text-[10px] text-neon-yellow/80 font-bold">READY</span>
            </div>
          )}
        </div>
      </div>

    </div>
  )
}