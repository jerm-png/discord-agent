import { cn } from '../lib/utils'
import type { ReactNode } from 'react'

interface CyberFrameProps {
  children: ReactNode
  variant?: 'cyan' | 'pink'
  className?: string
  cornerSize?: number
  notchSize?: number
}

export function CyberFrame({
  children,
  variant = 'cyan',
  className,
  cornerSize = 14,
  notchSize = 24,
}: CyberFrameProps) {
  const colors =
    variant === 'cyan'
      ? { start: '#00f0ff', end: '#ff2a6d', glow: 'rgba(0, 240, 255, 0.3)' }
      : { start: '#ff2a6d', end: '#00f0ff', glow: 'rgba(255, 42, 109, 0.3)' }

  return (
    <div className={cn('relative', className)}>
      {/* SVG Border Frame */}
      <svg
        className="absolute inset-0 w-full h-full pointer-events-none"
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient
            id={`border-gradient-${variant}`}
            x1="0%"
            y1="0%"
            x2="100%"
            y2="100%"
          >
            <stop offset="0%" stopColor={colors.start} />
            <stop
              offset="50%"
              stopColor={variant === 'cyan' ? '#05ffa1' : '#d100d1'}
            />
            <stop offset="100%" stopColor={colors.end} />
          </linearGradient>
          <filter id={`glow-${variant}`}>
            <feGaussianBlur stdDeviation="3" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Main border path - chamfered corners */}
        <path
          d={`
            M ${cornerSize} 0
            L calc(100% - ${cornerSize}px) 0
            L 100% ${cornerSize}
            L 100% calc(100% - ${cornerSize}px)
            L calc(100% - ${cornerSize}px) 100%
            L ${cornerSize} 100%
            L 0 calc(100% - ${cornerSize}px)
            L 0 ${cornerSize}
            Z
          `}
          fill="none"
          stroke={`url(#border-gradient-${variant})`}
          strokeWidth="2"
          filter={`url(#glow-${variant})`}
          vectorEffect="non-scaling-stroke"
        />
      </svg>

      {/* Corner accent notches - top left */}
      <div
        className="absolute top-[2px] left-[18px] h-[3px] rounded-sm"
        style={{
          width: `${notchSize}px`,
          background: `linear-gradient(90deg, ${colors.start}, transparent)`,
          boxShadow: `0 0 8px ${colors.start}`,
        }}
      />
      <div
        className="absolute top-[18px] left-[2px] w-[3px] rounded-sm"
        style={{
          height: `${notchSize}px`,
          background: `linear-gradient(180deg, ${colors.start}, transparent)`,
          boxShadow: `0 0 8px ${colors.start}`,
        }}
      />

      {/* Corner accent notches - top right */}
      <div
        className="absolute top-[2px] right-[18px] h-[3px] rounded-sm"
        style={{
          width: `${notchSize}px`,
          background: `linear-gradient(90deg, transparent, ${colors.end})`,
          boxShadow: `0 0 8px ${colors.end}`,
        }}
      />
      <div
        className="absolute top-[18px] right-[2px] w-[3px] rounded-sm"
        style={{
          height: `${notchSize}px`,
          background: `linear-gradient(180deg, ${colors.end}, transparent)`,
          boxShadow: `0 0 8px ${colors.end}`,
        }}
      />

      {/* Corner accent notches - bottom left */}
      <div
        className="absolute bottom-[2px] left-[18px] h-[3px] rounded-sm"
        style={{
          width: `${notchSize}px`,
          background: `linear-gradient(90deg, ${colors.start}88, transparent)`,
          boxShadow: `0 0 6px ${colors.start}66`,
        }}
      />
      <div
        className="absolute bottom-[18px] left-[2px] w-[3px] rounded-sm"
        style={{
          height: `${notchSize}px`,
          background: `linear-gradient(180deg, transparent, ${colors.start}88)`,
          boxShadow: `0 0 6px ${colors.start}66`,
        }}
      />

      {/* Corner accent notches - bottom right */}
      <div
        className="absolute bottom-[2px] right-[18px] h-[3px] rounded-sm"
        style={{
          width: `${notchSize}px`,
          background: `linear-gradient(90deg, transparent, ${colors.end}88)`,
          boxShadow: `0 0 6px ${colors.end}66`,
        }}
      />
      <div
        className="absolute bottom-[18px] right-[2px] w-[3px] rounded-sm"
        style={{
          height: `${notchSize}px`,
          background: `linear-gradient(180deg, transparent, ${colors.end}88)`,
          boxShadow: `0 0 6px ${colors.end}66`,
        }}
      />

      {/* Corner dots/lights */}
      <div
        className="absolute w-2 h-2 rounded-full"
        style={{
          top: `${cornerSize - 2}px`,
          left: `${cornerSize - 2}px`,
          background: colors.start,
          boxShadow: `0 0 10px ${colors.start}, 0 0 20px ${colors.start}`,
        }}
      />
      <div
        className="absolute w-2 h-2 rounded-full"
        style={{
          top: `${cornerSize - 2}px`,
          right: `${cornerSize - 2}px`,
          background: colors.end,
          boxShadow: `0 0 10px ${colors.end}, 0 0 20px ${colors.end}`,
        }}
      />
      <div
        className="absolute w-1.5 h-1.5 rounded-full opacity-60"
        style={{
          bottom: `${cornerSize - 1}px`,
          left: `${cornerSize - 1}px`,
          background: colors.start,
          boxShadow: `0 0 6px ${colors.start}`,
        }}
      />
      <div
        className="absolute w-1.5 h-1.5 rounded-full opacity-60"
        style={{
          bottom: `${cornerSize - 1}px`,
          right: `${cornerSize - 1}px`,
          background: colors.end,
          boxShadow: `0 0 6px ${colors.end}`,
        }}
      />

      {/* Content container with clipped corners */}
      <div
        className="relative bg-gradient-to-b from-[#12121a] to-[#0c0c12] m-[2px]"
        style={{
          clipPath: `polygon(
            0 ${cornerSize}px,
            ${cornerSize}px 0,
            calc(100% - ${cornerSize}px) 0,
            100% ${cornerSize}px,
            100% calc(100% - ${cornerSize}px),
            calc(100% - ${cornerSize}px) 100%,
            ${cornerSize}px 100%,
            0 calc(100% - ${cornerSize}px)
          )`,
        }}
      >
        {children}
      </div>
    </div>
  )
}
