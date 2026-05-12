import { useEffect, useState } from 'react'

function formatTime(d: Date): string {
  return [
    d.getHours().toString().padStart(2, '0'),
    d.getMinutes().toString().padStart(2, '0'),
    d.getSeconds().toString().padStart(2, '0'),
  ].join(':')
}

export function SystemStatusBar() {
  const [time, setTime] = useState(() => formatTime(new Date()))

  useEffect(() => {
    const id = setInterval(() => setTime(formatTime(new Date())), 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="industrial-panel border-b border-[#00f0ff]/10 flex items-center h-9 px-4 gap-0 flex-shrink-0 relative z-10">
      {/* Left: branding */}
      <div className="flex items-center gap-3 pr-4 border-r border-[#ffffff]/5">
        <div className="w-1.5 h-1.5 rounded-full bg-[#00f0ff] pulse-dot" />
        <span className="font-mono text-[10px] text-[#00f0ff] tracking-[0.2em] glow-cyan-text">
          DRIFT_OS
        </span>
      </div>

      {/* Center metrics */}
      <div className="flex items-center gap-0 flex-1 overflow-hidden">
        <Metric label="MODEL" value="DRIFT // SONNET-4" />
        <div className="industrial-divider-v h-5 mx-0" />
        <Metric label="CTX" value="200K" />
        <div className="industrial-divider-v h-5 mx-0" />
        <Metric label="SID" value="DRIFT-SYS" />
        <div className="industrial-divider-v h-5 mx-0" />

        {/* MEM bar */}
        <div className="flex items-center gap-2 px-4">
          <span className="font-mono text-[9px] text-[#9090a8]/70 tracking-widest">MEM</span>
          <div className="w-16 h-1.5 bg-[#0a0a0f] border border-[#ffffff]/10 overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-[#00f0ff] to-[#05ffa1]"
              style={{ width: '73%', boxShadow: '0 0 6px rgba(0,240,255,0.6)' }}
            />
          </div>
          <span className="font-mono text-[9px] text-[#00f0ff]/70">73%</span>
        </div>

        <div className="industrial-divider-v h-5 mx-0" />

        {/* PING */}
        <div className="flex items-center gap-1.5 px-4">
          <span className="font-mono text-[9px] text-[#9090a8]/70 tracking-widest">PING</span>
          <span className="font-mono text-[9px] text-[#05ffa1]">12ms</span>
        </div>
      </div>

      {/* Right: time */}
      <div className="flex items-center gap-2 pl-4 border-l border-[#ffffff]/5">
        <span className="font-mono text-[9px] text-[#9090a8]/50 tracking-widest">SYS</span>
        <span className="font-mono text-[10px] text-[#fcee0a]/80 tracking-widest">
          {time}
        </span>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5 px-4">
      <span className="font-mono text-[9px] text-[#9090a8]/70 tracking-widest">{label}</span>
      <span className="font-mono text-[9px] text-[#f0f0f5]/80">{value}</span>
    </div>
  )
}
